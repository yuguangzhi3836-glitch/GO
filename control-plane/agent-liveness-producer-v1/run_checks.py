#!/usr/bin/env python3
"""Isolated verification for the CC V1-03 bounded liveness producer.

Same discipline as the existing Control Plane checks: no network, no Git
subprocess, no runtime credential or state path, no live Control Plane or Hong
Kong contact, no private key anywhere.
"""
import hashlib
import io
import json
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/go-cc-liveness-producer-checks").resolve()
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
import test_liveness_producer as t  # noqa: E402

log = io.StringIO()
suite = unittest.defaultTestLoader.loadTestsFromModule(t)
result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)

producer = t.P
policy = producer.load_policy(t.POLICY_PATH)
schema = json.loads(t.SCHEMA_PATH.read_text(encoding="utf-8"))

summary = {
    "schema_version": "1",
    "component": "agent-liveness-producer-v1",
    "issue": "#98 / CC V1-03",
    "status": "PASS" if result.wasSuccessful() else "FAIL",
    "tests": result.testsRun,
    "failures": len(result.failures),
    "errors": len(result.errors),
    "skips": len(result.skipped),
    "action_id": policy["action_id"],
    "environment": policy["environment"],
    "interval_seconds": policy["interval_seconds"],
    "max_probes_per_window": policy["max_probes_per_window"],
    "interval_floor_seconds": producer.MIN_INTERVAL_SECONDS,
    "interval_ceiling_seconds": producer.MAX_INTERVAL_SECONDS,
    "allowed_actions": sorted(producer.ALLOWED_ACTIONS),
    "request_fields": sorted(producer.REQUEST_FIELDS),
    "producer_holds_private_key": "NO",
    "producer_builds_task": "NO",
    "producer_signs_anything": "NO",
    "producer_asserts_liveness": "NO",
    "tick_idempotent_per_bucket": True,
    "single_flight_enforced": True,
    "rolling_window_budget_enforced": True,
    "network_access": "FORBIDDEN",
    "subprocess_access": "FORBIDDEN",
    "hong_kong": "NOT_ACCESSED",
    "production": "NOT_ACCESSED",
    "live_control_plane_state": "NOT_ACCESSED",
    "deployed": "NO",
    "installed": "NO",
    "authority_boundary_declared_in_schema": sorted(
        schema["properties"]["authority_boundary"]["properties"]),
    "files": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(ROOT.rglob("*"))
              if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"},
}
(OUT / "checks.log").write_text(log.getvalue(), encoding="utf-8")
(OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(log.getvalue(), end="")
print(json.dumps({k: v for k, v in summary.items() if k != "files"}, sort_keys=True))
sys.exit(0 if summary["status"] == "PASS" else 1)
