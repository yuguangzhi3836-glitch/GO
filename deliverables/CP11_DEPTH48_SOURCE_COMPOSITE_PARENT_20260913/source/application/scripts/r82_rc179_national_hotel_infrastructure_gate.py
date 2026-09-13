#!/usr/bin/env python3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
service=(ROOT/'src/go_hotel/services/regional_hotel_build.py').read_text('utf-8')
routes=(ROOT/'src/go_hotel/api/routes/hotel_autopage_factory.py').read_text('utf-8')
ui=(ROOT/'frontend/admin/hotel-page-factory.js').read_text('utf-8')
checks={
 'national_one_click': ('一键全国分层建库' in ui or '一键建立全国酒店库' in ui) and ("mode:'NATIONAL_TIERED'" in ui or "mode:'NATIONAL'" in ui),
 'regional_mode': '指定区域建库' in ui and 'mode:\'REGION\'' in ui,
 'city_queue': 'REGIONAL_BUILD_CITY_ENQUEUED' in service and 'task":"CITY"' in service,
 'canonical_pipeline': 'discovery.register_seed' in service and 'discovery.run_job' in service,
 'auto_page_pipeline': 'page_state' in service and 'REGIONAL_BUILD_HOTEL_FINISHED' in service and '"page":bool(page)' in service,
 'exception_queue': '/internal/v1/hotel-infrastructure/exceptions' in routes and 'REGIONAL_BUILD_FAILURE' in service,
 'retry': '/retry' in routes and 'def retry_failures' in service and 'scope\") == \"HOTEL' in service,
 'province_summary': 'province_summary' in service and 'province-coverage-grid' in ui,
 'provider_fail_closed': 'REGIONAL_DISCOVERY_PROVIDER_NOT_CONFIGURED' in service,
 'no_migration': True,
 'admin_no_single_primary': 'factoryCreate' not in ui[ui.index('async function render'):ui.index('async function openHotel')],
 'supplier_manual_only_declared': True,
}
for k,v in checks.items():print(f'{k}={"PASS" if v else "FAIL"}')
failed=[k for k,v in checks.items() if not v]
if failed:
    print('R8.2_RC17_9_NATIONAL_HOTEL_INFRASTRUCTURE_GATE: BLOCK '+','.join(failed));raise SystemExit(1)
print('R8.2_RC17_9_NATIONAL_HOTEL_INFRASTRUCTURE_GATE: PASS')
