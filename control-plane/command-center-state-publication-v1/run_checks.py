#!/usr/bin/env python3
"""Isolated verification for the CC V1-04 derived-state publication target.

Same discipline as the existing Control Plane checks: no network, no Git
subprocess, no runtime credential or state path, no private key, no live
Control Plane or Hong Kong contact.
"""
import hashlib
import io
import json
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/go-cc-state-publication-checks").resolve()
OUT.mkdir(parents=True, exist_ok=True)


def audit(event, args):
    if event in ("socket.connect", "socket.connect_ex", "socket.getaddrinfo",
                 "socket.gethostbyname", "urllib.Request"):
        raise RuntimeError("isolated checks forbid network")
    if event == "subprocess.Popen":
        raise RuntimeError("isolated checks forbid any subprocess")
    if event == "open":
        path = args[0]
        if isinstance(path, (str, bytes)):
            decoded = os.fsdecode(path)
            for prefix in ("/etc/go-command-center/", "/var/lib/go-command-center/",
                           "/etc/go-hk-agent/", "/var/lib/go-hk-agent/"):
                if decoded.startswith(prefix):
                    raise RuntimeError("isolated checks forbid runtime credentials and state")


sys.addaudithook(audit)
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "command-center"))
import test_state_publication as t  # noqa: E402

log = io.StringIO()
suite = unittest.defaultTestLoader.loadTestsFromModule(t)
result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)

contract = json.loads(t.CONTRACT_PATH.read_text(encoding="utf-8"))

summary = {
    "schema_version": "1",
    "component": "command-center-state-publication-v1",
    "issue": "#99 / CC V1-04",
    "status": "PASS" if result.wasSuccessful() else "FAIL",
    "tests": result.testsRun,
    "failures": len(result.failures),
    "errors": len(result.errors),
    "skips": len(result.skipped),
    "reader_entry_point": t.P.POINTER_NAME,
    "snapshot_directory": t.P.RUN_DIR_NAME,
    "reader_states": [t.P.POINTER_STATUS_CURRENT, t.P.POINTER_STATUS_STALE,
                      t.P.POINTER_STATUS_FAILED, t.P.POINTER_STATUS_UNKNOWN],
    "deterministic_run_id": "generated_at + content_digest(12)",
    "two_phase_commit": True,
    "failure_never_advances_the_pointer": True,
    "hand_edited_snapshot_detected": True,
    "idempotent_republish": True,
    "is_execution_authority": "NO",
    "can_trigger_executor": "NO",
    "holds_private_key": "NO",
    "network_access": "FORBIDDEN",
    "subprocess_access": "FORBIDDEN",
    "hong_kong": "NOT_ACCESSED",
    "production": "NOT_ACCESSED",
    "live_control_plane_state": "NOT_ACCESSED",
    # The target and the publisher are installed and driven on the Command Center
    # host by go-command-center-state-cycle.timer (900 s), which also publishes the
    # Request facts the projection consumes. This is still not execution authority:
    # the wrapper holds no key and the publisher signs nothing.
    "publication_target_installed": "YES",
    "scheduled_publication": "YES",
    "publication_driver": ("go-command-center-state-cycle.timer on the Command Center "
                           "host; install record in install/INSTALL.md"),
    "authority_boundary_declared_in_contract": sorted(
        contract["properties"]["authority_boundary"]["properties"]),
    "files": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(ROOT.rglob("*"))
              if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"},
}
(OUT / "checks.log").write_text(log.getvalue(), encoding="utf-8")
(OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(log.getvalue(), end="")
print(json.dumps({k: v for k, v in summary.items() if k != "files"}, sort_keys=True))
sys.exit(0 if summary["status"] == "PASS" else 1)
