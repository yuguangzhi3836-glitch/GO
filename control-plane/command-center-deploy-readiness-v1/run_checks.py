#!/usr/bin/env python3
"""Isolated verification for the CC V1-06 read-only Deploy Readiness evaluator.

Same discipline as the existing Control Plane checks: no network, no Git
subprocess, no runtime credential or state path, no private key anywhere, no
live Control Plane or Hong Kong contact.

The summary below is what the evaluator claims about itself, and the test suite
is what makes it true. The claims that matter: an unprovable mandatory gate
never becomes YES, an advisory gate never blocks, and a verdict that says YES
still authorises nothing.
"""
import hashlib
import io
import json
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/go-cc-deploy-readiness-checks").resolve()
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
import test_deploy_readiness as t  # noqa: E402

log = io.StringIO()
suite = unittest.defaultTestLoader.loadTestsFromModule(t)
result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)

evaluator = t.R
contract = json.loads(t.CONTRACT.read_text(encoding="utf-8"))
declared = {name: value for name, value in contract["x-go-gates"].items() if name != "note"}

summary = {
    "schema_version": "1",
    "component": "command-center-deploy-readiness-v1",
    "issue": "#101 / CC V1-06.1",
    "status": "PASS" if result.wasSuccessful() else "FAIL",
    "tests": result.testsRun,
    "failures": len(result.failures),
    "errors": len(result.errors),
    "skips": len(result.skipped),
    "verdict_set": contract["properties"]["verdict"]["properties"]["deploy_ready"]["enum"],
    "gates": sorted(declared),
    "mandatory_gates": sorted(name for name, value in declared.items() if value["mandatory"]),
    "advisory_gates": sorted(name for name, value in declared.items() if not value["mandatory"]),
    "unknown_is_never_promoted_to_yes": True,
    "every_gate_is_mandatory": all(value["mandatory"] for value in declared.values()),
    "canary_is_mandatory_and_re_derived": True,
    "release_gates_is_mandatory": True,
    "live_switch_provenance_is_mandatory": True,
    "yes_implies_the_live_bridge_would_accept": True,
    "bridge_rules_are_read_from_the_live_bridge_component": str(
        (ROOT.parent / "boss-deploy-request-v1" / "go_deploy_request.py").is_file()).upper(),
    "approval_authority_must_be_distinct_from_the_task_signer": True,
    "a_yes_is_not_an_approval": True,
    "reads_only_the_derived_state_and_the_supplied_bundle": True,
    "evaluator_holds_private_key": "NO",
    "evaluator_signs_anything": "NO",
    "evaluator_creates_or_publishes_a_task": "NO",
    "evaluator_opens_the_request_switch": "NO",
    "accepts_caller_supplied_parameters": "NO",
    "rollback_readiness": "NOT_IN_SCOPE",
    "network_access": "FORBIDDEN",
    "subprocess_access": "FORBIDDEN",
    "hong_kong": "NOT_ACCESSED",
    "production": "NOT_ACCESSED",
    "live_control_plane_state": "READ_ONLY_BUNDLE_OR_ABSENT",
    "deployed": "NO",
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
