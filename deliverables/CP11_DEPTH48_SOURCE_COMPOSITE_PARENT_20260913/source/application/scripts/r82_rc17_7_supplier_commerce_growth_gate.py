#!/usr/bin/env python3
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
app=(ROOT/'frontend/shared/app.js').read_text(encoding='utf-8')
config=(ROOT/'frontend/supplier/config.js').read_text(encoding='utf-8')
service=(ROOT/'src/go_hotel/services/hotel_partner_core.py').read_text(encoding='utf-8')
routes=(ROOT/'src/go_hotel/api/routes/hotel_partner_core.py').read_text(encoding='utf-8')
checks={
 'hotel_webpage_nav': "route:'/hotel-webpage',label:'酒店网页'" in config,
 'inventory_rates_nav': "route:'/rates',label:'房态房价'" in config,
 'benefits_nav': "route:'/benefits',label:'官方权益'" in config,
 'promotions_nav': "route:'/marketing',label:'自主促销'" in config,
 'ai_marketing_nav': "route:'/ai-marketing',label:'GO AI 营销建议'" in config,
 'growth_data_nav': "route:'/analytics-hub',label:'经营数据'" in config and "route:'/growth-data',label:'经营数据明细'" in config,
 'hotel_webpage_endpoint': "@router.get('/hotel-webpage')" in routes and 'def webpage_workspace' in service,
 'ari_editor': 'ari/date-override' in app and '设置某日房态房价' in app,
 'benefit_editor': 'GO 官方直连权益' in app and 'recommendation_pool_unchanged' in app,
 'promotion_persistence': '/policies' in app and 'PROMOTION_EARLY_BOOKING' in app and 'PROMOTION_LAST_MINUTE' in app,
 'ai_fail_safe': 'AI 不自动执行' in app and '不会自动修改价格、库存、促销或权益' in app,
 'no_fake_growth': '不展示无证据的同行提升百分比' in app and '没有真实样本时' in app,
 'mobile_marketing': "['/marketing-rights','促销权益','◇']" in app,
 'mobile_inventory_rates': "['房态房价','维护价格计划、库存、早餐、取消与预付规则。','/rates']" in app and "route:'/rates',label:'房态房价'" in config,
 'hotel_content_route': 'async function supplierContentTemplate()' in app,
 'no_new_migration_reference': '0112_' not in app and '0112_' not in service and '0112_' not in routes,
}
failed=[]
for k,v in checks.items():
 print(f'{k}={"PASS" if v else "FAIL"}')
 if not v: failed.append(k)
if failed:
 print('R8.2_RC17_7_SUPPLIER_COMMERCE_GROWTH_GATE: BLOCK')
 print('FAILED:'+','.join(failed))
 raise SystemExit(1)
print('R8.2_RC17_7_SUPPLIER_COMMERCE_GROWTH_GATE: PASS')
