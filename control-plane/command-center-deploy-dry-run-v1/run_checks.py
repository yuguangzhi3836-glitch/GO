#!/usr/bin/env python3
"""Isolated verification for the CC V1-07 DEPLOY dry-run rehearsal.

Same discipline as the existing Control Plane checks: no network, no Git
subprocess, no runtime credential or state path, no private key anywhere, no
live Control Plane or Hong Kong contact.

The claims below are what the rehearsal says about itself, and the test suite is
what makes them true. The two that matter most: a TASK_CANDIDATE is not a Task,
and DEPLOY_PERFORMED is false in every outcome.

The rehearsal's request-check vocabulary used to be cross-checked against the
Boss Request Bridge's own source. That component was retired on 2026-10-08
together with the rest of the Old Command Center request path, so the
cross-check was retired with it instead of being re-anchored to a copy of the
retired implementation. The vocabulary the rehearsal uses is declared by its
own published contract, contracts/deploy_dry_run_v1.schema.json.
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
    # The rehearsal's refusal vocabulary used to be cross-checked against the Boss
    # Request Bridge's own source. That component was retired on 2026-10-08, so the
    # cross-check was retired with it rather than re-anchored to a copy of the
    # retired implementation. The vocabulary is declared by the rehearsal's own
    # published contract, which is what `checks.request_checks` is read from.
    "refusal_vocabulary_source": "contracts/deploy_dry_run_v1.schema.json",
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
