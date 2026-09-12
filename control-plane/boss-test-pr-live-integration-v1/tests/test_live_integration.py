import datetime as dt
import ast
import hashlib
import importlib.machinery
import importlib.util
import pathlib
import os
import shlex
import subprocess
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.modules.setdefault("fcntl", types.SimpleNamespace(LOCK_EX=0, LOCK_UN=0, flock=lambda *args, **kwargs: None))
loader = importlib.machinery.SourceFileLoader("bridge_candidate", str(ROOT / "command-center" / "go-boss-request-bridge"))
spec = importlib.util.spec_from_loader(loader.name, loader)
bridge = importlib.util.module_from_spec(spec)
loader.exec_module(bridge)
sys.path.insert(0, str(ROOT / "hk-staging"))
from hk_agent import test_pr, transport


class IntegrationTests(unittest.TestCase):
    def rollback_sandbox(self, role):
        raw = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = pathlib.Path(raw.name)
        backup = root / "backup"
        backup.mkdir()
        targets = root / "targets"
        targets.mkdir()
        names = (
            ("go-boss-request-bridge", "boss-request-bridge-v1.json")
            if role == "command-center"
            else ("transport.py", "agent.json", "test_pr.py", "Dockerfile.go-application-python-v1", "docker-access.conf")
        )
        present = names if role == "command-center" else names[:2]
        records, installed, target_paths = [], [], {}
        for index, name in enumerate(names):
            target = targets / name
            target.write_text(f"candidate-{name}", encoding="utf-8")
            target.chmod(0o640 if index % 2 == 0 else 0o600)
            target_paths[name] = target
            installed.append(f"{name}|{hashlib.sha256(target.read_bytes()).hexdigest()}")
            if name in present:
                original = backup / name
                original.write_text(f"original-{name}", encoding="utf-8")
                original.chmod(0o640 if index % 2 == 0 else 0o600)
                owner_mode = subprocess.check_output(
                    ["bash", "-lc", f"stat -c '%u:%g|%a' {shlex.quote(self.bash_path(original))}"],
                    text=True,
                ).strip()
                if role == "command-center":
                    records.append(f"{name}|{hashlib.sha256(original.read_bytes()).hexdigest()}|{owner_mode}")
                else:
                    records.append(f"{name}|present|{hashlib.sha256(original.read_bytes()).hexdigest()}|{owner_mode}")
            elif role == "hk-staging":
                records.append(f"{name}|absent|||")
            else:
                raise AssertionError("unexpected command-center state")
        (backup / "state.tsv").write_text("\n".join(records) + "\n", encoding="utf-8")
        (backup / "installed.tsv").write_text("\n".join(installed) + "\n", encoding="utf-8")
        env = os.environ.copy()
        if role == "command-center":
            env.update({
                "GO_CC_ROLLBACK_BACKUP": self.bash_path(backup),
                "GO_CC_BRIDGE_PATH": self.bash_path(target_paths["go-boss-request-bridge"]),
                "GO_CC_CONFIG_PATH": self.bash_path(target_paths["boss-request-bridge-v1.json"]),
            })
        else:
            runtime_root = targets / "runtime-root"
            build_root = runtime_root / "builds"
            runtime_root.mkdir()
            build_root.mkdir()
            runtime_root.chmod(0o700)
            build_root.chmod(0o700)
            systemctl_mock = root / "systemctl-mock"
            systemctl_mock.write_text("#!/bin/sh\n[ \"$1\" = is-active ] && exit 3\nexit 0\n", encoding="utf-8")
            systemctl_mock.chmod(0o700)
            owner, mode = subprocess.check_output(
                ["bash", "-lc", f"stat -c '%u:%g %a' {shlex.quote(self.bash_path(runtime_root))}"], text=True,
            ).strip().split()
            build_mode = subprocess.check_output(
                ["bash", "-lc", f"stat -c '%a' {shlex.quote(self.bash_path(build_root))}"], text=True,
            ).strip()
            records.extend(("runtime_root|absent|||", "builds|absent|||"))
            installed.extend((f"runtime_root|directory|{owner}|{mode}", f"builds|directory|{owner}|{build_mode}"))
            (backup / "state.tsv").write_text("\n".join(records) + "\n", encoding="utf-8")
            (backup / "installed.tsv").write_text("\n".join(installed) + "\n", encoding="utf-8")
            target_paths["runtime_root"] = runtime_root
            target_paths["builds"] = build_root
            env.update({
                "GO_HK_ROLLBACK_BACKUP": self.bash_path(backup),
                "GO_HK_TRANSPORT_PATH": self.bash_path(target_paths["transport.py"]),
                "GO_HK_AGENT_CONFIG_PATH": self.bash_path(target_paths["agent.json"]),
                "GO_HK_TEST_PR_PATH": self.bash_path(target_paths["test_pr.py"]),
                "GO_HK_DOCKERFILE_PATH": self.bash_path(target_paths["Dockerfile.go-application-python-v1"]),
                "GO_HK_DOCKER_DROPIN_PATH": self.bash_path(target_paths["docker-access.conf"]),
                "GO_HK_RUNTIME_ROOT": self.bash_path(runtime_root),
                "GO_HK_BUILD_ROOT": self.bash_path(build_root),
                "GO_HK_AGENT_UNIT": "test-pr-agent-not-active.service",
                "GO_SYSTEMCTL": self.bash_path(systemctl_mock),
            })
        return raw, backup, target_paths, env

    @staticmethod
    def bash_path(path):
        return subprocess.check_output(["cygpath", "-u", str(path)], text=True).strip()

    def run_rollback(self, role, env):
        return subprocess.run(
            ["bash", self.bash_path(ROOT / "install" / "uninstall.sh"), role],
            env=env,
            text=True,
            capture_output=True,
        )

    def setUp(self):
        self.at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        self.request = {
            "schema_version": "1", "request_id": "test-pr-request-001",
            "action_id": "HK_STAGING_TEST_PR", "environment": "HK-STAGING-01",
            "pr_number": "42", "requested_at": bridge.iso(self.at),
        }

    def test_verify_contract_is_still_accepted(self):
        request = {"schema_version": "1", "request_id": "verify-request-001",
                   "action_id": "HK_STAGING_VERIFY", "environment": "HK-STAGING-01",
                   "requested_at": bridge.iso(self.at)}
        self.assertEqual(bridge.validate_request(bridge.canonical(request), self.at)["action_id"], "HK_STAGING_VERIFY")

    def test_test_pr_rejects_every_caller_override(self):
        self.assertEqual(bridge.validate_request(bridge.canonical(self.request), self.at)["pr_number"], "42")
        for key, value in (("repository", "https://invalid"), ("ref", "refs/heads/main"),
                           ("commit_sha", "a" * 40), ("build_command", "id"),
                           ("dockerfile", "Dockerfile"), ("network", "host"),
                           ("services", ["api"])):
            bad = dict(self.request)
            bad[key] = value
            with self.assertRaises(bridge.Reject):
                bridge.validate_request(bridge.canonical(bad), self.at)

    def test_real_ed25519_signature_and_hk_evidence_adapter(self):
        task = bridge.derive_test_pr(self.request, self.at, lambda _: "b5732c02dd95092a63def7eaa0d2cf332b1e2996")
        self.assertNotIn("ref", task["parameters"]["source"])
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            root = pathlib.Path(raw)
            private = Ed25519PrivateKey.generate()
            pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
            public = private.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
            (root / "signer.pem").write_bytes(pem)
            (root / "verify.pub").write_bytes(public)
            signed = bridge.sign(task, root / "signer.pem")
            private.public_key().verify(bytes.fromhex(signed["signature"]), bridge.canonical(task))
            ledger = transport.Ledger(str(root / "ledger.sqlite3"))
            transport.validate(signed, {"environment": "HK-STAGING-01", "authority": "GO-COMMAND-CENTER", "task_verify_key": str(root / "verify.pub")}, ledger)
            original = test_pr.execute
            try:
                test_pr.execute = lambda _: {
                    "schema_version": "1", "executor_version": "test-pr-v1", "action_id": "HK_STAGING_TEST_PR",
                    "status": "SUCCESS", "result": "TEST_PR_OK", "source_pr_number": "42",
                    "source_commit_sha": task["parameters"]["source"]["commit_sha"],
                    "task_canonical_sha256": hashlib.sha256(transport.canonical(signed)).hexdigest(),
                    "built_image_id": "sha256:" + "a" * 64, "gate_results": {"source_commit": "PASS"},
                    "application_health_proven": False, "deployment_performed": False,
                }
                evidence = transport.evidence(signed, transport.dispatch_action(signed))
            finally:
                test_pr.execute = original
            self.assertFalse(evidence["application_health_proven"])
            self.assertFalse(evidence["deployment_performed"])
            self.assertEqual(evidence["source_commit_sha"], task["parameters"]["source"]["commit_sha"])

    def test_fixed_fetch_and_isolation_literals(self):
        source = (ROOT / "hk-staging" / "hk_agent" / "test_pr.py").read_text(encoding="utf-8")
        self.assertIn('["/usr/bin/git", "-C", str(workspace), "fetch", "--no-tags", "--depth", "1", "origin", commit]', source)
        self.assertIn('"--network", "none"', source)
        self.assertIn('"--read-only", "--cap-drop", "ALL"', source)
        self.assertNotIn("docker compose", source.lower())
        self.assertNotIn("root.mkdir", source)

    def test_offline_builder_profile_is_pinned_and_non_networked(self):
        dockerfile = (ROOT / "hk-staging" / "Dockerfile.go-application-python-v1").read_text(encoding="utf-8").lower()
        source = (ROOT / "hk-staging" / "hk_agent" / "test_pr.py").read_text(encoding="utf-8")
        self.assertNotIn("pip install", dockerfile)
        self.assertNotIn("apt", dockerfile)
        self.assertNotIn("curl", dockerfile)
        self.assertIn('"--network", "none", "--pull=false"', source)
        self.assertIn('"--entrypoint", "/bin/sh"', source)
        self.assertIn("TEST_PR_BUILDER_IMAGE_REJECT", source)
        self.assertIn("TEST_PR_DEPENDENCY_PROFILE_REJECT", source)

    def test_host_agent_has_no_tomllib_import(self):
        source = (ROOT / "hk-staging" / "hk_agent" / "test_pr.py").read_text(encoding="utf-8")
        imports = [node.names[0].name for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Import)]
        self.assertNotIn("tomllib", imports)
        self.assertIn('"--network", "none"', source)
        self.assertIn('"--entrypoint", "python"', source)

    def test_build_root_validation_rejects_unsafe_state_and_accepts_provisioned_root(self):
        original = test_pr.BUILD_ROOT
        try:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
                base = pathlib.Path(raw)
                test_pr.BUILD_ROOT = str(base / "missing")
                with self.assertRaisesRegex(test_pr.Reject, "TEST_PR_BUILD_ROOT_REJECT"):
                    test_pr._build_root()
                target = base / "target"
                target.mkdir()
                uid, gid = 1001, 1002
                valid = types.SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=uid, st_gid=gid)
                with mock.patch.object(pathlib.Path, "lstat", return_value=types.SimpleNamespace(st_mode=stat.S_IFLNK, st_uid=0, st_gid=0)):
                    test_pr.BUILD_ROOT = str(target)
                    with self.assertRaisesRegex(test_pr.Reject, "TEST_PR_BUILD_ROOT_REJECT"):
                        test_pr._build_root()
                test_pr.BUILD_ROOT = str(target)
                with mock.patch.object(pathlib.Path, "lstat", return_value=types.SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=uid, st_gid=gid)), \
                     mock.patch.object(test_pr.os, "geteuid", return_value=uid, create=True), \
                     mock.patch.object(test_pr.os, "getegid", return_value=gid, create=True):
                    with self.assertRaisesRegex(test_pr.Reject, "TEST_PR_BUILD_ROOT_REJECT"):
                        test_pr._build_root()
                with mock.patch.object(pathlib.Path, "lstat", return_value=valid), \
                     mock.patch.object(test_pr.os, "geteuid", return_value=uid + 1, create=True), \
                     mock.patch.object(test_pr.os, "getegid", return_value=gid, create=True):
                    with self.assertRaisesRegex(test_pr.Reject, "TEST_PR_BUILD_ROOT_REJECT"):
                        test_pr._build_root()
                with mock.patch.object(pathlib.Path, "lstat", return_value=valid), \
                     mock.patch.object(test_pr.os, "geteuid", return_value=uid, create=True), \
                     mock.patch.object(test_pr.os, "getegid", return_value=gid, create=True), \
                     mock.patch.object(test_pr.os, "access", return_value=False):
                    with self.assertRaisesRegex(test_pr.Reject, "TEST_PR_BUILD_ROOT_REJECT"):
                        test_pr._build_root()
                with mock.patch.object(pathlib.Path, "lstat", return_value=valid), \
                     mock.patch.object(test_pr.os, "geteuid", return_value=uid, create=True), \
                     mock.patch.object(test_pr.os, "getegid", return_value=gid, create=True), \
                     mock.patch.object(test_pr.os, "access", return_value=True):
                    self.assertEqual(test_pr._build_root(), target)
        finally:
            test_pr.BUILD_ROOT = original

    def test_persistent_replay_and_publish_shape_remain_integrated(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            root = pathlib.Path(raw)
            channel = root / "channel.json"
            channel.write_text('{"version":3,"mode":"PERSISTENT","publish_enabled":true,"allowed_actions":["HK_STAGING_VERIFY","HK_STAGING_TEST_PR"],"allowed_environment":"HK-STAGING-01"}')
            private = Ed25519PrivateKey.generate()
            (root / "signer.pem").write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            request = dict(self.request)
            proposal = {"path": "requests/test-pr-request-001.json", "raw": bridge.canonical(request)}
            task = bridge.derive_test_pr(request, self.at, lambda _: "b5732c02dd95092a63def7eaa0d2cf332b1e2996")
            original = bridge.read_pr, bridge.derive_formal_task, bridge.publish_task, bridge.remote_task
            published = {}
            try:
                bridge.read_pr = lambda *_: proposal
                bridge.derive_formal_task = lambda _: task
                bridge.publish_task = lambda value: published.setdefault("task", value) and "c" * 40
                bridge.remote_task = lambda _: bridge.canonical(published["task"]) + b"\n"
                first = bridge.persistent_process("7", "a" * 40, str(root / "ledger"), str(root / "signer.pem"), str(channel))
                self.assertEqual(first["status"], "published")
                self.assertEqual(published["task"]["parameters"]["source"]["commit_sha"], task["parameters"]["source"]["commit_sha"])
                self.assertEqual(bridge.persistent_process("7", "a" * 40, str(root / "ledger"), str(root / "signer.pem"), str(channel))["status"], "already_seen")
            finally:
                bridge.read_pr, bridge.derive_formal_task, bridge.publish_task, bridge.remote_task = original

    def test_command_center_backup_and_rollback_guard_set_is_complete(self):
        install = (ROOT / "install" / "install-command-center.sh").read_text(encoding="utf-8")
        rollback = (ROOT / "install" / "uninstall.sh").read_text(encoding="utf-8")
        preflight = (ROOT / "install" / "preflight.sh").read_text(encoding="utf-8")
        self.assertIn("sha256sum -c SHA256SUMS", install)
        self.assertIn("record /usr/local/libexec/go-boss-request-bridge go-boss-request-bridge", install)
        self.assertIn("record /etc/go-command-center/boss-request-bridge-v1.json boss-request-bridge-v1.json", install)
        self.assertIn('test ! -e "$backup/state.tsv"', install)
        self.assertIn("88880363d761eb924aac1910caa7696619dbbb0b4fcb112b63cf726de3bf1335", preflight)
        self.assertIn('test "$(sha256sum "$path" | awk', rollback)
        self.assertIn('test "$(sha256sum "$backup/$name" | awk', rollback)
        self.assertIn('validate go-boss-request-bridge "$bridge"', rollback)
        self.assertIn('validate boss-request-bridge-v1.json "$config"', rollback)
        self.assertIn('restore go-boss-request-bridge "$bridge"', rollback)
        self.assertIn('restore boss-request-bridge-v1.json "$config"', rollback)
        self.assertIn("cp -p", rollback)
        self.assertLess(rollback.index('test "$(sha256sum "$path" | awk'), rollback.index("cp -p"))

    def test_hk_backup_and_rollback_guard_set_is_complete(self):
        install = (ROOT / "install" / "install-hk-agent.sh").read_text(encoding="utf-8")
        rollback = (ROOT / "install" / "uninstall.sh").read_text(encoding="utf-8")
        preflight = (ROOT / "install" / "preflight.sh").read_text(encoding="utf-8")
        for statement in (
            "record /opt/go-hk-agent-rebuilt/hk_agent/transport.py transport.py",
            "record /etc/go-hk-agent/agent.json agent.json",
            "record /opt/go-hk-agent-rebuilt/hk_agent/test_pr.py test_pr.py",
            "record /usr/local/libexec/go-hk-test-pr/Dockerfile.go-application-python-v1 Dockerfile.go-application-python-v1",
            "record \"$docker_dropin\" docker-access.conf",
            "record_dir \"$runtime_root\" runtime_root",
            "record_dir \"$build_root\" builds",
        ):
            self.assertIn(statement, install)
        self.assertIn("82ab805b921081ec0299ffa20576963476e12f57e711438f46ada2342a7c7b30", preflight)
        self.assertIn("test ! -e /opt/go-hk-agent-rebuilt/hk_agent/test_pr.py", preflight)
        self.assertIn("test ! -e /usr/local/libexec/go-hk-test-pr/Dockerfile.go-application-python-v1", preflight)
        self.assertIn('install -d -o root -g root -m 0711 "$runtime_root"', install)
        self.assertIn('install -d -o "$agent_uid" -g "$agent_gid" -m 0700 "$build_root"', install)
        self.assertIn("SupplementaryGroups=docker", install)
        self.assertIn('test ! -e /var/lib/go-hk-test-pr', preflight)
        self.assertIn('test -S /var/run/docker.sock', preflight)
        self.assertIn('elif test "$existed" = absent; then', rollback)
        self.assertIn('rm -- "$path"', rollback)
        self.assertIn('validate transport.py "$transport"', rollback)
        self.assertIn('validate agent.json "$agent_config"', rollback)
        self.assertIn('validate test_pr.py "$test_pr"', rollback)
        self.assertIn('validate Dockerfile.go-application-python-v1 "$dockerfile"', rollback)
        self.assertIn('validate docker-access.conf "$docker_dropin"', rollback)
        self.assertIn('validate_dir runtime_root "$runtime_root"', rollback)
        self.assertIn('validate_dir builds "$build_root"', rollback)
        self.assertIn('remove_dir "$build_root"', rollback)
        self.assertIn('test "$(sha256sum "$path" | awk', rollback)
        self.assertLess(rollback.index('test "$(sha256sum "$path" | awk'), rollback.index('rm -- "$path"'))

    def test_hk_directory_rollback_refuses_drift_symlink_or_contents_before_files_change(self):
        for mutation in ("mode", "symlink", "contents"):
            raw, backup, targets, env = self.rollback_sandbox("hk-staging")
            with raw:
                expected = targets["transport.py"].read_bytes()
                build = targets["builds"]
                if mutation == "mode":
                    lines = (backup / "installed.tsv").read_text(encoding="utf-8").splitlines()
                    rewritten = []
                    for line in lines:
                        if line.startswith("builds|directory|"):
                            fields = line.split("|")
                            fields[3] = "700" if fields[3] != "700" else "755"
                            line = "|".join(fields)
                        rewritten.append(line)
                    (backup / "installed.tsv").write_text("\n".join(rewritten) + "\n", encoding="utf-8")
                elif mutation == "symlink":
                    build.rmdir()
                    try:
                        build.symlink_to(targets["transport.py"])
                    except OSError:
                        # Windows developer machines commonly lack symlink privilege; the
                        # Linux rollback predicate itself remains directly asserted here.
                        source = (ROOT / "install" / "uninstall.sh").read_text(encoding="utf-8")
                        self.assertIn('test -d "$path" && test ! -L "$path"', source)
                        continue
                else:
                    (build / "unexpected").write_text("drift", encoding="utf-8")
                self.assertNotEqual(self.run_rollback("hk-staging", env).returncode, 0)
                self.assertEqual(targets["transport.py"].read_bytes(), expected)

    def test_command_center_two_phase_rollback_refuses_drift_or_corrupt_backup(self):
        raw, backup, targets, env = self.rollback_sandbox("command-center")
        with raw:
            expected = targets["go-boss-request-bridge"].read_bytes()
            targets["boss-request-bridge-v1.json"].write_text("drift", encoding="utf-8")
            self.assertNotEqual(self.run_rollback("command-center", env).returncode, 0)
            self.assertEqual(targets["go-boss-request-bridge"].read_bytes(), expected)
        raw, backup, targets, env = self.rollback_sandbox("command-center")
        with raw:
            expected = targets["go-boss-request-bridge"].read_bytes()
            (backup / "boss-request-bridge-v1.json").write_text("corrupt", encoding="utf-8")
            self.assertNotEqual(self.run_rollback("command-center", env).returncode, 0)
            self.assertEqual(targets["go-boss-request-bridge"].read_bytes(), expected)

    def test_hk_two_phase_rollback_refuses_drift_or_corrupt_backup(self):
        raw, backup, targets, env = self.rollback_sandbox("hk-staging")
        with raw:
            expected = targets["transport.py"].read_bytes()
            targets["Dockerfile.go-application-python-v1"].write_text("drift", encoding="utf-8")
            self.assertNotEqual(self.run_rollback("hk-staging", env).returncode, 0)
            self.assertEqual(targets["transport.py"].read_bytes(), expected)
        raw, backup, targets, env = self.rollback_sandbox("hk-staging")
        with raw:
            expected = targets["transport.py"].read_bytes()
            (backup / "agent.json").write_text("corrupt", encoding="utf-8")
            self.assertNotEqual(self.run_rollback("hk-staging", env).returncode, 0)
            self.assertEqual(targets["transport.py"].read_bytes(), expected)

    def test_two_phase_rollback_restores_complete_preinstall_state(self):
        for role in ("command-center", "hk-staging"):
            raw, backup, targets, env = self.rollback_sandbox(role)
            with raw:
                result = self.run_rollback(role, env)
                self.assertEqual(result.returncode, 0, result.stderr)
                for name, target in targets.items():
                    backup_file = backup / name
                    if backup_file.exists():
                        self.assertEqual(target.read_bytes(), backup_file.read_bytes())
                    else:
                        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
