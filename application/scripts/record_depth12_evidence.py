#!/usr/bin/env python3
"""Record measured catalog credit results against the immutable DEPTH11 archive."""
import difflib
import json
import re
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET
from record_depth04_evidence import digest, write
from resolve_depth12_regression import main as resolve_regression

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'verification/current_build/depth12'
OLD = ROOT / 'deliverables/GO_CP11_DEPTH_11_CATALOG_SUPPLIER_REMEDY_WORK_20260907.zip'
OLD_SHA = '651483528688d3bafce0507154d27c084cb4c33191b1e229cbf99451cb224d9b'


def main():
    if digest(OLD.read_bytes()) != OLD_SHA:
        raise ValueError('DEPTH11_BASELINE_CHANGED')
    suites = list(ET.parse(OUT / 'full_regression.xml').getroot().iter('testsuite'))
    if not suites:
        raise ValueError('CURRENT_FULL_REGRESSION_REQUIRED')
    resolve_regression()
    resolution = json.loads((OUT / 'regression_resolution.json').read_text())
    totals = {**resolution['effective_unique_results'], 'basis': resolution['basis'],
        'one_clean_full_run': False, 'full_run_observed_failures': resolution['full_run']['failures'],
        'resolution_evidence': 'verification/current_build/depth12/regression_resolution.json'}
    cases = [c for s in suites for c in s.findall('testcase') if 'test_depth12_' in c.get('classname', '')]
    tap = (OUT / 'frontend.tap').read_text()
    matches = re.findall(r'(?:ℹ|#) pass (\d+)', tap)
    if not matches or not re.search(r'(?:ℹ|#) fail 0\b', tap):
        raise ValueError('FRONTEND_RESULT_NOT_PASSING')
    syntax = json.loads((OUT / 'javascript_syntax.json').read_text())
    immutable = json.loads((OUT / 'immutable_baseline.json').read_text())
    if not all(v['all_match'] for v in immutable.values()):
        raise ValueError('IMMUTABLE_BASELINE_CHANGED')
    if not all(v['passed'] for v in syntax['files']):
        raise ValueError('JAVASCRIPT_SYNTAX_FAILED')
    previous = json.loads((ROOT / 'verification/current_build/depth11/CURRENT_BUILD_STATUS.json').read_text())
    status = {**previous, 'build': 'CP11_DEPTH_12_CATALOG_STAY_CREDIT', 'python': totals,
        'baseline': {**previous['baseline'], 'depth11_work_sha256': OLD_SHA},
        'frontend': {'logic_passed': int(matches[-1]), 'syntax_files_passed': len(syntax['files']),
            'node': syntax['node'], 'browser_visual_accepted': False, 'frozen_node_22_22_certified': False},
        'immutable': {k: {p: v[p] for p in ['count', 'all_match']} for k, v in immutable.items()},
        'migrations': {'current_head': '0120_catalog_stay_credit', 'original_files_unchanged': 114,
            'added_files': previous['migrations']['added_files'] + ['alembic/versions/0120_catalog_stay_credit.py'],
            'roundtrip_evidence': previous['migrations']['roundtrip_evidence'] + ['tests/test_depth12_migration.py']},
        'engineering_gaps': ['COMPLETE_MASTER_REQUIREMENT_DECOMPOSITION', 'ALL_VERTICAL_ADVANCED_AFTER_SALES_E2E',
            'CATALOG_ORIGINAL_BOOKING_PUBLISHED_RULE_SNAPSHOT_AND_ADVANCED_CHANGES',
            'HISTORICAL_CREDIT_PROVENANCE_RECONCILIATION', 'COMPLETE_SUPPLIER_SELF_SERVICE_AND_GUEST_LIABILITY_TERMS',
            'RENTAL_SUPPLIER_POLICY_AND_DEPOSIT_SETTLEMENT', 'EXTERNAL_PERSONAL_SOURCE_CONNECTORS',
            '14_CELL_DURABLE_EXECUTION_AND_RECOVERY']}
    status['money_scope'] = previous['money_scope'] + (
        ' DEPTH12 additionally caps capture/release to their own authorization and refund/compensation to their own capture, '
        'so an action cannot borrow unused budget from another parent movement in the same payment root.')
    status['catalog_stay_credit_scope'] = (
        'New CNY isolated catalog contracts bind actual confirmed original captures less prior refunds, property/account/currency, '
        'a currently accepted conversion quote and immutable expiry of at most 365 days. Source funds are reserved before supplier '
        'cancellation; unknown responses remain query-only. Redemption reserves value once, uses explicit current named traveler '
        'and purpose/field consent, and separates prepaid value from cash-only shortfall authorization/capture. '
        'Higher price requires a bound accepted amount; lower price forfeits the difference without a residual balance. '
        'Customer cancellation preserves accepted conversion-contract tiers, refunds only unused cash supplements and restores only '
        'unused credit with the original expiry; supplier-fault refunds use original applied-credit and supplemental cash captures '
        'without reissuing credit or refunding forfeiture. Atomic failure recovery and repeated use are tested. '
        'Conversion-time accepted rules are not represented as original-booking published FareRuleSnapshots. Original booking '
        'publication/snapshot, retained-value policy for previously consumed change fees, credit-aware date changes, no-show and '
        'partial fulfillment on this catalog path remain open. Historical unproven credit is read-only pending reconciliation.')
    status['catalog_supplier_remedy_scope'] = previous['catalog_supplier_remedy_scope'].replace(
        'Legacy credit redemption orders are explicitly held for value reconciliation, not treated as zero-paid cash orders.',
        'DEPTH12 new funded credit redemptions are reconciled to applied original source captures and cash shortfalls; '
        'historical credit without a proven contract remains held for reconciliation.')
    status['direct_hotel_scope'] = previous['direct_hotel_scope'].replace(
        'legacy credit, complete supplier UI', 'catalog credit is additionally tested within the DEPTH12 scope; complete supplier UI')
    status['supplier_remedy_scope'] = previous['supplier_remedy_scope'].replace(
        'legacy credit value, complete supplier', 'historical credit provenance and advanced credit flows, complete supplier')
    status['validation_scope'] = (
        f'Full run includes {len(cases)} DEPTH12 backend tests. Its single expired-date/old-consent fixture failure is retained in '
        'full_regression.xml; all three tests in that module were rerun after the fixture-only correction. Source fingerprints '
        'prove runtime, frontend, migrations and all other tests are unchanged. Effective unique results replace those three '
        'observations without double counting; this is not represented as one clean full run. Frontend checks verify logic only.')
    status['historical_test_change_depth12'] = (
        'The existing sprint1m credit redemption test now explicitly obtains and accepts conversion/redemption quote hashes; '
        'its property, value and high-price supplement assertions are preserved. Migration-head assertion advances to 0120. '
        'Sprint1x expired fixed stay dates become future fixture dates, with explicit conversion quote acceptance; its refund, '
        'credit and review assertions are preserved and all three module tests are rerun. '
        'Old cash cancellation/change assertions remain in the full suite; their passing does not certify all advanced scenarios.')
    status['release_gate'] = status['FINAL_RELEASE_GATE'] = 'HOLD'
    status['engineering_complete'] = status['deployed'] = False
    write(OUT / 'CURRENT_BUILD_STATUS.json', status)
    roots = {'src', 'frontend', 'tests', 'tests_frontend', 'scripts', 'alembic'}
    current = {p.relative_to(ROOT).as_posix(): p for name in roots for p in (ROOT / name).rglob('*')
        if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc', '.pyo'}}
    changes, patch = [], []
    with zipfile.ZipFile(OLD) as z:
        names = {n for n in z.namelist() if n.split('/')[0] in roots and not n.endswith('/')}
        for name in sorted(set(current) | names):
            before = z.read(name) if name in names else b''
            after = current[name].read_bytes() if name in current else b''
            if before == after:
                continue
            changes.append({'path': name, 'status': 'MODIFIED' if name in names and name in current else 'ADDED' if name in current else 'DELETED',
                'before_sha256': digest(before) if name in names else None, 'after_sha256': digest(after) if name in current else None})
            try:
                patch.extend(difflib.unified_diff(before.decode().splitlines(True), after.decode().splitlines(True), fromfile='DEPTH11/' + name, tofile='DEPTH12/' + name))
            except UnicodeDecodeError:
                pass
    write(ROOT / 'acceptance/DEPTH12_SOURCE_CHANGES.json', {'baseline_work_sha256': OLD_SHA, 'changes': changes})
    (ROOT / 'acceptance/DEPTH12_SOURCE_CHANGES.patch').write_text(''.join(patch))
    register = json.loads((ROOT / 'acceptance/MASTER_CLOSURE_REGISTER.json').read_text())
    for req in register['requirements']:
        if req['id'] in {'ALL-02', 'PAY-01', 'HOTEL-03'}:
            req.update(status='LOCAL_NEW_CATALOG_CREDIT_AND_REMEDIES_TESTED', fully_accepted=False,
                current_evidence=['verification/current_build/depth12/regression_resolution.json', 'verification/current_build/depth12/frontend.tap'],
                scope_note=status['catalog_stay_credit_scope'] + ' ' + status['catalog_supplier_remedy_scope'])
    register['current_build_report'] = 'verification/current_build/depth12/CURRENT_BUILD_STATUS.json'
    write(ROOT / 'acceptance/MASTER_CLOSURE_REGISTER.json', register)
    print(json.dumps({'python': totals, 'new_backend_tests': len(cases), 'frontend_passed': int(matches[-1]), 'changed_files': len(changes)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
