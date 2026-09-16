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
import io
import json
import os
import pathlib
import stat
import sys
import tarfile
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hk-staging"))

from hk_agent import artifact_store  # noqa: E402

POSIX = os.name == "posix"


class Completed:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


def synthetic_save(path, config_bytes, repo_tags=("go-hk-test-pr:" + "a" * 40,)):
    """Write a ``docker save``-shaped archive whose config blob hashes to its own name."""
    digest = hashlib.sha256(config_bytes).hexdigest()
    index = json.dumps([{"Config": digest, "RepoTags": list(repo_tags), "Layers": []}]).encode()
    with tarfile.open(path, "w") as tar:
        for name, payload in ((digest, config_bytes), ("manifest.json", index)):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    return "sha256:" + digest


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

    def __call__(self, argv, timeout=None):
        self.calls.append(list(argv))
        if argv[1] == "image" and argv[2] == "inspect":
            target = argv[3]
            return Completed(self.inspect_answers.get(target, self.image_id))
        if argv[1] == "save":
            destination = argv[argv.index("--output") + 1]
            payload = self.save_bytes if self.save_bytes is not None else self.config_bytes
            synthetic_save(destination, payload)
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

    def runner(self, **kwargs):
        runner = Runner(self.image_id, self.config)
        for key, value in kwargs.items():
            setattr(runner, key, value)
        return runner

    def sealed(self, **kwargs):
        return artifact_store.seal(self.runner(**kwargs), self.ref, self.image_id, self.root)

    def object_path(self, package_sha256):
        return self.store / "objects" / (package_sha256 + ".tar")


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


class CrossUidWriterTests(StoreFixture):
    """The writer half of the cross-uid contract.

    In production the store is written by ``go-hk-agent`` (systemd
    ``User=go-hk-agent``) and read by root, because the agent invokes the Hong Kong
    executor as ``sudo``.  Ownership is a property of the evidence -- which account
    may have written it -- so the writer compares against the trusted account and
    additionally refuses to run as anything else.
    """

    def test_the_writer_accepts_a_store_owned_by_the_trusted_account(self):
        record = self.sealed()
        stored = self.object_path(record["package_sha256"])
        self.assertEqual(hashlib.sha256(stored.read_bytes()).hexdigest(),
                         record["package_sha256"])

    def test_the_writer_refuses_a_store_owned_by_another_account(self):
        self.anchor(lambda: self.other_identity())
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
        self.anchor(lambda: self.other_identity())
        with self.assertRaisesRegex(artifact_store.Reject, "SEALED_ARTIFACT_STORE_UNTRUSTED"):
            self.sealed()

    def test_the_writer_refuses_to_run_as_another_account(self):
        self._relax(artifact_store, "_process_identity", lambda: self.other_identity())
        with self.assertRaisesRegex(artifact_store.Reject, "SEALED_ARTIFACT_WRITER_IDENTITY"):
            self.sealed()
        self.assertEqual(list((self.store / "objects").iterdir()), [])

    def test_the_writer_runs_as_the_trusted_account(self):
        self._relax(artifact_store, "_process_identity", lambda: self.identity)
        self.assertEqual(artifact_store.require_writer_identity(), self.identity)
        self.assertTrue(self.sealed()["package_sha256"])

    @unittest.skipUnless(POSIX, "mode bits are not expressible on this platform")
    def test_a_store_with_the_wrong_mode_is_never_written_to(self):
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
        record = self.sealed()
        stored = self.object_path(record["package_sha256"])
        if not POSIX:
            self._relax(artifact_store, "UNTRUSTED_BITS", 0o077)
        os.chmod(stored, 0o666)
        self.addCleanup(os.chmod, stored, artifact_store.FILE_MODE)
        with self.assertRaisesRegex(artifact_store.Reject, "SEALED_ARTIFACT_PACKAGE_UNTRUSTED"):
            self.sealed()

    def test_resealing_never_replaces_the_stored_object(self):
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
             "DIRECTORY_MODE", "UNTRUSTED_BITS")

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
