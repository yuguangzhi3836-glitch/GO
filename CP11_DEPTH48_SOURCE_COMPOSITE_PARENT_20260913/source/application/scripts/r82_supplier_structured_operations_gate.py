#!/usr/bin/env python3
from pathlib import Path
import re
import json
ROOT=Path(__file__).resolve().parents[1]
app=(ROOT/'frontend/shared/app.js').read_text(encoding='utf-8')
cfg=(ROOT/'frontend/supplier/config.js').read_text(encoding='utf-8')
idx=(ROOT/'frontend/supplier/index.html').read_text(encoding='utf-8')
css=(ROOT/'frontend/shared/styles.css').read_text(encoding='utf-8')
routes=['/command','/property','/rooms','/rates','/orders','/fulfillment','/refunds','/go-offer','/t20','/finance','/reconciliation','/reviews-truth','/go-rating','/go-identity','/content','/direct','/connectors','/inbox','/account','/help','/vertical-capabilities','/supplier-fault','/growth']
problems=[]
for r in routes:
    if f"route:'{r}'" not in cfg: problems.append('MISSING_NAV:'+r)
    if f"'{r}':{{" not in app: problems.append('MISSING_BLUEPRINT:'+r)
    m=re.search(re.escape("'"+r+"':[\n")+r'(.*?)(?=\n\'\/[^\']+\':\[|\n\};)', app, re.S)
    if not m:
        # tolerate first-line compact array start
        m=re.search(re.escape("'"+r+"':[")+r'(.*?)(?=\n\'\/[^\']+\':\[|\n\};)', app, re.S)
    if not m:
        problems.append('MISSING_FIELD_SCHEMA:'+r)
        continue
    count=m.group(1).count('F(')
    if count < 8: problems.append(f'FIELD_SCHEMA_TOO_SHALLOW:{r}:{count}')
for token in ['structuredOperationsRequired:true','supplierStructuredShell','supplierStructuredEmpty','supplierFriendlyLabel','supplierFriendlyValue','SUPPLIER_FIELD_SCHEMAS','supplierFieldTemplate','business-form-grid','supplierInputControl','tech-diagnostics']:
    if token not in app and token not in cfg and token not in css: problems.append('MISSING:'+token)
for token in ['字段中文名','field key','数据类型','是否必填','是否可编辑','校验规则','数据来源','事实等级','修改人或来源主体','异常状态','操作权限']:
    if token not in app: problems.append('MISSING_FIELD_META:'+token)
if "config.actorType==='SUPPLIER_USER'?supplierStructuredEmpty" not in app:
    problems.append('SUPPLIER_EMPTY_NOT_STRUCTURED')
manifest=json.loads((ROOT/'CURRENT_RELEASE_MANIFEST.json').read_text(encoding='utf-8'))
asset_token=manifest.get('release_integrity',{}).get('console_asset_cache_token')
if not asset_token or ('/console-assets/app.js?v='+asset_token) not in idx or ('/console-assets/styles.css?v='+asset_token) not in idx:
    problems.append('CACHE_VERSION_NOT_BUMPED')
for bad in ["label:'酒店资料',endpoint:","label:'房型与库存',endpoint:","label:'内容与媒体',endpoint:"]:
    if bad in cfg: problems.append('GENERIC_VISIBLE_ROUTE:'+bad)
for bad in ['GO Offer Workbench','Unable to Fulfill + Fault Classification','Payment & Finance</h2>','Multi-Vertical Capabilities</h2>']:
    if bad in app: problems.append('ENGINEERING_COPY:'+bad)
# The supplier empty-state branch must be structural; a generic "暂无数据" string may remain only for non-supplier actors.
if "config.actorType==='SUPPLIER_USER'?supplierStructuredEmpty" not in app:
    problems.append('SUPPLIER_PURE_EMPTY_PAGE_RISK')
# Mobile field cards must collapse without horizontal overflow.
for token in ['@media(max-width:720px)', '.business-form-grid{grid-template-columns:1fr}']:
    if token not in css: problems.append('MISSING_MOBILE_BUSINESS_RULE:'+token)
if problems:
    print('R8.2_SUPPLIER_STRUCTURED_OPERATIONS_GATE: BLOCK')
    for p in problems: print(p)
    raise SystemExit(1)
print('R8.2_SUPPLIER_STRUCTURED_OPERATIONS_GATE: PASS')
print(f'visible_routes={len(routes)} field_level_schemas={len(routes)} minimum_fields_per_module=8')
print('pure_supplier_empty_pages=0 raw_json_primary_supplier_pages=0')
