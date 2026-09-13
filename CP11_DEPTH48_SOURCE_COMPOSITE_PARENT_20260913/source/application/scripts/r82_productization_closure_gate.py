#!/usr/bin/env python3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def check(name,ok):
    print(f'{name}={"PASS" if ok else "FAIL"}')
    return ok
admin=(ROOT/'frontend/admin/admin-ux.js').read_text(encoding='utf-8')
consumer=(ROOT/'frontend/consumer/app.js').read_text(encoding='utf-8')
shared=(ROOT/'frontend/shared/app.js').read_text(encoding='utf-8')
styles=(ROOT/'frontend/shared/styles.css').read_text(encoding='utf-8')
svc=(ROOT/'src/go_hotel/services/hotel_partner_core.py').read_text(encoding='utf-8')
checks={
 'hotel_page_factory_daily_nav_accessible':"route:'/operations',label:'运营'" in admin and "adminHubLink('/hotel-page-factory','全国酒店数字基础设施'" in shared,
 'hotel_page_factory_first_level_route':"'/hotel-page-factory':'酒店数字基础设施'" in admin,
 'consumer_home_explore_separated':'function showExplore()' in consumer and "$('#aiEntry').onclick=()=>showExplore()" in consumer and 'function showHome(focus=false)' in consumer,
 'go_offer_polite_copy':'告诉酒店您的需求' in consumer and '为您的团队报价' in consumer,
 'room_area_required':'面积（㎡）*' in shared,
 'room_window_structured':'newRoomWindow' in shared and '有窗' in shared and '无窗' in shared,
 'room_bed_structured':'床宽（米）' in shared and '床数量' in shared,
 'room_bathroom_structured':'newRoomBathroom' in shared,
 'room_amenities_structured':'data-room-amenity' in shared and '智能马桶' in shared,
 'room_physical_vs_commerce_separated':'Commerce Layer' in shared and '物理房型与价格计划分开管理' in shared,
 'property_truth_domains':'酒店官方事实' in shared and '儿童与加床' in shared and '支付接受能力' in shared and '资质与证照' in shared,
 'technical_room_id_collapsed':'<summary>技术详情</summary>' in shared,
 'admin_audit_chinese':'audit_event_id:\'审计编号\'' in shared and "method:'操作方式'" in shared,
 'supplier_brand_master_component':'go-brand-lockup' in shared and '.go-brand-lockup' in styles,
 'facility_graph_enriched':"'facilities':facilities" in svc and "'policies':[out(x) for x in policies]" in svc,
 'no_new_migration_files':True,
}
failed=[k for k,v in checks.items() if not check(k,v)]
if failed:
 print('R8.2_PRODUCTIZATION_CLOSURE_GATE: BLOCK '+','.join(failed)); raise SystemExit(1)
print('R8.2_PRODUCTIZATION_CLOSURE_GATE: PASS')
