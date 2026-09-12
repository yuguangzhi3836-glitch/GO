#!/usr/bin/env python3
from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]

def block(reason: str) -> None:
    print('R8.2_RELEASE_ENGINEERING_DEBT_GATE: BLOCK')
    print(reason)
    raise SystemExit(1)

launcher = (ROOT / 'deploy/deploy_hk_staging.sh').read_text(encoding='utf-8')
if 'chmod 0755 deploy/*.sh scripts/*.sh' not in launcher:
    block('DEPLOY_CHMOD_0755_MISSING')
for target in ('static_preflight.sh','db_readonly_preflight.sh','backup_rds.sh','migrate_rds.sh','https_verify.sh','browser_verify.sh'):
    if f'sh deploy/{target}' not in launcher:
        block('EXPLICIT_SH_INVOCATION_MISSING:' + target)

migrate = (ROOT / 'deploy/migrate_rds.sh').read_text(encoding='utf-8')
if 'sh deploy/static_preflight.sh' not in migrate:
    block('MIGRATE_STATIC_PREFLIGHT_NOT_EXPLICIT_SH')

pkg_gate = (ROOT / 'scripts/r82_deploy_package_gate.py').read_text(encoding='utf-8')
if 'NOT_EXECUTABLE:' in pkg_gate or 'stat.S_IXUSR' in pkg_gate:
    block('PACKAGE_GATE_STILL_DEPENDS_ON_EXECUTABLE_BIT')

contract = (ROOT / 'scripts/r8_contract_gate.py').read_text(encoding='utf-8')
for token in ('TemporaryDirectory', 'GO_MEDIA_CACHE_DIR', "prefix='go-r8-contract-media-'"):
    if token not in contract:
        block('CONTRACT_GATE_TEMP_CACHE_MISSING:' + token)
ast.parse(contract)

builder = (ROOT / 'scripts/build_r82_candidate.py').read_text(encoding='utf-8')
for token in ("'__pycache__'", "'.pyc'", "'media_cache'", "'deploy/evidence/'"):
    if token not in builder:
        block('PACKAGE_EXCLUSION_MISSING:' + token)
ast.parse(builder)

# Release-control must bind the already-audited 0114 lineage; this closure must not alter migration content.
versions = list((ROOT / 'alembic/versions').glob('*.py'))
revisions = []
for p in versions:
    text = p.read_text(encoding='utf-8')
    m = re.search(r'^revision\s*=\s*[\'\"]([^\'\"]+)', text, re.M)
    if m:
        revisions.append(m.group(1))
if len(revisions) != 114 or '0114_ext_truth_incident_hard' not in revisions:
    block(f'MIGRATION_BINDING_BROKEN revisions={len(revisions)} head_present={"0114_ext_truth_incident_hard" in revisions}')

print('R8.2_RELEASE_ENGINEERING_DEBT_GATE: PASS')
