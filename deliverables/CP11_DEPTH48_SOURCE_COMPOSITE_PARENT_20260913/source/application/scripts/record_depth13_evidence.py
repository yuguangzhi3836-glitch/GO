#!/usr/bin/env python3
"""Record measured catalog fare evidence against the saved DEPTH12 archive."""
import difflib
import json
import re
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET
from record_depth04_evidence import digest, write
from resolve_depth13_regression import main as resolve_regression

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'verification/current_build/depth13'
OLD=ROOT/'deliverables/GO_CP11_DEPTH_12_CATALOG_STAY_CREDIT_WORK_20260907.zip'
OLD_SHA='7fa510f3e9e9a5cbf7140fbe5838e276c8fe0e6ab46cfc3517cf3b957c4829bc'


def main():
    if digest(OLD.read_bytes())!=OLD_SHA:raise ValueError('DEPTH12_BASELINE_CHANGED')
    suites=list(ET.parse(OUT/'full_regression.xml').getroot().iter('testsuite'))
    if not suites:raise ValueError('CURRENT_FULL_REGRESSION_REQUIRED')
    resolve_regression()
    resolution=json.loads((OUT/'regression_resolution.json').read_text())
    totals={**resolution['effective_unique_results'],'basis':resolution['basis'],'one_clean_full_run':False,
        'full_run_observed_failures':resolution['full_run']['failures'],
        'resolution_evidence':'verification/current_build/depth13/regression_resolution.json'}
    new_cases=[c for s in suites for c in s.findall('testcase') if 'test_depth13_' in c.get('classname','')]
    tap=(OUT/'frontend.tap').read_text();matches=re.findall(r'(?:ℹ|#) pass (\d+)',tap)
    if not matches or not re.search(r'(?:ℹ|#) fail 0\b',tap):raise ValueError('FRONTEND_RESULT_NOT_PASSING')
    syntax=json.loads((OUT/'javascript_syntax.json').read_text())
    immutable=json.loads((OUT/'immutable_baseline.json').read_text())
    if not all(x['passed'] for x in syntax['files']) or not all(x['all_match'] for x in immutable.values()):raise ValueError('BASELINE_OR_SYNTAX_FAILED')
    upgrade=json.loads((OUT/'upgrade_12_to_13.json').read_text())
    if not all(upgrade[k] for k in ['original_credit_value_preserved','original_expiry_preserved','value_ledger_checked']) or upgrade['original_booking_snapshot_fabricated']:raise ValueError('CROSS_VERSION_UPGRADE_NOT_VERIFIED')
    previous=json.loads((ROOT/'verification/current_build/depth12/CURRENT_BUILD_STATUS.json').read_text())
    status={**previous,'build':'CP11_DEPTH_13_CATALOG_FARE_SNAPSHOT','python':totals,
        'baseline':{**previous['baseline'],'depth12_work_sha256':OLD_SHA},
        'frontend':{'logic_passed':int(matches[-1]),'syntax_files_passed':len(syntax['files']),'node':syntax['node'],
            'browser_visual_accepted':False,'frozen_node_22_22_certified':False},
        'immutable':{k:{p:v[p] for p in ['count','all_match']} for k,v in immutable.items()},
        'migrations':{'current_head':'0121_catalog_fare_snapshot','original_files_unchanged':114,
            'added_files':previous['migrations']['added_files']+['alembic/versions/0121_catalog_fare_snapshot.py'],
            'roundtrip_evidence':previous['migrations']['roundtrip_evidence']+['tests/test_depth13_migration.py']},
        'engineering_gaps':['COMPLETE_MASTER_REQUIREMENT_DECOMPOSITION','ALL_VERTICAL_ADVANCED_AFTER_SALES_E2E',
            'CATALOG_CASH_AFTER_SALES_MONEY_RECOVERY_AND_ADVANCED_FLOWS','HISTORICAL_ORDER_AND_CREDIT_PROVENANCE_RECONCILIATION',
            'COMPLETE_SUPPLIER_SELF_SERVICE_AND_GUEST_LIABILITY_TERMS','RENTAL_SUPPLIER_POLICY_AND_DEPOSIT_SETTLEMENT',
            'EXTERNAL_PERSONAL_SOURCE_CONNECTORS','14_CELL_DURABLE_EXECUTION_AND_RECOVERY']}
    status['catalog_fare_scope']=(
        'Supplier owner/admin/revenue-manager permission and supplier ownership govern explicit publication of immutable '
        'property/supplier/connector/fare-family/currency rules. Current-version checks prevent conflicting publication; quoted '
        'terms remain fixed until their quote expires. Signed customer order creation requires explicit current offer-rule hash '
        'acceptance before profile release; order, acceptance snapshot and evidence commit together. Local anonymous fixtures '
        'are separately marked ISOLATED_FIXTURE, never as a human acceptance. Original snapshot controls ordinary cancellation '
        'and change fees and new credit conversion; timezones, check-in times, cooling windows, tier boundaries and exact integer '
        'basis-point fees are tested. New catalog credit cancellation inherits these frozen terms; actual saved DEPTH12 credit '
        'survives migration, redemption and cancellation without invented original booking snapshots. Mobile conversion now '
        'requires the same quoted consent and replay identity. Legacy supplier direct cancel/change execution no longer bypasses '
        'independent fault review or customer consent; the supplier workbench uses the existing independently reviewed inability-to-fulfill flow. '
        'Cash cancellation with multiple changed-payment roots, unknown changes/cancels, partial fulfillment, no-show execution '
        'and customer-authorized supplier-assisted amendments remain open. Source rules are supplier-declared or explicit simulation, '
        'not represented as externally verified hotel mandates.')
    status['catalog_stay_credit_scope']=previous['catalog_stay_credit_scope']+(
        ' DEPTH13 new original bookings now retain a published accepted rule snapshot. Its explicit supported retained-value policy '
        'includes net confirmed cash and paid change fees; alternative retained-fee policies are not implemented. Historical DEPTH12 '
        'contracts keep their originally accepted conversion terms, without backfilling original booking acceptance.')
    status['validation_scope']=(f'The full cumulative run includes {len(new_cases)} DEPTH13 backend tests. Two legacy event-contract failures are retained; all four tests in their two modules are rerun after adding the new acceptance event assertions. Runtime, frontend, migrations and other test fingerprints are unchanged; this is not represented as one clean full run. Targeted results overlap '
        'and are not added. The separate actual DEPTH12-to-13 upgrade replay is identified independently. Frontend logic, syntax and '
        'ASGI cold-start do not establish browser visual acceptance. Historical DEPTH12 failure and scoped fixture retest remain preserved.')
    status['historical_test_change_depth13']=(
        'Authenticated existing hotel test entry points now submit the current prebook rule hash and explicit confirmation. '
        'Three DEPTH12 tests publish new supplier versions or seed a one-day rule before booking instead of editing the obsolete '
        'mutable rule row. Their immutable expiry/fee and restoration assertions are preserved. Mobile booking fixture dates become '
        'future-relative so ordinary cancellation tests do not use an already-started stay; assertions remain unchanged. Golden-path and persistence tests now assert the new acceptance event in addition to the original six transaction events, including its snapshot hash and identical outbox payload.')
    status['upgrade_replay']='verification/current_build/depth13/upgrade_12_to_13.json'
    status['release_gate']=status['FINAL_RELEASE_GATE']='HOLD'
    status['engineering_complete']=status['deployed']=False
    write(OUT/'CURRENT_BUILD_STATUS.json',status)
    roots={'src','frontend','tests','tests_frontend','scripts','alembic'}
    current={p.relative_to(ROOT).as_posix():p for name in roots for p in (ROOT/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'}}
    changes=[];patch=[]
    with zipfile.ZipFile(OLD) as z:
        names={n for n in z.namelist() if n.split('/')[0] in roots and not n.endswith('/')}
        for name in sorted(set(current)|names):
            before=z.read(name) if name in names else b'';after=current[name].read_bytes() if name in current else b''
            if before==after:continue
            changes.append({'path':name,'status':'MODIFIED' if name in names and name in current else 'ADDED' if name in current else 'DELETED',
                'before_sha256':digest(before) if name in names else None,'after_sha256':digest(after) if name in current else None})
            try:patch.extend(difflib.unified_diff(before.decode().splitlines(True),after.decode().splitlines(True),fromfile='DEPTH12/'+name,tofile='DEPTH13/'+name))
            except UnicodeDecodeError:pass
    write(ROOT/'acceptance/DEPTH13_SOURCE_CHANGES.json',{'baseline_work_sha256':OLD_SHA,'changes':changes})
    (ROOT/'acceptance/DEPTH13_SOURCE_CHANGES.patch').write_text(''.join(patch))
    register=json.loads((ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json').read_text())
    for req in register['requirements']:
        if req['id']=='HOTEL-03':req.update(status='LOCAL_CATALOG_PUBLISHED_RULE_AND_ORDER_SNAPSHOT_TESTED',fully_accepted=False,
            current_evidence=['verification/current_build/depth13/regression_resolution.json','verification/current_build/depth13/upgrade_12_to_13.json'],scope_note=status['catalog_fare_scope'])
    register['current_build_report']='verification/current_build/depth13/CURRENT_BUILD_STATUS.json'
    write(ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json',register)
    print(json.dumps({'python':totals,'new_backend_tests':len(new_cases),'frontend_passed':int(matches[-1]),'changed_files':len(changes)},ensure_ascii=False))


if __name__=='__main__':main()
