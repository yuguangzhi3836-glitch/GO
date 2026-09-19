"""The executor's media-preservation gate (CCV1-95 WP-9 phase 1).

Five things are proven here:

1. **The storage identity is the directory's, not its contents.**  A healthy cache
   whose bytes change -- which is normal operation -- keeps the same identity, so the
   gate cannot refuse a deployment merely for having been written to.  A cache that is
   swapped for a different directory does change it, and is refused.

2. **Absence of a cache is never reported as preservation.**  A host with no cache
   yields ``NOT_ACTIVE``, not ``PASS``.  The one answer that would be a lie is the one
   the vocabulary cannot express.

3. **The mount is a real requirement.**  A cache that survived untouched but is no
   longer read by the eight services is refused, because that is the loss the gate
   exists for -- the application would silently write to a container-local cache.

4. **The wiring is visible and the pins agree.**  `deploy_runtime.run_deploy()` calls
   the gate on both sides of the mutation, and every sha256 that has to be updated when
   this module changes is asserted to be the value it must be -- so a missed pin is a
   failing test rather than a silent one.

5. **The gate mutates nothing.**  It reads the filesystem and refuses; it opens no file
   for writing, runs no command and contacts nothing.

Standard library only. No network, no Git, no Docker, no live Hong Kong contact.
"""
import ast
import hashlib
import importlib.machinery
import importlib.util
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT / "hk-staging"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

RUNTIME = REPO / "hk-staging" / "source" / "executor" / "runtime"
GUARD_PATH = RUNTIME / "media_guard.py"
DEPLOY_RUNTIME_PATH = RUNTIME / "deploy_runtime.py"
INSTALL_FACT_PATH = RUNTIME / "install_fact.py"
LAUNCHER_PATH = REPO / "hk-staging" / "source" / "executor" / "go-hk-deployctl"

IMAGE = "sha256:" + "a" * 64


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


g = load("media_guard_under_test", GUARD_PATH)


def blob_sha256(path):
    """The hash of the blob, not of this checkout's copy of it.

    A pin is a repository-blob hash. The host is staged from the blob and therefore
    holds LF; this worktree has `core.autocrlf=true` and holds CRLF, so the two
    differ by line endings alone. Compare the normalised form -- the form the host
    receives -- which is also what the installation-fact suite compares.
    """
    raw = pathlib.Path(path).read_bytes()
    return hashlib.sha256(raw.replace(bytes((13, 10)), bytes((10,)))).hexdigest()


def container(service, image=IMAGE, mounted=True, source=None, destination=None,
              read_write=True, environment=None, extra_mounts=(), project="go-822-staging"):
    """One `docker inspect` row, shaped exactly as the runtime reads it."""
    mounts = []
    if mounted:
        mounts.append({"Type": "bind", "Source": source or g.CACHE,
                       "Destination": destination or g.CACHE, "RW": read_write})
    mounts.extend(extra_mounts)
    if environment is None:
        environment = [g.CACHE_ENV + "=" + g.CACHE]
    return {"Id": "id-" + service, "Image": image,
            "Config": {"Labels": {"com.docker.compose.project": project,
                                  "com.docker.compose.service": service},
                       "Env": environment},
            "Mounts": mounts}


def inventory(image=IMAGE, **over):
    rows = []
    for index, service in enumerate(g.SERVICES):
        options = dict(over.get("all", {}))
        if service in over:
            options = over[service]
        rows.append(container(service, image=image, **options))
    return rows


class CacheFixture(unittest.TestCase):
    """A temporary directory standing in for the host's cache path."""

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.original = g.CACHE
        self.addCleanup(setattr, g, "CACHE", self.original)

    def write_cache(self, path):
        """The leaf names a healthy cache carries, with the types they really have."""
        path.mkdir()
        for entry in g.CONTENTS:
            target = path / entry
            if entry == "files":          # a directory in a real cache
                target.mkdir()
            else:                          # `index.sqlite3`
                target.write_bytes(b"media")
        return path

    def make_cache(self, name="cache", leaf=True):
        path = self.root / name
        path.mkdir()
        if leaf:
            for entry in g.CONTENTS:
                target = path / entry
                # `files` is a directory in a real cache; `index.sqlite3` is a file.
                if entry == "files":
                    target.mkdir()
                else:
                    target.write_bytes(b"media")
        g.CACHE = str(path)
        return path


