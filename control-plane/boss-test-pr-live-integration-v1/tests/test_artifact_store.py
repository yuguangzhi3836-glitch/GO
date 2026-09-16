"""Regression for the sealed candidate-artifact store (contract go.sealed-artifact.v1).

These tests exist because of the ephemeral-artifact bug: TEST_PR V2 built an
image, reported ``built_image_id`` in signed Evidence, and then deleted the
image in its ``finally`` block.  The Evidence was true and the artifact did not
exist, so no later CANARY or DEPLOY could use it.

Every test here runs offline, against a synthetic ``docker save`` archive and a
recording runner.  No Docker daemon, no registry, no host access.

Coverage, named by the contract requirement it holds:

* a sealed package is content-addressed and re-seals idempotently
* a package can only be sealed under the identity Docker actually reports
* tampering with a stored package is refused, not repaired
* a symlinked object, a symlinked store, an untrusted store mode and an
  over-sized package are all refused
* a package whose archive is not the claimed image is refused, at seal and at load
* a ``docker load`` that yields a different image is refused
* a caller can never supply a path, a filename, a tag or a Docker argv

The production checks are POSIX ownership and mode checks.  Where this suite runs
on a platform that cannot express them (a Windows workstation), ``setUp`` relaxes
only the *expected* constant to what the platform can represent, so the rules
themselves stay exactly as the live system applies them; the dedicated negative
tests drive the comparison directly on any platform.  The Linux gate is the
authority for the POSIX behaviour.
"""
import hashlib
import importlib.machinery
import importlib.util
import inspect
import json
import os
import pathlib
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hk-staging"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from hk_agent import artifact_store  # noqa: E402

from archive_fixtures import (  # noqa: E402
    OCI_CONFIG_TYPE, OCI_INDEX_TYPE, OCI_LAYOUT, OCI_MANIFEST_TYPE, append_member, appended,
    hybrid_save, mutated, oci_save, read_tar, refile, synthetic_save, write_tar)

POSIX = os.name == "posix"


class Completed:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


def can_symlink():
    try:
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "t"
            target.write_text("x", encoding="utf-8")
            (pathlib.Path(directory) / "l").symlink_to(target)
        return True
    except (OSError, NotImplementedError):
        return False


SYMLINKS = can_symlink()

READER_PATH = (ROOT.parents[1] / "hk-staging" / "source" / "executor" / "runtime"
               / "artifact_runtime.py")


