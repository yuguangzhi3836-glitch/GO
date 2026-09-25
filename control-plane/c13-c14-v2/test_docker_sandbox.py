"""Synthetic parser/isolation tests; real execution is a separate CI job."""
import base64
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch, Mock
import xml.etree.ElementTree as ET

from acceptance_gate import Refusal
from c13_attestation import CANDIDATE, TREE, SCOPE
from c14_isolated_runner import SCOPE_COMMANDS
from docker_sandbox import DockerSandbox, parse_output, TMPFS, ENTRYPOINT, ENTRY_ARGS, MAX_OUTPUT
from house_bridge import canonical, frozen_junit_counts
from sandbox_payload import unpack_source, git_object, suite_environment

IMAGE = "sha256:" + "a" * 64


def raw_fixture():
    inventory = json.loads(Path(__file__).with_name("c14_frozen_test_inventory.json").read_text())
    files = {"pytest.log": b"synthetic fixture\n", "suite.log": b"synthetic fixture\n",
             "postgres.log": b"synthetic fixture\n", "setup.log": b"synthetic fixture\n"}
    for name, filename in (("pytest", "pytest.xml"), ("isolated_postgres", "junit.xml")):
        suite = ET.Element("testsuite", name=name, tests=str(len(inventory[name])), failures="0", errors="0", skipped="0")
        for case in inventory[name]:
            ET.SubElement(suite, "testcase", **case)
        root = ET.Element("testsuites") if name == "pytest" else suite
        if root is not suite:
            root.append(suite)
        files[filename] = ET.tostring(root)
    files["execution.json"] = canonical({"source_commit": CANDIDATE, "database_backend": "postgresql",
        "postgres_server_version": "18.4 (synthetic)", "tests": 10, "failures": 0,
        "status": "EVIDENCE_READY", "hard_death_auto_recovery": "PASS"})
    files["results.json"] = canonical([{"case": c["name"], "status": "PASS"} for c in inventory["isolated_postgres"]])
    return {"contract": "GO_C14_SANDBOX_OUTPUT_V1", "candidate_sha": CANDIDATE, "application_tree": TREE,
        "postgres_version": "18.4 (synthetic)", "pytest_exit": 0, "postgres_exit": 0,
        "files": {k: base64.b64encode(v).decode() for k, v in files.items()}}


def info():
    return {"Image": IMAGE, "Config": {"User": "65532:65532", "Entrypoint": [ENTRYPOINT], "Cmd": ENTRY_ARGS},
        "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
        "CapDrop": ["ALL"], "Tmpfs": TMPFS, "Memory": 2147483648, "PidsLimit": 128,
        "NanoCpus": 2000000000, "SecurityOpt": ["no-new-privileges"], "IpcMode": "private"}, "Mounts": []}


class ParserTests(unittest.TestCase):
    def test_both_real_suite_shapes_and_lossless_raw_files(self):
        fixture = raw_fixture()
        result = parse_output(canonical(fixture), IMAGE, "b" * 64)
        self.assertEqual(frozen_junit_counts(result["junit"]), [71, 0, 0, 0])
        for encoded in fixture["files"].values():
            self.assertIn(base64.b64decode(encoded), result["stdout"])

    def test_missing_raw_and_false_exit_cannot_pass(self):
        for field in ("pytest_exit", "postgres_exit", "files", "candidate_sha", "postgres_version"):
            fixture = raw_fixture()
            fixture[field] = 1 if field.endswith("exit") else {} if field == "files" else "wrong"
            with self.subTest(field=field), self.assertRaises(Refusal):
                parse_output(canonical(fixture), IMAGE, "b" * 64)

    def test_raw_failure_survives(self):
        fixture = raw_fixture()
        root = ET.fromstring(base64.b64decode(fixture["files"]["pytest.xml"]))
        root[0].set("failures", "1")
        ET.SubElement(root[0][0], "failure", message="actual test failed")
        fixture["files"]["pytest.xml"] = base64.b64encode(ET.tostring(root)).decode()
        fixture["pytest_exit"] = 1
        result = parse_output(canonical(fixture), IMAGE, "b" * 64)
        self.assertEqual(frozen_junit_counts(result["junit"]), [71, 1, 0, 0])

    def test_sqlite_or_unproven_recovery_refused(self):
        for key, value in (("database_backend", "sqlite"), ("hard_death_auto_recovery", "NOT_PROVEN"), ("source_commit", "other")):
            fixture = raw_fixture()
            data = json.loads(base64.b64decode(fixture["files"]["execution.json"]))
            data[key] = value
            fixture["files"]["execution.json"] = base64.b64encode(canonical(data)).decode()
            with self.subTest(key=key), self.assertRaises(Refusal):
                parse_output(canonical(fixture), IMAGE, "b" * 64)

    def test_inventory_cannot_replace_missing_or_renamed_case(self):
        fixture = raw_fixture()
        root = ET.fromstring(base64.b64decode(fixture["files"]["junit.xml"]))
        root[0].set("name", "different-case")
        fixture["files"]["junit.xml"] = base64.b64encode(ET.tostring(root)).decode()
        with self.assertRaises(Refusal):
            parse_output(canonical(fixture), IMAGE, "b" * 64)


