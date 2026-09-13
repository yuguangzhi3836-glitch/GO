#!/usr/bin/env python3
"""Record frozen DEPTH16 execution-control checks without promoting deployment status."""
import difflib
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'verification/current_build/depth16'
OLD = ROOT/'deliverables/GO_CP11_DEPTH_15_CREDIT_SOURCE_EXCLUSION_WORK_20260907.zip'
OLD_SHA = '3f3c4d99431ff31cdfb3844e2464ce81542d29d2f77c876e8b5d563583695ea6'


def sha(b): return hashlib.sha256(b).hexdigest()
def write(p, b): p.write_text(json.dumps(b, ensure_ascii=False, indent=2)+'\n')


def main():
    assert sha(OLD.read_bytes()) == OLD_SHA, 'SAVED_DEPTH15_BASELINE_CHANGED'
    current = {p.relative_to(ROOT).as_posix(): sha(p.read_bytes())
        for folder in ['src', 'frontend', 'alembic', 'tests', 'tests_frontend']
        for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc', '.pyo'}}
    assert current == json.loads((OUT/'full_run_source_fingerprint.json').read_text())['files'], 'FINAL_SOURCE_CHANGED'
    tree = ET.parse(OUT/'full_regression.xml'); suites = list(tree.getroot().iter('testsuite'))
    assert suites, 'FINAL_FULL_RUN_REQUIRED'
    total = {k: sum(int(s.get(k, '0')) for s in suites) for k in ['tests', 'failures', 'errors', 'skipped']}
    assert not total['failures'] and not total['errors'], 'CLEAN_FULL_RUN_REQUIRED'
    total.update(passed=total['tests']-total['skipped'], one_clean_full_run=True,
        seconds=sum(float(s.get('time', '0')) for s in suites))
    new = [c for c in tree.getroot().iter('testcase') if 'test_depth16_' in c.get('classname', '')]
    assert len(new) == 49 and not any(len(c) for c in new), 'ALL_CURRENT_AUTHORITY_CASES_REQUIRED'
    immutable = json.loads((OUT/'immutable_baseline.json').read_text())
    assert all(g['all_match'] for g in immutable.values()), 'IMMUTABLE_BASELINE_FAILED'
    for group in immutable.values():
        assert all(sha((ROOT/f['path']).read_bytes()) == f['sha256'] for f in group['files']), 'IMMUTABLE_FILE_CHANGED'
    previous = json.loads((ROOT/'verification/current_build/depth15/CURRENT_BUILD_STATUS.json').read_text())
    scope = ('C14 decision primitives recheck qualification validity, revocation, policy version and all rule-bound '
        'condition evidence at final decision time. Conditions from all applicable rules are conjunctive, exact-action-bound '
        'and fresh; uncovered legal exposures hold, and HOLD/BLOCK dominate. Application-configured resolvers, not caller '
        'metadata, supply condition evidence. Risk facts impose money/PII/truth minimums and strict types; nonzero reversibility '
        'cannot become R0. Input collections are copied immutably. Missing historical qualification dates are not fabricated. '
        'Fresh independent evidence and a later window are required after suspension/revocation. This does not certify durable '
        '14-cell dispatch, persistent qualifications, actual verifier identities, immutable runtime auditing or complete route integration.')
    corrected_cash_scope = previous.get('catalog_cash_fare_scope', '').replace(
        'advanced credit allocation after lower-price forfeiture remains held, as do amendments following partial refund until room value allocation is reconciled.',
        'amendments following partial refund remain held until room value allocation is reconciled. DEPTH15 closes source allocation after verified accepted lower-price forfeiture.')
    status = {**previous, 'build': 'CP11_DEPTH_16_CURRENT_AUTONOMY_AUTHORITY', 'python': total,
        'baseline': {**previous['baseline'], 'depth15_work_sha256': OLD_SHA},
        'new_backend_cases_passed': len(new), 'autonomy_current_authority_scope': scope,
        'catalog_cash_fare_scope': corrected_cash_scope,
        'frontend': {**previous['frontend'], 'basis': 'DEPTH15_PASSED_78_INHERITED_WITH_ALL_FRONTEND_AND_TEST_HASHES_UNCHANGED',
            'current_iteration_rerun': False},
        'immutable': {k: {f: v[f] for f in ['count', 'all_match']} for k, v in immutable.items()},
        'migrations': {**previous['migrations'], 'depth16_added_files': [], 'depth16_changed_files': []},
        'validation_scope': 'One clean full regression of frozen source. The 77-case targeted run overlaps and is not added. '
            'Frontend and frontend tests are byte-identical to saved DEPTH15; its 78 logic passes are inherited, not rerun. '
            'Database schema, all 123 migrations, original V7 master and consumer brand assets are unchanged.',
        'historical_test_change_depth16': 'No existing test assertions or fixtures changed.',
        'next_vertical_audit': 'acceptance/FLIGHT_RIDE_NEXT_CLOSURE_CONTRACT.md',
        'engineering_complete': False, 'release_gate': 'HOLD', 'FINAL_RELEASE_GATE': 'HOLD', 'deployed': False}
    write(OUT/'CURRENT_BUILD_STATUS.json', status)
    roots = {'src', 'frontend', 'tests', 'tests_frontend', 'scripts', 'alembic'}
    files = {p.relative_to(ROOT).as_posix(): p for folder in roots for p in (ROOT/folder).rglob('*')
        if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc', '.pyo'}
        and p.name != 'official_rooms_source.html'}
    changes = []; patch = []
    with zipfile.ZipFile(OLD) as z:
        names = {n for n in z.namelist() if n.split('/')[0] in roots and not n.endswith('/')}
        for n in sorted(set(files)|names):
            before = z.read(n) if n in names else b''; after = files[n].read_bytes() if n in files else b''
            if before == after: continue
            changes.append({'path': n, 'status': 'MODIFIED' if n in files and n in names else 'ADDED' if n in files else 'DELETED',
                'before_sha256': sha(before) if n in names else None, 'after_sha256': sha(after) if n in files else None})
            try:
                patch.extend(difflib.unified_diff(before.decode().splitlines(True), after.decode().splitlines(True),
                    fromfile='DEPTH15/'+n, tofile='DEPTH16/'+n))
            except UnicodeDecodeError: pass
    write(ROOT/'acceptance/DEPTH16_SOURCE_CHANGES.json', {'baseline_work_sha256': OLD_SHA, 'changes': changes})
    (ROOT/'acceptance/DEPTH16_SOURCE_CHANGES.patch').write_text(''.join(patch))
    register = json.loads((ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json').read_text())
    for item in register['requirements']:
        if item['id'] in {'GOV-01', 'GOV-02', 'GOV-03'}:
            item.update(status='CURRENT_QUALIFICATION_AND_CONDITIONS_TESTED_DURABLE_DISPATCH_OPEN', fully_accepted=False,
                current_evidence=['verification/current_build/depth16/full_regression.xml',
                    'tests/autonomy/test_depth16_current_authority.py'], scope_note=scope)
        if item['id'] in {'HOTEL-03', 'ALL-02', 'PAY-01', 'TRIPS-01'}:
            item['scope_note'] = corrected_cash_scope+' '+previous['credit_source_exclusion_scope']
        if item['id'] in {'FLIGHT-02', 'RIDE-01'}:
            item['next_closure_contract'] = 'acceptance/FLIGHT_RIDE_NEXT_CLOSURE_CONTRACT.md'
    register['current_build_report'] = 'verification/current_build/depth16/CURRENT_BUILD_STATUS.json'
    write(ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json', register)
    report = ROOT/'acceptance/GO_DEPTH16_REVIEW.md'
    measured = (f"最终冻结代码完整回归：{total['tests']} 项，{total['passed']} 通过、{total['skipped']} 项 PostgreSQL 专项跳过，"
        f"失败和错误均为 0。本轮新增 {len(new)} 项自治控制测试全部通过，覆盖过期、撤销、条件遗漏、冒用、乱序核验、"
        "核验中规则替换及类型混淆。既有测试与断言不变；77 项定向测试包含于完整回归，不重复累加。")
    report.write_text(report.read_text().replace('MEASURED_RESULTS_PENDING', measured))
    print(json.dumps({'python': total, 'new_backend': len(new), 'frontend_inherited': 78, 'changed_files': len(changes)}))


if __name__ == '__main__': main()
