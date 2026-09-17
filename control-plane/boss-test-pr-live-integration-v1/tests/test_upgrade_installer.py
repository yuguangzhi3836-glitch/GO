import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "upgrade_hk_agent", ROOT / "install" / "upgrade_hk_agent.py")
upgrade = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(upgrade)
CANDIDATE_SHA = "f" * 40


class UpgradeSandbox:
    def __init__(self, case):
        self.raw = tempfile.TemporaryDirectory()
        case.addCleanup(self.raw.cleanup)
        self.base = Path(self.raw.name)
        self.live = self.base / "live"
        self.candidate = self.base / "candidate"
        self.live.mkdir()
        self.candidate.mkdir()
        self.old = {}
        for index, (name, (source, canonical, mode)) in enumerate(upgrade.FILES.items()):
            candidate = self.candidate / source
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_bytes(("candidate-" + name).encode())
            if index < 4:
                target = upgrade.rooted(canonical, self.live)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(("before-" + name).encode())
                target.chmod(mode)
                self.old[name] = target.read_bytes()
        for name, canonical in upgrade.PROTECTED.items():
            target = upgrade.rooted(canonical, self.live)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(("protected-" + name).encode())
            target.chmod(0o640)
        for name in ("store", "objects"):
            target = upgrade.rooted(upgrade.DIRECTORIES[name], self.live)
            target.mkdir(parents=True)
            target.chmod(0o700)
        lines = []
        for source, _, _ in upgrade.FILES.values():
            if source == "SHA256SUMS":
                continue
            path = self.candidate / source
            lines.append(f"{upgrade.digest(path)}  {source}")
        (self.candidate / "SHA256SUMS").write_text("\n".join(lines) + "\n")
        self.before = {
            "schema": upgrade.SCHEMA,
            "candidate_sha": CANDIDATE_SHA,
            "observed_at": "2026-09-17T16:00:00Z",
            "files": {},
            "directories": {},
            "service": {"timer_active": True, "timer_enabled": True,
                        "service_active": False},
        }
        for name in upgrade.ALL_FILE_KEYS:
            canonical = upgrade.FILES[name][1] if name in upgrade.FILES else upgrade.PROTECTED[name]
            self.before["files"][name] = upgrade.snapshot(upgrade.rooted(canonical, self.live))
        for name, canonical in upgrade.DIRECTORIES.items():
            self.before["directories"][name] = upgrade.directory_snapshot(
                upgrade.rooted(canonical, self.live))
        self.before_path = self.base / "before.json"
        self.before_path.write_text(json.dumps(self.before, sort_keys=True))
        self.state = self.base / "timer.state"
        self.state.write_text("active")
        self.systemctl = self.base / "systemctl"
        self.systemctl.write_text(
            "#!/bin/sh\n"
            f"state='{self.state}'\n"
            "action=$1; unit=${3:-${2:-}}\n"
            "case \"$action:$unit\" in\n"
            "  is-active:go-hk-agent.timer) test \"$(cat \"$state\")\" = active;;\n"
            "  is-active:go-hk-agent.service) exit 3;;\n"
            "  is-enabled:go-hk-agent.timer) exit 0;;\n"
            "  stop:go-hk-agent.timer) printf stopped > \"$state\";;\n"
            "  start:go-hk-agent.timer) printf active > \"$state\";;\n"
            "  *) exit 64;;\n"
            "esac\n")
        self.systemctl.chmod(0o755)

    def environment(self):
        return {"GO_HK_UPGRADE_TEST_MODE": "1",
                "GO_HK_UPGRADE_TEST_ROOT": str(self.live),
                "GO_SYSTEMCTL": str(self.systemctl)}

    def argv(self):
        return ["--root", str(self.candidate),
                "--observed-before", str(self.before_path),
                "--candidate-sha", CANDIDATE_SHA]


