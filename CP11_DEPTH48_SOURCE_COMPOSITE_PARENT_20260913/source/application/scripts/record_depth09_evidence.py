#!/usr/bin/env python3
"""Record funded hotel credit and measured validation relative to durable DEPTH08."""
import difflib,json,re,zipfile
from pathlib import Path
import xml.etree.ElementTree as ET
from record_depth04_evidence import digest,write

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'verification/current_build/depth09'
OLD=ROOT/'deliverables/GO_CP11_DEPTH_08_HOTEL_FARE_WORK_20260907.zip'
OLD_SHA='3f49de79c85c78fa252bc13e458e30f468663c9373e062610cbed6aaeb5d3a08'


def main():
    if digest(OLD.read_bytes())!=OLD_SHA:raise ValueError('DEPTH08_BASELINE_CHANGED')
    tree=ET.parse(OUT/'full_regression.xml');suites=list(tree.getroot().iter('testsuite'))
    totals={k:sum(int(s.get(k,'0')) for s in suites) for k in ['tests','failures','errors','skipped']}
    if totals['failures'] or totals['errors']:raise ValueError('CURRENT_REGRESSION_NOT_PASSING')
    totals['passed']=totals['tests']-totals['failures']-totals['errors']-totals['skipped']
    totals['seconds']=round(sum(float(s.get('time','0')) for s in suites),3)
    tap=(OUT/'frontend.tap').read_text();matches=re.findall(r'(?:ℹ|#) pass (\d+)',tap)
    if not matches:raise ValueError('FRONTEND_RESULT_UNRECOGNIZED')
    if not re.search(r'(?:ℹ|#) fail 0\b',tap):raise ValueError('FRONTEND_FAILURES_PRESENT')
    syntax=json.loads((OUT/'javascript_syntax.json').read_text())
    immutable=json.loads((OUT/'immutable_baseline.json').read_text())
    if not all(v['all_match'] for v in immutable.values()):raise ValueError('IMMUTABLE_BASELINE_CHANGED')
    if not all(v['passed'] for v in syntax['files']):raise ValueError('JAVASCRIPT_SYNTAX_FAILED')
    previous=json.loads((ROOT/'verification/current_build/depth08/CURRENT_BUILD_STATUS.json').read_text())
    master=ROOT/'GO_ULTIMATE_MASTER_PLAN_V7.0_2026-08-31_CONSTITUTIONAL_LEGAL_SYNC_MASTER.pdf'
    if digest(master.read_bytes())!=previous['baseline']['master_sha256']:raise ValueError('MASTER_CHANGED')
    status={**previous,'build':'CP11_DEPTH_09_HOTEL_STAY_CREDIT','python':totals,
        'baseline':{**previous['baseline'],'depth08_work_sha256':OLD_SHA},
        'frontend':{'logic_passed':int(matches[-1]),'syntax_files_passed':sum(x['passed'] for x in syntax['files']),
            'node':syntax['node'],'browser_visual_accepted':False,'frozen_node_22_22_certified':False},
        'immutable':{k:{p:v[p] for p in ['count','all_match']} for k,v in immutable.items()},
        'migrations':{'current_head':'0117_hosted_stay_credit','original_files_unchanged':114,
            'added_files':['alembic/versions/0115_rental_change_settlement.py','alembic/versions/0116_hosted_fare_snapshot.py','alembic/versions/0117_hosted_stay_credit.py'],
            'roundtrip_evidence':['tests/test_depth06_migration.py','tests/test_depth08_migration.py','tests/test_depth09_migration.py']},
        'rental_scope':'CNY isolated fixed-day pricing, pickup/return reprice quote, amount consent, durable change/refund plans; repeated positive/negative changes and original remaining-capture refunds, partial failure recovery and SQLite concurrency tested. Supplier dynamic pricing, close-to-pickup penalties and deposit settlement remain unaccepted.',
        'direct_hotel_scope':'Funded property-only StayCredit conversion, new reservation redemption with higher-price cash shortfall and lower-price forfeiture, source/value conservation ledger and original expiry. Cancellation/no-show/partial fulfillment restore only unused prepaid value under explicit supplier snapshot terms. Independent cash refunds reserve exact original cash/credit captures; mixed-source failures are atomic and retryable. Customer conversion/redemption dialogs show current quoted rules and require current named traveler/purpose consent. SQLite concurrency, migration 0117 and cumulative regression tested. Supplier disruption compensation, complete supplier UI and advanced other-vertical flows remain open; no PostgreSQL or browser visual acceptance claimed.',
        'engineering_gaps':['COMPLETE_MASTER_REQUIREMENT_DECOMPOSITION','ALL_VERTICAL_ADVANCED_AFTER_SALES_E2E',
            'DIRECT_HOTEL_SUPPLIER_DISRUPTION_AND_SUPPLIER_UI','RENTAL_SUPPLIER_POLICY_AND_DEPOSIT_SETTLEMENT',
            'EXTERNAL_PERSONAL_SOURCE_CONNECTORS','14_CELL_DURABLE_EXECUTION_AND_RECOVERY'],
        'acceptance_separation':'Live provider evidence is a separate deployment obligation; its absence does not waive isolated engineering acceptance.'}
    final=ET.parse(OUT/'credit_final.xml');suites=list(final.getroot().iter('testsuite'))
    post={k:sum(int(s.get(k,'0')) for s in suites) for k in ['tests','failures','errors','skipped']}
    if post['failures'] or post['errors'] or post['skipped']:raise ValueError('FINAL_CREDIT_VALIDATION_NOT_PASSING')
    post['passed']=post['tests'];post['seconds']=round(sum(float(s.get('time','0')) for s in suites),3)
    status['post_regression_credit_validation']=post
    status['validation_scope']='Full suite precedes the final unused-credit refund-expiry boundary clarification. All credit tests, including two added expiry/refund cases, and all frontend logic tests passed after that change. No claim that the two new cases were in the earlier full run.'
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
            try:patch.extend(difflib.unified_diff(before.decode().splitlines(True),after.decode().splitlines(True),fromfile='DEPTH08/'+name,tofile='DEPTH09/'+name))
            except UnicodeDecodeError:pass
    write(ROOT/'acceptance/DEPTH09_SOURCE_CHANGES.json',{'baseline_work_sha256':OLD_SHA,'changes':changes})
    (ROOT/'acceptance/DEPTH09_SOURCE_CHANGES.patch').write_text(''.join(patch))
    register=json.loads((ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json').read_text())
    for r in register['requirements']:
        if r['id'] in {'ALL-02','PAY-01','HOTEL-02','HOTEL-03'}:
            r['status']='LOCAL_PROPERTY_CREDIT_VALUE_AND_ORIGINAL_REFUND_TESTED'
            r['current_evidence']=['verification/current_build/depth09/full_regression.xml','verification/current_build/depth09/frontend.tap']
            r['fully_accepted']=False
            r['scope_note']=status['direct_hotel_scope']
    register['current_build_report']='verification/current_build/depth09/CURRENT_BUILD_STATUS.json'
    write(ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json',register)
    print(json.dumps({'python':totals,'frontend_passed':int(matches[-1]),'changed_files':len(changes)},ensure_ascii=False))

if __name__=='__main__':main()
