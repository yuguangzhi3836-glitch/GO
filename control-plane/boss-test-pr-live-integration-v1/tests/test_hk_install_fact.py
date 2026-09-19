"""CCV1-86 (WP-5): the Hong Kong install fact, the candidate store it binds, and the gate.

What is proven here, in the order a deployment resolves it:

* a candidate fact can only be installed under its own digest, and a legacy
  `go.hk-candidate-contract.v*` document cannot be installed at all;
* the environment graph is a controlled fact derived from the canonical runtime pointer,
  not something the executor reaches for at deployment time;
* the install fact's canonical byte form, its signature, its module set and its runtime
  digest all answer to the bytes that are actually on disk;
* the launcher refuses to run any action at all when the fact is missing, unsigned,
  signed by the wrong key, or disagrees with a single module -- and that refusal happens
  before the deploy runtime is even loaded, so no runner and no host contact exists yet;
* an installation can be replaced without losing the previous one.

Two things this suite deliberately does not pretend:

* the store policy is POSIX (uid 0, mode bits, `O_NOFOLLOW`). This workstation cannot
  grant those, so stat results are served by a shim that answers as a correct host would,
  and the policy is exercised with violating results as well -- the part a Windows run
  could never otherwise show.
* Windows marks a 0400 file read-only and then refuses to overwrite or delete it. On the
  HK host the mode is advisory to other users and `rename`/`unlink` are governed by the
  directory, so a re-install or a deliberate edit needs no such step. `writable` and
  `remove` are that difference, and it belongs to the workstation, not to the contract.

Standard library plus `cryptography` (the same dependency the agent already has for its
evidence signatures). No network, no Git, no Docker, no live Hong Kong contact.
"""
import base64
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT.parents[1]
RUNTIME = REPO / "hk-staging" / "source" / "executor" / "runtime"
LAUNCHER = REPO / "hk-staging" / "source" / "executor" / "go-hk-deployctl"
INSTALL_DIR = REPO / "hk-staging" / "install"

sys.path.insert(0, str(HERE))

import test_candidate_digest_wiring as wiring  # noqa: E402  (the WP-1/WP-4A vectors)

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402


