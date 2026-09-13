#!/usr/bin/env python3
"""Combine a full run with an explicitly scoped fixture-only retest, preserving both XMLs."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'verification/current_build/depth12'
CHANGED_TEST = 'tests/test_sprint1x_consumer_e2e.py'
CLASS = 'tests.test_sprint1x_consumer_e2e'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cases(path):
    items = list(ET.parse(path).getroot().iter('testcase'))
    keyed = {(x.get('classname'), x.get('name')): x for x in items}
    if len(keyed) != len(items):
        raise ValueError('DUPLICATE_TEST_CASE_IDENTITY')
    return keyed


def counts(items):
    return {'tests': len(items), 'failures': sum(x.find('failure') is not None for x in items.values()),
        'errors': sum(x.find('error') is not None for x in items.values()),
        'skipped': sum(x.find('skipped') is not None for x in items.values())}


def main():
    before = json.loads((OUT / 'full_run_source_fingerprint.json').read_text())['files']
    current = {p.relative_to(ROOT).as_posix(): sha(p) for name in ['src', 'frontend', 'alembic', 'tests', 'tests_frontend']
        for p in (ROOT / name).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc', '.pyo'}}
    changed = [n for n in sorted(set(before) | set(current)) if before.get(n) != current.get(n)]
    if changed != [CHANGED_TEST]:
        raise ValueError('RETEST_ONLY_VALID_FOR_THIS_SINGLE_FIXTURE_CHANGE:' + str(changed))
    full_path = OUT / 'full_regression.xml'
    retest_path = OUT / 'legacy_consumer_retest.xml'
    full, retest = cases(full_path), cases(retest_path)
    expected = {k for k in full if k[0] == CLASS}
    if not expected or set(retest) != expected or any(counts(retest)[k] for k in ['failures', 'errors', 'skipped']):
        raise ValueError('ALL_CHANGED_MODULE_TESTS_MUST_BE_RETESTED_AND_PASS')
    unresolved = {k for k, v in full.items() if (v.find('failure') is not None or v.find('error') is not None) and k not in retest}
    if unresolved:
        raise ValueError('UNRESOLVED_FULL_RUN_FAILURES:' + str(unresolved))
    combined = {**full, **retest}
    final = counts(combined)
    final['passed'] = final['tests'] - final['failures'] - final['errors'] - final['skipped']
    final['seconds'] = round(sum(float(x.get('time', 0)) for x in combined.values()), 3)
    data = {'basis': 'FULL_RUN_PLUS_SINGLE_TEST_MODULE_FIXTURE_RETEST', 'one_clean_full_run': False,
        'runtime_frontend_migrations_and_all_other_tests_unchanged': True,
        'full_run': {'path': 'verification/current_build/depth12/full_regression.xml', 'sha256': sha(full_path), **counts(full)},
        'retest': {'path': 'verification/current_build/depth12/legacy_consumer_retest.xml', 'sha256': sha(retest_path), **counts(retest)},
        'changed_test_files': [{'path': n, 'before_sha256': before[n], 'after_sha256': current[n]} for n in changed],
        'reason': 'Replace expired fixed stay dates with future fixture dates and explicitly accept the new conversion quote; original business assertions preserved.',
        'effective_unique_results': final, 'results_are_not_added_twice': True,
        'original_failure_xml_preserved': True,
        'current_code_fingerprint_sha256': hashlib.sha256(json.dumps(current, sort_keys=True).encode()).hexdigest()}
    (OUT / 'regression_resolution.json').write_text(json.dumps(data, indent=2))
    print(json.dumps(final))


if __name__ == '__main__':
    main()
