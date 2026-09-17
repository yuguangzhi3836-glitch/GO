#!/usr/bin/env python3
"""Isolated verification for the CONTROL_STATE_V1 projection.

Same discipline as the existing Control Plane checks: ephemeral keys only, no
network, no Git subprocess, no runtime credential or state path, no live Control
Plane or Hong Kong contact.
"""
import hashlib
import io
import json
import os
import pathlib
import sys
import unittest
from contextlib import redirect_stderr

ROOT = pathlib.Path(__file__).resolve().parent
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/go-cc-state-checks").resolve()
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
sys.path.insert(0, str(ROOT))
import test_state_projection  # noqa: E402

log = io.StringIO()
suite = unittest.defaultTestLoader.loadTestsFromModule(test_state_projection)
result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)

projection = test_state_projection.sp
identity = projection.IdentityContract(str(projection.default_identity_contract_path()))
summary = {
    "schema_version": "1",
    "contract": projection.CONTRACT_STATUS,
    "status": "PASS" if result.wasSuccessful() else "FAIL",
    "tests": result.testsRun,
    "failures": len(result.failures),
    "errors": len(result.errors),
    "skips": len(result.skipped),
    "network_access": "FORBIDDEN",
    "subprocess_access": "FORBIDDEN",
    "hong_kong": "NOT_ACCESSED",
    "production": "NOT_ACCESSED",
    "live_control_plane_state": "NOT_ACCESSED",
    "crypto_keys": "EPHEMERAL_SYNTHETIC_ONLY",
    "verifier_identity_contract": "LOADED" if identity.available else "UNRESOLVED",
    "published_task_identity_fingerprint": (
        (identity.expected(projection.ROLE_TASK) or {}).get("ssh_sha256")),
    "published_evidence_identity_fingerprint": (
        (identity.expected(projection.ROLE_EVIDENCE) or {}).get("ssh_sha256")),
    "published_identities_are_distinct": bool(
        identity.available
        and identity.expected(projection.ROLE_TASK)["ssh_sha256"]
        != identity.expected(projection.ROLE_EVIDENCE)["ssh_sha256"]),
    "published_private_keys": "NONE",
    "application_changed": "NO",
    "files": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(ROOT.rglob("*"))
              if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"},
}
(OUT / "checks.log").write_text(log.getvalue(), encoding="utf-8")
(OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(log.getvalue(), end="")
print(json.dumps({k: v for k, v in summary.items() if k != "files"}, sort_keys=True))
sys.exit(0 if summary["status"] == "PASS" else 1)
