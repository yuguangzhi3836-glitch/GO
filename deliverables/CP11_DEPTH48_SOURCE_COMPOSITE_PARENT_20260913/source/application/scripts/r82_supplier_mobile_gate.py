from pathlib import Path
import sys
import json
root=Path(__file__).resolve().parents[1]
app=(root/'frontend/shared/app.js').read_text()
css=(root/'frontend/shared/styles.css').read_text()
idx=(root/'frontend/supplier/index.html').read_text()
config=(root/'frontend/supplier/config.js').read_text()
manifest=json.loads((root/'CURRENT_RELEASE_MANIFEST.json').read_text(encoding='utf-8'))
asset_token=manifest.get('release_integrity',{}).get('console_asset_cache_token')
checks={
 'supplier_mobile_chrome': "supplierMobileChrome" in app and "supplier-mobile-bottom" in app,
 'fixed_mobile_primary_nav': all(x in app for x in ["['/command','首页'","['/operations-hub','履约'","['/marketing-rights','促销权益'","['/finance-hub','财务'","<span>我的</span>"]),
 'all_functions_sheet': 'supplier-mobile-function-grid' in app and 'data-mobile-menu-route' in app,
 'mobile_table_cards': 'data-label=' in app and '.supplier-shell td:before' in css,
 'desktop_sidebar_preserved': '.shell{min-height:100vh;display:grid;grid-template-columns:250px 1fr}' in css and '<aside class="sidebar">' in app,
 'mobile_sidebar_hidden_only': '@media(max-width:620px)' in css and '.supplier-shell>.sidebar{display:none!important}' in css,
 'mobile_touch_targets': 'min-height:44px' in css,
 'mobile_cache_buster': bool(asset_token) and ('/console-assets/app.js?v='+asset_token) in idx and ('/console-assets/styles.css?v='+asset_token) in idx,
 'supplier_chinese_primary_nav': all(x in config for x in ['经营中心','订单与履约','促销与权益','经营数据','财务','业务管理','异常中心']),
}
failed=[k for k,v in checks.items() if not v]
for k,v in checks.items(): print(f'{k}={"PASS" if v else "FAIL"}')
if failed:
    print('R8.2_SUPPLIER_MOBILE_GATE: FAIL -> '+','.join(failed)); sys.exit(1)
print('R8.2_SUPPLIER_MOBILE_GATE: PASS')
