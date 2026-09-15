#!/usr/bin/env python3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
app=(ROOT/'frontend/shared/app.js').read_text(encoding='utf-8')
docker=(ROOT/'Dockerfile').read_text(encoding='utf-8')
pre=(ROOT/'deploy/db_readonly_preflight.sh').read_text(encoding='utf-8')
checks={
 'supplier_first_property_returns_null': "function supplierFirstProperty()" in app and "return rows[0]||null" in app,
 'supplier_first_property_no_property_throw': "throw new Error('PROPERTY_REQUIRED')" not in app,
 'command_empty_state_reachable': "'/command':{title:'酒店经营中心'" in app and "empty:'当前没有待处理经营事项。'" in app,
 'rooms_empty_state_reachable': "supplierStructuredEmpty('/rooms'" in app,
 'inbox_empty_state_reachable': "supplierStructuredEmpty('/inbox'" in app,
 'runtime_image_contains_lineage_probe': 'COPY scripts/r82_rds_lineage_probe.py ./scripts/r82_rds_lineage_probe.py' in docker,
 'readonly_preflight_invokes_probe': 'python scripts/r82_rds_lineage_probe.py' in pre,
}
for k,v in checks.items(): print(f'{k}={"PASS" if v else "FAIL"}')
failed=[k for k,v in checks.items() if not v]
if failed:
    print('R8.2_RC09_3_HARDENING_GATE: BLOCK ' + ','.join(failed))
    raise SystemExit(1)
print('R8.2_RC09_3_HARDENING_GATE: PASS')
