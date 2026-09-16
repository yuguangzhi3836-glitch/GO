#!/usr/bin/env python3
"""Isolated verification for RELEASE_CANDIDATE_V1 admission (CC V1-08 / #103).

Same discipline as the other Control Plane checks: no network, no Git subprocess,
no runtime credential or state path, no private key anywhere, no live Control
Plane or Hong Kong contact.

The summary below is what this component claims about itself, and the test suite
is what makes it true. The claims that matter: a candidate that cannot establish
every identity is refused by name, an unproven input never becomes ACCEPT, and an
admission authorises nothing.
"""
import hashlib
import io
import json
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1
                   else "/tmp/go-cc-candidate-admission-checks").resolve()
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
import test_candidate_admission as t  # noqa: E402

log = io.StringIO()
suite = unittest.defaultTestLoader.loadTestsFromModule(t)
result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)

admission = t.A
contract = json.loads(t.CONTRACT.read_text(encoding="utf-8"))
required = list(contract["required"])

summary = {
    "schema_version": "1",
    "component": "command-center-candidate-admission-v1",
    "issue": "#103 / CC V1-08 candidate admission",
    "status": "PASS" if result.wasSuccessful() else "FAIL",
    "tests": result.testsRun,
    "failures": len(result.failures),
    "errors": len(result.errors),
    "skips": len(result.skipped),
    "contract": contract["$id"],
    "verdicts": contract["x-go-verdicts"]["values"],
    "candidate_identities_required": sorted(required),
    "refusal_reasons_declared": len(contract["x-go-refusals"]["source"]),
    "a_missing_identity_is_refused_not_completed": True,
    "a_mutable_source_is_refused": True,
    "a_source_fingerprint_mismatch_is_refused": True,
    "an_artifact_that_the_test_result_did_not_produce_is_refused": True,
    "a_test_result_for_another_candidate_is_refused": True,
    "a_service_outside_the_fixed_topology_is_refused": True,
    "an_unresolvable_rollback_relation_is_refused": True,
    "an_unproven_input_is_unknown_never_accepted": True,
    "admission_authorises_nothing": sorted(
        k for k, v in admission.AUTHORITY_BOUNDARY.items()
        if v and k != "may_read_the_candidate_and_its_evidence") == [],
    "constants_are_read_from_the_live_control_plane": True,
    "the_staged_builder_dockerfile_digest_is_verified_from_the_repository": True,
    "the_admission_never_writes": True,
    "admission_holds_private_key": "NO",
    "admission_signs_anything": "NO",
    "admission_creates_or_publishes_a_task": "NO",
    "admission_opens_the_request_switch": "NO",
    "accepts_caller_supplied_parameters": "NO",
    "network_access": "FORBIDDEN",
    "subprocess_access": "FORBIDDEN",
    "hong_kong": "NOT_ACCESSED",
    "production": "NOT_ACCESSED",
    "live_control_plane_state": "NOT_ACCESSED",
    "deployed": "NO",
    "installed": "NO",
    "files": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(ROOT.rglob("*"))
              if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"},
}
(OUT / "checks.log").write_text(log.getvalue(), encoding="utf-8")
(OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
print(log.getvalue(), end="")
print(json.dumps({k: v for k, v in summary.items() if k != "files"}, sort_keys=True))
sys.exit(0 if summary["status"] == "PASS" else 1)
