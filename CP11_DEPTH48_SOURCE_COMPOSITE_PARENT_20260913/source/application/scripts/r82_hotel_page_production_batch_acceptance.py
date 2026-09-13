#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os

from go_hotel.services.hotel_page_production_acceptance import hotel_page_production_acceptance_service as svc


def main() -> None:
    ap = argparse.ArgumentParser(description="RC13 controlled 1 -> 100 -> 1000 hotel page production acceptance")
    ap.add_argument("--level", type=int, choices=[1, 100, 1000])
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--no-cleanup", action="store_true", help="Debug only; do not use for normal Staging acceptance")
    ap.add_argument("--confirm", default="")
    args = ap.parse_args()

    if args.status:
        print(json.dumps({"latest_passed_level": svc.latest_passed_level(), "stats": svc.stats()}, ensure_ascii=False, indent=2))
        return
    if args.level is None:
        ap.error("--level is required unless --status is used")
    if (os.getenv("APP_ENV") or os.getenv("GO_ENV") or "").lower() != "staging":
        raise SystemExit("RC13_ACCEPTANCE_STAGING_ONLY")
    expected = f"RUN-RC13-{args.level}"
    if args.confirm != expected:
        raise SystemExit(f"confirmation required: --confirm {expected}")
    report = svc.run_level(args.level, actor="RC13_STAGING_ACCEPTANCE", cleanup=not args.no_cleanup)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