class StorageIdentityTests(CacheFixture):
    """What "the same storage" means, and what is not an answer."""

    def test_a_host_with_no_cache_reports_no_identity(self):
        g.CACHE = str(self.root / "absent")
        self.assertIsNone(g.storage_identity())

    def test_a_plain_cache_reports_its_directory_identity(self):
        path = self.make_cache()
        info = os.stat(str(path))
        identity = g.storage_identity()
        self.assertEqual(identity["device"], info.st_dev)
        self.assertEqual(identity["inode"], info.st_ino)
        self.assertEqual(identity["host_path"], g.CACHE)
        self.assertEqual(sorted(identity["contents"]), sorted(g.CONTENTS))

    def test_writing_through_the_cache_does_not_change_its_identity(self):
        """The property that makes the gate usable: bytes change, storage does not."""
        path = self.make_cache()
        first = g.storage_identity()
        (path / "index.sqlite3").write_bytes(b"a great deal more media than before")
        (path / "files" / "one.jpg").write_bytes(b"bytes")
        self.assertEqual(g.storage_identity(), first)

    def test_a_different_directory_is_a_different_identity(self):
        self.make_cache("one")
        first = g.storage_identity()
        g.CACHE = str(self.write_cache(self.root / "two"))
        self.assertNotEqual(g.storage_identity(), first)

    def test_a_file_at_the_cache_path_is_refused(self):
        path = self.root / "cache"
        path.write_bytes(b"not a directory")
        g.CACHE = str(path)
        with self.assertRaises(g.Reject) as caught:
            g.storage_identity()
        self.assertEqual(str(caught.exception), g.E_MEDIA_STORAGE_ABSENT)

    def test_a_cache_missing_a_leaf_is_refused(self):
        path = self.make_cache(leaf=False)
        (path / "index.sqlite3").write_bytes(b"media")
        with self.assertRaises(g.Reject) as caught:
            g.storage_identity()
        self.assertEqual(str(caught.exception), g.E_MEDIA_STORAGE_ABSENT)

    @unittest.skipIf(os.name == "nt", "creating symlinks needs a privilege on Windows")
    def test_a_symlink_at_the_cache_path_is_present_and_wrong(self):
        real = self.make_cache("real")
        link = self.root / "link"
        link.symlink_to(real, target_is_directory=True)
        g.CACHE = str(link)
        self.assertTrue(os.path.lexists(g.CACHE), "a symlink is present, not absent")
        with self.assertRaises(g.Reject) as caught:
            g.storage_identity()
        self.assertEqual(str(caught.exception), g.E_MEDIA_STORAGE_ABSENT)

    @unittest.skipIf(os.name == "nt", "creating symlinks needs a privilege on Windows")
    def test_a_dangling_symlink_is_not_absence(self):
        link = self.root / "dangling"
        link.symlink_to(self.root / "nowhere", target_is_directory=True)
        g.CACHE = str(link)
        with self.assertRaises(g.Reject) as caught:
            g.storage_identity()
        self.assertEqual(str(caught.exception), g.E_MEDIA_STORAGE_ABSENT)

    @unittest.skipIf(os.name == "nt", "creating symlinks needs a privilege on Windows")
    def test_a_symlinked_ancestor_is_refused(self):
        real = self.root / "real-parent"
        real.mkdir()
        cache = real / "cache"
        cache.mkdir()
        for entry in g.CONTENTS:
            target = cache / entry
            target.mkdir() if entry.endswith("/") else target.write_bytes(b"media")
        link = self.root / "linked-parent"
        link.symlink_to(real, target_is_directory=True)
        g.CACHE = str(link / "cache")
        with self.assertRaises(g.Reject) as caught:
            g.storage_identity()
        self.assertEqual(str(caught.exception), g.E_MEDIA_STORAGE_ABSENT)


