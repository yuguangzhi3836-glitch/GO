#!/usr/bin/env python3
"""Record measured flight/finance changes relative to the durable DEPTH04 ZIP."""
import difflib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile
from record_depth04_evidence import digest,write

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'verification/current_build/depth05'
OLD=ROOT/'deliverables/GO_CP11_DEPTH_04_VAULT_HARDENING_WORK_20260907.zip'
OLD_SHA='0ada7772c864651a5bd15e689e412eb531d52868a2457efef97d11561660fd97'

def main():
    if digest(OLD.read_bytes())!=OLD_SHA:raise ValueError('DEPTH04_BASELINE_CHANGED')
    tree=ET.parse(OUT/'full_regression.xml');suites=list(tree.getroot().iter('testsuite'))
    totals={key:sum(int(s.get(key,'0')) for s in suites) for key in ['tests','failures','errors','skipped']}
    totals['passed']=totals['tests']-totals['failures']-totals['errors']-totals['skipped']
    totals['seconds']=round(sum(float(s.get('time','0')) for s in suites),3)
    tap=(OUT/'frontend.tap').read_text();matches=re.findall(r'(?:ℹ|#) pass (\d+)',tap)
    if not matches:raise ValueError('FRONTEND_RESULT_UNRECOGNIZED')
    syntax=json.loads((OUT/'javascript_syntax.json').read_text())
    immutable=json.loads((OUT/'immutable_baseline.json').read_text())
    previous=json.loads((ROOT/'verification/current_build/depth04/CURRENT_BUILD_STATUS.json').read_text())
    status={**previous,'build':'CP11_DEPTH_05_FLIGHT_PARTY_REFUND','python':totals,
        'baseline':{**previous['baseline'],'depth04_work_sha256':OLD_SHA},
        'frontend':{'logic_passed':int(matches[-1]),'syntax_files_passed':sum(x['passed'] for x in syntax['files']),
            'node':syntax['node'],'browser_visual_accepted':False,'frozen_node_22_22_certified':False},
        'immutable':{k:{p:v[p] for p in ['count','all_match']} for k,v in immutable.items()},
        'flight_scope':'1–9 adults; per-leg server prices/taxes/refund fees, explicit distinct vault travelers, one simulated ticket per traveler per leg. Child/infant fares, partial-leg changes/refunds and protected connections remain unaccepted.',
        'refund_scope':'Whole-flight refund including captured change differences, original-capture allocation, durable pending claim and replay after partial failure. Local simulator only.',
        'money_scope':'Idempotency binds intent/type/amount/parent; released authorization cannot be captured; captured authorization cannot be released; SQLite concurrent refund budget tested. Six PostgreSQL tests remain skipped.'}
    write(OUT/'CURRENT_BUILD_STATUS.json',status)
    roots={'src','frontend','tests','tests_frontend','scripts'}
    current={p.relative_to(ROOT).as_posix():p for name in roots for p in (ROOT/name).rglob('*')
        if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'}}
    changes=[];patch=[]
    with zipfile.ZipFile(OLD) as z:
        old_names={n for n in z.namelist() if n.split('/')[0] in roots and not n.endswith('/')}
        for name in sorted(set(current)|old_names):
            before=z.read(name) if name in old_names else b'';after=current[name].read_bytes() if name in current else b''
            if before==after:continue
            changes.append({'path':name,'status':'MODIFIED' if name in old_names and name in current else 'ADDED' if name in current else 'DELETED',
                'before_sha256':digest(before) if name in old_names else None,'after_sha256':digest(after) if name in current else None})
            try:patch.extend(difflib.unified_diff(before.decode().splitlines(True),after.decode().splitlines(True),fromfile='DEPTH04/'+name,tofile='DEPTH05/'+name))
            except UnicodeDecodeError:pass
    write(ROOT/'acceptance/DEPTH05_SOURCE_CHANGES.json',{'baseline_work_sha256':OLD_SHA,'changes':changes})
    (ROOT/'acceptance/DEPTH05_SOURCE_CHANGES.patch').write_text(''.join(patch))
    register=json.loads((ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json').read_text())
    for requirement in register['requirements']:
        if requirement['id'] in {'FLIGHT-01','ALL-02','PAY-01'}:
            requirement['status']='LOCAL_PARTY_AND_ORIGINAL_REFUND_TESTED_EXTERNAL_ACCEPTANCE_PENDING'
            requirement['current_evidence']=['verification/current_build/depth05/full_regression.xml','verification/current_build/depth05/frontend.tap']
            requirement['fully_accepted']=False
            requirement['scope_note']=status['flight_scope'] if requirement['id']=='FLIGHT-01' else status['refund_scope'] if requirement['id']=='ALL-02' else status['money_scope']
    register['current_build_report']='verification/current_build/depth05/CURRENT_BUILD_STATUS.json'
    write(ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json',register)
    print(json.dumps({'python':totals,'frontend_passed':int(matches[-1]),'changed_files':len(changes)},ensure_ascii=False))

if __name__=='__main__':main()
