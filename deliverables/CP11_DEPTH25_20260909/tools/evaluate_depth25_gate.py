#!/usr/bin/env python3
"""Evaluate evidence separately from unresolved whole-system acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def cases(path):
    return {(c.get('classname'), c.get('name')): c for c in ET.parse(path).iter('testcase')}


def evaluate(root):
    evidence = root / 'verification/current_build/depth25'
    status = json.loads((evidence / 'CURRENT_BUILD_STATUS.json').read_text())
    source = json.loads((evidence / 'source_fingerprint.json').read_text())['files']
    current = cases(evidence / 'full_regression.xml')
    previous = cases(root / 'verification/current_build/depth24/full_regression.xml')
    bad = [key for key, c in current.items() if c.find('failure') is not None or c.find('error') is not None]
    skipped = [key for key, c in current.items() if c.find('skipped') is not None]
    expected_skip_modules = {'tests.test_p0_0100_postgres_concurrency', 'tests.test_p0_0101_postgres_race_matrix'}
    runtime = status['remote_runtime']
    actual_pg = cases(evidence / 'remote_original/postgres_existing.xml')
    pg_passed = {k for k, c in actual_pg.items() if not any(c.find(t) is not None for t in ('failure', 'error', 'skipped'))}
    overlay = json.loads((evidence / 'remote_original/depth25_source_overlay.json').read_text())
    technical = {
        'frozen_source': all((root / p).is_file() and sha(root / p) == h for p, h in source.items()),
        'complete_previous_test_inventory': set(previous) <= set(current),
        'full_run_no_failures': not bad and status['python']['one_clean_full_run'],
        'local_skips_are_six_isolated_postgres_cases': len(skipped) == 6 and all(k[0] in expected_skip_modules for k in skipped),
        'exact_skipped_cases_passed_in_postgres': set(skipped) <= pg_passed,
        'actual_postgres_and_redis_and_frozen_node': runtime['runtime_acceptance'] == 'PASS',
        'migration_history': runtime['checks']['migration_history']['accepted'],
        'runtime_source_binding': overlay['frozen_files_verified'] == len(source) and all(source[f['path']] == f['sha256'] for f in overlay['files']),
    }
    master = json.loads((root / 'acceptance/MASTER_CLOSURE_REGISTER.json').read_text())
    trace = json.loads((root / 'acceptance/MASTER_V7_PARAGRAPH_TRACE.json').read_text())
    browser = json.loads((evidence / 'BROWSER_ACCEPTANCE.json').read_text())
    open_requirements = [{'id': r['id'], 'requirement': r['requirement'], 'status': r['status']}
                         for r in master['requirements'] if not r.get('fully_accepted')]
    source_not_assessed = [r['source_id'] for r in trace['rows'] if r['decomposition_state'] == 'UNASSESSED_SOURCE']
    acceptance = {
        'critical_master_requirements': not open_requirements,
        'complete_master_decomposition': not source_not_assessed,
        'actual_browser': browser['accepted'],
        'cross_device_visual': browser['cross_device_acceptance'],
    }
    accepted = all(technical.values()) and all(acceptance.values())
    result = {
        'build': status['build'], 'FINAL_RELEASE_GATE': 'PASS' if accepted else 'HOLD',
        'engineering_complete': accepted, 'deployed': False,
        'technical_runtime_checks': technical, 'whole_system_acceptance': acceptance,
        'test_counts_are_separate_runs': True, 'local_skipped_test_ids': skipped,
        'open_critical_requirements': open_requirements,
        'unassessed_source_paragraph_count': len(source_not_assessed),
        'source_paragraph_note': 'Source paragraphs are not automatically equivalent to executable requirements.',
        'browser_blocker': browser['browser_error'],
        'evidence_sha256': {p.name: sha(p) for p in [evidence / 'CURRENT_BUILD_STATUS.json',
                            evidence / 'full_regression.xml', evidence / 'source_fingerprint.json',
                            evidence / 'REMOTE_RUNTIME_FINAL.log', evidence / 'BROWSER_ACCEPTANCE.json']},
    }
    (evidence / 'FINAL_RELEASE_GATE.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ['FINAL_RELEASE_GATE','technical_runtime_checks','whole_system_acceptance','unassessed_source_paragraph_count']}, indent=2))
    return 0 if accepted else 2


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    raise SystemExit(evaluate(parser.parse_args().source.resolve()))