class UpgradeInstallerTests(unittest.TestCase):
    def test_installer_has_explicit_upgrade_route_and_shell_syntax(self):
        source = (ROOT / "install" / "install-hk-agent.sh").read_text()
        self.assertIn('upgrade)', source)
        self.assertIn('source-bound observed-before JSON required', source)
        self.assertIn('upgrade_hk_agent.py', source)
        if os.name == "posix":
            import subprocess
            result = subprocess.run(["bash", "-n", str(ROOT / "install" / "install-hk-agent.sh")],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_observed_before_drift_fails_before_any_write(self):
        box = UpgradeSandbox(self)
        target = upgrade.rooted(upgrade.FILES["transport.py"][1], box.live)
        target.write_bytes(b"drift")
        with mock.patch.dict(os.environ, box.environment(), clear=False):
            with self.assertRaisesRegex(RuntimeError, "OBSERVED_BEFORE_FILE_DRIFT"):
                upgrade.main(box.argv())
        self.assertEqual(box.state.read_text(), "active")
        self.assertFalse((box.live / "var" / "backups").exists())

    def test_upgrade_creates_unique_backup_and_exact_readback(self):
        box = UpgradeSandbox(self)
        with mock.patch.dict(os.environ, box.environment(), clear=False):
            upgrade.main(box.argv())
        backups = list((box.live / "var" / "backups").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertRegex(backups[0].name,
                         r"^HK-CHANGE-\d{8}T\d{6}Z-pr188-")
        receipt = json.loads((backups[0] / "receipt.json").read_text())
        self.assertEqual(receipt["result"], "PASS")
        self.assertEqual(receipt["candidate_sha"], CANDIDATE_SHA)
        self.assertEqual(box.state.read_text(), "active")
        for name, (source, canonical, mode) in upgrade.FILES.items():
            target = upgrade.rooted(canonical, box.live)
            self.assertEqual(upgrade.digest(target),
                             upgrade.digest(box.candidate / source))
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), mode)
        failures = upgrade.rooted(upgrade.DIRECTORIES["failures"], box.live)
        self.assertEqual(stat.S_IMODE(failures.stat().st_mode), 0o700)
        for name, canonical in upgrade.PROTECTED.items():
            self.assertEqual(upgrade.snapshot(upgrade.rooted(canonical, box.live)),
                             box.before["files"][name])

    def test_mid_swap_failure_rolls_back_and_restores_timer(self):
        box = UpgradeSandbox(self)
        real = upgrade.atomic_install
        counter = {"candidate": 0, "failed": False}

        def failing(source, target, mode, uid, gid):
            if str(source).startswith(str(box.candidate)):
                counter["candidate"] += 1
                if counter["candidate"] == 3 and not counter["failed"]:
                    counter["failed"] = True
                    raise RuntimeError("INJECTED_SWAP_FAILURE")
            return real(source, target, mode, uid, gid)

        with mock.patch.dict(os.environ, box.environment(), clear=False), \
                mock.patch.object(upgrade, "atomic_install", side_effect=failing):
            with self.assertRaisesRegex(RuntimeError, "INJECTED_SWAP_FAILURE"):
                upgrade.main(box.argv())
        self.assertEqual(box.state.read_text(), "active")
        for name, expected in box.old.items():
            target = upgrade.rooted(upgrade.FILES[name][1], box.live)
            self.assertEqual(target.read_bytes(), expected)
        for name in tuple(upgrade.FILES)[4:]:
            self.assertFalse(upgrade.rooted(upgrade.FILES[name][1], box.live).exists())
        backups = list((box.live / "var" / "backups").iterdir())
        receipt = json.loads((backups[0] / "receipt.json").read_text())
        self.assertEqual(receipt["result"], "FAILED")
        self.assertEqual(receipt["rollback_errors"], [])

    def test_candidate_binding_mismatch_fails_before_any_write(self):
        box = UpgradeSandbox(self)
        value = json.loads(box.before_path.read_text())
        value["candidate_sha"] = "e" * 40
        box.before_path.write_text(json.dumps(value))
        with mock.patch.dict(os.environ, box.environment(), clear=False):
            with self.assertRaisesRegex(RuntimeError, "BEFORE_BINDING"):
                upgrade.main(box.argv())
        self.assertEqual(box.state.read_text(), "active")
        self.assertFalse((box.live / "var" / "backups").exists())

    def test_manifest_tamper_fails_before_any_write(self):
        box = UpgradeSandbox(self)
        (box.candidate / "hk-staging" / "hk_agent" / "transport.py").write_bytes(b"tampered")
        with mock.patch.dict(os.environ, box.environment(), clear=False):
            with self.assertRaisesRegex(RuntimeError, "CANDIDATE_MANIFEST_MISMATCH"):
                upgrade.main(box.argv())
        self.assertEqual(box.state.read_text(), "active")
        self.assertFalse((box.live / "var" / "backups").exists())


if __name__ == "__main__":
    unittest.main()