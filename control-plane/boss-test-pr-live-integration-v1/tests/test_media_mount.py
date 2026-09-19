"""The fixed Hong Kong media mount (WP-9, product decision of 2026-09-19).

Ten things are proven here, and they are the ten the product asked for:

1. **A deployment mounts the media directory without being told to.**  `run_deploy()`
   recreates the containers through `media_mount.recreate()`, and the command that
   builder produces contains the fixed bind mount.
2. **A rollback does the same**, through the same builder -- not through a copy of it.
3. **There is no other door.**  No file in the executor tree other than `media_mount.py`
   contains the recreation flag, so "every path that recreates the business containers"
   is a set of two rather than a claim about the ones somebody remembered.
4. **Nothing about the mount comes from a candidate.**  No Task field, no plan field and
   no function parameter can name a path, a service list or a topology; the definition
   lives in one module and the overlay is the *last* Compose file, so it has the final
   word over every earlier one.
5. **A healthy mount reports success.**
6. **A missing mount fails the operation**, with `MEDIA_MOUNT=FAILED` and a reason.
7. **A mount that points somewhere else fails**, whichever end is wrong.
8. **The check reads the running containers, not the command line.**  A correct command
   whose mount Docker did not apply is a failure; that is the whole point of checking.
9. **An unreadable directory fails**, and a missing probe is reported as a missing probe
   rather than as an inaccessible directory.
10. **The media directory itself is never written, moved or deleted** -- by this module or
    by a recreation it drives.

Standard library only. No network, no Git, no Docker, no live Hong Kong contact.
"""
import ast
import hashlib
import importlib.machinery
import importlib.util
import inspect
import json
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
RUNTIME = REPO / "hk-staging" / "source" / "executor" / "runtime"
EXECUTOR = REPO / "hk-staging" / "source" / "executor"
MEDIA_PATH = RUNTIME / "media_mount.py"
DEPLOY_PATH = RUNTIME / "deploy_runtime.py"
ROLLBACK_PATH = RUNTIME / "rollback_runtime.py"
INSTALL_FACT_PATH = RUNTIME / "install_fact.py"
LAUNCHER_PATH = EXECUTOR / "go-hk-deployctl"
SOURCE_MANIFEST = REPO / "hk-staging" / "SOURCE_SHA256SUMS.txt"

IMAGE = "sha256:" + "a" * 64

# Windows expresses only the read-only bit through `chmod`, so a file's `st_mode` there is
# `0666` whatever the module asked for. The permission assertions are Linux properties and
# are written as such rather than weakened: the suite runs on both hosts, and a test that
# cannot tell the difference would report the gap as a pass.
POSIX = os.name == "posix"


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def blob_sha256(path):
    """The hash of the blob, not of this checkout's copy of it.

    A pin is a repository-blob hash. The host is staged from the blob and therefore holds
    LF; this worktree has `core.autocrlf=true` and holds CRLF, so the two differ by line
    endings alone. Compare the normalised form -- the form the host receives -- which is
    also what the installation-fact suite compares.
    """
    raw = pathlib.Path(path).read_bytes()
    return hashlib.sha256(raw.replace(bytes((13, 10)), bytes((10,)))).hexdigest()


m = load("media_mount_under_test", MEDIA_PATH)

# Captured before any test patches it: the directory the executor actually writes to is
# what the product decision fixes, and a value a test injected must not stand in for it.
DEFAULT_OVERLAY_DIR = m.OVERLAY_DIR


class Result(object):
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def container(service, running=True, mount=True, source=None, destination=None,
              read_write=True, environment=None, extra_mounts=(), project=None,
              image=IMAGE, identifier=None):
    """One `docker inspect` row, shaped exactly as the module reads it."""
    mounts = []
    if mount:
        mounts.append({"Type": "bind", "Source": source or m.HOST_PATH,
                       "Destination": destination or m.CONTAINER_PATH, "RW": read_write})
    mounts.extend(extra_mounts)
    if environment is None:
        environment = [m.CACHE_ENV + "=" + m.CONTAINER_PATH]
    return {"Id": identifier or ("id-" + service), "Image": image,
            "State": {"Running": running, "Status": "running" if running else "exited"},
            "Config": {"Labels": {"com.docker.compose.project": project or m.PROJECT,
                                  "com.docker.compose.service": service},
                       "Env": environment},
            "Mounts": mounts}