class MountTests(CacheFixture):
    """The eight services must be reading the cache, and nothing else."""

    def test_the_eight_mounted_services_pass(self):
        self.assertEqual(g.require_mounts(inventory(), IMAGE), g.PRESERVED)

    def test_a_service_without_the_mount_refuses(self):
        rows = inventory()
        rows[3] = container(g.SERVICES[3], mounted=False)
        with self.assertRaises(g.Reject) as caught:
            g.require_mounts(rows, IMAGE)
        self.assertEqual(str(caught.exception), g.E_MEDIA_MOUNT_DRIFT)

    def test_a_mount_from_another_host_directory_refuses(self):
        rows = inventory()
        rows[0] = container(g.SERVICES[0], source="/var/lib/go-hotel/other-cache")
        with self.assertRaises(g.Reject) as caught:
            g.require_mounts(rows, IMAGE)
        self.assertEqual(str(caught.exception), g.E_MEDIA_MOUNT_DRIFT)

    def test_a_mount_at_another_container_path_refuses(self):
        rows = inventory()
        rows[0] = container(g.SERVICES[0], destination="/state/media")
        with self.assertRaises(g.Reject) as caught:
            g.require_mounts(rows, IMAGE)
        self.assertEqual(str(caught.exception), g.E_MEDIA_MOUNT_DRIFT)

    def test_a_read_only_mount_refuses(self):
        rows = inventory()
        rows[0] = container(g.SERVICES[0], read_write=False)
        with self.assertRaises(g.Reject) as caught:
            g.require_mounts(rows, IMAGE)
        self.assertEqual(str(caught.exception), g.E_MEDIA_MOUNT_DRIFT)

    def test_a_shadowing_second_mount_refuses(self):
        rows = inventory()
        rows[0] = container(g.SERVICES[0], extra_mounts=[
            {"Type": "bind", "Source": "/tmp/empty", "Destination": g.CACHE + "/files",
             "RW": True}])
        with self.assertRaises(g.Reject) as caught:
            g.require_mounts(rows, IMAGE)
        self.assertEqual(str(caught.exception), g.E_MEDIA_MOUNT_DRIFT)

    def test_a_volume_instead_of_a_bind_mount_refuses(self):
        rows = inventory()
        rows[0] = container(g.SERVICES[0], extra_mounts=[])
        rows[0]["Mounts"] = [{"Type": "volume", "Source": g.CACHE,
                              "Destination": g.CACHE, "RW": True}]
        with self.assertRaises(g.Reject) as caught:
            g.require_mounts(rows, IMAGE)
        self.assertEqual(str(caught.exception), g.E_MEDIA_MOUNT_DRIFT)

    def test_an_environment_pointing_elsewhere_refuses(self):
        """The quiet loss: the mount is there but the application is told to ignore it."""
        rows = inventory()
        rows[0] = container(g.SERVICES[0], environment=[g.CACHE_ENV + "=var/media_cache"])
        with self.assertRaises(g.Reject) as caught:
            g.require_mounts(rows, IMAGE)
        self.assertEqual(str(caught.exception), g.E_MEDIA_MOUNT_DRIFT)

    def test_a_missing_environment_refuses(self):
        rows = inventory()
        rows[0] = container(g.SERVICES[0], environment=[])
        with self.assertRaises(g.Reject) as caught:
            g.require_mounts(rows, IMAGE)
        self.assertEqual(str(caught.exception), g.E_MEDIA_MOUNT_DRIFT)

    def test_a_duplicated_environment_value_refuses(self):
        rows = inventory()
        rows[0] = container(g.SERVICES[0],
                            environment=[g.CACHE_ENV + "=" + g.CACHE, g.CACHE_ENV + "=" + g.CACHE])
        with self.assertRaises(g.Reject) as caught:
            g.require_mounts(rows, IMAGE)
        self.assertEqual(str(caught.exception), g.E_MEDIA_MOUNT_DRIFT)

    def test_the_wrong_image_refuses(self):
        with self.assertRaises(g.Reject) as caught:
            g.require_mounts(inventory(), "sha256:" + "b" * 64)
        self.assertEqual(str(caught.exception), g.E_MEDIA_MOUNT_DRIFT)

    def test_a_duplicated_service_refuses(self):
        rows = inventory()
        rows[7] = container(g.SERVICES[0])
        with self.assertRaises(g.Reject) as caught:
            g.require_mounts(rows, IMAGE)
        self.assertEqual(str(caught.exception), g.E_MEDIA_MOUNT_DRIFT)

    def test_seven_services_refuse(self):
        with self.assertRaises(g.Reject) as caught:
            g.require_mounts(inventory()[:7], IMAGE)
        self.assertEqual(str(caught.exception), g.E_MEDIA_MOUNT_DRIFT)

    def test_a_container_from_another_compose_project_refuses(self):
        rows = inventory()
        rows[0] = container(g.SERVICES[0], project="someone-elses-staging")
        with self.assertRaises(g.Reject) as caught:
            g.require_mounts(rows, IMAGE)
        self.assertEqual(str(caught.exception), g.E_MEDIA_MOUNT_DRIFT)


