#!/usr/bin/env python3
"""Record measured catalog cancellation evidence against the durable DEPTH10 archive."""
import difflib
import json
import re
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET
from record_depth04_evidence import digest, write

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'verification/current_build/depth11'
OLD = ROOT / 'deliverables/GO_CP11_DEPTH_10_HOTEL_SUPPLIER_REMEDY_WORK_20260907.zip'
OLD_SHA = 'a46357c911851d609a9325dc2c3f0c4374c7f46f1e582e4f6c4aa3ab167a2b61'


def main():
    if digest(OLD.read_bytes()) != OLD_SHA:
        raise ValueError('DEPTH10_BASELINE_CHANGED')
    suites = list(ET.parse(OUT / 'full_regression.xml').getroot().iter('testsuite'))
    totals = {k: sum(int(s.get(k, '0')) for s in suites) for k in ['tests', 'failures', 'errors', 'skipped']}
    if not suites or totals['failures'] or totals['errors']:
        raise ValueError('CURRENT_REGRESSION_NOT_PASSING')
    totals['passed'] = totals['tests'] - totals['skipped']
    totals['seconds'] = round(sum(float(s.get('time', '0')) for s in suites), 3)
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
    previous = json.loads((ROOT / 'verification/current_build/depth10/CURRENT_BUILD_STATUS.json').read_text())
    status = {**previous, 'build': 'CP11_DEPTH_11_CATALOG_SUPPLIER_REMEDY', 'python': totals,
        'baseline': {**previous['baseline'], 'depth10_work_sha256': OLD_SHA},
        'frontend': {'logic_passed': int(matches[-1]), 'syntax_files_passed': len(syntax['files']),
            'node': syntax['node'], 'browser_visual_accepted': False, 'frozen_node_22_22_certified': False},
        'immutable': {k: {p: v[p] for p in ['count', 'all_match']} for k, v in immutable.items()},
        'migrations': {'current_head': '0119_catalog_supplier_remedy', 'original_files_unchanged': 114,
            'added_files': previous['migrations']['added_files'] + ['alembic/versions/0119_catalog_supplier_remedy.py'],
            'roundtrip_evidence': previous['migrations']['roundtrip_evidence'] + ['tests/test_depth11_migration.py']},
        'engineering_gaps': ['COMPLETE_MASTER_REQUIREMENT_DECOMPOSITION', 'ALL_VERTICAL_ADVANCED_AFTER_SALES_E2E',
            'LEGACY_HOTEL_STAY_CREDIT_VALUE_AND_RECOVERY', 'COMPLETE_SUPPLIER_SELF_SERVICE_AND_GUEST_LIABILITY_TERMS',
            'RENTAL_SUPPLIER_POLICY_AND_DEPOSIT_SETTLEMENT', 'EXTERNAL_PERSONAL_SOURCE_CONNECTORS',
            '14_CELL_DURABLE_EXECUTION_AND_RECOVERY'],
        'acceptance_separation': 'Inventory, prices and payment require complete functionality and isolated execution evidence. Live synchronization is not a prerequisite for that engineering acceptance and does not replace it; deployment certification remains separately recorded.'}
    status['direct_hotel_scope'] = previous['direct_hotel_scope'].replace(
        'legacy supplier compensation, complete supplier UI and advanced other-vertical flows remain open',
        'catalog cash-order supplier compensation is additionally tested in DEPTH11; legacy credit, complete supplier UI and advanced other-vertical flows remain open')
    status['supplier_remedy_scope'] = previous['supplier_remedy_scope'].replace(
        'Guest liability fee policy, legacy OrderRow path, complete supplier self-service, live providers, PostgreSQL and browser acceptance remain open.',
        'Catalog cash OrderRow remedies are additionally tested in DEPTH11. Guest liability fee policy, legacy credit value, complete supplier self-service, PostgreSQL and browser acceptance remain open. Live provider integration is tracked separately.')
    status['catalog_supplier_remedy_scope'] = (
        'CNY isolated catalog cash orders: supplier claims and structured evidence do not decide liability; an independent checker binds current evidence and approved original-capture refund lines. '
        'Supplier cancellation is durably requested once; lost replies remain unknown until status reconciliation, without resend or premature refunds. '
        'Original payment plus captured change supplements are refunded to their own canonical captures in one atomic stage, followed by independently funded compensation. '
        'Finite settlement/reserve/current scoped bank/protection priority and cross-order-family recovery receipt deduplication share the hosted funding engine. '
        'Supplier, finance and customer surfaces preserve ownership, CSRF and idempotency; approved money budgets freeze conflicting actions. '
        'Legacy credit redemption orders are explicitly held for value reconciliation, not treated as zero-paid cash orders. No browser visual or live provider acceptance is claimed.')
    status['validation_scope'] = 'Full cumulative regression includes all 18 DEPTH11 tests, the 21 DEPTH10 tests and updated legacy API tests. Targeted results overlap and are not added to the full total. Frontend tests verify logic only.'
    status['historical_test_change'] = 'Seven sprint1n tests now explicitly submit evidence, require independent review and execute the approved remedy before checking their original funding/refund/idempotency assertions. The removed automatic supplier-label decision was the defect, not a required business behavior.'
    status['release_gate'] = 'HOLD'
    status['engineering_complete'] = False
    status['deployed'] = False
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
                patch.extend(difflib.unified_diff(before.decode().splitlines(True), after.decode().splitlines(True), fromfile='DEPTH10/' + name, tofile='DEPTH11/' + name))
            except UnicodeDecodeError:
                pass
    write(ROOT / 'acceptance/DEPTH11_SOURCE_CHANGES.json', {'baseline_work_sha256': OLD_SHA, 'changes': changes})
    (ROOT / 'acceptance/DEPTH11_SOURCE_CHANGES.patch').write_text(''.join(patch))
    register = json.loads((ROOT / 'acceptance/MASTER_CLOSURE_REGISTER.json').read_text())
    for req in register['requirements']:
        if req['id'] in {'ALL-02', 'PAY-01', 'HOTEL-02', 'HOTEL-03'}:
            req.update(status='LOCAL_HOSTED_AND_CATALOG_CASH_SUPPLIER_REMEDY_TESTED', fully_accepted=False,
                current_evidence=['verification/current_build/depth11/full_regression.xml', 'verification/current_build/depth11/frontend.tap'],
                scope_note=status['direct_hotel_scope'] + ' ' + status['catalog_supplier_remedy_scope'])
    register['current_build_report'] = 'verification/current_build/depth11/CURRENT_BUILD_STATUS.json'
    write(ROOT / 'acceptance/MASTER_CLOSURE_REGISTER.json', register)
    print(json.dumps({'python': totals, 'frontend_passed': int(matches[-1]), 'changed_files': len(changes)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
