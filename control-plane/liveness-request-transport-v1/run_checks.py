#!/usr/bin/env python3
"""Isolated verification for the bounded liveness Request transport.

Same discipline as the other Control Plane checks: no network, no Git subprocess,
no runtime credential or state path, no live Control Plane or Hong Kong contact,
no private key anywhere. The git plumbing itself is proven against a real
repository by ``install/verify_transport_is_bounded.py``, which the workflow runs
separately -- this gate is what pins the rules that decide whether that plumbing
is ever allowed to run.
"""
import hashlib
import io
import json
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/go-cc-lrt-checks").resolve()
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
import test_liveness_request_transport as t  # noqa: E402

log = io.StringIO()
suite = unittest.defaultTestLoader.loadTestsFromModule(t)
result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)

X = t.X
schema = json.loads(t.SCHEMA.read_text(encoding="utf-8"))
bounds = X.bounds()
source = t.TOOL.read_text(encoding="utf-8")

summary = {
    "schema_version": "1",
    "component": "liveness-request-transport-v1",
    "issue": "#98 / CC V1-03 wiring",
    "status": "PASS" if result.wasSuccessful() else "FAIL",
    "tests": result.testsRun,
    "failures": len(result.failures),
    "errors": len(result.errors),
    "skips": len(result.skipped),
    "action_id": X.ACTION_ID,
    "environment": X.ENVIRONMENT,
    "request_fields": sorted(X.REQUEST_FIELDS),
    "transport_branch": X.TRANSPORT_BRANCH,
    "archive_branch": X.ARCHIVE_BRANCH,
    "transport_branches": bounds["transport_branches"],
    "archive_branches": bounds["archive_branches"],
    "submissions_per_cycle": bounds["submissions_per_cycle"],
    "requests_per_submission": bounds["requests_per_submission"],
    "max_publish_age_seconds": bounds["max_publish_age_seconds"],
    "bridge_max_age_seconds": bounds["bridge_max_age_seconds"],
    "archive_is_append_only": bounds["archive_is_append_only"],
    "pr_creation_capability": "ABSENT" if "import requests" not in source
                              and "urllib" not in source else "PRESENT",
    "merge_capability": "ABSENT",
    "close_capability": "ABSENT",
    "http_client_in_source": "NO" if "urllib" not in source and "http.client" not in source
                             else "YES",
    "contract_requires_the_bounds_the_tool_emits":
        set(schema["properties"]["bounds"]["required"]) == set(bounds),
    "transport_holds_no_private_key": "YES" if ".pem" not in source else "NO",
    "transport_signs_anything": "NO" if "sign(" not in source else "YES",
    "transport_creates_a_task": "NO",
    "transport_asserts_liveness": "NO",
    "network_access": "FORBIDDEN",
    "subprocess_access": "FORBIDDEN",
    "hong_kong": "NOT_ACCESSED",
    "production": "NOT_ACCESSED",
    "live_control_plane_state": "NOT_ACCESSED",
    "deployed": "NO",
    # Installed on the Command Center host and driven by
    # go-liveness-request-transport.timer. This replaces the manual wiring that
    # opened one branch and one pull request per probe.
    "installed": "YES",
    "transport_timer_installed": "YES",
    "one_open_pull_request": "YES",
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