class PreservationTests(CacheFixture):
    """The two-sided question, which is what a wired deploy path asks."""

    def test_a_preserved_cache_reports_pass(self):
        self.make_cache()
        state = g.before(inventory(), IMAGE)
        result = g.after(state, inventory(), IMAGE)
        self.assertEqual(result["media_persistence"], g.PRESERVED)
        self.assertEqual(result["media_mounts"], g.PRESERVED)
        self.assertEqual(result["media_storage_identity"], state["media_storage_identity"])

    def test_a_cache_that_was_already_gone_is_never_reported_as_preserved(self):
        g.CACHE = str(self.root / "absent")
        state = g.before(inventory(), IMAGE)
        self.assertIsNone(state["media_storage_identity"])
        result = g.after(state, inventory(), IMAGE)
        self.assertEqual(result["media_persistence"], g.NOT_ACTIVE)
        self.assertNotEqual(result["media_persistence"], g.PRESERVED)

    def test_a_replaced_cache_refuses_in_the_identity_code(self):
        first = self.make_cache("one")
        state = g.before(inventory(), IMAGE)
        g.CACHE = str(self.write_cache(self.root / "two"))
        self.assertTrue(first.exists(), "the original is still there; only the path moved")
        with self.assertRaises(g.Reject) as caught:
            g.after(state, inventory(), IMAGE)
        self.assertEqual(str(caught.exception), g.E_MEDIA_STORAGE_IDENTITY_DRIFT)

    def test_a_cache_that_is_deleted_refuses_rather_than_reporting_absence(self):
        self.make_cache()
        state = g.before(inventory(), IMAGE)
        shutil.rmtree(g.CACHE)
        with self.assertRaises(g.Reject) as caught:
            g.after(state, inventory(), IMAGE)
        self.assertEqual(str(caught.exception), g.E_MEDIA_STORAGE_ABSENT)

    def test_a_preserved_cache_that_is_no_longer_mounted_refuses(self):
        """The whole point: untouched bytes, unread by anything, is still a loss."""
        self.make_cache()
        state = g.before(inventory(), IMAGE)
        unmounted = inventory()
        unmounted[5] = container(g.SERVICES[5], mounted=False)
        with self.assertRaises(g.Reject) as caught:
            g.after(state, unmounted, IMAGE)
        self.assertEqual(str(caught.exception), g.E_MEDIA_MOUNT_DRIFT)

    def test_before_records_whether_the_cache_was_already_mounted(self):
        self.make_cache()
        self.assertTrue(g.before(inventory(), IMAGE)["media_mounted_before"])
        unmounted = [container(service, mounted=False) for service in g.SERVICES]
        self.assertFalse(g.before(unmounted, IMAGE)["media_mounted_before"])

    def test_an_unmounted_host_may_still_be_brought_onto_the_cache(self):
        """First activation: the cache exists, nothing mounts it yet, the deploy fixes that."""
        self.make_cache()
        unmounted = [container(service, mounted=False) for service in g.SERVICES]
        state = g.before(unmounted, IMAGE)
        result = g.after(state, inventory(), IMAGE)
        self.assertEqual(result["media_persistence"], g.PRESERVED)

    def test_bringing_a_cache_onto_a_host_without_one_still_requires_the_mount(self):
        g.CACHE = str(self.root / "absent")
        state = g.before([container(service, mounted=False) for service in g.SERVICES], IMAGE)
        self.assertIsNone(state["media_storage_identity"])
        self.make_cache()
        created_unmounted = [container(service, mounted=False) for service in g.SERVICES]
        with self.assertRaises(g.Reject) as caught:
            g.after(state, created_unmounted, IMAGE)
        self.assertEqual(str(caught.exception), g.E_MEDIA_MOUNT_DRIFT)

    def test_a_fabricated_state_refuses(self):
        self.make_cache()
        for wrong in ({}, {"media_mounted_before": True}, None, "state"):
            with self.subTest(state=wrong):
                with self.assertRaises(g.Reject) as caught:
                    g.after(wrong, inventory(), IMAGE)
                self.assertEqual(str(caught.exception), g.E_MEDIA_STORAGE_IDENTITY_DRIFT)


