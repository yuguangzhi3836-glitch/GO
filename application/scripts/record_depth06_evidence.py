#!/usr/bin/env python3
"""Record measured rental/direct-hotel changes relative to the durable DEPTH05."""
import difflib,json,re,zipfile
from pathlib import Path
import xml.etree.ElementTree as ET
from record_depth04_evidence import digest,write

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'verification/current_build/depth06'
OLD=ROOT/'deliverables/GO_CP11_DEPTH_05_FLIGHT_PARTY_REFUND_WORK_20260907.zip'
OLD_SHA='ccfe6da4f4872b1f6ba1a34df8cadef25fad86454f87069685c40fc8ebd10506'


def main():
    if digest(OLD.read_bytes())!=OLD_SHA:raise ValueError('DEPTH05_BASELINE_CHANGED')
    tree=ET.parse(OUT/'full_regression.xml');suites=list(tree.getroot().iter('testsuite'))
    totals={k:sum(int(s.get(k,'0')) for s in suites) for k in ['tests','failures','errors','skipped']}
    totals['passed']=totals['tests']-totals['failures']-totals['errors']-totals['skipped']
    totals['seconds']=round(sum(float(s.get('time','0')) for s in suites),3)
    tap=(OUT/'frontend.tap').read_text();matches=re.findall(r'(?:ℹ|#) pass (\d+)',tap)
    if not matches:raise ValueError('FRONTEND_RESULT_UNRECOGNIZED')
    if not re.search(r'(?:ℹ|#) fail 0\b',tap):raise ValueError('FRONTEND_FAILURES_PRESENT')
    syntax=json.loads((OUT/'javascript_syntax.json').read_text())
    immutable=json.loads((OUT/'immutable_baseline.json').read_text())
    previous=json.loads((ROOT/'verification/current_build/depth05/CURRENT_BUILD_STATUS.json').read_text())
    master=ROOT/'GO_ULTIMATE_MASTER_PLAN_V7.0_2026-08-31_CONSTITUTIONAL_LEGAL_SYNC_MASTER.pdf'
    if digest(master.read_bytes())!=previous['baseline']['master_sha256']:raise ValueError('MASTER_CHANGED')
    status={**previous,'build':'CP11_DEPTH_06_RENTAL_DIRECT_SETTLEMENT','python':totals,
        'baseline':{**previous['baseline'],'depth05_work_sha256':OLD_SHA},
        'frontend':{'logic_passed':int(matches[-1]),'syntax_files_passed':sum(x['passed'] for x in syntax['files']),
            'node':syntax['node'],'browser_visual_accepted':False,'frozen_node_22_22_certified':False},
        'immutable':{k:{p:v[p] for p in ['count','all_match']} for k,v in immutable.items()},
        'migrations':{'current_head':'0115_rental_change_settlement','original_files_unchanged':114,
            'added_files':['alembic/versions/0115_rental_change_settlement.py'],
            'roundtrip_evidence':'tests.test_depth06_migration::test_rental_settlement_migration_roundtrip_preserves_existing_refunds'},
        'rental_scope':'CNY isolated fixed-day pricing, pickup/return reprice quote, amount consent, durable change/refund plans; repeated positive/negative changes and original remaining-capture refunds, partial failure recovery and SQLite concurrency tested. Supplier dynamic pricing, close-to-pickup penalties and deposit settlement remain unaccepted.',
        'direct_hotel_scope':'Official offer and dated inventory retained; explicit amount-bound simulated authorization, owner recovery, atomic pending cancellation/expiry release, unknown funds keep stock, fulfillment-before-contract-capture and capture replay tested. Shared money graph, full stay lifecycle, post-confirmation cancellation policy and bank settlement remain unaccepted.',
        'engineering_gaps':['COMPLETE_MASTER_REQUIREMENT_DECOMPOSITION','ALL_VERTICAL_ADVANCED_AFTER_SALES_E2E',
            'DIRECT_HOTEL_SHARED_MONEY_GRAPH_AND_STAY_SETTLEMENT','RENTAL_SUPPLIER_POLICY_AND_DEPOSIT_SETTLEMENT',
            'EXTERNAL_PERSONAL_SOURCE_CONNECTORS','14_CELL_DURABLE_EXECUTION_AND_RECOVERY'],
        'acceptance_separation':'Live provider evidence is a separate deployment obligation; its absence does not waive isolated engineering acceptance.'}
    write(OUT/'CURRENT_BUILD_STATUS.json',status)
    roots={'src','frontend','tests','tests_frontend','scripts','alembic'}
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
            try:patch.extend(difflib.unified_diff(before.decode().splitlines(True),after.decode().splitlines(True),fromfile='DEPTH05/'+name,tofile='DEPTH06/'+name))
            except UnicodeDecodeError:pass
    write(ROOT/'acceptance/DEPTH06_SOURCE_CHANGES.json',{'baseline_work_sha256':OLD_SHA,'changes':changes})
    (ROOT/'acceptance/DEPTH06_SOURCE_CHANGES.patch').write_text(''.join(patch))
    register=json.loads((ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json').read_text())
    for r in register['requirements']:
        if r['id'] in {'RENTAL-01','ALL-02','PAY-01','HOTEL-02'}:
            r['status']='LOCAL_RENTAL_SETTLEMENT_AND_DIRECT_AUTHORIZATION_TESTED'
            r['current_evidence']=['verification/current_build/depth06/full_regression.xml','verification/current_build/depth06/frontend.tap']
            r['fully_accepted']=False
            r['scope_note']=status['rental_scope'] if r['id']=='RENTAL-01' else status['direct_hotel_scope'] if r['id']=='HOTEL-02' else 'Rental original-capture refunds and direct-hotel contract authorization/release; see CURRENT_BUILD_STATUS scope and gaps.'
    register['current_build_report']='verification/current_build/depth06/CURRENT_BUILD_STATUS.json'
    write(ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json',register)
    print(json.dumps({'python':totals,'frontend_passed':int(matches[-1]),'changed_files':len(changes)},ensure_ascii=False))

if __name__=='__main__':main()
