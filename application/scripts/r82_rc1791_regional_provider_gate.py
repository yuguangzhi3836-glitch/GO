from pathlib import Path
import os

ROOT=Path(__file__).resolve().parents[1]
svc=(ROOT/'src/go_hotel/services/regional_hotel_build.py').read_text()
ui=(ROOT/'frontend/admin/hotel-page-factory.js').read_text()
compose=(ROOT/'docker-compose.staging.yml').read_text()
checks={
    'harbin_osm_bootstrap_allowlist':'OSM_BOOTSTRAP_CITY_ALLOWLIST = {"哈尔滨市"}' in svc,
    'osm_public_fact_only':'"rights_status":"PUBLIC_BUSINESS_FACT"' in svc,
    'national_requires_production_provider':'NATIONAL_DISCOVERY_PROVIDER_REQUIRED' in svc,
    'provider_summary':'harbin_bootstrap_ready' in svc and 'national_ready' in svc,
    'staging_bootstrap_env':'GO_HOTEL_REGION_DISCOVERY_BOOTSTRAP_OSM' in compose,
    'ui_chinese_provider_status':'尚未配置酒店发现数据源' in ui and '哈尔滨首城发现源已就绪' in ui,
    'ui_national_fail_closed':"provider.national_ready?'':'disabled'" in ui,
}
for k,v in checks.items(): print(f'{k}={"PASS" if v else "FAIL"}')
if not all(checks.values()): raise SystemExit(2)
print('R8.2_RC17_9_1_REGIONAL_PROVIDER_GATE=PASS')
