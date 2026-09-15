#!/usr/bin/env python3
"""Isolated verification for the CC V1-05 Bridge Request fact export.

Same discipline as the existing Control Plane checks: no network, no Git
subprocess, no runtime credential or state path, no private key anywhere, no
live Control Plane or Hong Kong contact.

The summaries below are the claims this component makes about itself, and the
test suite is what makes them true. The last three are the ones that matter:
the export is not Execution Authority, a fact never carries a refusal reason it
dropped, and an acceptance is never believed on a fact's word alone.
"""
import hashlib
import io
import json
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/go-cc-request-visibility-checks").resolve()
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
import test_request_visibility as t  # noqa: E402

log = io.StringIO()
suite = unittest.defaultTestLoader.loadTestsFromModule(t)
result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)

exporter = t.X
schema = json.loads(t.CONTRACT.read_text(encoding="utf-8"))
vocabulary = exporter.Vocabulary(t.CONTRACT)

direct_tokens, argument_tokens = t.bridge_refusal_tokens()
bridge_tokens = sorted(direct_tokens | argument_tokens)
unclassified = sorted(token for token in bridge_tokens
                      if vocabulary.classify(token) == "UNCLASSIFIED_REJECT")

summary = {
    "schema_version": "1",
    "component": "command-center-request-visibility-v1",
    "issue": "#100 / CC V1-05",
    "status": "PASS" if result.wasSuccessful() else "FAIL",
    "tests": result.testsRun,
    "failures": len(result.failures),
    "errors": len(result.errors),
    "skips": len(result.skipped),
    "fact_kinds": list(schema["properties"]["kind"]["enum"]),
    "reason_classes": sorted(vocabulary.by_class),
    "reason_origins": sorted(o for o in schema["properties"]["reason"]["properties"]["origin"]["enum"]
                             if o),
    "reason_classes_source": "contracts/request_fact_v1.schema.json",
    "bridge_sources_scanned": [str(p.relative_to(t.REPO)) for p in t.BRIDGE_SOURCES],
    "bridge_refusal_tokens_observed": len(bridge_tokens),
    "bridge_refusal_tokens_direct": len(direct_tokens),
    "bridge_refusal_tokens_via_the_reason_argument": len(argument_tokens),
    "bridge_refusal_call_shapes_scanned": 2,
    "bridge_refusal_tokens_unclassified": unclassified,
    "every_bridge_refusal_is_classified": unclassified == [],
    "unknown_token_preserved_as": "UNCLASSIFIED_REJECT",
    "duplicate_and_replay_have_their_own_kinds": True,
    "acceptance_requires_proof": "binding.proof_required is true for REQUEST_VALIDATED",
    "acceptance_is_corroborated_by_the_consumer": True,
    "exporter_holds_private_key": "NO",
    "exporter_signs_anything": "NO",
    "exporter_builds_task": "NO",
    "exporter_writes_a_ledger": "NO",
    "ledger_opened_read_only": True,
    "re_export_is_idempotent": True,
    "undated_observation_produces_no_fact": True,
    "network_access": "FORBIDDEN",
    "subprocess_access": "FORBIDDEN",
    "hong_kong": "NOT_ACCESSED",
    "production": "NOT_ACCESSED",
    "live_control_plane_state": "NOT_ACCESSED",
    "bridge_ledger_read": "NO_LOCAL_COPY_AVAILABLE",
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
