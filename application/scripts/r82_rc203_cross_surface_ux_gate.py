#!/usr/bin/env python3
from pathlib import Path
import json,re,sys,subprocess
ROOT=Path(__file__).resolve().parents[1]
errors=[]
consumer=(ROOT/'frontend/consumer/app.js').read_text(encoding='utf-8')
hosted=(ROOT/'frontend/consumer/hosted-direct.js').read_text(encoding='utf-8')
shared=(ROOT/'frontend/shared/app.js').read_text(encoding='utf-8')
admin=(ROOT/'frontend/admin/admin-ux.js').read_text(encoding='utf-8')
supplier=(ROOT/'frontend/supplier/config.js').read_text(encoding='utf-8')
css=(ROOT/'frontend/shared/styles.css').read_text(encoding='utf-8')+(ROOT/'frontend/consumer/styles.css').read_text(encoding='utf-8')
manifest=json.loads((ROOT/'CURRENT_RELEASE_MANIFEST.json').read_text(encoding='utf-8'))
# Consumer: no browser-native engineering dialogs
for name,text in [('consumer',consumer),('hosted_direct',hosted),('shared_console',shared)]:
    if re.search(r'\b(?:prompt|confirm|alert)\s*\(',text): errors.append('NATIVE_DIALOG_REMAINS:'+name)
for token in ['uxSheet','uxConfirm','aria-modal','处理中…']:
    if token not in consumer: errors.append('CONSUMER_UX_SHEET_MISSING:'+token)
for token in ['hd-sheet-backdrop','showHdNotice']:
    if token not in hosted and token not in (ROOT/'frontend/consumer/direct.html').read_text(encoding='utf-8'): errors.append('HOSTED_DIRECT_UX_MISSING:'+token)
# Admin: exactly three primary mental spaces
m=re.search(r"const main=\[(.*?)\];",admin,re.S)
if not m: errors.append('ADMIN_PRIMARY_NAV_BLOCK_MISSING')
else:
    labels=re.findall(r"label:'([^']+)'",m.group(1))
    if labels!=['运营','异常中心','治理后台']: errors.append('ADMIN_PRIMARY_NAV_NOT_THREE_SPACES:'+repr(labels))
for token in ['adminOperationsHub','adminExceptionCenter','adminGovernanceHub']:
    if token not in shared: errors.append('ADMIN_HUB_HANDLER_MISSING:'+token)
# Partner: task-oriented 7 primary entries and rights placement preserved
m2=re.search(r"nav:\[(.*?)\],hiddenNav:\[",supplier,re.S)
expected=['经营中心','订单与履约','促销与权益','经营数据','财务','业务管理','异常中心']
if not m2: errors.append('PARTNER_PRIMARY_NAV_MISSING')
else:
    labels=re.findall(r"label:'([^']+)'",m2.group(1))
    if labels!=expected: errors.append('PARTNER_PRIMARY_NAV_NOT_TASK_ORIENTED:'+repr(labels))
for token in ['员工优价 / 业主权益','Friends & Family','促销与权益']:
    if token not in supplier and token not in shared: errors.append('PARTNER_RIGHTS_BOUNDARY_MISSING:'+token)
# Cross-surface accessibility/minimum interaction states
for token in [':focus-visible','prefers-reduced-motion','min-height:44px']:
    if token not in css: errors.append('ACCESSIBILITY_BASELINE_MISSING:'+token)
# Cache exact current token on three surfaces
for rel in ['frontend/consumer/index.html','frontend/supplier/index.html','frontend/admin/index.html']:
    if '20260825-rc20.3' not in (ROOT/rel).read_text(encoding='utf-8'): errors.append('CACHE_TOKEN_NOT_RC203:'+rel)
# Preserve six A verticals and no B
v=manifest.get('rc20_2',{}).get('vertical_classification',{})
for name in ['HOTEL','FLIGHT','RAIL','RIDE','RENTAL','ATTRACTION']:
    if v.get(name)!='A': errors.append('VERTICAL_NOT_A:'+name)
if manifest.get('rc20_2',{}).get('open_b_class_verticals') not in ([],None): errors.append('B_CLASS_REOPENED')
if errors:
    print('R8.2_RC20_3_CROSS_SURFACE_UX_GATE: BLOCK')
    for e in errors: print(e)
    sys.exit(1)
for rel in ['frontend/consumer/app.js','frontend/consumer/hosted-direct.js','frontend/admin/admin-ux.js','frontend/shared/app.js']:
    r=subprocess.run(['node','--check',str(ROOT/rel)])
    if r.returncode: sys.exit(r.returncode)
print('verticals=HOTEL:A,FLIGHT:A,RAIL:A,RIDE:A,RENTAL:A,ATTRACTION:A')
print('consumer_ux=A_ENGINEERING')
print('partner_ux=A_ENGINEERING_REAL_DEVICE_EVIDENCE_PENDING')
print('admin_ux=A_ENGINEERING')
print('open_b_or_bux=0_ENGINEERING')
print('R8.2_RC20_3_CROSS_SURFACE_UX_GATE: PASS')