def load_reader():
    """The executor's read side, loaded from its own file (it ships elsewhere)."""
    loader = importlib.machinery.SourceFileLoader("artifact_reader_under_test",
                                                  str(READER_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class Runner:
    """Records every argv and answers the Docker calls the store makes."""

    def __init__(self, image_id, config_bytes):
        self.image_id = image_id
        self.config_bytes = config_bytes
        self.calls = []
        self.inspect_answers = {}
        self.load_answers = {}
        self.save_returncode = 0
        self.save_bytes = None
        # What `docker save` produces.  The default is the legacy docker-archive;
        # an OCI host produces the other format, and which one is written is a
        # property of the host, not of the store.
        self.save_writer = synthetic_save

    def __call__(self, argv, timeout=None):
        self.calls.append(list(argv))
        if argv[1] == "image" and argv[2] == "inspect":
            target = argv[3]
            return Completed(self.inspect_answers.get(target, self.image_id))
        if argv[1] == "save":
            destination = argv[argv.index("--output") + 1]
            payload = self.save_bytes if self.save_bytes is not None else self.config_bytes
            self.save_writer(destination, payload)
            return Completed("", self.save_returncode)
        if argv[1] == "load":
            for key, value in self.load_answers.items():
                self.inspect_answers[key] = value
            return Completed("Loaded image")
        raise AssertionError("unexpected docker argv: %r" % (argv,))


class StoreFixture(unittest.TestCase):
    """A real store on the running platform, with an injectable trust anchor.

    ``self.identity`` is what the contract says the owner of the store must be.
    The files on disk carry whatever the platform gives them, so injecting the
    anchor is how these tests express "written by a different account" without
    needing a second account -- which is precisely the seam the production
    resolver occupies.  ``artifact_store._IDENTITY_RESOLVER`` is the only thing
    replaced; the ownership comparison, the modes and the byte checks are the
    live ones.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = pathlib.Path(self.tmp.name) / "store"
        self.store.mkdir(mode=0o700)
        (self.store / "objects").mkdir(mode=0o700)
        self.config = b'{"architecture":"amd64","os":"linux"}'
        self.config_digest = hashlib.sha256(self.config).hexdigest()
        self.image_id = "sha256:" + self.config_digest
        self.ref = "go-hk-test-pr:" + "a" * 40
        self.root = str(self.store)
        self.identity = (os.stat(self.store).st_uid, os.stat(self.store).st_gid)
        self.anchor(lambda: self.identity)
        if not POSIX:
            # Keep the rule and relax only what the platform can express.
            self._relax(artifact_store, "DIRECTORY_MODE",
                        stat.S_IMODE(os.stat(self.store).st_mode))
            self._relax(artifact_store, "FILE_MODE", 0o666)
            self._relax(artifact_store, "UNTRUSTED_BITS", 0)

    def _relax(self, module, name, value):
        original = getattr(module, name)
        setattr(module, name, value)
        self.addCleanup(setattr, module, name, original)

    def anchor(self, resolver, module=None):
        """Point a contract module's trust anchor at ``resolver`` for one test."""
        self._relax(module or artifact_store, "_IDENTITY_RESOLVER", resolver)

    def other_identity(self):
        """An account that is not the store's owner, on any platform."""
        uid, gid = self.identity
        return (uid + 1 if uid != 0 else 1, gid + 1 if gid != 0 else 1)

    def as_writer(self, identity=None):
        """Pin the process identity so a test varies exactly one variable.

        The writer gate compares the running account with the trusted one.  On a
        platform with effective ids that comparison happens for real, so a test
        *about who owns the store* must not silently also become a test about who
        is running -- and a test about who is running must say so explicitly.
        """
        chosen = self.identity if identity is None else identity
        self._relax(artifact_store, "_process_identity", lambda: chosen)

    def runner(self, **kwargs):
        runner = Runner(self.image_id, self.config)
        for key, value in kwargs.items():
            setattr(runner, key, value)
        return runner

    def sealed(self, **kwargs):
        return artifact_store.seal(self.runner(**kwargs), self.ref, self.image_id, self.root)

    def object_path(self, package_sha256):
        return self.store / "objects" / (package_sha256 + ".tar")

    def setup_reader(self):
        """Load the executor's read side with its own anchor, exactly as it ships."""
        self.reader = load_reader()
        self.anchor(lambda: self.identity, module=self.reader)
        if not POSIX:
            # The reader carries its own copy of the constants; relax only what
            # this platform can express, never the rule itself.
            self._relax(self.reader, "DIRECTORY_MODE",
                        stat.S_IMODE(os.stat(self.store).st_mode))
            self._relax(self.reader, "FILE_MODE", 0o666)
            self._relax(self.reader, "UNTRUSTED_BITS", 0)
        return self.reader

    def refuses(self, code, save_writer, **kwargs):
        """A refused archive leaves no object, no temporary and no package."""
        with self.assertRaisesRegex(artifact_store.Reject, code):
            self.sealed(save_writer=save_writer, **kwargs)
        self.assertEqual(list((self.store / "objects").iterdir()), [])


class SealedArtifactStoreTests(StoreFixture):
    """The store's own behaviour, on whatever platform this suite runs."""

    # ------------------------------------------------------------------ seal
    def test_a_sealed_package_is_named_by_its_own_content(self):
        runner = self.runner()
        record = artifact_store.seal(runner, self.ref, self.image_id, self.root)
        self.assertEqual(record["schema"], artifact_store.SCHEMA)
        self.assertEqual(record["image_id"], self.image_id)
        self.assertEqual(record["store"], "store")
        stored = self.object_path(record["package_sha256"])
        self.assertTrue(stored.is_file())
        self.assertEqual(hashlib.sha256(stored.read_bytes()).hexdigest(),
                         record["package_sha256"])
        self.assertEqual(record["package_bytes"], stored.stat().st_size)
        self.assertEqual([c[1] for c in runner.calls], ["image", "save"])

    def test_no_partial_temporary_file_is_left_behind(self):
        self.sealed()
        self.assertEqual([p.name for p in (self.store / "objects").iterdir()],
                         [p.name for p in (self.store / "objects").iterdir()
                          if not p.name.startswith(".")])

    def test_re_sealing_the_same_image_is_idempotent(self):
        first = self.sealed()
        second = self.sealed()
        self.assertEqual(first["package_sha256"], second["package_sha256"])
        self.assertEqual(len(list((self.store / "objects").iterdir())), 1)

    def test_the_package_can_only_be_sealed_as_the_image_docker_reports(self):
        runner = self.runner(image_id="sha256:" + "b" * 64)
        with self.assertRaisesRegex(artifact_store.Reject,
                                    "SEALED_ARTIFACT_BUILT_IMAGE_MISMATCH"):
            artifact_store.seal(runner, self.ref, self.image_id, self.root)
        self.assertEqual(list((self.store / "objects").iterdir()), [])

    def test_an_archive_that_is_not_the_claimed_image_is_refused_at_seal(self):
        runner = self.runner()
        runner.save_bytes = b'{"architecture":"arm64"}'
        runner.inspect_answers[self.ref] = "sha256:" + hashlib.sha256(
            runner.save_bytes).hexdigest()  # Docker agrees with the caller ...
        with self.assertRaisesRegex(artifact_store.Reject,
                                    "SEALED_ARTIFACT_BUILT_IMAGE_MISMATCH"):
            artifact_store.seal(runner, self.ref, self.image_id, self.root)
        self.assertEqual(list((self.store / "objects").iterdir()), [])

    def test_a_different_object_under_the_same_name_is_a_collision(self):
        record = self.sealed()
        self.object_path(record["package_sha256"]).write_bytes(b"not the package")
        with self.assertRaisesRegex(artifact_store.Reject, "SEALED_ARTIFACT_COLLISION"):
            self.sealed()

    def test_a_failed_save_leaves_nothing_behind(self):
        runner = self.runner()

        def failing(argv, timeout=None):
            if argv[1] == "save":
                pathlib.Path(argv[argv.index("--output") + 1]).write_bytes(b"")
                raise RuntimeError("docker save failed")
            return Completed(self.image_id)

        with self.assertRaises(RuntimeError):
            artifact_store.seal(failing, self.ref, self.image_id, self.root)
        self.assertEqual(list((self.store / "objects").iterdir()), [])

    # --------------------------------------------------------------- resolve
    def test_a_tampered_package_is_refused(self):
        record = self.sealed()
        stored = self.object_path(record["package_sha256"])
        stored.write_bytes(stored.read_bytes() + b"tamper")
        with self.assertRaisesRegex(artifact_store.Reject, "SEALED_ARTIFACT_PACKAGE_TAMPERED"):
            artifact_store.resolve(record["package_sha256"], self.root)

    def test_an_untrusted_object_mode_is_refused(self):
        record = self.sealed()
        stored = self.object_path(record["package_sha256"])
        if not POSIX:
            self._relax(artifact_store, "UNTRUSTED_BITS", 0o077)
        os.chmod(stored, 0o666)
        self.addCleanup(os.chmod, stored, artifact_store.FILE_MODE)
        with self.assertRaisesRegex(artifact_store.Reject,
                                    "SEALED_ARTIFACT_PACKAGE_UNTRUSTED"):
            artifact_store.resolve(record["package_sha256"], self.root)

    @unittest.skipUnless(SYMLINKS, "this platform cannot create symlinks")
    def test_a_symlinked_object_is_never_followed(self):
        record = self.sealed()
        stored = self.object_path(record["package_sha256"])
        elsewhere = pathlib.Path(self.tmp.name) / "elsewhere.tar"
        elsewhere.write_bytes(stored.read_bytes())
        stored.unlink()
        stored.symlink_to(elsewhere)
        with self.assertRaisesRegex(artifact_store.Reject,
                                    "SEALED_ARTIFACT_PACKAGE_UNAVAILABLE"):
            artifact_store.resolve(record["package_sha256"], self.root)

    def test_an_oversized_package_is_refused(self):
        record = self.sealed()
        self._relax(artifact_store, "MAX_PACKAGE_BYTES", 16)
        with self.assertRaisesRegex(artifact_store.Reject, "SEALED_ARTIFACT_PACKAGE_OVERSIZED"):
            artifact_store.resolve(record["package_sha256"], self.root)

    def test_an_empty_package_is_refused(self):
        record = self.sealed()
        self.object_path(record["package_sha256"]).write_bytes(b"")
        with self.assertRaisesRegex(artifact_store.Reject, "SEALED_ARTIFACT_PACKAGE_OVERSIZED"):
            artifact_store.resolve(record["package_sha256"], self.root)

    def test_an_untrusted_store_mode_is_refused(self):
        self._relax(artifact_store, "DIRECTORY_MODE", 0o701)
        with self.assertRaisesRegex(artifact_store.Reject, "SEALED_ARTIFACT_STORE_UNTRUSTED"):
            artifact_store.resolve("a" * 64, self.root)

    @unittest.skipUnless(SYMLINKS, "this platform cannot create symlinks")
    def test_a_symlinked_store_is_refused(self):
        alias = pathlib.Path(self.tmp.name) / "alias"
        alias.symlink_to(self.store)
        with self.assertRaisesRegex(artifact_store.Reject,
                                    "SEALED_ARTIFACT_STORE_UNAVAILABLE"):
            artifact_store.resolve("a" * 64, str(alias))

    def test_a_missing_store_is_refused(self):
        with self.assertRaisesRegex(artifact_store.Reject,
                                    "SEALED_ARTIFACT_STORE_UNAVAILABLE"):
            artifact_store.resolve("a" * 64, str(pathlib.Path(self.tmp.name) / "absent"))

    def test_a_caller_cannot_name_a_path_or_a_file(self):
        for value in ("../../etc/passwd", "objects/" + "a" * 64 + ".tar", "a" * 64 + ".tar",
                      "A" * 64, "", None, 64):
            with self.assertRaisesRegex(artifact_store.Reject,
                                        "SEALED_ARTIFACT_PACKAGE_IDENTITY"):
                artifact_store.package_path(value, self.root)

    def test_an_absent_package_is_refused(self):
        with self.assertRaisesRegex(artifact_store.Reject,
                                    "SEALED_ARTIFACT_PACKAGE_UNAVAILABLE"):
            artifact_store.resolve("a" * 64, self.root)

    # ------------------------------------------------------------------ load
    def test_loading_restores_exactly_the_candidate(self):
        record = self.sealed()
        runner = self.runner()
        result = artifact_store.load(runner, record["package_sha256"], self.image_id, self.root)
        self.assertEqual(result["load"], "PASS")
        self.assertEqual(result["image_present"], "PASS")
        self.assertEqual(result["image_id"], self.image_id)
        self.assertEqual([c[1] for c in runner.calls], ["load", "image"])
        self.assertEqual(runner.calls[0][:3], ["/usr/bin/docker", "load", "--input"])
        self.assertTrue(runner.calls[0][3].endswith(record["package_sha256"] + ".tar"))
        self.assertEqual(runner.calls[1][3], self.image_id)

    def test_a_package_that_is_not_the_candidate_is_refused_at_load(self):
        record = self.sealed()
        other = "sha256:" + hashlib.sha256(b'{"architecture":"arm64"}').hexdigest()
        with self.assertRaisesRegex(artifact_store.Reject, "SEALED_ARTIFACT_CONFIG_MISMATCH"):
            artifact_store.load(self.runner(), record["package_sha256"], other, self.root)

    def test_a_load_that_yields_another_image_is_refused(self):
        record = self.sealed()
        runner = self.runner(load_answers={self.image_id: "sha256:" + "7" * 64})
        with self.assertRaisesRegex(artifact_store.Reject,
                                    "SEALED_ARTIFACT_LOADED_IMAGE_MISMATCH"):
            artifact_store.load(runner, record["package_sha256"], self.image_id, self.root)

    def test_a_failed_load_is_refused(self):
        record = self.sealed()

        def failing(argv, timeout=None):
            if argv[1] == "load":
                return Completed("", returncode=1)
            raise AssertionError(argv)

        with self.assertRaisesRegex(artifact_store.Reject, "SEALED_ARTIFACT_LOAD_FAILED"):
            artifact_store.load(failing, record["package_sha256"], self.image_id, self.root)

    def test_a_tampered_package_never_reaches_docker(self):
        record = self.sealed()
        runner = self.runner()
        self.object_path(record["package_sha256"]).write_bytes(b"tamper")
        with self.assertRaisesRegex(artifact_store.Reject, "SEALED_ARTIFACT_PACKAGE_TAMPERED"):
            artifact_store.load(runner, record["package_sha256"], self.image_id, self.root)
        self.assertEqual(runner.calls, [])

    def test_a_caller_cannot_choose_the_image_identity_shape(self):
        record = self.sealed()
        for value in ("1c9598d6", "latest", "", None, "sha256:" + "a" * 63):
            with self.assertRaisesRegex(artifact_store.Reject,
                                        "SEALED_ARTIFACT_IMAGE_IDENTITY"):
                artifact_store.load(self.runner(), record["package_sha256"], value, self.root)

    def test_a_caller_cannot_choose_the_image_reference_shape(self):
        for value in ("../x", "x", "", None, "UPPER:tag", "tag:", "/abs/path:x"):
            with self.assertRaisesRegex(artifact_store.Reject,
                                        "SEALED_ARTIFACT_IMAGE_REFERENCE"):
                artifact_store.seal(self.runner(), value, self.image_id, self.root)
        # A bare image ID is a legal Docker reference, but it still has to be the
        # image Docker reports, so naming one grants no authority at all.
        with self.assertRaisesRegex(artifact_store.Reject,
                                    "SEALED_ARTIFACT_BUILT_IMAGE_MISMATCH"):
            artifact_store.seal(self.runner(image_id="sha256:" + "b" * 64),
                                self.image_id, self.image_id, self.root)

    def test_tags_are_recorded_but_never_used(self):
        record = artifact_store.seal(self.runner(), self.ref, self.image_id, self.root,
                                     tags=("go-hk-test-pr:" + "a" * 40,))
        self.assertEqual(record["image_tags"], ["go-hk-test-pr:" + "a" * 40])
        for call in self.runner().calls:
            self.assertEqual(call[0], "/usr/bin/docker")

    def test_the_store_contract_is_pinned_not_guessed(self):
        self.assertEqual(artifact_store.SCHEMA, "go.sealed-artifact.v1")
        self.assertEqual(artifact_store.STORE_ROOT, "/var/lib/go-hk-artifacts")
        self.assertEqual(artifact_store.OBJECT_DIR, "objects")
        self.assertEqual(artifact_store.SUFFIX, ".tar")
        # The modes are pinned in the module's own source, not derived from the
        # running platform, so the live store cannot silently become world-readable.
        source = (ROOT / "hk-staging" / "hk_agent" / "artifact_store.py").read_text(
            encoding="utf-8")
        self.assertIn("FILE_MODE = 0o600", source)
        self.assertIn("DIRECTORY_MODE = 0o700", source)
        self.assertIn("UNTRUSTED_BITS = 0o077", source)
        self.assertIn("MAX_PACKAGE_BYTES = 4 * 1024 * 1024 * 1024", source)


class OciArchiveTests(StoreFixture):
    """The archive format the Hong Kong host actually produces.

    The first real TEST_PR proved the parser wrong and the fixtures right: the host
    writes an OCI image layout (Docker 29.7.2 on the containerd image store) and
    every fixture in this suite wrote a legacy docker-archive.  The fixtures here
    compute every digest and size from the bytes they actually write, so a parser
    cannot agree with them by accident -- which is precisely how the legacy-only
    parser survived a green suite and then refused the host.
    """

    def oci(self, **kwargs):
        return self.sealed(save_writer=lambda path, payload: oci_save(path, payload, **kwargs))

    # --------------------------------------------------------------- accepted
    def test_an_oci_archive_seals_resolves_and_loads(self):
        record = self.oci()
        stored = self.object_path(record["package_sha256"])
        self.assertTrue(stored.is_file())
        self.assertEqual(record["image_id"], self.image_id)
        self.assertEqual(artifact_store.resolve(record["package_sha256"], self.root), str(stored))
        runner = self.runner()
        loaded = artifact_store.load(runner, record["package_sha256"], self.image_id, self.root)
        self.assertEqual(loaded["load"], "PASS")
        self.assertEqual([call[1] for call in runner.calls], ["load", "image"])

    def test_a_nested_oci_index_is_followed(self):
        """``manifests[0]`` is not an index entry; the graph is followed instead."""
        for nesting in (1, 2, 3):
            with self.subTest(nesting=nesting):
                self.assertEqual(self.oci(nesting=nesting)["image_id"], self.image_id)

    def test_the_deepest_legal_nesting_is_still_followed(self):
        record = self.oci(nesting=artifact_store.MAX_DESCRIPTOR_DEPTH)
        self.assertEqual(record["image_id"], self.image_id)

    def test_an_attestation_manifest_is_not_the_candidate(self):
        """Docker writes attestations into the same index; they are not the image."""
        self.assertEqual(self.oci(attestation=True)["image_id"], self.image_id)

    def test_an_unrelated_member_is_ignored(self):
        """An archive may carry anything else; none of it can change which image it is."""
        record = self.sealed(save_writer=appended(oci_save, "notes.txt", b"anything"))
        self.assertEqual(record["image_id"], self.image_id)

    def test_a_legacy_archive_still_seals(self):
        """The format the suite started with must not have been traded for the other."""
        record = self.sealed()
        self.assertEqual(record["image_id"], self.image_id)
        self.assertTrue(self.object_path(record["package_sha256"]).is_file())

    def test_the_hybrid_format_docker_writes_is_read(self):
        """An OCI layout with a legacy index beside it, in both reference forms.

        This is the shape the failing traceback pointed at: ``manifest.json`` was
        present, was a one-element list, and its ``Config`` was not a bare digest.
        """
        for reference in (None, "blobs/sha256/" + self.config_digest, self.config_digest):
            with self.subTest(reference=reference):
                record = self.sealed(save_writer=lambda path, payload, ref=reference:
                                     hybrid_save(path, payload, reference=ref))
                self.assertEqual(record["image_id"], self.image_id)

    def test_the_candidate_identity_is_the_config_bytes_and_nothing_else(self):
        """Three identities, never interchanged.

        The image id is the SHA256 of the config bytes.  The package is addressed by
        the SHA256 of the whole archive, and every node of the graph carries a digest
        of its own.  Only the first decides which image the archive is.
        """
        record = self.oci(attestation=True)
        stored = self.object_path(record["package_sha256"])
        archive_sha = hashlib.sha256(stored.read_bytes()).hexdigest()
        nested = json.loads(read_tar(stored)["index.json"])["manifests"][0]["digest"]
        self.assertEqual(archive_sha, record["package_sha256"])
        self.assertEqual(record["image_id"], "sha256:" + self.config_digest)
        self.assertNotEqual(nested, "sha256:" + self.config_digest)
        self.assertNotEqual(archive_sha, self.config_digest)

    # --------------------------------------------------------------- refused
    def test_bytes_that_are_not_the_claimed_image_are_refused(self):
        """Docker insisting the image is X does not make the archive be X."""
        runner = self.runner(save_writer=oci_save)
        runner.save_bytes = b'{"architecture":"arm64"}'
        runner.inspect_answers[self.ref] = self.image_id
        with self.assertRaisesRegex(artifact_store.Reject, "SEALED_ARTIFACT_CONFIG_MISMATCH"):
            artifact_store.seal(runner, self.ref, self.image_id, self.root)
        self.assertEqual(list((self.store / "objects").iterdir()), [])

    def test_a_blob_that_does_not_hash_to_its_descriptor_is_refused(self):
        def transform(entries):
            entries["blobs/sha256/" + self.config_digest] = b'{"architecture":"arm64"}'

        self.refuses("SEALED_ARTIFACT_BLOB_MISMATCH", mutated(oci_save, transform))

    def test_a_descriptor_with_the_wrong_size_is_refused(self):
        self.refuses("SEALED_ARTIFACT_BLOB_MISMATCH",
                     mutated(oci_save, lambda entries: refile(
                         entries, lambda manifest: manifest["config"].__setitem__(
                             "size", manifest["config"]["size"] + 1))))

    def test_a_descriptor_whose_blob_is_absent_is_refused(self):
        self.refuses("SEALED_ARTIFACT_BLOB_MISSING",
                     mutated(oci_save, lambda entries: entries.pop(
                         "blobs/sha256/" + self.config_digest)))

    def test_a_layer_blob_that_is_absent_is_refused(self):
        """Every blob the graph describes must be there, layers included."""
        layers = [b"layer-one", b"layer-two"]

        def transform(entries):
            for name in [name for name in entries
                         if name.startswith("blobs/sha256/") and entries[name] in layers]:
                entries.pop(name)

        self.refuses("SEALED_ARTIFACT_BLOB_MISSING",
                     mutated(lambda path, payload: oci_save(path, payload, layers=layers),
                             transform))

    def test_a_duplicate_layout_marker_is_refused(self):
        """Two `index.json` members is one name too many to be authority."""
        self.refuses("SEALED_ARTIFACT_MEMBER_DUPLICATE",
                     appended(oci_save, "index.json", b"{}"))

    def test_a_duplicate_blob_path_is_refused(self):
        self.refuses("SEALED_ARTIFACT_MEMBER_DUPLICATE",
                     appended(oci_save, "blobs/sha256/" + self.config_digest, b"second copy"))

    def test_an_unsupported_media_type_is_never_candidate_authority(self):
        self.refuses("SEALED_ARTIFACT_MEDIA_TYPE_UNSUPPORTED",
                     mutated(oci_save, lambda entries: refile(
                         entries, lambda manifest: manifest["config"].__setitem__(
                             "mediaType", "application/vnd.example.image.v1+json"))))

    def test_a_descriptor_graph_that_is_too_deep_is_refused(self):
        self.refuses("SEALED_ARTIFACT_DESCRIPTOR_LIMIT",
                     lambda path, payload: oci_save(
                         path, payload, nesting=artifact_store.MAX_DESCRIPTOR_DEPTH + 1))

    def test_a_descriptor_count_over_the_budget_is_refused(self):
        self._relax(artifact_store, "MAX_DESCRIPTOR_COUNT", 1)
        self.refuses("SEALED_ARTIFACT_DESCRIPTOR_LIMIT",
                     lambda path, payload: oci_save(path, payload, attestation=True))

    def test_one_identity_at_two_canonical_locations_is_refused(self):
        """Ambiguity is refused, never resolved by preferring a location."""
        self.refuses("SEALED_ARTIFACT_BLOB_AMBIGUOUS",
                     mutated(hybrid_save, lambda entries: entries.__setitem__(
                         self.config_digest, self.config)))

    def test_two_layouts_that_name_different_images_are_refused(self):
        def transform(entries):
            manifest_digest = [name.split("/")[-1] for name in entries
                               if name.startswith("blobs/sha256/")
                               and b'"config"' in entries[name]][0]
            entries["manifest.json"] = json.dumps(
                [{"Config": "blobs/sha256/" + manifest_digest, "RepoTags": [], "Layers": []}]
            ).encode()

        self.refuses("SEALED_ARTIFACT_LAYOUT_AMBIGUOUS", mutated(hybrid_save, transform))

    def test_a_member_that_traverses_is_refused(self):
        self.refuses("SEALED_ARTIFACT_MEMBER_UNSAFE",
                     appended(oci_save, "../outside", b"x"))

    def test_an_absolute_member_is_refused(self):
        self.refuses("SEALED_ARTIFACT_MEMBER_UNSAFE",
                     appended(oci_save, "/etc/passwd", b"x"))

    def test_a_symlinked_blob_is_refused(self):
        self.refuses("SEALED_ARTIFACT_MEMBER_UNSAFE",
                     appended(oci_save, "blobs/sha256/" + "f" * 64, kind=tarfile.SYMTYPE,
                              linkname="../../outside"))

    def test_a_hardlinked_blob_is_never_authority(self):
        self.refuses("SEALED_ARTIFACT_MEMBER_UNSAFE",
                     appended(oci_save, "blobs/sha256/" + "f" * 64, kind=tarfile.LNKTYPE,
                              linkname="blobs/sha256/" + self.config_digest))

    def test_an_oci_layout_without_its_marker_is_refused(self):
        self.refuses("SEALED_ARTIFACT_OCI_INVALID",
                     mutated(oci_save, lambda entries: entries.pop("oci-layout")))

    def test_an_index_that_names_no_image_is_refused(self):
        def transform(entries):
            entries["index.json"] = json.dumps(
                {"schemaVersion": 2, "mediaType": OCI_INDEX_TYPE, "manifests": []}).encode()

        self.refuses("SEALED_ARTIFACT_OCI_INVALID", mutated(oci_save, transform))

    def test_an_archive_that_is_not_an_archive_is_refused(self):
        def not_an_archive(path, config_bytes):
            pathlib.Path(path).write_bytes(b"this is not a tar archive")

        self.refuses("SEALED_ARTIFACT_ARCHIVE_INVALID", not_an_archive)

    def test_a_legacy_index_that_is_not_one_entry_is_refused(self):
        for payload in (b"[]", b'{"Config":"x"}',
                        json.dumps([{"Config": "a" * 64}, {"Config": "b" * 64}]).encode()):
            with self.subTest(payload=payload[:20]):
                self.refuses("SEALED_ARTIFACT_ARCHIVE_INVALID",
                             mutated(synthetic_save,
                                     lambda entries, body=payload: entries.__setitem__(
                                         "manifest.json", body)))

    def test_a_legacy_reference_that_names_a_path_of_its_own_choosing_is_refused(self):
        """The digest comes from the reference's own last component, and only two
        locations are ever read; anything else is a path the JSON tried to choose."""
        cases = (("../../etc/passwd", "SEALED_ARTIFACT_MEMBER_UNSAFE"),
                 ("/etc/passwd", "SEALED_ARTIFACT_MEMBER_UNSAFE"),
                 ("elsewhere/" + self.config_digest, "SEALED_ARTIFACT_MEMBER_UNSAFE"),
                 ("blobs/sha256/" + "f" * 64, "SEALED_ARTIFACT_BLOB_MISSING"),
                 ("not-a-digest", "SEALED_ARTIFACT_ARCHIVE_INVALID"),
                 ("blobs/sha256/" + "z" * 64, "SEALED_ARTIFACT_ARCHIVE_INVALID"))
        for reference, code in cases:
            with self.subTest(reference=reference):
                self.refuses(code, mutated(
                    synthetic_save,
                    lambda entries, ref=reference: entries.__setitem__(
                        "manifest.json", json.dumps([{"Config": ref}]).encode())))


class OciReaderTests(StoreFixture):
    """The executor's read side must accept the same packages the agent seals.

    A writer that seals a layout the reader refuses is worse than either half being
    wrong: the candidate would be sealed as durable and then be unusable at CANARY
    or DEPLOY.  Both formats are therefore proved on both sides.
    """

    def setUp(self):
        super().setUp()
        self.reader = self.setup_reader()

    def seal_and_read(self, save_writer, **kwargs):
        record = self.sealed(save_writer=save_writer, **kwargs)
        runner = self.runner()
        result = self.reader.materialise(runner, record["package_sha256"], self.image_id,
                                         self.root)
        return record, runner, result

    def test_the_reader_materialises_an_oci_package(self):
        record, runner, result = self.seal_and_read(oci_save)
        self.assertEqual(result["artifact_materialised"], "PASS")
        self.assertEqual([call[1] for call in runner.calls], ["load", "image"])
        self.assertEqual(runner.calls[1][3], self.image_id)

    def test_the_reader_materialises_a_legacy_package(self):
        _, runner, result = self.seal_and_read(synthetic_save)
        self.assertEqual(result["artifact_package"], "PASS")

    def test_the_reader_materialises_the_hybrid_format(self):
        _, _, result = self.seal_and_read(hybrid_save)
        self.assertEqual(result["artifact_materialised"], "PASS")

    def test_the_reader_refuses_a_package_that_is_not_the_candidate(self):
        record = self.sealed(save_writer=oci_save)
        other = "sha256:" + hashlib.sha256(b'{"architecture":"arm64"}').hexdigest()
        with self.assertRaisesRegex(self.reader.Reject, "E_ARTIFACT_CONFIG_MISMATCH"):
            self.reader.materialise(self.runner(), record["package_sha256"], other, self.root)

    def test_the_reader_refuses_a_tampered_package(self):
        record = self.sealed(save_writer=oci_save)
        self.object_path(record["package_sha256"]).write_bytes(b"tamper")
        with self.assertRaisesRegex(self.reader.Reject, "E_ARTIFACT_PACKAGE_TAMPERED"):
            self.reader.materialise(self.runner(), record["package_sha256"], self.image_id,
                                    self.root)

    def test_the_reader_refuses_a_load_that_yields_another_image(self):
        record = self.sealed(save_writer=oci_save)
        runner = self.runner(load_answers={self.image_id: "sha256:" + "7" * 64})
        with self.assertRaisesRegex(self.reader.Reject, "E_ARTIFACT_LOADED_IMAGE_MISMATCH"):
            self.reader.materialise(runner, record["package_sha256"], self.image_id, self.root)

    def test_the_reader_refuses_an_oci_graph_the_writer_would_refuse(self):
        """Same fixture corpus, same refusals: neither side is the weaker one."""
        def transform(entries):
            entries.pop("blobs/sha256/" + self.config_digest)

        with self.assertRaisesRegex(artifact_store.Reject, "SEALED_ARTIFACT_BLOB_MISSING"):
            self.sealed(save_writer=mutated(oci_save, transform))
        self.assertEqual(list((self.store / "objects").iterdir()), [])


class CrossUidWriterTests(StoreFixture):
    """The writer half of the cross-uid contract.

    In production the store is written by ``go-hk-agent`` (systemd
    ``User=go-hk-agent``) and read by root, because the agent invokes the Hong Kong
    executor as ``sudo``.  Ownership is a property of the evidence -- which account
    may have written it -- so the writer compares against the trusted account and
    additionally refuses to run as anything else.
    """

    def test_the_writer_accepts_a_store_owned_by_the_trusted_account(self):
        self.as_writer()
        record = self.sealed()
        stored = self.object_path(record["package_sha256"])
        self.assertEqual(hashlib.sha256(stored.read_bytes()).hexdigest(),
                         record["package_sha256"])

    def test_the_writer_refuses_a_store_owned_by_another_account(self):
        # Both the running account and the contract say "somebody else", and the
        # store on disk is not theirs: the owner check is what has to refuse.
        foreign = self.other_identity()
        self.as_writer(foreign)
        self.anchor(lambda: foreign)
        with self.assertRaisesRegex(artifact_store.Reject, "SEALED_ARTIFACT_STORE_UNTRUSTED"):
            self.sealed()
        self.assertEqual(list((self.store / "objects").iterdir()), [],
                         "a store owned by another account must receive nothing")

    def test_a_root_owned_store_is_refused_when_the_writer_must_be_go_hk_agent(self):
        """root is the reader, never the writer.

        On a platform where every path reports as root's, the directory on disk is
        root-owned and this is exactly the case under test; elsewhere the same rule
        is exercised by the test above with a synthetic foreign account.
        """
        if self.identity != (0, 0):
            self.skipTest("this platform cannot present a root-owned store")
        foreign = self.other_identity()
        self.as_writer(foreign)
        self.anchor(lambda: foreign)
        with self.assertRaisesRegex(artifact_store.Reject, "SEALED_ARTIFACT_STORE_UNTRUSTED"):
            self.sealed()

    def test_the_writer_refuses_to_run_as_another_account(self):
        self._relax(artifact_store, "_process_identity", lambda: self.other_identity())
        with self.assertRaisesRegex(artifact_store.Reject, "SEALED_ARTIFACT_WRITER_IDENTITY"):
            self.sealed()
        self.assertEqual(list((self.store / "objects").iterdir()), [])

    def test_the_writer_runs_as_the_trusted_account(self):
        self.as_writer()
        self.assertEqual(artifact_store.require_writer_identity(), self.identity)
        self.assertTrue(self.sealed()["package_sha256"])

    @unittest.skipUnless(POSIX, "mode bits are not expressible on this platform")
    def test_a_store_with_the_wrong_mode_is_never_written_to(self):
        self.as_writer()
        os.chmod(self.store, 0o755)
        self.addCleanup(os.chmod, self.store, artifact_store.DIRECTORY_MODE)
        with self.assertRaisesRegex(artifact_store.Reject, "SEALED_ARTIFACT_STORE_UNTRUSTED"):
            self.sealed()

    def test_an_unresolvable_writer_account_is_never_guessed(self):
        def unavailable():
            raise artifact_store.Reject("SEALED_ARTIFACT_ACCOUNT_UNAVAILABLE")
        self.anchor(unavailable)
        for call in (artifact_store.trusted_identity,
                     self.sealed,
                     lambda: artifact_store.resolve("a" * 64, self.root)):
            with self.assertRaisesRegex(artifact_store.Reject,
                                        "SEALED_ARTIFACT_ACCOUNT_UNAVAILABLE"):
                call()

    def test_the_anchor_is_a_shape_checked_pair_of_ids(self):
        for value in ((1,), (1, 2, 3), "1:2", (-1, 2), (1.5, 2), (True, 2), (None, 2)):
            self.anchor(lambda value=value: value)
            with self.assertRaisesRegex(artifact_store.Reject,
                                        "SEALED_ARTIFACT_ACCOUNT_UNTRUSTED"):
                artifact_store.trusted_identity()

    def test_seal_reverifies_the_stored_object_before_reporting_it_sealed(self):
        """A stored object a reader would refuse is never reported as sealed."""
        self.as_writer()
        record = self.sealed()
        stored = self.object_path(record["package_sha256"])
        if not POSIX:
            self._relax(artifact_store, "UNTRUSTED_BITS", 0o077)
        os.chmod(stored, 0o666)
        self.addCleanup(os.chmod, stored, artifact_store.FILE_MODE)
        with self.assertRaisesRegex(artifact_store.Reject, "SEALED_ARTIFACT_PACKAGE_UNTRUSTED"):
            self.sealed()

    def test_resealing_never_replaces_the_stored_object(self):
        self.as_writer()
        record = self.sealed()
        stored = self.object_path(record["package_sha256"])
        before = os.stat(stored).st_mtime_ns
        self.assertEqual(self.sealed()["package_sha256"], record["package_sha256"])
        self.assertEqual(os.stat(stored).st_mtime_ns, before,
                         "an address that already resolved must not be rewritten")


class CrossUidReaderTests(StoreFixture):
    """The reader half: root consumes the store, the writer still owns it."""

    def setUp(self):
        super().setUp()
        self.reader = load_reader()
        # The reader is a separate module with its own anchor, exactly as it ships.
        self.anchor(lambda: self.identity, module=self.reader)
        if not POSIX:
            # The reader carries its own copy of the constants; relax only what
            # this platform can express, never the rule itself.
            self._relax(self.reader, "DIRECTORY_MODE",
                        stat.S_IMODE(os.stat(self.store).st_mode))
            self._relax(self.reader, "FILE_MODE", 0o666)
            self._relax(self.reader, "UNTRUSTED_BITS", 0)

    def sealed_for_reading(self):
        record = self.sealed()
        return record, self.object_path(record["package_sha256"])

    def test_the_reader_accepts_an_object_the_trusted_writer_owns(self):
        """Root reading a package it does not own is the normal case."""
        record, stored = self.sealed_for_reading()
        self.anchor(lambda: self.identity, module=self.reader)
        self.assertEqual(self.reader.resolve(record["package_sha256"], self.root), str(stored))

    def test_the_reader_never_consults_its_own_process_identity(self):
        source = READER_PATH.read_text(encoding="utf-8")
        for symbol in ("geteuid", "getuid", "getegid", "getgid", "getlogin"):
            self.assertNotIn(symbol, source,
                             "the reader judges the writer's account, not its own")
        record, stored = self.sealed_for_reading()
        self.anchor(lambda: self.identity, module=self.reader)
        self.assertEqual(self.reader.resolve(record["package_sha256"], self.root), str(stored))

    def test_the_reader_judges_the_writer_account_not_the_owner_of_the_file(self):
        source = READER_PATH.read_text(encoding="utf-8")
        self.assertIn("if (info.st_uid, info.st_gid) != trusted_identity():", source)
        self.assertIn("def trusted_identity():", source)

    def test_the_reader_refuses_a_store_owned_by_another_account(self):
        record, _ = self.sealed_for_reading()
        self.anchor(lambda: self.other_identity(), module=self.reader)
        with self.assertRaisesRegex(self.reader.Reject, "E_ARTIFACT_STORE_UNTRUSTED"):
            self.reader.resolve(record["package_sha256"], self.root)

    def test_a_root_owned_store_is_refused_when_the_writer_must_be_go_hk_agent(self):
        if self.identity != (0, 0):
            self.skipTest("this platform cannot present a root-owned store")
        record, _ = self.sealed_for_reading()
        self.anchor(lambda: self.other_identity(), module=self.reader)
        with self.assertRaisesRegex(self.reader.Reject, "E_ARTIFACT_STORE_UNTRUSTED"):
            self.reader.resolve(record["package_sha256"], self.root)

    def test_the_reader_refuses_an_object_whose_mode_is_not_the_sealed_one(self):
        record, stored = self.sealed_for_reading()
        if not POSIX:
            self._relax(self.reader, "UNTRUSTED_BITS", 0o077)
        os.chmod(stored, 0o666)
        self.addCleanup(os.chmod, stored, self.reader.FILE_MODE)
        with self.assertRaisesRegex(self.reader.Reject, "E_ARTIFACT_PACKAGE_UNTRUSTED"):
            self.reader.resolve(record["package_sha256"], self.root)

    def test_the_reader_refuses_an_unresolvable_writer_account(self):
        record, _ = self.sealed_for_reading()

        def unavailable():
            raise self.reader.Reject("E_ARTIFACT_ACCOUNT_UNAVAILABLE")
        self.anchor(unavailable, module=self.reader)
        with self.assertRaisesRegex(self.reader.Reject, "E_ARTIFACT_ACCOUNT_UNAVAILABLE"):
            self.reader.resolve(record["package_sha256"], self.root)

    @unittest.skipUnless(POSIX and hasattr(os, "geteuid") and os.geteuid() == 0,
                         "constructing a foreign-owned object requires root")
    def test_an_object_really_owned_by_another_account_is_refused(self):
        """The strongest form of the rule, on a host that can express it.

        Both halves run as ordinary accounts in this suite, so this case is skipped
        unless the suite itself is running as root -- which is what the Hong Kong
        executor does.  It is kept so the rule is exercised wherever it can be, and
        so the skip is visible rather than implied.
        """
        record, stored = self.sealed_for_reading()
        foreign = 1 if self.identity[0] != 1 else 2
        os.chown(stored, foreign, foreign)
        self.addCleanup(os.chown, stored, self.identity[0], self.identity[1])
        with self.assertRaisesRegex(self.reader.Reject, "E_ARTIFACT_PACKAGE_UNTRUSTED"):
            self.reader.resolve(record["package_sha256"], self.root)


class CrossSideContractTests(unittest.TestCase):
    """The agent writes the store and the Hong Kong executor reads it.

    They ship in different units, so they cannot share a module.  They can only
    share a contract, and the contract is these constants -- so a test reads both
    files and fails if either side moves without the other.
    """

    WRITER = ROOT / "hk-staging" / "hk_agent" / "artifact_store.py"
    READER = READER_PATH

    NAMES = ("SCHEMA", "STORE_ROOT", "OBJECT_DIR", "SUFFIX", "MAX_PACKAGE_BYTES",
             "SHA256", "IMAGE_ID", "CONFIG_NAME",
             # The trust anchor is part of the interface between the two halves:
             # if they ever disagree about whose ownership counts, one of them is
             # reading a store the other would refuse to write.
             "TRUSTED_WRITER_USER", "TRUSTED_WRITER_GROUP", "FILE_MODE",
             "DIRECTORY_MODE", "UNTRUSTED_BITS",
             # The archive grammar is the other half of the same interface: a
             # writer that accepts a graph the reader refuses would seal a durable
             # artifact that CANARY and DEPLOY could never use.
             "LAYOUT_NAME", "INDEX_NAME", "BLOB_DIR", "OCI_LAYOUT_VERSION",
             "INDEX_MEDIA_TYPES", "MANIFEST_MEDIA_TYPES", "CONFIG_MEDIA_TYPES",
             "MAX_DESCRIPTOR_DEPTH", "MAX_DESCRIPTOR_COUNT", "MAX_ARCHIVE_MEMBERS",
             "MAX_DOCUMENT_BYTES", "ARCHIVE_REFUSALS")

    def names(self, module):
        return {name: getattr(module, name) for name in self.NAMES}

    def test_both_sides_declare_the_same_contract(self):
        self.assertTrue(self.READER.is_file(), "the executor reader moved: %s" % self.READER)
        self.assertEqual(self.names(load_reader()), self.names(artifact_store))

    def test_both_sides_name_the_same_trusted_writer_account(self):
        """The owner of the evidence, named identically on both sides.

        This is the relationship that failed before: the writer compared with the
        reader's uid and the reader compared with its own, so one operation could
        never be satisfied by a store either half would write.
        """
        for path in (self.WRITER, self.READER):
            source = path.read_text(encoding="utf-8")
            self.assertIn('TRUSTED_WRITER_USER = "go-hk-agent"', source, path.name)
            self.assertIn('TRUSTED_WRITER_GROUP = "go-hk-agent"', source, path.name)
            self.assertIn("def trusted_identity():", source, path.name)
            # The anchor is resolved, never written down as a number.
            self.assertNotIn("= 1000", source, path.name)
            self.assertRegex(source, r"_IDENTITY_RESOLVER = _system_identity")

    def test_only_the_writer_gates_its_own_identity(self):
        """A deliberate asymmetry: writing is gated, reading is not.

        The agent must be the trusted account to seal; root must be able to read a
        package it does not own.  The two files therefore differ here on purpose,
        and this test pins the direction of the difference rather than the text.
        """
        writer = self.WRITER.read_text(encoding="utf-8")
        reader = self.READER.read_text(encoding="utf-8")
        self.assertIn("def require_writer_identity():", writer)
        self.assertIn("SEALED_ARTIFACT_WRITER_IDENTITY", writer)
        self.assertNotIn("require_writer_identity", reader)
        self.assertNotIn("WRITER_IDENTITY", reader)

    def test_the_fixed_store_path_and_mode_are_written_in_both_files(self):
        for path in (self.WRITER, self.READER):
            source = path.read_text(encoding="utf-8")
            self.assertIn('STORE_ROOT = "/var/lib/go-hk-artifacts"', source, path.name)
            self.assertIn('OBJECT_DIR = "objects"', source, path.name)
            self.assertIn("MAX_PACKAGE_BYTES = 4 * 1024 * 1024 * 1024", source, path.name)
            self.assertIn("FILE_MODE = 0o600", source, path.name)
            self.assertIn("DIRECTORY_MODE = 0o700", source, path.name)

    def test_the_executor_never_accepts_a_caller_supplied_path(self):
        source = self.READER.read_text(encoding="utf-8")
        # The only path it will open is derived from a validated content address.
        self.assertIn("def resolve(package_sha256, root=STORE_ROOT):", source)
        self.assertNotIn("sys.argv", source)
        self.assertNotIn("input(", source)
        self.assertIn("DOCKER", source.upper().replace('"/usr/bin/docker"', "DOCKER"))

    # -- the same entry points, and the same decisions ------------------------
    def test_both_sides_offer_the_same_entry_point(self):
        """The same three operations, named for the side that describes them.

        The writer *loads* the image back (it is the one that removed the tag); the
        executor *materialises* it (it never had the tag at all).  Everything else --
        the archive grammar and the object checks -- is one entry point by one name,
        so a caller reading either file sees the same interface.
        """
        reader = load_reader()
        for writer_name, reader_name in (("image_config_digest", "image_config_digest"),
                                         ("resolve", "resolve"),
                                         ("load", "materialise")):
            with self.subTest(entry_point=writer_name):
                self.assertEqual(
                    list(inspect.signature(getattr(artifact_store, writer_name)).parameters),
                    list(inspect.signature(getattr(reader, reader_name)).parameters),
                    "%s is not the same entry point on both sides" % writer_name)

    def test_both_sides_declare_the_same_archive_refusal_vocabulary(self):
        reader = load_reader()
        self.assertEqual(artifact_store.ARCHIVE_REFUSALS, reader.ARCHIVE_REFUSALS)
        self.assertEqual(len(set(artifact_store.ARCHIVE_REFUSALS)),
                         len(artifact_store.ARCHIVE_REFUSALS))
        for module, source in ((artifact_store, self.WRITER), (reader, self.READER)):
            text = source.read_text(encoding="utf-8")
            used = set(re.findall(r'_refuse\("([A-Z_]+)"\)', text))
            self.assertTrue(used, source.name)
            self.assertLessEqual(used, set(module.ARCHIVE_REFUSALS),
                                 "%s refuses with a code outside the shared vocabulary" % source.name)
            self.assertIn("_REFUSAL_PREFIX = ", text, source.name)

    @staticmethod
    def outcome(module, path, image_id):
        """``(True, digest)`` or ``(False, refusal)`` -- never one side's raw text."""
        try:
            return True, module.image_config_digest(path, image_id)
        except module.Reject as exc:
            return False, str(exc)[len(module._REFUSAL_PREFIX):]

    def corpus(self):
        """Every accepted and refused shape, built from the bytes actually written."""
        config = b'{"architecture":"amd64","os":"linux"}'
        digest = hashlib.sha256(config).hexdigest()
        image_id = "sha256:" + digest
        other = "sha256:" + hashlib.sha256(b'{"architecture":"arm64"}').hexdigest()
        work = pathlib.Path(tempfile.mkdtemp(prefix="cc-archive-"))
        self.addCleanup(shutil.rmtree, work, True)
        cases = []

        def write(name, writer, identity=image_id):
            path = work / (name + ".tar")
            writer(str(path), config)
            cases.append((name, str(path), identity))

        def relabel_legacy_to_another_blob(entries):
            other_blob = [name.split("/")[-1] for name in entries
                          if name.startswith("blobs/sha256/") and b'"config"' in entries[name]][0]
            entries["manifest.json"] = json.dumps(
                [{"Config": "blobs/sha256/" + other_blob, "RepoTags": [], "Layers": []}]
            ).encode()

        write("legacy", synthetic_save)
        write("oci", oci_save)
        write("oci-nested", lambda path, payload: oci_save(path, payload, nesting=2))
        write("oci-attested", lambda path, payload: oci_save(path, payload, attestation=True))
        write("oci-deepest-legal",
              lambda path, payload: oci_save(path, payload,
                                             nesting=artifact_store.MAX_DESCRIPTOR_DEPTH))
        write("hybrid-oci-path", hybrid_save)
        write("hybrid-flat-path",
              lambda path, payload: hybrid_save(path, payload, reference=digest))
        write("unknown-extra-member",
              appended(oci_save, "notes.txt", b"anything"))
        write("not-the-candidate", oci_save, identity=other)
        write("blob-absent", mutated(oci_save, lambda entries: entries.pop(
            "blobs/sha256/" + digest)))
        write("blob-mismatched", mutated(oci_save, lambda entries: entries.__setitem__(
            "blobs/sha256/" + digest, b'{"architecture":"arm64"}')))
        write("descriptor-size-wrong", mutated(oci_save, lambda entries: refile(
            entries, lambda manifest: manifest["config"].__setitem__(
                "size", manifest["config"]["size"] + 1))))
        write("media-type-unsupported", mutated(oci_save, lambda entries: refile(
            entries, lambda manifest: manifest["config"].__setitem__(
                "mediaType", "application/vnd.example.image.v1+json"))))
        write("layout-marker-absent", mutated(oci_save, lambda entries: entries.pop("oci-layout")))
        write("index-names-no-image", mutated(oci_save, lambda entries: entries.__setitem__(
            "index.json", json.dumps({"schemaVersion": 2, "mediaType": OCI_INDEX_TYPE,
                                      "manifests": []}).encode())))
        write("nested-too-deep", lambda path, payload: oci_save(
            path, payload, nesting=artifact_store.MAX_DESCRIPTOR_DEPTH + 1))
        write("duplicate-index", appended(oci_save, "index.json", b"{}"))
        write("duplicate-blob", appended(oci_save, "blobs/sha256/" + digest, b"copy"))
        write("member-traverses", appended(oci_save, "../outside", b"x"))
        write("member-absolute", appended(oci_save, "/etc/passwd", b"x"))
        write("blob-is-a-symlink", appended(oci_save, "blobs/sha256/" + "f" * 64,
                                            kind=tarfile.SYMTYPE, linkname="../../outside"))
        write("blob-is-a-hardlink", appended(oci_save, "blobs/sha256/" + "f" * 64,
                                             kind=tarfile.LNKTYPE,
                                             linkname="blobs/sha256/" + digest))
        write("identity-twice", mutated(hybrid_save, lambda entries: entries.__setitem__(
            digest, config)))
        write("layouts-disagree", mutated(hybrid_save, relabel_legacy_to_another_blob))
        write("legacy-index-malformed", mutated(synthetic_save, lambda entries: entries.__setitem__(
            "manifest.json", json.dumps([{"Config": "a" * 64}, {"Config": "b" * 64}]).encode())))
        write("not-an-archive", lambda path, payload: pathlib.Path(path).write_bytes(b"nope"))
        return cases

    def test_both_sides_decide_every_archive_the_same_way(self):
        """One corpus, two independent implementations, one verdict each.

        This is the test that would have caught a writer accepting a graph the reader
        refuses -- the arrangement in which a candidate is sealed as durable and then
        cannot be CANARYed or DEPLOYed.
        """
        reader = load_reader()
        accepted = 0
        for name, path, image_id in self.corpus():
            with self.subTest(archive=name):
                writer_outcome = self.outcome(artifact_store, path, image_id)
                reader_outcome = self.outcome(reader, path, image_id)
                self.assertEqual(writer_outcome, reader_outcome,
                                 "%s: the writer and the reader disagree" % name)
                if writer_outcome[0]:
                    accepted += 1
                    self.assertEqual(writer_outcome[1], hashlib.sha256(
                        b'{"architecture":"amd64","os":"linux"}').hexdigest(),
                        "%s: the digest is not the config bytes" % name)
        self.assertGreaterEqual(accepted, 8, "the corpus stopped accepting real archives")


class LiveTopologyContractTests(unittest.TestCase):
    """The store contract against the units that actually run it.

    The cross-uid defect existed in the repository while every test passed,
    because the tests all ran as one account.  These checks read the deployment
    topology itself, so "one uid in the tests, two in production" cannot come back
    unnoticed.
    """

    UNIT = ROOT.parents[1] / "hk-staging" / "systemd" / "go-hk-agent.service.txt"

    def test_the_agent_unit_runs_as_the_trusted_writer_account(self):
        source = self.UNIT.read_text(encoding="utf-8")
        self.assertIn("User=%s" % artifact_store.TRUSTED_WRITER_USER, source)
        self.assertIn("Group=%s" % artifact_store.TRUSTED_WRITER_GROUP, source)
        # and the trust anchor in the code is that same account
        self.assertEqual(artifact_store.TRUSTED_WRITER_USER, "go-hk-agent")
        self.assertEqual(artifact_store.TRUSTED_WRITER_GROUP, "go-hk-agent")

    def test_the_executor_still_runs_as_root_through_a_fixed_sudo_argv(self):
        """The reader is a different account, and that path is fixed, not chosen."""
        source = (ROOT / "hk-staging" / "hk_agent" / "deployment_actions.py").read_text(
            encoding="utf-8")
        self.assertIn('SUDO_EXECUTABLE = "/usr/bin/sudo"', source)
        self.assertIn('EXECUTOR_PATH = "/usr/local/libexec/go-hk-deployctl"', source)
        self.assertIn('"-n"', source)
        self.assertNotIn("shell=True", source)

    def test_the_install_creates_the_store_for_the_writer_not_for_root(self):
        install = (ROOT / "install" / "install-hk-agent.sh").read_text(encoding="utf-8")
        self.assertIn("artifact_user=go-hk-agent", install)
        self.assertIn("artifact_group=go-hk-agent", install)
        self.assertIn('install -d -o "$artifact_uid" -g "$artifact_gid" -m 0700', install)
        self.assertNotIn('install -d -o root -g root -m 0700 "$store_root"', install)
        # An existing store is never re-owned: it holds the only copy of artifacts.
        self.assertIn("STORE_OWNER_MISMATCH", install)

    def test_the_preflight_asserts_the_store_owner_after_install(self):
        preflight = (ROOT / "install" / "preflight.sh").read_text(encoding="utf-8")
        agent = '"$(id -u go-hk-agent):$(id -g go-hk-agent)"'
        for path in ("/var/lib/go-hk-artifacts", "/var/lib/go-hk-artifacts/objects"):
            self.assertIn('test "$(stat -c %%u:%%g %s)" = %s' % (path, agent), preflight)
            self.assertIn('test "$(stat -c %%a %s)" = 700' % path, preflight)


if __name__ == "__main__":
    unittest.main()
