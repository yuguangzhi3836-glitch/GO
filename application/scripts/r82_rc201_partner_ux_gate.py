#!/usr/bin/env python3
from pathlib import Path
import json, re, sys
ROOT=Path(__file__).resolve().parents[1]
errors=[]
config=(ROOT/'frontend/supplier/config.js').read_text(encoding='utf-8')
app=(ROOT/'frontend/shared/app.js').read_text(encoding='utf-8')
manifest=json.loads((ROOT/'CURRENT_RELEASE_MANIFEST.json').read_text(encoding='utf-8'))
expected=['经营中心','订单与履约','促销与权益','经营数据','财务','业务管理','异常中心']
# Extract only primary nav block before hiddenNav.
m=re.search(r"nav:\[(.*?)\],hiddenNav:\[",config,re.S)
if not m: errors.append('PRIMARY_NAV_BLOCK_MISSING')
else:
    block=m.group(1)
    labels=re.findall(r"label:'([^']+)'",block)
    if labels!=expected: errors.append('PRIMARY_NAV_NOT_TASK_ORIENTED:'+repr(labels))
    if len(labels)>7: errors.append('PRIMARY_NAV_TOO_LARGE')
for forbidden in ['GO 身份与礼遇','酒店网页','酒店资料','房型管理','房态房价','官方权益','GO Offer','T+20 与订阅','供应链连接']:
    if m and f"label:'{forbidden}'" in m.group(1): errors.append('DETAIL_ROUTE_LEAKED_TO_PRIMARY:'+forbidden)
for token in ['supplierOperationsHub','supplierMarketingRightsHub','supplierAnalyticsHub','supplierFinanceHub','supplierBusinessManagementHub','supplierExceptionCenter']:
    if token not in app: errors.append('HUB_HANDLER_MISSING:'+token)
for token in ['员工优价 / 业主权益','供应商自行与银行/PSP完成最终银行对账','GO 消费者身份/平台礼遇不在本模块配置','异常中心是唯一人工异常入口']:
    if token not in app: errors.append('BOUNDARY_COPY_MISSING:'+token)
rc201=manifest.get('rc20_1',{})
if rc201.get('expert_final_review_status')!='NO_GO_B_CLASS_OPEN': errors.append('EXPERT_REVIEW_NO_GO_NOT_PRESERVED')
if rc201.get('deployment_allowed') is not False: errors.append('DEPLOYMENT_MUST_REMAIN_BLOCKED')
if rc201.get('owner_staff_benefits_under_promotion') is not True: errors.append('OWNER_STAFF_PROMOTION_BOUNDARY_MISSING')
if manifest.get('release_integrity',{}).get('console_asset_cache_token') not in {'20260825-rc20.1','20260825-rc20.2','20260825-rc20.3'}: errors.append('CACHE_TOKEN_NOT_RC20_FAMILY')
for rel in ['frontend/supplier/index.html','frontend/admin/index.html']:
    if not any(t in (ROOT/rel).read_text(encoding='utf-8') for t in ('20260825-rc20.1','20260825-rc20.2','20260825-rc20.3')): errors.append('CACHE_TOKEN_STALE:'+rel)
if errors:
    print('R8.2_RC20_1_PARTNER_UX_GATE: BLOCK')
    for e in errors: print(e)
    sys.exit(1)
print('primary_navigation=7_task_oriented_modules')
print('owner_staff_rights=UNDER_PROMOTION_AND_RIGHTS')
print('bank_reconciliation_boundary=SUPPLIER_OWN_BANK_OR_PSP_RECONCILIATION')
print('expert_review_status=NO_GO_B_CLASS_OPEN')
print('R8.2_RC20_1_PARTNER_UX_GATE: PASS')
