#!/usr/bin/env python3
from pathlib import Path
import re, sys, json
ROOT=Path(__file__).resolve().parents[1]
shared=(ROOT/'frontend/shared/app.js').read_text(encoding='utf-8')
supplier_cfg=(ROOT/'frontend/supplier/config.js').read_text(encoding='utf-8')
supplier_plugin=(ROOT/'frontend/supplier/direct-value-economics.js').read_text(encoding='utf-8')
consumer=(ROOT/'frontend/consumer/app.js').read_text(encoding='utf-8')
admin_cfg=(ROOT/'frontend/admin/config.js').read_text(encoding='utf-8')
admin_plugins='\n'.join(p.read_text(encoding='utf-8') for p in (ROOT/'frontend/admin').glob('*.js'))
styles=(ROOT/'frontend/shared/styles.css').read_text(encoding='utf-8')
manifest=json.loads((ROOT/'CURRENT_RELEASE_MANIFEST.json').read_text(encoding='utf-8'))
asset_token=manifest.get('release_integrity',{}).get('console_asset_cache_token')
supplier_idx=(ROOT/'frontend/supplier/index.html').read_text(encoding='utf-8')
admin_idx=(ROOT/'frontend/admin/index.html').read_text(encoding='utf-8')

def block(msg):
 print('R8.2_THREE_SURFACE_PRODUCTIZATION_GATE: BLOCK'); print(msg); sys.exit(1)

supplier_routes=re.findall(r"route:'([^']+)'",supplier_cfg)
primary_match=re.search(r"nav:\[(.*?)\],hiddenNav:\[",supplier_cfg,re.S)
if not primary_match: block('SUPPLIER_PRIMARY_NAV_BLOCK_MISSING')
primary_routes=re.findall(r"route:'([^']+)'",primary_match.group(1))
if len(primary_routes)!=7: block(f'SUPPLIER_PRIMARY_ROUTE_COUNT:{len(primary_routes)}')
if len(supplier_routes)<28: block(f'SUPPLIER_TOTAL_ROUTE_COUNT_TOO_LOW:{len(supplier_routes)}')
for r in supplier_routes:
 if f"'{r}':" not in shared and f"'{r}'" not in shared: block('SUPPLIER_ROUTE_NOT_PRODUCTIZED:'+r)
checks={
 'supplier_business_paradigms':'SUPPLIER_PRODUCT_PARADIGM' in shared,
 'supplier_business_forms':'business-form-grid' in shared and 'supplierInputControl' in shared,
 'supplier_tech_hidden':'技术信息 / 高级信息' in shared,
 'supplier_real_save':'保存酒店资料' in shared and "method:'PATCH'" in shared,
 'supplier_no_english_nav':'Official Direct Value' not in supplier_plugin and 'Direct Channel Economics' not in supplier_plugin,
 'consumer_state_labels':'CONSUMER_STATE_LABELS' in consumer and 'consumerEmpty' in consumer,
 'consumer_chinese_trip_labels':all(x in consumer for x in ['<span>品类</span>','<span>支付</span>','<span>退款</span>']),
 'consumer_core_modules':all(x in consumer for x in ['酒店','机票','火车票','用车','门票','Offer','GO Trips','点评','收藏','我的']),
 'admin_productization_observer':'installAdminProductizationObserver' in shared and 'adminProductizeView' in shared,
 'admin_raw_json_collapsed':'技术信息' in shared and 'jsonCard(title,obj){return `<details' in shared,
 'admin_nav_chinese':'Official Direct Value' not in admin_plugins and "label:'赔付 / Liability'" not in admin_cfg,
 'mobile_single_column':'@media(max-width:720px)' in styles and '.business-form-grid{grid-template-columns:1fr}' in styles,
 'cache_bust_consumer':bool(asset_token) and ('/go-app/app.js?v='+asset_token) in (ROOT/'frontend/consumer/index.html').read_text() and ('/go-app/styles.css?v='+asset_token) in (ROOT/'frontend/consumer/index.html').read_text(),
 'cache_bust_supplier':bool(asset_token) and ('/console-assets/app.js?v='+asset_token) in supplier_idx and ('/console-assets/styles.css?v='+asset_token) in supplier_idx,
 'cache_bust_admin':bool(asset_token) and ('/console-assets/app.js?v='+asset_token) in admin_idx and ('/console-assets/styles.css?v='+asset_token) in admin_idx,
}
for k,v in checks.items(): print(f'{k}={"PASS" if v else "FAIL"}')
failed=[k for k,v in checks.items() if not v]
if failed: block('FAILED:'+','.join(failed))
print(f'supplier_primary_modules={len(primary_routes)}')
print(f'supplier_total_product_routes={len(supplier_routes)}')
print(f'admin_config_routes={len(re.findall(r"route:\'[^\']+\'",admin_cfg))}')
print('R8.2_THREE_SURFACE_PRODUCTIZATION_GATE: PASS')
