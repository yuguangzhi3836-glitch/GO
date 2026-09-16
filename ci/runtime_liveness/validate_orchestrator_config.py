#!/usr/bin/env python3
"""Fail-closed preflight for the durable GO Cell orchestrator."""
import argparse
import json
import os
from pathlib import Path
import stat


def validate(database: Path, token: str | None, tls_cert: Path | None,
             tls_key: Path | None, *, allow_http_loopback: bool = False) -> dict:
    errors = []
    if not database.is_absolute():
        errors.append("database path must be absolute")
    parent = database.parent
    if not parent.exists() or not parent.is_dir():
        errors.append("database parent directory does not exist")
    elif not os.access(parent, os.W_OK):
        errors.append("database parent directory is not writable")
    if not token or len(token) < 32:
        errors.append("orchestrator token must contain at least 32 characters")
    if not allow_http_loopback:
        if not tls_cert or not tls_cert.is_file():
            errors.append("TLS certificate is missing")
        if not tls_key or not tls_key.is_file():
            errors.append("TLS key is missing")
        elif stat.S_IMODE(tls_key.stat().st_mode) & 0o077:
            errors.append("TLS key must not be group/world accessible")
    return {"status": "ready" if not errors else "blocked", "errors": errors,
            "database": str(database), "tls_required": not allow_http_loopback}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--token-env", default="GO_CELL_ORCHESTRATOR_TOKEN")
    parser.add_argument("--tls-cert", type=Path)
    parser.add_argument("--tls-key", type=Path)
    parser.add_argument("--allow-http-loopback", action="store_true")
    args = parser.parse_args()
    result = validate(args.database, os.environ.get(args.token_env), args.tls_cert,
                      args.tls_key, allow_http_loopback=args.allow_http_loopback)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