class VocabularyTests(CacheFixture):
    """Two outcomes, three codes, and the gate result stays a gate result."""

    def test_the_three_codes_are_the_whole_vocabulary(self):
        codes = {g.E_MEDIA_STORAGE_ABSENT, g.E_MEDIA_MOUNT_DRIFT,
                 g.E_MEDIA_STORAGE_IDENTITY_DRIFT}
        self.assertEqual(codes, {"E_MEDIA_STORAGE_ABSENT", "E_MEDIA_MOUNT_DRIFT",
                                 "E_MEDIA_STORAGE_IDENTITY_DRIFT"})

    def test_the_two_outcomes_do_not_collapse(self):
        self.assertNotEqual(g.PRESERVED, g.NOT_ACTIVE)
        self.assertEqual({g.PRESERVED, g.NOT_ACTIVE}, {"PASS", "NOT_ACTIVE"})

    def test_every_gate_result_is_pass(self):
        self.make_cache()
        result = g.after(g.before(inventory(), IMAGE), inventory(), IMAGE)
        self.assertTrue(g.GATE_KEYS, "a module with no gate keys contributes nothing")
        for key, value in g.gates(result).items():
            self.assertIn(key, g.GATE_KEYS)
            self.assertEqual(value, g.PRESERVED)

    def test_the_identity_goes_into_the_record_and_not_the_gates(self):
        """A structured value in `gate_results` would break the gate-result rule."""
        self.make_cache()
        result = g.after(g.before(inventory(), IMAGE), inventory(), IMAGE)
        self.assertEqual(set(g.GATE_KEYS), {"media_persistence", "media_mounts"})
        self.assertNotIn("media_storage_identity", set(g.GATE_KEYS))
        self.assertIsInstance(g.record_fields(result)["media_storage_identity"], dict)

    def test_the_record_reports_absence_rather_than_inventing_an_identity(self):
        g.CACHE = str(self.root / "absent")
        result = g.after(g.before(inventory(), IMAGE), inventory(), IMAGE)
        fields = g.record_fields(result)
        self.assertIn("media_storage_identity", fields)
        self.assertIsNone(fields["media_storage_identity"],
                          "an absent cache is recorded as null, not omitted")