class SourceTests(unittest.TestCase):
    def test_external_test_entrypoint_can_import_both_source_and_test_helpers(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "application"
            (source / "src").mkdir(parents=True)
            (source / "tests").mkdir()
            (source / "src" / "sample_app.py").write_text("value = 7\n")
            (source / "tests" / "__init__.py").write_text("")
            (source / "tests" / "helper.py").write_text("from sample_app import value\n")
            result = subprocess.run([sys.executable, "-c", "from tests.helper import value; assert value == 7"],
                                    cwd=root, env=suite_environment(source), capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode())

    def archive(self, name="x.py", content=b"print('test')\n", link=False):
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w") as archive:
            item = tarfile.TarInfo(name)
            item.mode = 0o644
            item.size = len(content)
            if link:
                item.type, item.linkname = tarfile.SYMTYPE, "/etc/passwd"
            archive.addfile(item, io.BytesIO(content))
        tree = git_object(b"tree", b"100644 x.py\0" + git_object(b"blob", content)).hex()
        return raw.getvalue(), tree

    def test_verified_tree_extracts_exact_bytes(self):
        raw, tree = self.archive()
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "source"
            unpack_source(raw, target, tree)
            self.assertEqual((target / "x.py").read_bytes(), b"print('test')\n")

    def test_tamper_traversal_and_links_refused_before_extract(self):
        for name, link in (("../escape", False), ("/absolute", False), ("x.py", True), ("x.py", False)):
            raw, tree = self.archive(name=name, link=link)
            with tempfile.TemporaryDirectory() as root:
                target = Path(root) / "source"
                with self.assertRaises(ValueError):
                    unpack_source(raw, target, "0" * 40)
                self.assertFalse(target.exists())


class HostTests(unittest.TestCase):
    def host(self):
        return DockerSandbox("/trusted/repository", IMAGE, "/run/c14/docker.sock")

    def test_only_immutable_image_and_local_socket_configuration(self):
        for image, socket in (("postgres:18.4", "/run/docker.sock"), (IMAGE, "tcp://host:2375")):
            with self.assertRaises(Refusal):
                DockerSandbox("/repo", image, socket)
        self.assertNotIn("DOCKER_HOST", self.host().env)

    def test_inspect_rejects_daemon_isolation_drift(self):
        self.host()._check_container(info())
        for key, value in (("NetworkMode", "host"), ("Privileged", True), ("Binds", ["/:/host"]),
                           ("ReadonlyRootfs", False), ("Memory", 0), ("PidsLimit", 0)):
            data = copy.deepcopy(info())
            data["HostConfig"][key] = value
            with self.subTest(key=key), self.assertRaises(Refusal):
                self.host()._check_container(data)

    def test_refused_inspection_destroys_container(self):
        host = self.host()
        host._source_archive = lambda: b"fixture"
        calls = []
        def command(argv):
            calls.append(argv)
            if "image" in argv:
                return canonical([{"Id": IMAGE, "Config": {"Volumes": {"/var/lib/postgresql": {}}}}])
            if "inspect" in argv:
                data = info()
                data["HostConfig"]["NetworkMode"] = "host"
                return canonical([data])
            return b"ok"
        host._command = command
        with self.assertRaisesRegex(Refusal, "sandbox_isolation"):
            host.run_fixed_isolated_suite(CANDIDATE, TREE, SCOPE_COMMANDS)
        self.assertIn("rm", calls[-1])
        self.assertIn("--force", calls[-1])
        self.assertFalse(any("start" in c for c in calls))

    def capture_failure(self, *, timeout=True, oversized=False, cleanup_failure=False):
        host = self.host()
        host._source_archive = lambda: b"fixture"
        calls = []
        inspections = 0
        def command(argv):
            nonlocal inspections
            calls.append(argv)
            if "image" in argv:
                return canonical([{"Id": IMAGE, "Config": {"Volumes": {"/var/lib/postgresql": {}}}}])
            if "inspect" in argv:
                inspections += 1
                if inspections == 2:
                    raise subprocess.CalledProcessError(1, argv)
                return canonical([info()])
            if "rm" in argv and cleanup_failure:
                raise subprocess.CalledProcessError(1, argv)
            return b"ok"
        host._command = command
        process = Mock()
        process.communicate.side_effect = ([subprocess.TimeoutExpired("docker", 3300), (b"", b"")]
                                           if timeout else [(b"", b"")])
        stdout = b"x" * (MAX_OUTPUT + 100) if oversized else b"partial stdout\x00\xff\n"
        stderr = b"e" * 65000 if oversized else b"partial stderr\x00\xfe\n"
        def start(*args, **kwargs):
            kwargs["stdout"].write(stdout)
            kwargs["stderr"].write(stderr)
            return process
        reason = "sandbox_cleanup" if cleanup_failure else "sandbox_timeout" if timeout else "sandbox_host"
        with patch("docker_sandbox.subprocess.Popen", side_effect=start), \
                patch("docker_sandbox.parse_output") as parse, self.assertRaisesRegex(Refusal, reason):
            host.run_fixed_isolated_suite(CANDIDATE, TREE, SCOPE_COMMANDS)
        parse.assert_not_called()
        if timeout:
            process.kill.assert_called_once()
        else:
            process.kill.assert_not_called()
        self.assertEqual(host.last_output, stdout[:MAX_OUTPUT + 1])
        self.assertEqual(host.last_stderr, stderr[:64000])
        self.assertIn("rm", calls[-1])
        self.assertEqual(sum("create" in c for c in calls), 1)

    def test_timeout_kills_client_and_removes_container(self):
        self.capture_failure()

    def test_timeout_diagnostics_remain_bounded(self):
        self.capture_failure(oversized=True)

    def test_post_exit_inspect_failure_retains_diagnostics(self):
        self.capture_failure(timeout=False)

    def test_cleanup_failure_retains_diagnostics_and_refuses(self):
        self.capture_failure(cleanup_failure=True)


if __name__ == "__main__":
    unittest.main()
