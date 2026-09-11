#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from go_hotel.services.staging_operator import staging_operator_service as svc


def main() -> int:
    p = argparse.ArgumentParser(description="GO R8.2 Staging execution operator")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Show current checkpoint, blockers and missing evidence")
    ex = sub.add_parser("export", help="Export complete staging evidence bundle")
    ex.add_argument("--out", required=True)
    se = sub.add_parser("seal", help="Seal an already-GO checkpoint into a deterministic artifact")
    se.add_argument("--stage", required=True)
    se.add_argument("--out", required=True)
    args = p.parse_args()

    if args.command == "status":
        print(json.dumps(svc.operator_status(), indent=2, ensure_ascii=False, default=str))
        return 0
    if args.command == "export":
        payload = svc.export_bundle()
        result = svc.write_json_artifact(payload, args.out)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.command == "seal":
        payload = svc.seal_checkpoint(args.stage)
        result = svc.write_json_artifact(payload, args.out)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(3)