class WiringTests(CacheFixture):
    """The gate is wired, and every pin that has to move with it agrees."""

    def test_deploy_runtime_calls_the_gate_on_both_sides_of_the_mutation(self):
        source = DEPLOY_RUNTIME_PATH.read_text(encoding="utf-8")
        self.assertIn("_load_media_guard", source)
        self.assertIn("media.before(", source)
        self.assertIn("media.after(", source)

    def test_the_guard_pin_is_the_guard_s_bytes(self):
        source = DEPLOY_RUNTIME_PATH.read_text(encoding="utf-8")
        declared = [line for line in source.splitlines()
                    if line.startswith("_MEDIA_GUARD_SHA256")]
        self.assertEqual(len(declared), 1, "exactly one pin, or the loader has no value")
        pinned = declared[0].split("=", 1)[1].strip().strip('"')
        self.assertEqual(pinned, blob_sha256(GUARD_PATH))

    def test_the_launcher_pin_is_the_deploy_runtime_s_bytes(self):
        source = LAUNCHER_PATH.read_text(encoding="utf-8")
        declared = [line for line in source.splitlines()
                    if line.startswith("_DEPLOY_SHA256")]
        self.assertEqual(len(declared), 1)
        pinned = declared[0].split("=", 1)[1].strip().strip('"')
        self.assertEqual(pinned, blob_sha256(DEPLOY_RUNTIME_PATH))

    def test_the_install_fact_declares_the_new_module(self):
        fact = load("install_fact_under_test", INSTALL_FACT_PATH)
        self.assertIn("media_guard", fact.RUNTIME_MODULES)
        for name in fact.RUNTIME_MODULES:
            with self.subTest(module=name):
                self.assertTrue((RUNTIME / (name + ".py")).is_file(),
                                "a declared module must exist on disk")

    def test_the_services_are_the_same_fixed_eight_as_the_deploy_runtime(self):
        deploy = load("deploy_runtime_under_test", DEPLOY_RUNTIME_PATH)
        self.assertEqual(g.SERVICES, deploy.SERVICES)
        self.assertEqual(g.PROJECT, deploy.PROJECT)

    def test_the_cache_path_is_the_one_the_host_runs(self):
        """The path is a fact about the installed host, not a preference.

        `/var/lib/go-hotel/media-cache` is where the running installation binds the
        cache. The converged baseline records it here as the only value; a deployment
        cannot ask the guard to look somewhere else.
        """
        self.assertEqual(g.CACHE, "/var/lib/go-hotel/media-cache")
        self.assertEqual(g.CACHE_ENV, "GO_MEDIA_CACHE_DIR")


class PurityTests(unittest.TestCase):
    """The gate decides and refuses. It does not open, write or run anything."""

    def test_it_imports_nothing_that_could_run_or_reach_out(self):
        tree = ast.parse(GUARD_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported, {"os", "pathlib", "stat"})

    def test_it_calls_nothing_that_mutates_or_runs(self):
        forbidden = {"open", "mkdir", "makedirs", "remove", "unlink", "rename", "replace",
                     "rmtree", "chmod", "chown", "system", "popen", "run", "Popen",
                     "check_output", "check_call", "write_bytes", "write_text", "touch"}
        tree = ast.parse(GUARD_PATH.read_text(encoding="utf-8"))
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                function = node.func
                if isinstance(function, ast.Attribute):
                    called.add(function.attr)
                elif isinstance(function, ast.Name):
                    called.add(function.id)
        self.assertEqual(called & forbidden, set())

    def test_it_never_reads_the_cache_s_bytes(self):
        """A digest of the contents would refuse every healthy deployment."""
        source = GUARD_PATH.read_text(encoding="utf-8")
        for banned in ("sha256", "read_bytes", "read_text", "hashlib"):
            self.assertNotIn(banned, source)


if __name__ == "__main__":
    unittest.main()
