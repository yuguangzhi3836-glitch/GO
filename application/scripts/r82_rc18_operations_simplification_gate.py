#!/usr/bin/env python3
from pathlib import Path
import json,re
ROOT=Path(__file__).resolve().parents[1]
errors=[]
ux=(ROOT/'frontend/admin/admin-ux.js').read_text(encoding='utf-8')
app=(ROOT/'frontend/shared/app.js').read_text(encoding='utf-8')
manifest=json.loads((ROOT/'CURRENT_RELEASE_MANIFEST.json').read_text(encoding='utf-8'))
for token in ['运营','异常中心','治理后台']:
    if token not in ux: errors.append('MAIN_NAV_MISSING:'+token)
for token in ['今日运行状态','六大业务运营','全国酒店数字基础设施','供应商与合作伙伴','订单与履约','交易状态与证据']:
    if token not in app: errors.append('OPERATIONS_HUB_MISSING:'+token)
for route in ['/vertical-hotel','/vertical-flight','/vertical-rail','/vertical-ride','/vertical-rental','/vertical-attraction']:
    if route not in app: errors.append('ECOSYSTEM_VERTICAL_MISSING:'+route)
for fn in ['adminEcosystemOperations','adminTransactionEvidence','adminExceptionCenter','adminGovernanceHub']:
    if f'function {fn}' not in app and f'async function {fn}' not in app: errors.append('CUSTOM_HUB_MISSING:'+fn)
if 'routeCatalog=[...nav,...hiddenNav]' not in app: errors.append('HIDDEN_ROUTE_CATALOG_MISSING')
if '供应商与其银行/PSP之间的最终财务对账由供应商自行完成' not in app: errors.append('BANK_RECONCILIATION_BOUNDARY_MISSING')
if 'GO 不代替供应商进行银行流水对账' not in app: errors.append('GO_BANK_RECONCILIATION_NON_RESPONSIBILITY_MISSING')
if 'bank_amount_minor' in app: errors.append('BANK_STATEMENT_FIELD_STILL_EXPOSED_IN_FRONTEND')
ops=manifest.get('operations_simplification',{})
if ops.get('supplier_bank_psp_final_reconciliation_out_of_scope') is not True: errors.append('MANIFEST_BANK_BOUNDARY_MISSING')
if ops.get('ecosystem_verticals') != ['HOTEL','FLIGHT','RAIL','RIDE','RENTAL','ATTRACTION']: errors.append('MANIFEST_ECOSYSTEM_SET_MISMATCH')
# RC18 historical manifest keeps its 8-entry snapshot; current RC20.3 UI intentionally collapses the primary mental model to three spaces.
if len(ops.get('main_nav',[])) != 8: errors.append('RC18_MANIFEST_SNAPSHOT_MISMATCH')
# RC20.3 daily admin nav is intentionally three primary mental spaces; former RC18 routes remain reachable inside the Operations hub.
main_routes=['/operations','/exception-center','/governance']
for r in main_routes:
    if r not in ux: errors.append('MAIN_ROUTE_MISSING:'+r)
for r in ['/dashboard','/ecosystem-operations','/hotel-page-factory','/supplier-registry','/orders','/transaction-evidence']:
    if r not in app: errors.append('OPERATIONS_HUB_ROUTE_MISSING:'+r)
if 'c.hiddenNav=all.filter' not in ux: errors.append('GOVERNANCE_ROUTES_NOT_HIDDEN')
if errors:
    print('R8.2_RC18_OPERATIONS_SIMPLIFICATION_GATE: BLOCK')
    for e in errors: print(e)
    raise SystemExit(1)
print('full_ecosystem_verticals=PASS')
print('daily_nav_three_spaces=PASS')
print('exception_center=PASS')
print('governance_backend=PASS')
print('supplier_bank_reconciliation_boundary=PASS')
print('R8.2_RC18_OPERATIONS_SIMPLIFICATION_GATE: PASS')