class FakeHost(object):
    """A Docker that behaves the way a given mount actually turned out.

    `run()` answers the four argv shapes the module issues, records every one of them,
    and reports the container set it was configured with -- so a test can hand the check
    a perfect command line and a container set that disagrees with it.
    """

    def __init__(self, containers=None, probe_codes=None, compose_code=0):
        self.calls = []
        self.compose_code = compose_code
        self.rows = containers if containers is not None else [
            container(service) for service in m.SERVICES]
        self.probe_codes = dict(probe_codes or {})

    def run(self, argv):
        self.calls.append(list(argv))
        if argv[1:3] == ["compose", "--env-file"]:
            return Result(self.compose_code, "")
        if argv[1] == "ps":
            service = argv[-1].split("service=", 1)[1]
            return Result(0, "id-" + service + "\n")
        if argv[1] == "inspect":
            return Result(0, json.dumps(self.rows))
        if argv[1] == "exec":
            return Result(self.probe_codes.get(argv[2], 0), "")
        raise AssertionError("unexpected argv: %r" % (argv,))

    @property
    def recreation(self):
        return [call for call in self.calls if call[1] == "compose"]


class RecreationCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.overlay_dir = pathlib.Path(self.tmp.name) / "overlays"
        self._overlay_dir = m.OVERLAY_DIR
        m.OVERLAY_DIR = str(self.overlay_dir)
        self.addCleanup(self._restore)

    def _restore(self):
        m.OVERLAY_DIR = self._overlay_dir
        self.tmp.cleanup()

    def recreate(self, host, **kwargs):
        """Drive the shared builder the way a runtime drives it.

        `media_mount.recreate()` takes the caller's own command wrapper, so a non-zero
        Docker command is the wrapper's finding, exactly as `deploy_runtime._run()` and
        `rollback_runtime._run()` make it. Reproducing that here is what lets the cleanup
        test below fail the command rather than silently checking a host that never ran.
        """
        def run(argv):
            result = host.run(argv)
            if result.returncode != 0:
                raise m.MediaMountFailed(m.E_MEDIA_MOUNT_CONTAINERS)
            return result
        return m.recreate(host, run, **kwargs)


