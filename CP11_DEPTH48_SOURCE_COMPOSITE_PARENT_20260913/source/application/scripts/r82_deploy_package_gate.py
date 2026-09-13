from __future__ import annotations
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
required = [
    "deploy/.env.hk-staging.example",
    "deploy/docker-compose.hk-staging.yml",
    "deploy/static_preflight.sh",
    "deploy/db_readonly_preflight.sh",
    "deploy/backup_rds.sh",
    "deploy/migrate_rds.sh",
    "deploy/https_verify.sh",
    "deploy/browser_check.js",
    "deploy/browser_verify.sh",
    "deploy/deploy_hk_staging.sh",
    "deploy/README.md",
]
missing = [p for p in required if not (ROOT / p).is_file()]
if missing:
    print("R8.2_DEPLOY_PACKAGE_GATE: BLOCK")
    for p in missing:
        print("MISSING:" + p)
    raise SystemExit(1)

# ZIP extraction via Python can drop POSIX executable bits. Executability is no
# longer a release-gate prerequisite; deploy_hk_staging.sh restores 0755 and
# nested shell execution uses `sh file.sh`. We still validate POSIX /bin/sh.
for p in (ROOT / "deploy").glob("*.sh"):
    text = p.read_text(encoding="utf-8")
    first = text.splitlines()[0] if text.splitlines() else ""
    if first != "#!/bin/sh" or re.search(r"\bset\s+-[^\n]*o\s+pipefail\b", text) or re.search(r"(^|\n)\s*\[\[", text) or re.search(r"(^|[; ])[<>]\([^)]", text):
        print("R8.2_DEPLOY_PACKAGE_GATE: BLOCK")
        print("NON_POSIX_SHELL:" + p.name)
        raise SystemExit(1)

launcher = (ROOT / "deploy/deploy_hk_staging.sh").read_text(encoding="utf-8")
if "chmod 0755 deploy/*.sh scripts/*.sh" not in launcher:
    print("R8.2_DEPLOY_PACKAGE_GATE: BLOCK")
    print("MISSING_SHELL_MODE_RECOVERY")
    raise SystemExit(1)
print("R8.2_DEPLOY_PACKAGE_GATE: PASS")
