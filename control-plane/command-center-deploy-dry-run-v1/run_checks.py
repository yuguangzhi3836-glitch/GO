#!/usr/bin/env python3
"""Isolated verification for the CC V1-07 DEPLOY dry-run rehearsal.

Same discipline as the existing Control Plane checks: no network, no Git
subprocess, no runtime credential or state path, no private key anywhere, no
live Control Plane or Hong Kong contact.

The claims below are what the rehearsal says about itself, and the test suite is
what makes them true. The three that matter most: a TASK_CANDIDATE is not a Task,
DEPLOY_PERFORMED is false in every outcome, and no request-side refusal reason
exists that the Boss Request Bridge cannot itself raise.
"""
import hashlib
import io
import json
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/go-cc-deploy-dry-run-checks").resolve()
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
import test_deploy_dry_run as t  # noqa: E402

log = io.StringIO()
suite = unittest.defaultTestLoader.loadTestsFromModule(t)
result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)

rehearsal = t.D
contract = json.loads(t.CONTRACT.read_text(encoding="utf-8"))
checks = rehearsal.Checks(t.CONTRACT)
bridge = t.bridge_tokens()
stray = sorted(entry["token"] for entry in checks.request_checks if entry["token"] not in bridge)

summary = {
    "schema_version": "1",
    "component": "command-center-deploy-dry-run-v1",
    "issue": "#102 / CC V1-07",
    "status": "PASS" if result.wasSuccessful() else "FAIL",
    "tests": result.testsRun,
    "failures": len(result.failures),
    "errors": len(result.errors),
    "skips": len(result.skipped),
    "outcomes": contract["properties"]["decision"]["properties"]["outcome"]["enum"],
    "stages": sorted(set(contract["x-go-stages"]) - {"note"}),
    "request_checks": len(checks.request_checks),
    "reason_origins": sorted(o for o in
                             contract["properties"]["checks"]["items"]
                             ["properties"]["reason_origin"]["enum"] if o),
    "bridge_refusal_tokens_available": len(bridge),
    "request_checks_outside_the_bridge_vocabulary": stray,
    "no_new_refusal_vocabulary": stray == [],
    "candidate_is_a_task": "NO",
    "candidate_executable": "NO",
    "candidate_signed": "NO",
    "candidate_publish_authorized": "NO",
    "rehearsal_holds_private_key": "NO",
    "rehearsal_signs_anything": "NO",
    "rehearsal_publishes_a_task": "NO",
    "rehearsal_opens_the_request_switch": "NO",
    "rehearsal_executes_a_deployment": "NO",
    "accepts_caller_supplied_parameters": "NO",
    "record_consumes_nothing": True,
    "replay_is_refused": True,
    "task_published": "NO",
    "signed": "NO",
    "deploy_performed": "NO",
    "network_access": "FORBIDDEN",
    "subprocess_access": "FORBIDDEN",
    "hong_kong": "NOT_ACCESSED",
    "production": "NOT_ACCESSED",
    "live_control_plane_state": "NOT_ACCESSED",
    "installed": "NO",
    "files": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(ROOT.rglob("*"))
              if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"},
}
(OUT / "checks.log").write_text(log.getvalue(), encoding="utf-8")
(OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(log.getvalue(), end="")
print(json.dumps({k: v for k, v in summary.items() if k != "files"}, sort_keys=True))
sys.exit(0 if summary["status"] == "PASS" else 1)