def load_module(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


install_fact = load_module(RUNTIME / "install_fact.py", "wp5_install_fact")
candidate_source = load_module(RUNTIME / "candidate_source.py", "wp5_candidate_source")
installer = load_module(INSTALL_DIR / "hk_install_facts.py", "wp5_installer")

converged = wiring.converged
digest_of = wiring.digest_of

IMAGE = wiring.IMAGE
OTHER_IMAGE = wiring.OTHER_IMAGE
PACKAGE = wiring.PACKAGE
HEAD = wiring.HEAD
SOURCE_COMMIT = "1" * 40
SOURCE_TREE = "2" * 40
SIGNER = "eason-13490"

# The launcher names its pins after the capability; the fact names modules after their
# files. Two vocabularies, one set of bytes -- and this is where they are reconciled.
PIN_MODULES = {"COLLECTOR": "collector_runtime", "CANARY": "canary_runtime",
               "DEPLOY": "deploy_runtime", "ROLLBACK": "rollback_runtime",
               "ARTIFACT": "artifact_runtime"}

# The runtime digest of a fixed two-module vector, so that a later "harmless" change to the
# canonical form or to the sort order shows up as a failing assertion rather than as a
# silently different number.
FIXED_MODULES = [{"name": "alpha", "version": "1", "sha256": "a" * 64},
                 {"name": "beta", "version": "2", "sha256": "b" * 64}]
FIXED_RUNTIME_DIGEST = "1c1cf76cd52987e5fa8277bc72aeac93176a090c2c84f15146073069dd56ce15"


def canonical_proof(*, source_commit=SOURCE_COMMIT, source_tree=SOURCE_TREE, runtime_dir=None,
                    modules=None, verdict="PASS", **over):
    """A proof document of the shape `go-canonical-provenance install-source` writes.

    The proof's own rules -- which commit, which tree, which blobs -- are the WP-6 component's
    and are proved there, against real repositories. What is under test here is the binding
    the installer performs: a proof that is absent, refused, about another commit, about
    another tree, or silent about a module this installation will record must not install.
    """
    if modules is None:
        directory = pathlib.Path(runtime_dir or RUNTIME)
        modules = [{"name": name,
                    "path": "hk-staging/source/executor/runtime/%s.py" % name,
                    "sha256": install_fact.file_sha256(str(directory / (name + ".py"))),
                    "blob": "0" * 40}
                   for name in sorted(install_fact.RUNTIME_MODULES)]
    document = {"schema": "go.canonical-source-invariant.v1", "verdict": verdict,
                "phase": "INSTALL_SOURCE", "canonical_ref": "origin/main",
                "canonical_commit": "3" * 40, "authorized_deploy_commit": source_commit,
                "source_tree": source_tree, "modules": modules, "refusal": None,
                "codes": list(installer.CANONICAL_PROOF_CODES)}
    if verdict != "PASS":
        document["refusal"] = {"step": "commit_is_canonical",
                               "code": "E_COMMIT_NOT_CANONICAL",
                               "condition": "PROVENANCE_BROKEN"}
    document.update(over)
    return document


class OsShim:
    """`os`, with `lstat`/`fstat` answering as a correct host would.

    The policy under test is about uid and mode bits, which this workstation cannot
    express for its own files, so the shim supplies stat results instead of the policy
    being weakened. Everything else -- open, read, close, rename, path -- stays real.
    """

    def __init__(self, dir_mode=stat.S_IFDIR | 0o755, dir_uid=0,
                 file_mode=stat.S_IFREG | 0o400, file_uid=0, file_size=None):
        self.dir_mode, self.dir_uid = dir_mode, dir_uid
        self.file_mode, self.file_uid, self.file_size = file_mode, file_uid, file_size

    def __getattr__(self, name):
        return getattr(os, name)

    def lstat(self, path):
        if os.path.isdir(path):
            return types.SimpleNamespace(st_mode=self.dir_mode, st_uid=self.dir_uid)
        size = self.file_size if self.file_size is not None else os.path.getsize(path)
        return types.SimpleNamespace(st_mode=self.file_mode, st_uid=self.file_uid,
                                     st_size=size)

    def fstat(self, descriptor):
        size = self.file_size if self.file_size is not None else os.fstat(descriptor).st_size
        return types.SimpleNamespace(st_mode=self.file_mode, st_uid=self.file_uid,
                                     st_size=size)


def make_signer(directory, name="evidence-signing"):
    """A test signing key: the shape the HK evidence identity has, not a third identity."""
    key = Ed25519PrivateKey.generate()
    path = pathlib.Path(directory) / name
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                       serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    return path


class InstallCase(unittest.TestCase):
    """One controlled installation into a temporary state directory."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.state = self.root / "state"
        self.signer = make_signer(self.root)
        self.candidate = self.root / "candidate.json"
        self.write_candidate(converged())

    # ---- fixtures ----
    def write_candidate(self, document, name=None):
        name = name if name is not None else digest_of(document)
        path = self.root / (name + ".json")
        path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
        self.candidate = path
        return path

    def stub_candidate(self, document, name="candidate"):
        """Replace the candidate under test with one the installer will refuse."""
        return self.write_candidate(document, name=name)

    def pointer(self, head=HEAD, **over):
        document = {"schema": "go.canonical-hk-runtime.v1", "environment": "HK-STAGING-01",
                    "database": {"alembic_head": head}}
        document.update(over)
        return document

    def stage_runtime(self, drift_module=None):
        """A copy of the runtime directory, optionally with one module's bytes changed."""
        copy = self.root / "runtime-copy"
        if copy.exists():
            shutil.rmtree(copy)
        shutil.copytree(RUNTIME, copy, ignore=shutil.ignore_patterns("__pycache__"))
        if drift_module:
            path = copy / (drift_module + ".py")
            path.write_bytes(path.read_bytes() + b"\n# a later edit that was never installed\n")
        return copy

    def stage_lf_runtime(self):
        """The runtime as the host receives it: the repository blobs, so LF.

        `install-hk-executor-facts.sh` re-checks the staged tree against
        `hk-staging/SOURCE_SHA256SUMS.txt`, whose hashes are repository blobs, so a tree
        that is not the blobs cannot be installed. On this workstation the checkout is
        CRLF, which is why the bytes have to be normalised before they mean the same thing
        as a pin.
        """
        copy = self.root / "runtime-lf"
        if copy.exists():
            shutil.rmtree(copy)
        shutil.copytree(RUNTIME, copy, ignore=shutil.ignore_patterns("__pycache__"))
        for path in copy.glob("*.py"):
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
        return copy

    def writable(self, path):
        try:
            os.chmod(str(path), 0o600)
        except OSError:
            pass
        return path

    def remove(self, path):
        self.writable(path)
        os.unlink(str(path))

    def clear_readonly(self):
        for path in self.state.rglob("*"):
            if path.is_file():
                self.writable(path)

    # ---- the install ----
    def install(self, *, source_commit=SOURCE_COMMIT, source_tree=SOURCE_TREE,
                allowed=None, pointer=None, signing_key=None, token=None, now=None,
                runtime_dir=None, launcher=None, candidates=None, shim=None, proof=None):
        real_load = installer.load_runtime

        def patched(runtime_dir_):
            fact_module, install_module = real_load(runtime_dir_)
            install_module.os = shim or OsShim()
            return fact_module, install_module

        # The proof is built from the runtime directory this install will record, so the
        # default is a proof about exactly these bytes; a test that wants a proof that does
        # not hold passes one.
        supplied = proof if proof is not None else canonical_proof(
            source_commit=source_commit, source_tree=source_tree,
            runtime_dir=str(runtime_dir or RUNTIME))

        with patch.object(installer, "load_runtime", patched), \
             patch.object(installer, "os", shim or OsShim()):
            return installer.install(
                state_dir=str(self.state), runtime_dir=str(runtime_dir or RUNTIME),
                launcher_path=str(launcher or LAUNCHER),
                candidate_sources=[str(p) for p in (candidates or [self.candidate])],
                runtime_pointer=pointer if pointer is not None else self.pointer(),
                source_commit=source_commit, source_tree=source_tree,
                installer_identity=SIGNER, signing_key=str(signing_key or self.signer),
                canonical_proof=supplied,
                allowed_commits=allowed if allowed is not None
                else {converged()["source_commit"]},
                token=token, now=now)

    # ---- reading it back the way the launcher will ----
    def _paths(self, runtime_dir=None, launcher=None):
        return {
            "launcher_path": str(launcher or LAUNCHER),
            "runtime_dir": str(runtime_dir or RUNTIME),
            "fact_path": str(self.state / "install-fact-v1.json"),
            "key_path": str(self.state / "keys" / "install-fact-signing.pub"),
            "candidate_dir": str(self.state / "candidates-v1"),
            "environment_graph": str(self.state / "environment-graph-v1.json"),
        }

    def verify(self, shim=None, **over):
        paths = self._paths(**over)
        with patch.object(install_fact, "os", shim or OsShim()):
            return install_fact.load_installation(**paths)

    def read_fact(self):
        return json.loads((self.state / "install-fact-v1.json").read_text(encoding="utf-8"))

    def rewrite_fact(self, mutate, resign=False):
        document = self.read_fact()
        mutate(document)
        if resign:
            document.pop("signature", None)
            key = serialization.load_pem_private_key(self.signer.read_bytes(), password=None)
            document["signature"] = base64.b64encode(
                key.sign(install_fact.canonical(document))).decode("ascii")
        self.writable(self.state / "install-fact-v1.json").write_text(
            json.dumps(document, sort_keys=True), encoding="utf-8")
        return document


# --------------------------------------------------------------------------- #
# §19 the candidate store
# --------------------------------------------------------------------------- #
class CandidateStoreTests(InstallCase):
    def test_a_correct_candidate_installs_under_its_own_digest(self):
        summary = self.install()
        digest = digest_of(converged())
        self.assertEqual(summary["candidates"], [digest])
        installed = self.state / "candidates-v1" / (digest + ".json")
        self.assertTrue(installed.is_file())
        self.assertFalse(installed.is_symlink())
        self.assertTrue(self.verify())

    def test_a_file_named_after_another_digest_is_refused(self):
        self.write_candidate(converged(candidate_id="rc1-renamed"), name="f" * 64)
        with self.assertRaises(installer.InstallError) as caught:
            self.install()
        self.assertTrue(str(caught.exception).startswith(
            "E_INSTALL_CANDIDATE_FILENAME_MISMATCH"), str(caught.exception))

    def test_a_candidate_whose_body_was_edited_is_refused_by_its_filename(self):
        edited = converged()
        edited["artifact_digest"] = OTHER_IMAGE
        self.stub_candidate(edited)
        with self.assertRaises(installer.InstallError) as caught:
            self.install()
        self.assertTrue(str(caught.exception).startswith(
            "E_INSTALL_CANDIDATE_FILENAME_MISMATCH"), str(caught.exception))

    def test_every_legacy_contract_is_refused(self):
        for schema in ("go.hk-candidate-contract.v1", "go.hk-candidate-contract.v2",
                       "go.hk-candidate-contract.v3"):
            with self.subTest(schema=schema):
                legacy = converged()
                legacy["schema"] = schema
                self.stub_candidate(legacy)
                with self.assertRaises(installer.InstallError) as caught:
                    self.install()
                self.assertTrue(str(caught.exception).startswith(
                    "E_INSTALL_CANDIDATE_NOT_CONVERGED"), str(caught.exception))

    def test_a_candidate_from_outside_the_declared_lineage_is_refused(self):
        self.write_candidate(converged(source_commit="9" * 40))
        with self.assertRaises(installer.InstallError) as caught:
            self.install(allowed={SOURCE_COMMIT})
        self.assertTrue(str(caught.exception).startswith(
            "E_INSTALL_CANDIDATE_NOT_IN_LINEAGE"), str(caught.exception))

    def test_a_symlinked_candidate_destination_is_replaced_not_followed(self):
        digest = digest_of(converged())
        target = self.root / "elsewhere.json"
        target.write_text("{}", encoding="utf-8")
        (self.state / "candidates-v1").mkdir(parents=True, exist_ok=True)
        link = self.state / "candidates-v1" / (digest + ".json")
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("this platform cannot create a symlink here")
        self.install()
        self.assertFalse(link.is_symlink(), "the fact was written through the link")
        self.assertEqual(target.read_text(encoding="utf-8"), "{}")

    def test_only_root_ownership_and_a_non_writable_mode_are_acceptable(self):
        self.install()
        violations = [OsShim(file_uid=1000),                    # not root
                      OsShim(file_mode=stat.S_IFREG | 0o620),  # group writable
                      OsShim(file_mode=stat.S_IFREG | 0o606),  # world writable
                      OsShim(file_mode=stat.S_IFLNK | 0o400),  # a link, not a file
                      OsShim(file_mode=stat.S_IFDIR | 0o700)]  # not a file at all
        for shim in violations:
            with self.subTest(mode=oct(shim.file_mode), uid=shim.file_uid):
                with self.assertRaises(install_fact.Reject) as caught:
                    self.verify(shim=shim)
                self.assertEqual(str(caught.exception), "E_INSTALL_FACT_UNTRUSTED")

    def test_a_readable_but_unwritable_file_is_acceptable(self):
        for mode in (0o400, 0o440, 0o444, 0o600, 0o644):
            with self.subTest(mode=oct(mode)):
                self.assertIsNone(install_fact.file_violation(
                    types.SimpleNamespace(st_mode=stat.S_IFREG | mode, st_uid=0)))

    def test_an_untrusted_directory_on_the_way_is_a_refusal(self):
        self.install()
        for shim in (OsShim(dir_mode=stat.S_IFDIR | 0o777),
                     OsShim(dir_uid=1000),
                     OsShim(dir_mode=stat.S_IFLNK | 0o755)):
            with self.subTest(mode=oct(shim.dir_mode), uid=shim.dir_uid):
                with self.assertRaises(install_fact.Reject) as caught:
                    self.verify(shim=shim)
                self.assertEqual(str(caught.exception), "E_INSTALL_FACT_UNTRUSTED")

    def test_an_oversized_fact_is_refused_rather_than_read(self):
        self.install()
        with self.assertRaises(install_fact.Reject) as caught:
            self.verify(shim=OsShim(file_size=install_fact.MAX_FACT_BYTES + 1))
        self.assertEqual(str(caught.exception), "E_INSTALL_FACT_UNTRUSTED")

    def test_a_failed_write_leaves_neither_a_file_nor_a_temporary(self):
        self.state.mkdir(parents=True, exist_ok=True)
        target = self.state / "half-written.json"

        def explode(handle, data):
            handle.write(b"{")
            raise OSError("disk went away mid-write")

        with self.assertRaises(OSError):
            installer.atomic_write(target, b'{"a":1}\n', write=explode)
        self.assertFalse(target.exists(), "a partial file became visible")
        self.assertEqual([p.name for p in self.state.iterdir()], [],
                         "a temporary was left behind for the next run to trip over")

    def test_the_write_is_durable_before_it_is_visible(self):
        """`fsync` the file, then `fsync` the directory the rename landed in."""
        self.state.mkdir(parents=True, exist_ok=True)
        target = self.state / "durable.json"
        synced = []
        with patch.object(installer, "fsync_directory",
                          side_effect=lambda path, fsync=os.fsync: synced.append(path) or True):
            installer.atomic_write(target, b'{"a":1}\n',
                                   fsync=lambda descriptor: synced.append(descriptor))
        self.assertEqual(target.read_bytes(), b'{"a":1}\n')
        self.assertEqual(len(synced), 2, "the file and its directory must both be synced")
        self.assertEqual(synced[1], str(self.state))


# --------------------------------------------------------------------------- #
# §20 the environment graph
# --------------------------------------------------------------------------- #
class EnvironmentGraphTests(InstallCase):
    def test_the_graph_is_the_canonical_pointer_s_head(self):
        self.install()
        graph = json.loads((self.state / "environment-graph-v1.json").read_text("utf-8"))
        self.assertEqual(graph["environment"], "HK-STAGING-01")
        self.assertEqual(graph["migration_head"], HEAD)
        self.assertEqual(graph["schema"], installer.ENVIRONMENT_GRAPH_SCHEMA)
        self.assertEqual(graph["source_identity"],
                         "docs/canonical-baseline/CURRENT_HK_RUNTIME.json")

    def test_the_graph_the_launcher_reads_is_the_installed_one(self):
        self.install()
        with patch.object(candidate_source, "os", OsShim()), \
             patch.object(candidate_source, "ENVIRONMENT_GRAPH",
                          str(self.state / "environment-graph-v1.json")):
            self.assertEqual(candidate_source.environment_migration_head(), HEAD)

    def test_the_real_pointer_still_carries_the_head_the_installer_wants(self):
        """The installer's input is the repository's own pointer, not a test invention."""
        pointer = json.loads((REPO / "docs" / "canonical-baseline"
                              / "CURRENT_HK_RUNTIME.json").read_text(encoding="utf-8"))
        graph = installer.build_environment_graph(pointer)
        self.assertEqual(graph["migration_head"], pointer["database"]["alembic_head"])
        self.assertTrue(installer.MIGRATION_HEAD.fullmatch(graph["migration_head"]))

    def test_an_unsupported_environment_is_refused(self):
        with self.assertRaises(installer.InstallError) as caught:
            installer.build_environment_graph(self.pointer(), "PRODUCTION")
        self.assertEqual(str(caught.exception), "E_INSTALL_ENVIRONMENT_UNSUPPORTED")

    def test_a_pointer_without_a_head_stops_the_install(self):
        for pointer in ({}, {"database": {}}, {"database": {"alembic_head": ""}},
                        {"database": {"alembic_head": "not a head"}}, None):
            with self.subTest(pointer=pointer):
                with self.assertRaises(installer.InstallError) as caught:
                    installer.build_environment_graph(pointer)
                self.assertIn(str(caught.exception),
                              ("E_INSTALL_POINTER_INVALID",
                               "E_INSTALL_POINTER_MIGRATION_HEAD_MISSING"))

    def test_a_graph_that_does_not_match_what_was_installed_is_refused(self):
        self.install()
        self.writable(self.state / "environment-graph-v1.json").write_text(
            json.dumps({"schema": installer.ENVIRONMENT_GRAPH_SCHEMA,
                        "environment": "HK-STAGING-01",
                        "migration_head": "0135_some_other_head"}, sort_keys=True),
            encoding="utf-8")
        with self.assertRaises(install_fact.Reject) as caught:
            self.verify()
        self.assertEqual(str(caught.exception), "E_INSTALL_FACT_ENVIRONMENT_GRAPH_DRIFT")

    def test_a_missing_graph_is_refused(self):
        self.install()
        self.remove(self.state / "environment-graph-v1.json")
        with self.assertRaises(install_fact.Reject) as caught:
            self.verify()
        self.assertEqual(str(caught.exception), "E_INSTALL_FACT_ENVIRONMENT_GRAPH_MISSING")

    def test_an_off_environment_graph_is_refused_by_the_reader(self):
        self.install()
        self.writable(self.state / "environment-graph-v1.json").write_text(
            json.dumps({"environment": "HK-STAGING-02", "migration_head": HEAD}),
            encoding="utf-8")
        with patch.object(candidate_source, "os", OsShim()), \
             patch.object(candidate_source, "ENVIRONMENT_GRAPH",
                          str(self.state / "environment-graph-v1.json")):
            with self.assertRaises(candidate_source.Reject) as caught:
                candidate_source.environment_migration_head()
        self.assertEqual(str(caught.exception),
                         candidate_source.E_DATABASE_MIGRATION_GRAPH_MISMATCH)


# --------------------------------------------------------------------------- #
# §21 the install fact
# --------------------------------------------------------------------------- #
class InstallFactTests(InstallCase):
    def test_canonical_bytes_ignore_key_order_and_whitespace(self):
        left = {"b": [1, {"y": 2, "x": 1}], "a": "text"}
        right = {"a": "text", "b": [1, {"x": 1, "y": 2}]}
        self.assertEqual(install_fact.canonical(left), install_fact.canonical(right))
        self.assertEqual(install_fact.canonical(left),
                         b'{"a":"text","b":[1,{"x":1,"y":2}]}')

    def test_the_runtime_digest_has_a_fixed_vector(self):
        self.assertEqual(install_fact.runtime_digest(FIXED_MODULES), FIXED_RUNTIME_DIGEST)

    def test_the_runtime_digest_ignores_order_and_versions_but_not_bytes(self):
        self.assertEqual(install_fact.runtime_digest(list(reversed(FIXED_MODULES))),
                         FIXED_RUNTIME_DIGEST)
        relabelled = [dict(FIXED_MODULES[0], version="9"), FIXED_MODULES[1]]
        self.assertEqual(install_fact.runtime_digest(relabelled), FIXED_RUNTIME_DIGEST,
                         "version must not be able to change a module's identity")
        changed = [dict(FIXED_MODULES[0], sha256="c" * 64), FIXED_MODULES[1]]
        self.assertNotEqual(install_fact.runtime_digest(changed), FIXED_RUNTIME_DIGEST)

    def test_a_valid_installation_verifies_and_reports_an_identity(self):
        self.install()
        document = self.verify()
        identity = install_fact.installed_identity(document)
        self.assertEqual(identity["schema"], install_fact.INSTALLED_IDENTITY_SCHEMA)
        self.assertEqual(identity["source_commit"], SOURCE_COMMIT)
        self.assertEqual(identity["launcher_sha256"], document["launcher_sha256"])
        self.assertEqual(identity["runtime_digest"], document["runtime_digest"])
        self.assertEqual(identity["launcher_version"],
                         install_fact.declared_version(LAUNCHER.read_bytes()))

    def test_every_runtime_module_is_covered_including_the_dynamic_ones(self):
        """The fact must describe the whole trust chain, not only what the launcher names."""
        self.install()
        names = {module["name"] for module in self.read_fact()["runtime_modules"]}
        self.assertEqual(names, set(install_fact.RUNTIME_MODULES))
        for dynamic in ("candidate_source", "migration_guard", "media_guard",
                        "candidate_fact", "install_fact"):
            self.assertIn(dynamic, names, "a second-level module was left out")

    def test_the_module_serials_are_the_bytes_on_disk(self):
        self.install()
        for module in self.read_fact()["runtime_modules"]:
            with self.subTest(module=module["name"]):
                raw = (RUNTIME / (module["name"] + ".py")).read_bytes()
                self.assertEqual(module["sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(module["version"], install_fact.declared_version(raw))

    def test_a_version_constant_is_read_and_checked_not_decorative(self):
        self.assertEqual(install_fact.declared_version(b'"""x"""\nVERSION = "1.2.3"\n'),
                         "1.2.3")
        self.assertEqual(install_fact.declared_version(b"x = 1\n"),
                         install_fact.UNDECLARED_VERSION)
        self.assertEqual(install_fact.declared_version(b"this is not python"),
                         install_fact.UNDECLARED_VERSION)

    def test_a_broken_signature_is_refused(self):
        self.install()
        self.rewrite_fact(lambda d: d.__setitem__("signature", "A" * 88))
        with self.assertRaises(install_fact.Reject) as caught:
            self.verify()
        self.assertEqual(str(caught.exception), "E_INSTALL_FACT_SIGNATURE")

    def test_editing_the_fact_invalidates_its_signature(self):
        self.install()
        self.rewrite_fact(lambda d: d.__setitem__("runtime_digest", "0" * 64))
        with self.assertRaises(install_fact.Reject) as caught:
            self.verify()
        self.assertEqual(str(caught.exception), "E_INSTALL_FACT_SIGNATURE")

    def test_an_unknown_signer_identity_is_refused(self):
        self.install()
        self.rewrite_fact(lambda d: d.__setitem__(
            "signature_identity",
            re.sub(r"^[a-z-]+", "some-other-signer", d["signature_identity"])))
        with self.assertRaises(install_fact.Reject) as caught:
            self.verify()
        self.assertEqual(str(caught.exception), "E_INSTALL_FACT_SIGNER_UNKNOWN")

    def test_a_fact_naming_another_key_fingerprint_is_refused(self):
        self.install()
        self.rewrite_fact(lambda d: d.__setitem__(
            "signature_identity",
            "%s:SHA256:%s=" % (d["signature_identity"].split(":")[0], "A" * 43)))
        with self.assertRaises(install_fact.Reject) as caught:
            self.verify()
        self.assertEqual(str(caught.exception), "E_INSTALL_FACT_SIGNER_MISMATCH")

    def test_the_fingerprint_in_the_fact_is_compared_with_its_prefix(self):
        """The regression that made every signature look like another key's.

        `key_id()` returns `SHA256:<digest>`. A pattern that captured only the digest would
        never equal it, so verification would refuse every fact -- closed, but for the
        wrong reason and always. The positive case below is what catches that.
        """
        self.install()
        document = self.read_fact()
        match = install_fact.SIGNATURE_IDENTITY.fullmatch(document["signature_identity"])
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), install_fact.SIGNER_IDENTITY)
        self.assertTrue(match.group(2).startswith("SHA256:"))
        with patch.object(install_fact, "os", OsShim()):
            installed = install_fact.load_public_key(
                str(self.state / "keys" / "install-fact-signing.pub"))
        self.assertEqual(match.group(2), install_fact.key_id(installed))

    def test_replacing_the_public_key_invalidates_every_fact_signed_by_its_predecessor(self):
        """The fingerprint in the fact is what stops a swapped `.pub` from being believed."""
        self.install()
        key_path = self.state / "keys" / "install-fact-signing.pub"
        other = make_signer(self.root, "another-key")
        self.writable(key_path).write_bytes(installer.installed_public_key(str(other)))
        with self.assertRaises(install_fact.Reject) as caught:
            self.verify()
        self.assertEqual(str(caught.exception), "E_INSTALL_FACT_SIGNER_MISMATCH")

    def test_a_missing_installation_fact_is_refused(self):
        self.install()
        self.remove(self.state / "install-fact-v1.json")
        with self.assertRaises(install_fact.Reject) as caught:
            self.verify()
        self.assertEqual(str(caught.exception), "E_INSTALL_FACT_ABSENT")

    def test_a_temporary_fact_is_never_the_fact(self):
        self.install()
        document = self.read_fact()
        self.remove(self.state / "install-fact-v1.json")
        (self.state / "install-fact-v1.json.tmp.deadbeef").write_text(
            json.dumps(document, sort_keys=True), encoding="utf-8")
        with self.assertRaises(install_fact.Reject) as caught:
            self.verify()
        self.assertEqual(str(caught.exception), "E_INSTALL_FACT_ABSENT")

    def test_a_missing_module_is_named_in_the_refusal(self):
        self.install()
        empty = self.root / "empty-runtime"
        empty.mkdir()
        with self.assertRaises(install_fact.Reject) as caught:
            install_fact.verify_runtime_modules(self.read_fact(), str(empty))
        self.assertEqual(str(caught.exception), "E_INSTALL_FACT_MODULE_MISSING:install_fact")

    def test_a_module_the_fact_omits_is_a_refusal_not_a_shorter_list(self):
        self.install()
        self.rewrite_fact(lambda d: d["runtime_modules"].pop())
        with self.assertRaises(install_fact.Reject) as caught:
            self.verify()
        self.assertEqual(str(caught.exception), "E_INSTALL_FACT_MODULES")

    def test_a_drifted_module_is_named_in_the_refusal(self):
        """The realistic drift: the fact is internally consistent, the disk is not.

        Installed from a staged tree in which one module had been edited; the fact and its
        runtime digest agree with each other, and the host's bytes do not agree with the
        fact. That is what a partial or out-of-band change looks like from here.
        """
        staged = self.stage_runtime(drift_module="deploy_runtime")
        self.install(runtime_dir=staged)
        with self.assertRaises(install_fact.Reject) as caught:
            self.verify(runtime_dir=RUNTIME)
        self.assertEqual(str(caught.exception), "E_INSTALL_FACT_MODULE_DRIFT:deploy_runtime")

    def test_a_runtime_digest_that_does_not_describe_its_modules_is_refused(self):
        self.install()
        self.rewrite_fact(lambda d: d.__setitem__("runtime_digest", "0" * 64), resign=True)
        with self.assertRaises(install_fact.Reject) as caught:
            self.verify()
        self.assertEqual(str(caught.exception), "E_INSTALL_FACT_RUNTIME_DIGEST")

    def test_a_version_that_contradicts_the_module_is_refused(self):
        self.install()
        self.rewrite_fact(lambda d: d["runtime_modules"][0].__setitem__("version", "9.9.9"),
                          resign=True)
        with self.assertRaises(install_fact.Reject) as caught:
            self.verify()
        self.assertTrue(str(caught.exception).startswith("E_INSTALL_FACT_MODULE_"),
                        str(caught.exception))

    def test_a_candidate_the_fact_names_but_the_store_does_not_hold_is_refused(self):
        self.install()
        for path in list((self.state / "candidates-v1").iterdir()):
            self.remove(path)
        with self.assertRaises(install_fact.Reject) as caught:
            self.verify()
        self.assertTrue(str(caught.exception).startswith(
            "E_INSTALL_FACT_CANDIDATE_SET"), str(caught.exception))

    def test_a_candidate_that_changed_after_installation_is_refused(self):
        self.install()
        for path in list((self.state / "candidates-v1").iterdir()):
            installed = json.loads(path.read_text(encoding="utf-8"))
            installed["candidate_id"] = "rc1-edited-after-install"
            self.writable(path).write_text(json.dumps(installed, sort_keys=True),
                                           encoding="utf-8")
            break
        with self.assertRaises(install_fact.Reject) as caught:
            self.verify()
        self.assertTrue(str(caught.exception).startswith(
            "E_INSTALL_FACT_CANDIDATE_SET_DRIFT"), str(caught.exception))

    def test_a_launcher_whose_bytes_are_not_the_installed_ones_is_refused(self):
        self.install()
        copy = self.root / "go-hk-deployctl"
        copy.write_bytes(LAUNCHER.read_bytes() + b"\n# a later edit\n")
        with self.assertRaises(install_fact.Reject) as caught:
            self.verify(launcher=str(copy))
        self.assertEqual(str(caught.exception), "E_INSTALL_FACT_LAUNCHER")

    def test_an_unknown_field_is_refused(self):
        self.install()
        self.rewrite_fact(lambda d: d.__setitem__("migration_required", False))
        with self.assertRaises(install_fact.Reject) as caught:
            self.verify()
        self.assertEqual(str(caught.exception), "E_INSTALL_FACT_FIELDS")

    def test_the_fact_carries_no_authorisation_of_its_own(self):
        """An install fact states what is installed. It does not permit anything."""
        self.install()
        document = self.read_fact()
        for forbidden in ("request_id", "plan_id", "approval_id", "candidate_image_id",
                          "migration_required", "media_topology", "task_id"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, document)
        self.assertEqual(document["source_repository"], installer.REPOSITORY)

    def test_reading_an_identity_refuses_an_installation_that_does_not_verify(self):
        self.install()
        self.rewrite_fact(lambda d: d.__setitem__("launcher_sha256", "0" * 64))
        with patch.object(install_fact, "os", OsShim()):
            with self.assertRaises(install_fact.Reject):
                install_fact.read_installed_identity(**self._paths())


class ReinstatementTests(InstallCase):
    def test_a_new_installation_does_not_overwrite_the_previous_one(self):
        first = self.install(token="aaaa1111", now=1_700_000_000)
        self.clear_readonly()
        second = self.install(token="bbbb2222", now=1_700_000_100)
        self.assertNotEqual(first["installation_id"], second["installation_id"])
        archived = self.state / ("install-fact-v1.%s.json" % first["installation_id"])
        self.assertTrue(archived.is_file(), "the previous fact was not kept")
        self.assertEqual(json.loads(archived.read_text(encoding="utf-8"))["installation_id"],
                         first["installation_id"])
        self.assertEqual(self.read_fact()["installation_id"], second["installation_id"])
        self.assertEqual(second["previous_installation_id"], first["installation_id"])

    def test_the_archived_fact_is_still_readable_and_still_verifies(self):
        first = self.install(token="aaaa1111", now=1_700_000_000)
        self.clear_readonly()
        self.install(token="bbbb2222", now=1_700_000_100)
        archived = self.state / ("install-fact-v1.%s.json" % first["installation_id"])
        paths = self._paths()
        with patch.object(install_fact, "os", OsShim()):
            verified = install_fact.load_installation(
                paths["launcher_path"], paths["runtime_dir"], str(archived),
                paths["key_path"], paths["candidate_dir"], paths["environment_graph"])
        self.assertEqual(verified["installation_id"], first["installation_id"])

    def test_a_transcript_of_identities_survives_three_installations(self):
        ids, digests = [], []
        for index, token in enumerate(("aaaa1111", "bbbb2222", "cccc3333")):
            if index:
                self.clear_readonly()
            summary = self.install(token=token, now=1_700_000_000 + index * 100)
            ids.append(summary["installation_id"])
            digests.append(summary["runtime_digest"])
            self.assertTrue(self.verify())
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual(len(set(digests)), 1, "the same bytes installed three times")
        # two superseded facts kept aside, plus the current one
        self.assertEqual(len(list(self.state.glob("install-fact-v1*.json"))), 3)

    def test_an_installation_id_is_never_reused(self):
        seen = set()
        for index in range(8):
            if index:
                self.clear_readonly()
            seen.add(self.install(now=1_700_000_000)["installation_id"])
        self.assertEqual(len(seen), 8)


# --------------------------------------------------------------------------- #
# §22 the launcher's gate, and where it sits
# --------------------------------------------------------------------------- #
STUB = '''"""A stand-in for the verifier: proves the launcher calls it, with what, and first.

The runtime modules this launcher would load next are not present here and would fail
their own integrity check, so a marker written by this file is evidence of two things at
once: that the gate ran, and that it ran before anything below it.
"""
import json
import os


def load_installation(launcher_path, runtime_dir):
    marker = os.environ.get("WP5_STUB_MARKER")
    if marker:
        with open(marker, "w", encoding="utf-8") as handle:
            json.dump({"launcher_path": launcher_path, "runtime_dir": runtime_dir}, handle)
    raise ValueError("E_STUB_REACHED")
'''


class LauncherGateTests(InstallCase):
    """The gate fires first, for every action, with the launcher's own path."""

    def setUp(self):
        super().setUp()
        self.deployctl = self.root / "executor"
        (self.deployctl / "go-hk-deployctl-runtime").mkdir(parents=True)
        self.launcher = self.deployctl / "go-hk-deployctl"
        self.launcher.write_bytes(LAUNCHER.read_bytes())
        self.stub()

    def stub(self, body=STUB):
        (self.deployctl / "go-hk-deployctl-runtime" / "install_fact.py").write_text(
            body, encoding="utf-8")

    def run_action(self, argv):
        marker = self.root / "stub-called.json"
        if marker.exists():
            marker.unlink()
        environment = dict(os.environ, WP5_STUB_MARKER=str(marker))
        result = subprocess.run([sys.executable, str(self.launcher)] + argv,
                                capture_output=True, text=True, env=environment)
        self.marker = marker
        try:
            return json.loads(result.stdout.strip()), result.returncode
        except ValueError:
            self.fail("the launcher did not emit a document: %r / %r"
                      % (result.stdout[-400:], result.stderr[-400:]))

    def arguments(self):
        return {
            "verify": ["verify", "--release-id", "r-1", "--candidate-image-id",
                       IMAGE, "--expected-current-image-id", IMAGE],
            "canary": ["canary", "--release-id", "r-1", "--candidate-image-id", IMAGE,
                       "--candidate-package-sha256", PACKAGE,
                       "--expected-current-image-id", IMAGE],
            "deploy": ["deploy", "--release-id", "r-1", "--candidate-image-id", IMAGE,
                       "--candidate-package-sha256", PACKAGE,
                       "--expected-current-image-id", IMAGE,
                       "--canary-evidence-id", "c-1", "--approval-id", "a-1",
                       "--candidate-contract-sha256", "d" * 64,
                       "--task-id", "t-1", "--task-nonce", "n-1", "--task-authority",
                       "GO-COMMAND-CENTER", "--task-canonical-sha256", "d" * 64],
            "rollback": ["rollback", "--release-id", "r-1", "--source-deploy-task-id",
                         "s-1", "--approval-id", "a-1", "--task-id", "t-1",
                         "--task-nonce", "n-1", "--task-authority", "GO-COMMAND-CENTER",
                         "--task-canonical-sha256", "d" * 64],
        }

    def test_every_action_consults_the_install_fact_before_anything_else(self):
        for action, argv in self.arguments().items():
            with self.subTest(action=action):
                document, code = self.run_action(argv)
                self.assertEqual(document["status"], "REJECTED")
                self.assertEqual(document["gate_results"], {},
                                 "%s ran a gate before the installation was verified"
                                 % action)
                self.assertEqual(code, 2)
                self.assertTrue(self.marker.exists(),
                                "the install fact was not consulted for %s" % action)
                recorded = json.loads(self.marker.read_text(encoding="utf-8"))
                self.assertEqual(recorded["launcher_path"], str(self.launcher),
                                 "the launcher did not hand over its own path")
                self.assertEqual(pathlib.Path(recorded["runtime_dir"]).name,
                                 "go-hk-deployctl-runtime")

    def test_there_is_no_argument_that_could_point_the_gate_elsewhere(self):
        """The fact's location is the launcher's business, never a caller's."""
        for action, argv in self.arguments().items():
            for flag in argv[1::2]:
                with self.subTest(action=action, flag=flag):
                    self.assertNotIn("fact", flag.lower())
                    self.assertNotIn("install", flag.lower())

    def test_the_gate_runs_before_the_runtime_is_loaded(self):
        """The modules below the gate cannot load here, so the marker is the ordering proof."""
        document, _ = self.run_action(self.arguments()["deploy"])
        self.assertTrue(self.marker.exists())
        self.assertNotIn("runtime rejected", document.get("error_code", ""))
        self.assertNotIn("integrity", document.get("error_code", ""))
        self.assertEqual(document.get("error_code"), "E_STUB_REACHED")

    def test_a_bad_installation_never_reaches_a_runner(self):
        """`gate_results` empty and no deploy record: nothing ran at all."""
        document, _ = self.run_action(self.arguments()["deploy"])
        self.assertEqual(document["gate_results"], {})
        self.assertNotIn("deploy_record_id", document)

    def test_the_argument_contract_is_still_checked_after_the_gate(self):
        """The gate is a predecessor of the contract, not a replacement for it."""
        self.stub(STUB.replace('raise ValueError("E_STUB_REACHED")', "return {}"))
        argv = self.arguments()["verify"]
        argv[argv.index("--release-id") + 1] = "not a release id!"
        document, _ = self.run_action(argv)
        self.assertEqual(document["status"], "REJECTED")
        self.assertTrue(self.marker.exists(), "the gate was skipped for a read-only action")


class LauncherWiringTests(unittest.TestCase):
    """The launcher's source, read rather than executed."""

    def setUp(self):
        self.source = LAUNCHER.read_text(encoding="utf-8")

    def test_the_version_names_what_the_launcher_now_does(self):
        self.assertIn('VERSION = "0.7.0-environment-lock"', self.source)

    def test_all_four_actions_verify_the_installation_first(self):
        for action, marker in (("_deploy", "_load_deploy()"),
                               ("_rollback", "_load_rollback()"),
                               ("_canary", "_load_canary()"),
                               ("_verify", "_collect_verify(")):
            with self.subTest(action=action):
                body = self.source.split("def %s(" % action, 1)[1].split("\ndef ", 1)[0]
                self.assertIn("_verify_installation()", body)
                self.assertLess(body.index("_verify_installation()"), body.index(marker),
                                "%s loads its runtime before the installation is verified"
                                % action)

    def test_the_pin_set_is_unchanged_and_the_fact_did_not_add_one(self):
        """Dual verification: the pins remain, and the fact is not smuggled in as a pin."""
        pins = re.findall(r'_(\w+)_SHA256 = "([0-9a-f]{64})"', self.source)
        self.assertEqual(sorted(name for name, _ in pins), sorted(PIN_MODULES))

    def test_the_verifier_is_not_pinned_against_itself(self):
        """A constant for `install_fact.py` would be the verifier checking the verifier."""
        self.assertNotIn("INSTALL_FACT_SHA256", self.source)


# A pin's value, however it happens to be quoted. The modules are not consistent
# about it, and a test that assumed double quotes would silently match nothing.
PIN_VALUE = " = [\"']([0-9a-f]{64})[\"']"


class PinAndFactAgreementTests(InstallCase):
    """§14: the old pins and the new fact must describe the same bytes."""

    def all_pins(self):
        pins = {PIN_MODULES[name]: digest for name, digest in
                re.findall(r'_(\w+)_SHA256 = "([0-9a-f]{64})"',
                           LAUNCHER.read_text(encoding="utf-8"))}
        deploy_source = (RUNTIME / "deploy_runtime.py").read_text(encoding="utf-8")
        for constant, module in (("_CANDIDATE_SOURCE_SHA256", "candidate_source"),
                                 ("_MIGRATION_GUARD_SHA256", "migration_guard"),
                                 ("_MEDIA_GUARD_SHA256", "media_guard")):
            pins[module] = re.search(constant + PIN_VALUE,
                                     deploy_source).group(1)
        pins["candidate_fact"] = re.search("CANDIDATE_FACT_SHA256" + PIN_VALUE,
            (RUNTIME / "candidate_source.py").read_text(encoding="utf-8")).group(1)
        return pins

    def test_every_pinned_module_agrees_with_the_install_fact(self):
        """One number per module, over the form the host actually holds.

        The pins were always repository-blob hashes; the installer hashes the bytes it
        installs. On the HK host those are the same bytes, because the staged tree is the
        blob -- the install script re-checks it against `SOURCE_SHA256SUMS.txt` before it
        runs. This worktree is CRLF, so the two are only equal once the bytes are
        normalised to what the host would receive; that is what this stages.
        """
        staged = self.stage_lf_runtime()
        self.install(runtime_dir=staged)
        facts = {module["name"]: module["sha256"]
                 for module in self.read_fact()["runtime_modules"]}
        for name, pinned in sorted(self.all_pins().items()):
            with self.subTest(module=name):
                self.assertIn(name, facts, "the fact does not cover a pinned module")
                self.assertEqual(facts[name], pinned,
                                 "the pin and the install fact disagree about %s" % name)

    def test_the_two_definitions_are_the_same_definition(self):
        """As installed here, the fact hashes the worktree bytes -- and the pin does not.

        That difference is the checkout, not the contract: it disappears the moment the
        installed bytes are the repository blobs, which the test above demonstrates. This
        one records it rather than leaving a reader to wonder why two numbers differ.

        Which means the difference is only there on a checkout that actually produces CRLF.
        Both shapes are asserted, and neither passes by having nothing to compare: the two
        numbers are compared for every module either way, and the shape the test ran in is
        named.  Demanding a non-empty difference -- as this test first did -- is a statement
        about the checkout, and it is false on an all-LF one.
        """
        self.install()
        facts = {module["name"]: module["sha256"]
                 for module in self.read_fact()["runtime_modules"]}
        differing, crlf = set(), set()
        for name, pinned in sorted(self.all_pins().items()):
            bytes_ = (RUNTIME / (name + ".py")).read_bytes()
            raw = hashlib.sha256(bytes_).hexdigest()
            normalised = hashlib.sha256(bytes_.replace(b"\r\n", b"\n")).hexdigest()
            with self.subTest(module=name):
                self.assertEqual(pinned, normalised,
                                 "the pin is not this module's repository blob")
                self.assertEqual(facts[name], raw, "the fact is not this module's bytes")
            if raw != normalised:
                differing.add(name)
            if b"\r\n" in bytes_:
                crlf.add(name)
        if crlf:
            self.assertEqual(differing, crlf,
                             "the pin and the fact may differ only where this checkout's bytes "
                             "differ from the blob's, so the difference is fully explained by "
                             "line endings; checkout shape=%s" % (sorted(crlf),))
        else:
            self.assertEqual(differing, set(),
                             "this checkout is already LF, so the normalisation above is a "
                             "no-op and the two definitions coincide; that is the checkout's "
                             "shape, not a property of the contract")

    def test_the_fact_covers_more_than_the_pins_ever_did(self):
        self.install()
        covered = {module["name"] for module in self.read_fact()["runtime_modules"]}
        self.assertEqual(covered, set(install_fact.RUNTIME_MODULES))
        self.assertEqual(covered - set(self.all_pins()), {"install_fact"},
                         "the only module no pin ever covered is the verifier itself")


# --------------------------------------------------------------------------- #
# WP-6: the canonical provenance proof the installer now consumes
# --------------------------------------------------------------------------- #
class CanonicalProofTests(InstallCase):
    """The seam WP-5 declared: "proving the commit is on main ... belongs to WP-6".

    The installer cannot reach the repository, so the proof is made where the repository is
    and consumed here. What these tests pin is the binding, not the proof: a proof that is
    absent, refused, about another commit, about another tree, silent about a module being
    installed, or carrying a different hash for one, must not install anything.
    """

    # A value that is not a proof document, so that "no proof at all" can be asked for: the
    # install helper builds a default proof for every other call, and `None` is how a caller
    # says "use the default".
    NO_PROOF = object()

    def test_a_proof_that_holds_installs(self):
        self.install()
        self.assertTrue(self.verify())

    def test_an_absent_proof_is_refused(self):
        with self.assertRaises(installer.InstallError) as caught:
            self.install(proof=self.NO_PROOF)
        self.assertEqual(str(caught.exception), "E_INSTALL_CANONICAL_PROOF")
        self.assertFalse((self.state / "install-fact-v1.json").exists())

    def test_a_refused_proof_is_not_an_install(self):
        with self.assertRaises(installer.InstallError) as caught:
            self.install(proof=canonical_proof(verdict="REFUSED"))
        self.assertEqual(str(caught.exception), "E_INSTALL_CANONICAL_PROOF")

    def test_a_proof_about_another_commit_is_refused(self):
        with self.assertRaises(installer.InstallError) as caught:
            self.install(proof=canonical_proof(source_commit="4" * 40))
        self.assertEqual(str(caught.exception), "E_INSTALL_CANONICAL_PROOF")

    def test_a_proof_about_another_tree_is_refused(self):
        with self.assertRaises(installer.InstallError) as caught:
            self.install(proof=canonical_proof(source_tree="5" * 40))
        self.assertEqual(str(caught.exception), "E_INSTALL_CANONICAL_PROOF")

    def test_a_proof_silent_about_a_module_being_installed_is_refused(self):
        partial = canonical_proof()
        partial["modules"] = [entry for entry in partial["modules"]
                              if entry["name"] != "deploy_runtime"]
        with self.assertRaises(installer.InstallError) as caught:
            self.install(proof=partial)
        self.assertEqual(str(caught.exception), "E_INSTALL_CANONICAL_PROOF")

    def test_a_proof_carrying_another_hash_for_a_module_is_refused(self):
        altered = canonical_proof()
        for entry in altered["modules"]:
            if entry["name"] == "deploy_runtime":
                entry["sha256"] = "0" * 64
        with self.assertRaises(installer.InstallError) as caught:
            self.install(proof=altered)
        self.assertEqual(str(caught.exception), "E_INSTALL_CANONICAL_PROOF")

    def test_a_proof_without_a_resolved_canonical_commit_is_refused(self):
        with self.assertRaises(installer.InstallError) as caught:
            self.install(proof=canonical_proof(canonical_commit=None))
        self.assertEqual(str(caught.exception), "E_INSTALL_CANONICAL_PROOF")

    def test_a_proof_declaring_another_refusal_vocabulary_is_refused(self):
        with self.assertRaises(installer.InstallError) as caught:
            self.install(proof=canonical_proof(codes=["E_SOMETHING_ELSE"]))
        self.assertEqual(str(caught.exception), "E_INSTALL_CANONICAL_PROOF")

    def test_nothing_is_written_when_the_proof_is_refused(self):
        with self.assertRaises(installer.InstallError):
            self.install(proof=canonical_proof(verdict="REFUSED"))
        # Nothing at all: not even the directories the write would have needed. A refused
        # install is not a half-install for the launcher to refuse later.
        if self.state.exists():
            self.fail("a refused install created %s" % sorted(
                p.name for p in self.state.iterdir()))
        self.assertFalse((self.state / "install-fact-v1.json").exists())

    def test_the_gate_runs_before_the_first_write(self):
        # Source-level, and positional: the proof check must appear before any `atomic(` call
        # in `install`. A gate that ran after the store was written would leave a half-install
        # for the launcher to refuse.
        source = (INSTALL_DIR / "hk_install_facts.py").read_text(encoding="utf-8")
        body = source[source.index("def install("):]
        body = body[:body.index("\ndef ")]
        self.assertIn("check_canonical_proof(", body)
        self.assertLess(body.index("check_canonical_proof("), body.index("atomic("))
        self.assertLess(body.index("check_canonical_proof("), body.index("ensure_directory("))

    def test_the_proof_schema_is_the_one_wp6_publishes(self):
        schema = (REPO / "control-plane" / "command-center-canonical-provenance-v1"
                  / "contracts" / "canonical_source_invariant_v1.schema.json")
        if not schema.is_file():  # pragma: no cover
            self.skipTest("the WP-6 component is not in this tree")
        document = json.loads(schema.read_text(encoding="utf-8"))
        self.assertEqual(document["$id"], installer.CANONICAL_PROOF_SCHEMA)
        self.assertEqual(tuple(document["x-go-refusals"]["source"]),
                         installer.CANONICAL_PROOF_CODES)
        # And the producer's own module agrees with what the installer requires, so the two
        # halves of the seam cannot drift apart silently.
        module = load_module(REPO / "control-plane"
                             / "command-center-canonical-provenance-v1"
                             / "canonical_provenance.py", "wp6_provenance")
        self.assertEqual(module.SCHEMA, installer.CANONICAL_PROOF_SCHEMA)
        self.assertEqual(module.PHASE_INSTALL_SOURCE, installer.CANONICAL_PROOF_PHASE)
        self.assertEqual(tuple(module.CODES), installer.CANONICAL_PROOF_CODES)


if __name__ == "__main__":
    unittest.main()
