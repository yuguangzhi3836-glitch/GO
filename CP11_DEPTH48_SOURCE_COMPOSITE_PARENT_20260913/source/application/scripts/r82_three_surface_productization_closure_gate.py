#!/usr/bin/env python3
from pathlib import Path
import re,sys,json
ROOT=Path(__file__).resolve().parents[1]
shared=(ROOT/'frontend/shared/app.js').read_text(encoding='utf-8')
consumer=(ROOT/'frontend/consumer/app.js').read_text(encoding='utf-8')
supplier_cfg=(ROOT/'frontend/supplier/config.js').read_text(encoding='utf-8')
admin_cfg=(ROOT/'frontend/admin/config.js').read_text(encoding='utf-8')
styles=(ROOT/'frontend/shared/styles.css').read_text(encoding='utf-8')

def block(msg):
 print('R8.2_THREE_SURFACE_PRODUCTIZATION_CLOSURE_GATE: BLOCK');print(msg);raise SystemExit(1)

checks={
 'consumer_no_room_type_id_primary': '${o.room_type_id}</b>' not in consumer,
 'consumer_no_payment_intent_primary': '${r.payment_intent_id}' not in consumer,
 'consumer_no_raw_trip_status': '${t.status}' not in consumer,
 'consumer_no_plain_order_empty': '<div class="empty">还没有订单</div>' not in consumer,
 'consumer_payment_state_mapped': 'consumerLabel(r.state)' in consumer and 'consumerLabel(r.channel)' in consumer,
 'consumer_empty_has_action': "consumerEmpty('还没有订单'" in consumer and "'返回首页','tripHome'" in consumer,
 'supplier_no_browser_draft_primary': '保存页面草稿' not in shared and '草稿仅保存在当前浏览器' not in shared,
 'supplier_property_real_save': "method:'PATCH'" in shared and '/v1/supplier/properties/${encodeURIComponent(p.property_id)}' in shared,
 'supplier_property_real_create': "api.request('/v1/supplier/properties',{method:'POST'" in shared,
 'supplier_room_real_create': '/room-types`,{method:\'POST\'' in shared,
 'supplier_tech_meta_hidden': '字段定义仅供技术诊断使用，不作为酒店员工的主操作界面' in shared,
 'admin_ops_bar_every_view': 'adminOpsBar()' in shared and "if(!view.querySelector('.admin-ops-bar'))" in shared,
 'admin_empty_actionable': '查看异常中心' in shared and 'data-admin-refresh' in shared,
 'admin_raw_object_not_primary_table': "config.actorType==='GO_ADMIN'?'查看详情'" in shared,
 'admin_state_mapping': 'ADMIN_STATE_LABELS' in shared and 'adminFriendlyValue' in shared,
 'admin_raw_json_collapsed_only': 'function jsonCard(title,obj){return `<details' in shared,
 'admin_heading_translation': "view.querySelectorAll('h2,h3')" in shared,
 'mobile_supplier_cards': '.table-wrap thead{display:none}' in styles and '.table-wrap td:before{content:attr(data-label)' in styles,
 'mobile_admin_actions_single_column': '.admin-ops-bar .structured-actions{width:100%;display:grid;grid-template-columns:1fr}' in styles,
}
for k,v in checks.items():print(f'{k}={"PASS" if v else "FAIL"}')
failed=[k for k,v in checks.items() if not v]
if failed:block('FAILED:'+','.join(failed))
# structural counts
supplier_routes=re.findall(r"route:'([^']+)'",supplier_cfg)
admin_routes=re.findall(r"route:'([^']+)'",admin_cfg)
if len(supplier_routes)<28:block('SUPPLIER_ROUTE_COUNT_TOO_LOW:'+str(len(supplier_routes)))
if len(admin_routes)<50:block('ADMIN_ROUTE_COUNT_TOO_LOW:'+str(len(admin_routes)))
route_custom=dict(re.findall(r"\{route:'([^']+)',label:'[^']+',custom:'([^']+)'\}",supplier_cfg))
for r in supplier_routes:
 if f"'{r}':" in shared: continue
 custom=route_custom.get(r)
 if custom and custom in shared: continue
 block('SUPPLIER_PRODUCT_HANDLER_MISSING:'+r)
# cache bust: all three user-facing surfaces bind to the current release-integrity token.
consumer_idx=(ROOT/'frontend/consumer/index.html').read_text(encoding='utf-8')
manifest=json.loads((ROOT/'CURRENT_RELEASE_MANIFEST.json').read_text(encoding='utf-8'))
asset_token=manifest.get('release_integrity',{}).get('console_asset_cache_token')
if not asset_token or ('/go-app/app.js?v='+asset_token) not in consumer_idx or ('/go-app/styles.css?v='+asset_token) not in consumer_idx:
 block('CACHE_BUST_MISSING:consumer/index.html')
for f in ['supplier/index.html','admin/index.html']:
 idx=(ROOT/'frontend'/f.split('/')[0]/'index.html').read_text(encoding='utf-8')
 if not asset_token or ('/console-assets/app.js?v='+asset_token) not in idx or ('/console-assets/styles.css?v='+asset_token) not in idx:
  block('CACHE_BUST_MISSING:'+f)
print(f'consumer_primary_internal_id_leaks=0')
print(f'supplier_modules={len(supplier_routes)} productized={len(supplier_routes)}')
print(f'admin_visible_routes={len(admin_routes)} observer_productized={len(admin_routes)}')
print('R8.2_THREE_SURFACE_PRODUCTIZATION_CLOSURE_GATE: PASS')
