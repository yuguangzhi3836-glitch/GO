#!/usr/bin/env python3
from pathlib import Path
import subprocess, sys

ROOT = Path(__file__).resolve().parents[1]
errors=[]
svc=(ROOT/'src/go_hotel/services/rc20_module_depth.py').read_text(encoding='utf-8')
route=(ROOT/'src/go_hotel/api/routes/rc20_module_depth.py').read_text(encoding='utf-8')
ui=(ROOT/'frontend/shared/app.js').read_text(encoding='utf-8')
main=(ROOT/'src/go_hotel/main.py').read_text(encoding='utf-8')
for token in ['NORMAL_PATH','EXCEPTION_RECOVERY','STATE_MACHINE','EVIDENCE_CHAIN','HUMAN_OPERABLE']:
    if token not in svc: errors.append('RC20_DIMENSION_MISSING:'+token)
for v in ['HOTEL','FLIGHT','RAIL','RIDE','RENTAL','ATTRACTION']:
    if f'"{v}"' not in svc: errors.append('RC20_VERTICAL_MISSING:'+v)
if '/module-depth' not in route: errors.append('RC20_ADMIN_DEPTH_ROUTE_MISSING')
if 'rc20_module_depth_router' not in main: errors.append('RC20_ROUTER_NOT_REGISTERED')
if 'RC20 模块深度验收' not in ui: errors.append('RC20_ADMIN_UI_MISSING')
if not any(t in (ROOT/'frontend/admin/index.html').read_text(encoding='utf-8') for t in ('20260825-rc20.2','20260825-rc20.3')): errors.append('RC20_ADMIN_CACHE_TOKEN_MISSING')
if not any(t in (ROOT/'frontend/supplier/index.html').read_text(encoding='utf-8') for t in ('20260825-rc20.2','20260825-rc20.3')): errors.append('RC20_SUPPLIER_CACHE_TOKEN_MISSING')

if errors:
    print('R8.2_RC20_MODULE_DEPTH_GATE: BLOCK')
    for e in errors: print(e)
    sys.exit(1)

# Engineering E2E depth suite. This verifies actual happy paths, negative paths,
# changes/refunds, evidence projection and hotel transaction/fulfillment flows.
tests = [
    'tests/test_rc20_module_depth_contract.py',
    'tests/test_rc20_2_all_b_to_a.py',
    'tests/test_sprint3a_flight.py',
    'tests/test_sprint3b_rail.py',
    'tests/test_sprint3c_mobility.py',
    'tests/test_sprint3d_attractions.py',
    'tests/test_consumer_unified_lifecycle.py',
    'tests/test_first_go_hosted_direct_booking_pilot.py',
    'tests/test_guest_stay_fulfillment_settlement_eligibility.py',
    'tests/test_post_stay_dispute_refund_reconciliation.py',
]
cmd=[sys.executable,'-m','pytest','-q',*tests]
proc=subprocess.run(cmd,cwd=ROOT)
if proc.returncode != 0:
    print('R8.2_RC20_MODULE_DEPTH_GATE: BLOCK')
    print('RC20_ENGINEERING_E2E_SUITE_FAILED')
    sys.exit(proc.returncode)
print('R8.2_RC20_MODULE_DEPTH_GATE: PASS')
print('RC20_STAGING_BROWSER_E2E: REQUIRED_BEFORE_FINAL_PASS')
