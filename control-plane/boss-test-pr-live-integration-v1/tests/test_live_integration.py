import ast
import base64
import datetime as dt
import hashlib
import importlib.machinery
import importlib.util
import json
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
from hk_agent import deployment_actions, test_pr, transport


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

    def test_python_bytecode_cache_is_fixed_and_isolated(self):
        source = (ROOT / "hk-staging" / "hk_agent" / "test_pr.py").read_text(encoding="utf-8")
        self.assertIn('PYTHONPYCACHEPREFIX = "/tmp/pycache"', source)
        self.assertIn('"--env", "PYTHONPYCACHEPREFIX=" + PYTHONPYCACHEPREFIX', source)
        self.assertIn('"--tmpfs", "/tmp:rw,nosuid,nodev,size=64m"', source)
        self.assertIn('"--read-only", "--cap-drop", "ALL"', source)
        self.assertIn('"--network", "none"', source)
        self.assertIn('"--security-opt", "no-new-privileges"', source)
        self.assertNotIn('PYTHONPYCACHEPREFIX", task', source)

    def test_compileall_redirects_bytecode_from_read_only_source_and_rejects_invalid_python(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            root = pathlib.Path(raw)
            source = root / "source"
            cache = root / "cache"
            source.mkdir()
            cache.mkdir()
            valid = source / "valid.py"
            valid.write_text("value = 42\n", encoding="utf-8")
            source.chmod(0o555)
            env = os.environ.copy()
            env["PYTHONPYCACHEPREFIX"] = str(cache)
            result = subprocess.run([sys.executable, "-m", "compileall", "-q", str(source)], env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(any(source.rglob("__pycache__")))
            self.assertTrue(any(cache.rglob("*.pyc")))
            source.chmod(0o755)
            (source / "invalid.py").write_text("def broken(:\n", encoding="utf-8")
            invalid = subprocess.run([sys.executable, "-m", "compileall", "-q", str(source)], env=env, text=True, capture_output=True)
            self.assertNotEqual(invalid.returncode, 0)

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


class FailureClosureTests(unittest.TestCase):
    """CC V1-02.  A claimed attempt that fails is reported on, signed and bound.

    Before this, a failure touched only the agent-local SQLite ledger, so the
    control bus could not tell "never picked up" from "picked up and failed".
    """

    STATE_V1 = ROOT.parents[0] / "command-center-state-v1"

    def setUp(self):
        key, self.task_verify_key, self.evidence_key, self.evidence_verify_key = self.key_material()
        self.task_key = key
        self.evidence_private = self.evidence_key
        self.published = []

    # -- helpers --------------------------------------------------------------
    def key_material(self):
        workspace = pathlib.Path(tempfile.mkdtemp(prefix="ccv102-"))
        self.workspace = workspace
        task_private = Ed25519PrivateKey.generate()
        evidence_private = Ed25519PrivateKey.generate()
        (workspace / "task.pem").write_bytes(task_private.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        (workspace / "task.pub").write_bytes(task_private.public_key().public_bytes(
            serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH))
        (workspace / "evidence.pem").write_bytes(evidence_private.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        (workspace / "evidence.pub").write_bytes(evidence_private.public_key().public_bytes(
            serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH))
        return (task_private, str(workspace / "task.pub"),
                evidence_private, str(workspace / "evidence.pub"))

    @staticmethod
    def iso(moment):
        return moment.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def signed_task(self, action="HK_STAGING_VERIFY", **over):
        now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        issued = now - dt.timedelta(minutes=1)
        value = {
            "schema_version": "1", "task_id": "cc-v1-02-task", "nonce": "nonce-cc-v1-02",
            "issued_at": self.iso(issued), "expires_at": self.iso(issued + dt.timedelta(minutes=15)),
            "authority": "GO-COMMAND-CENTER", "environment": "HK-STAGING-01",
            "action_id": action,
            "parameters": {"release_id": "release-cc-v1-02",
                           "candidate_image_id": "sha256:" + "a" * 64,
                           "expected_current_image_id": "sha256:" + "a" * 64},
        }
        value.update(over)
        value["signature"] = self.task_key.sign(transport.canonical(value)).hex()
        return value

    def config(self):
        return {"environment": "HK-STAGING-01", "authority": "GO-COMMAND-CENTER",
                "tasks_repo": "git@example.invalid:tasks.git", "tasks_key": "unused",
                "evidence_repo": "git@example.invalid:evidence.git", "evidence_key": "unused",
                "task_verify_key": self.task_verify_key,
                "evidence_signing_key": str(self.workspace / "evidence.pem")}

    def isolated_run(self, task, *, executor=None, push=None, ledger=None):
        """Drive run_once with the network transport replaced by fixtures."""
        captured = {"tasks": {"%s.json" % task["task_id"]: task},
                    "clones": [], "published": self.published, "segments": []}

        def fake_clone(repo, key, target):
            target = pathlib.Path(target)
            captured["clones"].append(target.name)
            staged = captured["tasks"] if target.name == "tasks" else captured.get(
                "staged_%s" % target.name, {})
            (target / "tasks").mkdir(parents=True, exist_ok=True)
            (target / "evidence").mkdir(parents=True, exist_ok=True)
            for name, value in staged.items():
                (target / "tasks" / name).write_text(json.dumps(value), encoding="utf-8")

        def fake_git(key, args, cwd=None):
            captured["segments"].append(list(args))
            return "f" * 40

        def fake_push(data, cfg, work, stage=None, refuse_overwrite=False, dirname="evidence"):
            if push is not None:
                return push(data, cfg, work, stage=stage,
                            refuse_overwrite=refuse_overwrite, dirname=dirname)
            self.published.append(data)
            return "f" * 40

        real_dispatch = transport.dispatch_action
        if executor is not None:
            def dispatch_one(task, _executor=executor, _real=real_dispatch):
                return _real(task, _executor)
            transport.dispatch_action = dispatch_one

        originals = (transport.clone, transport.git, transport.push_evidence, transport.dispatch_action)
        transport.clone, transport.git, transport.push_evidence = fake_clone, fake_git, fake_push
        try:
            ledger = ledger or (self.workspace / "ledger.sqlite3")
            result = transport.run_once(str(self.write_config()), str(ledger), task["task_id"])
        finally:
            transport.clone, transport.git, transport.push_evidence, transport.dispatch_action = originals
        return result, captured

    def write_config(self):
        path = self.workspace / "agent.json"
        path.write_text(json.dumps(self.config()), encoding="utf-8")
        return path

    class BrokenExecutor:
        """Reports a completed subprocess whose stdout cannot be accepted."""

        def __init__(self, stage, stdout):
            self.stage, self.stdout = stage, stdout

        def run(self, argv):
            return {"stdout": self.stdout, "stderr": "", "returncode": 1}

    # -- the closure ----------------------------------------------------------
    def test_a_claimed_attempt_that_fails_publishes_signed_bound_evidence(self):
        task = self.signed_task()
        broken = self.BrokenExecutor("parser", "{not json")
        result, _ = self.isolated_run(task, executor=broken)

        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["rejected"], 1)
        publication = result["failure_evidence"][0]
        self.assertTrue(publication["published"], publication)
        self.assertEqual(len(self.published), 1)

        record = self.published[0]
        # bound to the original Task, no binding lost on failure
        self.assertEqual(record["task_id"], task["task_id"])
        self.assertEqual(record["nonce"], task["nonce"])
        self.assertEqual(record["action_id"], task["action_id"])
        self.assertEqual(record["environment"], task["environment"])
        # a failure record is never a success record
        self.assertEqual(record["status"], "FAILED")
        self.assertNotEqual(record["executor_result"], "VERIFY_OK")
        # signed with the same evidence identity, and the signature verifies
        self.assertTrue(record["signature"])
        self.evidence_private.public_key().verify(
            base64.b64decode(record["signature"]), transport.canonical(record))
        # the whole gate chain passed before the executor output was refused
        self.assertEqual(set(record["gate_results"].values()), {"PASS"})
        # closed semantics
        self.assertEqual(record["failure"]["kind"], "RESULT_REJECT")
        self.assertEqual(record["failure"]["stage"], "parser")
        self.assertEqual(record["failure"]["reason_code"], "EXECUTOR_OUTPUT_REJECTED")
        self.assertTrue(record["failure"]["execution_attempted"])
        self.assertTrue(record["failure"]["attempt_budget_exhausted"])
        # nothing here authorizes anything
        self.assertIs(record["retry_permitted"], False)
        self.assertIs(record["replay_authorized"], False)
        self.assertIs(record["authorizes_any_action"], False)

    def test_the_published_record_satisfies_the_published_contract(self):
        task = self.signed_task()
        broken = self.BrokenExecutor("parser", "{not json")
        self.isolated_run(task, executor=broken)
        record = self.published[0]

        schema = json.loads((self.STATE_V1 / "contracts" / "failure_evidence_v1.schema.json").read_text(encoding="utf-8"))
        missing = [key for key in schema["required"] if key not in record]
        self.assertEqual(missing, [], "the agent produced a record the contract does not describe")
        for key, rule in schema["properties"].items():
            if "const" in rule and key in record:
                self.assertEqual(record[key], rule["const"], key)
        self.assertEqual(dict(record["failure"])["schema_version"],
                         schema["properties"]["failure"]["properties"]["schema_version"]["const"])
        for key in schema["properties"]["failure"]["required"]:
            self.assertIn(key, record["failure"])

    def test_a_task_rejected_before_the_claim_publishes_nothing(self):
        # An unauthenticated Task must never be able to cause a write, so a bad
        # signature produces no record at all.
        task = self.signed_task()
        task["signature"] = "0" * 128
        result, _ = self.isolated_run(task)
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(result["failure_evidence"][0],
                         {"attempted": False, "published": False, "reason": "task_not_claimed"})
        self.assertEqual(self.published, [])

    def test_an_expired_task_that_was_never_claimed_publishes_nothing(self):
        now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        task = self.signed_task(issued_at=self.iso(now - dt.timedelta(hours=2)),
                                expires_at=self.iso(now - dt.timedelta(hours=1)))
        result, _ = self.isolated_run(task)
        self.assertEqual(result["rejected"], 1)
        self.assertFalse(result["failure_evidence"][0]["attempted"])
        self.assertEqual(self.published, [])

    def test_a_failed_publication_is_neither_success_nor_a_retry(self):
        task = self.signed_task()
        broken = self.BrokenExecutor("parser", "{not json")
        ledger = self.workspace / "ledger.sqlite3"

        def refusing_push(data, cfg, work, stage=None, refuse_overwrite=False, dirname="evidence"):
            self.published.append(data)
            raise transport.Reject("GITHUB_TRANSPORT_REJECT", stage=stage)

        result, _ = self.isolated_run(task, executor=broken,
                                      push=refusing_push, ledger=ledger)
        self.assertEqual(result["processed"], 0, "a failed work item must never be counted as processed")
        publication = result["failure_evidence"][0]
        self.assertTrue(publication["attempted"])
        self.assertFalse(publication["published"])
        self.assertIn("not a success", publication["note"])

        # the attempt budget was claimed durably, so the next poll refuses the
        # Task instead of re-executing it
        self.assertTrue(transport.Ledger(str(ledger)).attempted(task["task_id"], task["nonce"]))
        second, _ = self.isolated_run(task, executor=broken,
                                      ledger=ledger)
        self.assertEqual(second["processed"], 0)
        self.assertEqual(second["failure_evidence"][0],
                         {"attempted": False, "published": False, "reason": "task_not_claimed"})
        self.assertEqual(len(self.published), 1, "a refused publication was retried")

    def test_a_published_failure_is_not_republished_on_the_next_poll(self):
        task = self.signed_task()
        broken = self.BrokenExecutor("parser", "{not json")
        ledger = self.workspace / "ledger.sqlite3"
        first, _ = self.isolated_run(task, executor=broken,
                                     ledger=ledger)
        self.assertTrue(first["failure_evidence"][0]["published"])
        self.assertEqual(len(self.published), 1)

        second, _ = self.isolated_run(task, executor=broken,
                                      ledger=ledger)
        self.assertEqual(second["rejected"], 1)
        self.assertEqual(second["failure_evidence"][0]["reason"], "task_not_claimed")
        self.assertEqual(len(self.published), 1, "one Task identity published twice")

    def test_a_duplicate_record_is_refused_rather_than_overwritten(self):
        task = self.signed_task()
        record = transport.failure_evidence(task, transport.Reject("GITHUB_TRANSPORT_REJECT"),
                                            stage=transport.STAGE_EVIDENCE_PUBLISH)
        name = (task["task_id"] + "-" + task["nonce"]) + ".json"
        existing = self.workspace / "evidence-failure" / "evidence" / name
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_text('{"published":"first"}', encoding="utf-8")

        def fake_clone(repo, key, target):
            self.assertEqual(pathlib.Path(target).name, "evidence-failure")
            pathlib.Path(target).mkdir(parents=True, exist_ok=True)
            (pathlib.Path(target) / "evidence").mkdir(exist_ok=True)
            (pathlib.Path(target) / "evidence" / name).write_text(existing.read_text(encoding="utf-8"), encoding="utf-8")

        original_clone = transport.clone
        transport.clone = fake_clone
        try:
            with self.assertRaisesRegex(transport.Reject, "EVIDENCE_DUPLICATE_REJECT"):
                transport.push_evidence(transport.sign(record, str(self.workspace / "evidence.pem")),
                                        self.config(), self.workspace,
                                        refuse_overwrite=True, dirname="evidence-failure")
        finally:
            transport.clone = original_clone
        self.assertEqual(existing.read_text(encoding="utf-8"), '{"published":"first"}')

    def test_the_success_path_is_unchanged(self):
        task = self.signed_task()
        executor = deployment_actions.FakeExecutor()
        result, _ = self.isolated_run(task, executor=executor)
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["rejected"], 0)
        self.assertEqual(result["failure_evidence"], [])
        self.assertEqual(len(result["evidence_commits"]), 1)
        self.assertEqual(len(self.published), 1)
        record = self.published[0]
        self.assertEqual(record["status"], "SUCCESS")
        self.assertNotIn("failure", record)
        self.assertNotIn("retry_permitted", record)

    # -- the closed vocabularies ----------------------------------------------
    def test_reasons_are_closed_and_free_text_is_never_echoed(self):
        self.assertEqual(transport.failure_reason("GITHUB_TRANSPORT_REJECT"), "GITHUB_TRANSPORT_REJECT")
        self.assertEqual(transport.failure_reason("executor rejected"), "UNCLASSIFIED_REJECT")
        self.assertEqual(transport.failure_reason("-----BEGIN PRIVATE KEY----- leaked"),
                         "UNCLASSIFIED_REJECT")
        self.assertEqual(transport.failure_reason("executor rejected", "parser"),
                         "EXECUTOR_OUTPUT_REJECTED")
        self.assertEqual(transport.failure_reason("whatever", "no_such_stage"),
                         "UNCLASSIFIED_REJECT")

    def test_kinds_are_closed_and_unmapped_stages_are_never_echoed(self):
        self.assertEqual(transport.failure_kind("parser"), "RESULT_REJECT")
        self.assertEqual(transport.failure_kind("subprocess_nonzero"), "EXECUTION_FAILED")
        self.assertEqual(transport.failure_kind(transport.STAGE_ROLLBACK_HANDOFF), "HANDOFF_FAILED")
        self.assertEqual(transport.failure_kind("something_new"), "AGENT_REJECT")

    def test_gate_results_report_where_the_attempt_stopped(self):
        stopped_at_signature = transport.failure_gate_results("signature")
        self.assertEqual(stopped_at_signature["schema"], "PASS")
        self.assertEqual(stopped_at_signature["signature"], "FAIL")
        self.assertEqual(stopped_at_signature["parameters"], "NOT_EVALUATED")
        all_passed = transport.failure_gate_results("parser")
        self.assertEqual(set(all_passed.values()), {"PASS"})

    def test_the_contract_and_the_producer_agree_on_the_closed_sets(self):
        # The published contract and the agent's vocabularies must not drift: a
        # record the contract does not describe would be unreadable to a reader
        # that trusts the contract.
        schema = json.loads((self.STATE_V1 / "contracts" / "failure_evidence_v1.schema.json")
                            .read_text(encoding="utf-8"))
        block = schema["properties"]["failure"]["properties"]
        self.assertEqual(set(block["reason_code"]["enum"]),
                         set(transport.FAILURE_REASON_CODES) | {transport.FAILURE_REASON_FALLBACK})
        self.assertEqual(set(block["kind"]["enum"]),
                         set(transport.FAILURE_KIND_BY_STAGE.values()) | {transport.FAILURE_KIND_FALLBACK})
        self.assertEqual(set(block["stage"]["enum"]),
                         {transport.STAGE_AGENT, transport.STAGE_ROLLBACK_HANDOFF,
                          transport.STAGE_EXECUTOR, transport.STAGE_RESULT,
                          transport.STAGE_EVIDENCE_BUILD, transport.STAGE_EVIDENCE_PUBLISH,
                          "subprocess", "subprocess_nonzero", "subprocess_error", "parser"})

    def test_failure_stages_are_not_swallowed_as_agent_reject(self):
        reject = transport.Reject("EXECUTOR_RESULT_REJECT", stage=transport.STAGE_EVIDENCE_BUILD)
        self.assertEqual(getattr(reject, "stage"), transport.STAGE_EVIDENCE_BUILD)
        self.assertEqual(str(reject), "EXECUTOR_RESULT_REJECT")
        # an executor refusal is normalised to one type the caller already handles
        executor_reject = deployment_actions.Reject("executor stdout rejected", stdout="raw", stage="parser")
        staged = transport._staged(executor_reject, transport.STAGE_EXECUTOR)
        self.assertIsInstance(staged, transport.Reject)
        self.assertEqual(staged.stage, "parser")
        self.assertEqual(staged.stdout, "raw")


if __name__ == "__main__":
    unittest.main()
