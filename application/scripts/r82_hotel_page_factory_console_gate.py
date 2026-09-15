#!/usr/bin/env python3
from pathlib import Path
import re, subprocess, sys
ROOT=Path(__file__).resolve().parents[1]
config=(ROOT/'frontend/admin/config.js').read_text(encoding='utf-8')
index=(ROOT/'frontend/admin/index.html').read_text(encoding='utf-8')
ui=(ROOT/'frontend/admin/hotel-page-factory.js').read_text(encoding='utf-8')
app=(ROOT/'frontend/shared/app.js').read_text(encoding='utf-8')
routes=(ROOT/'src/go_hotel/api/routes/hotel_autopage_factory.py').read_text(encoding='utf-8')
svc=(ROOT/'src/go_hotel/services/hotel_autopage_factory.py').read_text(encoding='utf-8')
release=(ROOT/'scripts/release_gate_r82.sh').read_text(encoding='utf-8')
checks={
 'admin_first_level_nav': "route:'/hotel-page-factory'" in config and "label:'酒店数字基础设施'" in config,
 'factory_script_loaded': '/go-admin/hotel-page-factory.js' in index,
 'factory_custom_route': "adminHotelPageFactory" in app and 'GO_HOTEL_PAGE_FACTORY.render' in app,
 'fixed_operating_states': all(x in ui for x in ['待建网页','采集中','待合并','待媒体审核','待发布','已发布','待酒店认领','已认领','GO Direct']),
 'primary_cta': ('一键全国分层建库' in ui or '一键建立全国酒店库' in ui) and '启动指定区域建库' in ui,
 'detail_required_facts': all(x in ui for x in ['资料完整度','来源数','房型数','图片数','媒体 Rights','页面预览','重新采集','重新生成','发布网页','下架网页']),
 'technical_ids_hidden': '<details class="card tech-diagnostics">' in ui and 'Hotel ID' in ui and '最近 Discovery Job' in ui,
 'admin_single_hotel_not_primary': 'factoryCreate' not in ui[ui.index('async function render'):ui.index('async function openHotel')],
 'no_bulk_ui_entry': '/internal/v1/hotel-discovery/batches/run' not in ui,
 'overview_api': '/internal/v1/hotel-autopage/factory/overview' in routes and 'def factory_overview' in svc,
 'detail_api': '/internal/v1/hotel-autopage/factory/hotels/{hotel_id}' in routes and 'def factory_detail' in svc,
 'publication_api': '/internal/v1/hotel-autopage/factory/hotels/{hotel_id}/publication' in routes and 'def set_publication' in svc,
 'unpublish_is_fail_closed': "if p.page_state!='PUBLISHED':raise ValueError('HOTEL_PAGE_NOT_PUBLISHED')" in svc,
 'rights_gate_visible': 'rights_pending_count' in svc and 'media_harvester_service.list_assets' in svc,
 'claim_go_direct_visible': 'registration_state' in svc and 'GO_DIRECT' in svc,
 'security_hardening_inherited': 'r82_discovery_ssrf_guard_gate.py' in release,
 'console_gate_in_release_gate': 'r82_hotel_page_factory_console_gate.py' in release,
 'no_schema_model_added': 'class HotelPageFactory' not in (ROOT/'src/go_hotel/db/models.py').read_text(encoding='utf-8'),
}
failed=[]
for k,v in checks.items():
    print(f'{k}={"PASS" if v else "FAIL"}')
    if not v: failed.append(k)
for js in [ROOT/'frontend/admin/hotel-page-factory.js',ROOT/'frontend/admin/config.js',ROOT/'frontend/admin/admin-ux.js']:
    r=subprocess.run(['node','--check',str(js)],capture_output=True,text=True)
    ok=r.returncode==0
    print(f'node_syntax_{js.name}={"PASS" if ok else "FAIL"}')
    if not ok:
        print(r.stderr);failed.append('node:'+js.name)
if failed:
    raise SystemExit('R8.2_HOTEL_PAGE_FACTORY_CONSOLE_GATE: FAIL '+','.join(failed))
print('R8.2_HOTEL_PAGE_FACTORY_CONSOLE_GATE: PASS')
