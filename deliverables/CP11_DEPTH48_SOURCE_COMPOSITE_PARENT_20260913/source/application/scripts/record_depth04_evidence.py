#!/usr/bin/env python3
"""Record measured DEPTH04 results and source differences without promoting release."""
import difflib
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'verification/current_build/depth04'
OLD=ROOT/'deliverables/GO_CP11_DEPTH_03_MASTER_ALIGNMENT_WORK_20260907.zip'
OLD_SHA='f24c5ccadcb7f762a83f16a372151b30ecda9ab50882c2e5e55052614cc5d791'

def digest(data):return hashlib.sha256(data).hexdigest()
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

def main():
    if digest(OLD.read_bytes())!=OLD_SHA:raise ValueError('DEPTH03_BASELINE_CHANGED')
    tree=ET.parse(OUT/'full_regression.xml');suites=list(tree.getroot().iter('testsuite'))
    totals={key:sum(int(s.get(key,'0')) for s in suites) for key in ['tests','failures','errors','skipped']}
    totals['passed']=totals['tests']-totals['failures']-totals['errors']-totals['skipped']
    totals['seconds']=round(sum(float(s.get('time','0')) for s in suites),3)
    tap=(OUT/'frontend.tap').read_text();matches=re.findall(r'(?:ℹ|#) pass (\d+)',tap)
    if not matches:raise ValueError('FRONTEND_RESULT_UNRECOGNIZED')
    syntax=json.loads((OUT/'javascript_syntax.json').read_text())
    immutable=json.loads((OUT/'immutable_baseline.json').read_text())
    status={'build':'CP11_DEPTH_04_VAULT_HARDENING','FINAL_RELEASE_GATE':'HOLD','engineering_complete':False,'deployed':False,
        'baseline':{'parent_sha256':'8fccf16481e886f0e2925b727be3a35be41a53a8334bf95c7047e26176f746eb',
            'master_sha256':'877aa1d093d675155d20c4b6e424b70454ee89c9969f52810abfd5086d6db66d','depth03_work_sha256':OLD_SHA},
        'python':totals,'frontend':{'logic_passed':int(matches[-1]),'syntax_files_passed':sum(x['passed'] for x in syntax['files']),
            'node':syntax['node'],'browser_visual_accepted':False,'frozen_node_22_22_certified':False},
        'immutable':{k:{p:v[p] for p in ['count','all_match']} for k,v in immutable.items()},
        'blocked_gates':['ISOLATED_POSTGRESQL_6_TESTS','FROZEN_NODE_22_22','SUPPORTED_BROWSER_PREVIEW','OFFICIAL_ROOM_PHOTOS_UNAVAILABLE'],
        'engineering_gaps':['COMPLETE_MASTER_REQUIREMENT_DECOMPOSITION','ALL_VERTICAL_ADVANCED_AFTER_SALES_E2E',
            'OFFICIAL_HOTEL_PAYMENT_PATH_UNIFICATION','EXTERNAL_PERSONAL_SOURCE_CONNECTORS','14_CELL_DURABLE_EXECUTION_AND_RECOVERY'],
        'vault_scope':'Owner edits, conflict review, source fingerprint controls, permission revocation, deletion and export tested locally. No external OAuth connector or browser acceptance claimed.',
        'live_evidence_pending':['AUTHORIZED_SUPPLIER','LICENSED_PSP','SIGNED_CALLBACKS','STATEMENT_RECONCILIATION','REAL_DEVICE_E2E']}
    write(OUT/'CURRENT_BUILD_STATUS.json',status)
    roots={'src','frontend','tests','tests_frontend','scripts'}
    current={p.relative_to(ROOT).as_posix():p for name in roots for p in (ROOT/name).rglob('*')
        if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'}}
    changes=[];patch=[]
    with zipfile.ZipFile(OLD) as z:
        old_names={n for n in z.namelist() if n.split('/')[0] in roots and not n.endswith('/')}
        for name in sorted(set(current)|old_names):
            before=z.read(name) if name in old_names else b''
            after=current[name].read_bytes() if name in current else b''
            if before==after:continue
            changes.append({'path':name,'status':'MODIFIED' if name in old_names and name in current else 'ADDED' if name in current else 'DELETED',
                'before_sha256':digest(before) if name in old_names else None,'after_sha256':digest(after) if name in current else None})
            try:patch.extend(difflib.unified_diff(before.decode().splitlines(True),after.decode().splitlines(True),fromfile='DEPTH03/'+name,tofile='DEPTH04/'+name))
            except UnicodeDecodeError:pass
    write(ROOT/'acceptance/DEPTH04_SOURCE_CHANGES.json',{'baseline_work_sha256':OLD_SHA,'changes':changes})
    (ROOT/'acceptance/DEPTH04_SOURCE_CHANGES.patch').write_text(''.join(patch))
    register=json.loads((ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json').read_text())
    cases=[c.get('name') for c in tree.getroot().iter('testcase') if c.get('classname','').endswith('test_depth04_vault_management')]
    for requirement in register['requirements']:
        if requirement['id'] in {'VAULT-01','VAULT-02','VAULT-03','VAULT-04'}:
            requirement['status']='LOCAL_FUNCTIONAL_TESTED_BROWSER_ACCEPTANCE_PENDING'
            requirement['current_evidence']=['verification/current_build/depth04/full_regression.xml','verification/current_build/depth04/frontend.tap']
            requirement['targeted_cases']=cases
            requirement['fully_accepted']=False
            if requirement['id']=='VAULT-03':
                requirement['implementation']='frontend/consumer/vault-manager.js; src/go_hotel/services/personal_vault_management.py'
                requirement['scope_note']='Source controls apply to this imported source fingerprint, not an external OAuth account connection.'
    register['current_build_report']='verification/current_build/depth04/CURRENT_BUILD_STATUS.json'
    write(ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json',register)
    print(json.dumps({'python':totals,'frontend_passed':status['frontend']['logic_passed'],'changed_files':len(changes)},ensure_ascii=False))

if __name__=='__main__':main()
