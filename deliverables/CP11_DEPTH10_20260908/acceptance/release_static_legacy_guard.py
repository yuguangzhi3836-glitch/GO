#!/usr/bin/env python3
"""Fail release if assembled production code still routes through legacy authorities."""
from __future__ import annotations

import json
import pathlib
import re
import sys

FORBIDDEN = {
    "legacy_redis_import": re.compile(r"from\s+go_hotel\.queue\.redis_queue\s+import\s+RedisQueue"),
    "legacy_regional_enqueue": re.compile(r"regional_hotel_build\s+import\s+enqueue|regional_hotel_build\.enqueue"),
    "legacy_media_import": re.compile(r"from\s+go_hotel\.services\.media_harvester\s+import"),
    "local_media_index": re.compile(r"index\.json"),
}
ALLOW_PATH_SUFFIXES = {
    "services/regional_build_cutover.py",
    "acceptance/release_static_legacy_guard.py",
}


def scan(root: pathlib.Path) -> dict:
    violations = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if any(rel.endswith(x) for x in ALLOW_PATH_SUFFIXES):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for code, pattern in FORBIDDEN.items():
            if pattern.search(text):
                violations.append({"code": code, "path": rel})
    return {"gate": "DEPTH10_LEGACY_PRODUCTION_GUARD", "status": "PASS" if not violations else "HOLD", "violations": violations}


def main(argv):
    if len(argv) != 2:
        print("usage: release_static_legacy_guard.py <assembled-source-root>", file=sys.stderr)
        return 2
    root = pathlib.Path(argv[1]).resolve()
    result = scan(root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