class TheCommandTests(RecreationCase):
    """1, 2, 3 and 4: the mount is in the command because the definition says so."""

    def setUp(self):
        super().setUp()
        self.deploy_source = DEPLOY_PATH.read_text(encoding="utf-8")
        self.rollback_source = ROLLBACK_PATH.read_text(encoding="utf-8")

    def test_deploy_delegates_to_the_shared_builder(self):
        self.assertIn("media.recreate(", self.deploy_source)
        self.assertIn("_load_media_mount()", self.deploy_source)

    def test_rollback_delegates_to_the_shared_builder(self):
        self.assertIn("media.recreate(", self.rollback_source)
        self.assertIn("_load_media_mount()", self.rollback_source)

    def test_no_other_file_builds_a_recreating_command(self):
        """The recreation flag is a string constant in exactly one module.

        Reading the tree this way rather than listing the entry points is deliberate: it
        asserts "nothing else can recreate the containers", which is the property, rather
        than "the two paths I remembered are wired", which is a subset of it. Docstrings
        that quote the flag are not string constants and do not count.
        """
        holders = set()
        for path in sorted((REPO / "hk-staging" / "source").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value == "--force-recreate":
                    holders.add(path.relative_to(REPO).as_posix())
        self.assertEqual(holders, {"hk-staging/source/executor/runtime/media_mount.py"})

    def test_the_builder_puts_the_media_overlay_last(self):
        argv = m.recreate_argv("/run/go-hk-deployctl/media-mount-x.yaml",
                               extra_files=["/run/go-hk-deployctl/deploy-x.yaml"])
        self.assertEqual(argv[-len(m.SERVICES) - 6:-len(m.SERVICES)],
                         ["-f", "/run/go-hk-deployctl/media-mount-x.yaml",
                          "up", "-d", "--no-deps", "--force-recreate"])
        self.assertEqual(argv[argv.index("-f") + 1:],
                         [m.COMPOSE, "-f", "/run/go-hk-deployctl/deploy-x.yaml",
                          "-f", "/run/go-hk-deployctl/media-mount-x.yaml",
                          "up", "-d", "--no-deps", "--force-recreate", *m.SERVICES])
        self.assertEqual(list(argv[-len(m.SERVICES):]), list(m.SERVICES))

    def test_the_overlay_carries_the_same_definition_for_every_service(self):
        text = m.overlay_text()
        self.assertEqual(m.overlay_sha256(),
                         hashlib.sha256(text.encode("utf-8")).hexdigest())
        for service in m.SERVICES:
            self.assertIn("  " + service + ":\n", text)
        self.assertEqual(text.count("source: " + m.HOST_PATH + "\n"), len(m.SERVICES))
        self.assertEqual(text.count("target: " + m.CONTAINER_PATH + "\n"), len(m.SERVICES))
        self.assertEqual(text.count(m.CACHE_ENV + ": " + m.CONTAINER_PATH + "\n"),
                         len(m.SERVICES))
        # Docker must not invent the directory: a missing host path is a failure of the
        # recreation, not a silently empty cache.
        self.assertEqual(text.count("create_host_path: false\n"), len(m.SERVICES))
        self.assertFalse(m.CREATE_HOST_PATH)
        self.assertEqual(m.CONTAINER_PATH, m.HOST_PATH)

    def test_nothing_about_the_mount_comes_from_a_caller(self):
        for function in (m.recreate_argv, m.recreate, m.verify, m.judge):
            parameters = set(inspect.signature(function).parameters)
            self.assertFalse(
                parameters & {"path", "host_path", "container_path", "services",
                              "topology", "contract", "candidate", "expected"},
                "%s takes an input that would let a caller name the mount" % function.__name__)
        source = MEDIA_PATH.read_text(encoding="utf-8").lower()
        for forbidden in ("topology", "candidate_contract", "authorization", "marker"):
            self.assertNotIn(forbidden, source,
                             "the fixed mount must not carry a %s notion" % forbidden)

    def test_the_launcher_offers_no_media_command_line_option(self):
        source = LAUNCHER_PATH.read_text(encoding="utf-8")
        for flag in ("--media", "--media-path", "--media-mount", "--volume", "--compose-file"):
            self.assertNotIn('"' + flag + '"', source)


class TheVerdictTests(RecreationCase):
    """5, 6, 7, 8 and 9: what the check reads, and what it says."""

    def test_a_healthy_mount_reports_success(self):
        host = FakeHost()
        result = self.recreate(host)
        self.assertEqual(result, {"MEDIA_MOUNT": "SUCCESS"})
        self.assertEqual(len(host.recreation), 1)
        self.assertEqual(host.recreation[0][-len(m.SERVICES):], list(m.SERVICES))

    def test_a_missing_mount_fails_the_operation(self):
        host = FakeHost([container(service, mount=False) for service in m.SERVICES])
        with self.assertRaises(m.MediaMountFailed) as caught:
            self.recreate(host)
        self.assertEqual(caught.exception.reason, m.E_MEDIA_MOUNT_ABSENT)
        # The failure carries the result the operation must report, so a caller cannot
        # report a plain success for a recreation that left the directory unmounted.
        self.assertEqual(caught.exception.gate_results,
                         {"MEDIA_MOUNT": "FAILED",
                          "MEDIA_MOUNT_REASON": m.E_MEDIA_MOUNT_ABSENT})
        self.assertEqual(str(caught.exception), m.E_MEDIA_MOUNT_ABSENT)

    def test_the_check_reads_the_containers_not_the_command_line(self):
        """The command is perfect and the containers disagree -- the containers win."""
        host = FakeHost([container(service, mount=False) for service in m.SERVICES])
        with self.assertRaises(m.MediaMountFailed):
            self.recreate(host)
        self.assertIn("-f", host.recreation[0])
        self.assertIn(m.HOST_PATH, m.overlay_text())

    def test_a_mount_from_somewhere_else_fails(self):
        host = FakeHost([container(service, source="/var/lib/other-cache")
                         for service in m.SERVICES])
        with self.assertRaises(m.MediaMountFailed) as caught:
            self.recreate(host)
        self.assertEqual(caught.exception.reason, m.E_MEDIA_MOUNT_ABSENT)

    def test_a_mount_at_somewhere_else_fails(self):
        host = FakeHost([container(service, destination="/var/lib/go-hotel/media_cache")
                         for service in m.SERVICES])
        with self.assertRaises(m.MediaMountFailed) as caught:
            self.recreate(host)
        self.assertEqual(caught.exception.reason, m.E_MEDIA_MOUNT_ABSENT)

    def test_a_read_only_mount_fails(self):
        rows = [container(m.SERVICES[0], read_write=False)]
        rows += [container(service) for service in m.SERVICES[1:]]
        with self.assertRaises(m.MediaMountFailed) as caught:
            self.recreate(FakeHost(rows))
        self.assertEqual(caught.exception.reason, m.E_MEDIA_MOUNT_ABSENT)

    def test_a_second_mount_over_the_cache_fails(self):
        shadow = {"Type": "bind", "Source": m.HOST_PATH + "/files",
                  "Destination": m.HOST_PATH + "/files", "RW": True}
        rows = [container(m.SERVICES[0], extra_mounts=[shadow])]
        rows += [container(service) for service in m.SERVICES[1:]]
        with self.assertRaises(m.MediaMountFailed) as caught:
            self.recreate(FakeHost(rows))
        self.assertEqual(caught.exception.reason, m.E_MEDIA_MOUNT_ABSENT)

    def test_a_cache_resolved_somewhere_else_fails(self):
        rows = [container(m.SERVICES[0], environment=[m.CACHE_ENV + "=var/media_cache"])]
        rows += [container(service) for service in m.SERVICES[1:]]
        with self.assertRaises(m.MediaMountFailed) as caught:
            self.recreate(FakeHost(rows))
        self.assertEqual(caught.exception.reason, m.E_MEDIA_MOUNT_ENV_DRIFT)

    def test_a_missing_or_stopped_container_fails(self):
        with self.assertRaises(m.MediaMountFailed) as caught:
            self.recreate(FakeHost([container(service) for service in m.SERVICES[:-1]]))
        self.assertEqual(caught.exception.reason, m.E_MEDIA_MOUNT_CONTAINERS)
        with self.assertRaises(m.MediaMountFailed) as caught:
            self.recreate(FakeHost([container(m.SERVICES[0], running=False)]
                                   + [container(service) for service in m.SERVICES[1:]]))
        self.assertEqual(caught.exception.reason, m.E_MEDIA_MOUNT_CONTAINERS)
        with self.assertRaises(m.MediaMountFailed) as caught:
            self.recreate(FakeHost([container(m.SERVICES[0], project="other")]
                                   + [container(service) for service in m.SERVICES[1:]]))
        self.assertEqual(caught.exception.reason, m.E_MEDIA_MOUNT_CONTAINERS)

    def test_an_unreadable_directory_fails(self):
        codes = {("id-" + m.SERVICES[0]): 7}
        with self.assertRaises(m.MediaMountFailed) as caught:
            self.recreate(FakeHost(probe_codes=codes))
        self.assertEqual(caught.exception.reason, m.E_MEDIA_MOUNT_INACCESSIBLE)

    def test_a_missing_probe_is_reported_as_a_missing_probe(self):
        """A probe that could not run must not be blamed on the media directory."""
        codes = {("id-" + m.SERVICES[0]): 127}
        with self.assertRaises(m.MediaMountFailed) as caught:
            self.recreate(FakeHost(probe_codes=codes))
        self.assertEqual(caught.exception.reason, m.E_MEDIA_MOUNT_PROBE_UNAVAILABLE)

    def test_the_probe_asks_the_container_about_the_fixed_path(self):
        argv = m.probe_argv("id-api")
        self.assertEqual(argv[:5], [m.DOCKER, "exec", "id-api", "python", "-c"])
        self.assertEqual(argv[-1], m.CONTAINER_PATH)
        self.assertIn("listdir", argv[5])

    def test_the_verdict_vocabulary_has_two_words(self):
        self.assertEqual((m.SUCCESS, m.FAILED), ("SUCCESS", "FAILED"))
        self.assertEqual(m.MEDIA_MOUNT, "MEDIA_MOUNT")
        self.assertEqual(m.MEDIA_MOUNT_REASON, "MEDIA_MOUNT_REASON")


class TheDirectoryTests(RecreationCase):
    """10: the media directory is read at most, and moved never."""

    def test_a_recreation_does_not_touch_the_media_directory(self):
        cache = pathlib.Path(self.tmp.name) / "media-cache"
        (cache / "files").mkdir(parents=True)
        (cache / "index.sqlite3").write_bytes(b"sqlite-bytes")
        (cache / "files" / "photo.jpg").write_bytes(b"photo-bytes")
        before = {path.relative_to(cache): path.read_bytes()
                  for path in sorted(cache.rglob("*")) if path.is_file()}
        previous = (m.HOST_PATH, m.CONTAINER_PATH)
        m.HOST_PATH = str(cache)
        m.CONTAINER_PATH = str(cache)
        try:
            # The container rows are rebuilt after the definition moves, so the mount and
            # the environment are the ones the module now expects: this test is about the
            # directory surviving a recreation, not about the paths.
            host = FakeHost([container(service) for service in m.SERVICES])
            self.assertEqual(self.recreate(host), {"MEDIA_MOUNT": "SUCCESS"})
        finally:
            m.HOST_PATH, m.CONTAINER_PATH = previous
        after = {path.relative_to(cache): path.read_bytes()
                 for path in sorted(cache.rglob("*")) if path.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(sorted(p.name for p in cache.iterdir()),
                         ["files", "index.sqlite3"])

    def test_the_only_file_this_module_removes_is_its_own_overlay(self):
        tree = ast.parse(MEDIA_PATH.read_text(encoding="utf-8"), str(MEDIA_PATH))
        removers = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Attribute) and inner.attr in (
                            "unlink", "rmdir", "remove", "rmtree", "rename", "replace"):
                        removers.add(node.name)
        self.assertEqual(removers, {"remove_overlay"})
        self.assertNotIn("shutil", MEDIA_PATH.read_text(encoding="utf-8"))

    def test_the_overlay_is_cleaned_up_even_when_the_recreation_fails(self):
        host = FakeHost(compose_code=1)
        with self.assertRaises(m.MediaMountFailed):
            self.recreate(host)
        self.assertEqual(list(self.overlay_dir.iterdir()), [])

    def test_the_overlay_is_written_where_only_the_executor_writes(self):
        self.assertEqual(DEFAULT_OVERLAY_DIR, "/run/go-hk-deployctl")
        path = m.write_overlay()
        try:
            # `OVERLAY_DIR` is read when the overlay is written, not bound as a default
            # argument, so the patched constant is what decides the location -- and the
            # default above is what the executor will use on the host.
            self.assertEqual(pathlib.Path(path).parent, self.overlay_dir)
            self.assertTrue(path.endswith(".yaml"))
            self.assertEqual(pathlib.Path(path).read_text(encoding="utf-8"),
                             m.overlay_text())
        finally:
            m.remove_overlay(path)

    @unittest.skipUnless(POSIX, "mode bits are not expressible on this platform")
    def test_the_overlay_is_written_private(self):
        path = m.write_overlay()
        try:
            self.assertEqual(pathlib.Path(path).stat().st_mode & 0o777, 0o600)
        finally:
            m.remove_overlay(path)


class TheWiringTests(unittest.TestCase):
    """The module is the executor's, it is registered, and every pin agrees."""

    def test_the_media_module_replaces_the_old_guard_everywhere(self):
        self.assertFalse((RUNTIME / "media_guard.py").exists())
        self.assertFalse((ROOT / "tests" / "test_media_guard.py").exists())
        module_list = INSTALL_FACT_PATH.read_text(encoding="utf-8")
        self.assertIn("    'media_mount',\n", module_list)
        self.assertNotIn("media_guard", module_list)
        for path in (DEPLOY_PATH, ROLLBACK_PATH, LAUNCHER_PATH, SOURCE_MANIFEST):
            self.assertNotIn("media_guard", path.read_text(encoding="utf-8"),
                             "%s still names the retired module" % path.name)

    def test_both_doors_pin_the_same_definition(self):
        digest = blob_sha256(MEDIA_PATH)
        deploy = DEPLOY_PATH.read_text(encoding="utf-8")
        rollback = ROLLBACK_PATH.read_text(encoding="utf-8")
        self.assertIn('_MEDIA_MOUNT_SHA256 = "%s"' % digest, deploy)
        self.assertIn('_MEDIA_MOUNT_SHA256="%s"' % digest, rollback)
        self.assertIn("_load_sibling(\"media_mount\", _MEDIA_MOUNT_SHA256",
                      deploy)
        self.assertIn("media_mount.py", rollback)

    def test_the_install_fact_pins_the_new_runtimes(self):
        launcher = LAUNCHER_PATH.read_text(encoding="utf-8")
        self.assertIn('_DEPLOY_SHA256 = "%s"' % blob_sha256(DEPLOY_PATH), launcher)
        self.assertIn('_ROLLBACK_SHA256 = "%s"' % blob_sha256(ROLLBACK_PATH), launcher)

    def test_the_media_module_is_in_the_source_manifest(self):
        manifest = SOURCE_MANIFEST.read_text(encoding="utf-8")
        self.assertIn("media_mount.py", manifest)
        self.assertIn(blob_sha256(MEDIA_PATH), manifest)

    def test_both_results_carry_the_mount_finding(self):
        self.assertIn("**media_result", DEPLOY_PATH.read_text(encoding="utf-8"))
        self.assertIn("**media_result", ROLLBACK_PATH.read_text(encoding="utf-8"))

    def test_the_launcher_reports_a_gate_result_carrying_refusal(self):
        """`MEDIA_MOUNT=FAILED` reaches the document without parsing a sentence."""
        source = LAUNCHER_PATH.read_text(encoding="utf-8")
        self.assertEqual(source.count('getattr(exc,"gate_results",None) or gates'), 2)


if __name__ == "__main__":
    unittest.main()
