"""Same-runner ABBA comparison; never treats failed capacity as acceptance."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASELINE = 'c1da06116a8943a78bb1080b3737232d7eb5e955'
CANDIDATE = '2fdea57fb1a8779ccabd6fbf5da96e3fa6554068'
ORDER = [('baseline', BASELINE), ('candidate', CANDIDATE),
         ('candidate', CANDIDATE), ('baseline', BASELINE)]

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()

def write(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')

def main():
    out = ROOT / 'transaction-comparison-evidence'
    out.mkdir(exist_ok=False)
    head = git('rev-parse', 'HEAD')
    assert head == os.environ['EXPECTED_HEAD']
    harness = ROOT / 'ci/multi_instance'
    hashes = {str(p.relative_to(harness)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in harness.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    summary = {'comparison_head': head, 'order': [x[0] for x in ORDER],
               'baseline': BASELINE, 'candidate': CANDIDATE,
               'harness_sha256': hashes, 'instrumentation': False,
               'scope': 'Same runner/dependencies/database server; fresh schema and service processes per round. Full cold service staircase, not HTTP or production capacity.',
               'rounds': [], 'status': 'RUNNING'}
    write(out / 'summary.json', summary)
    try:
        for i, (label, sha) in enumerate(ORDER, 1):
            checkout = ROOT / f'comparison-worktree-{i}'
            git('worktree', 'add', '--detach', str(checkout), sha)
            try:
                # Application bytes remain exactly at the pinned commit. Both
                # versions execute the identical current measurement harness.
                target = checkout / 'ci/multi_instance'
                shutil.rmtree(target)
                shutil.copytree(harness, target, ignore=shutil.ignore_patterns('__pycache__'))
                assert not git('-C', str(checkout), 'diff', '--name-only', 'HEAD', '--', 'application')
                assert {str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in target.rglob('*') if p.is_file()} == hashes
                folder = out / f'{i}-{label}'
                env = dict(os.environ, EXPECTED_HEAD=sha)
                print(f'ROUND {i} {label} {sha}', flush=True)
                code = subprocess.call([sys.executable, str(target / 'run.py'), '--out', str(folder)], env=env, cwd=checkout)
                binding = json.loads((folder / 'binding.json').read_text())
                result = json.loads((folder / 'result.json').read_text())
                assert binding['head'] == sha
                assert binding['application_tree'] == git('rev-parse', sha + ':application')
                assert binding['diagnostic_instrumentation'] is False
                assert result['correctness'] == 'PASS', 'CORRECTNESS_FAILURE_STOPS_COMPARISON'
                assert result['status'] in ('STOPPED_AT_FAILED_TIER', 'BOUNDED_SERVICE_PLAN_PASS')
                assert code == (0 if result['status'] == 'BOUNDED_SERVICE_PLAN_PASS' else 1)
                assert all(s['errors'] == 0 and s['sql'] == 'PASS' for s in result['stages'])
                summary['rounds'].append({'round': i, 'label': label, 'head': sha,
                                          'application_tree': binding['application_tree'],
                                          'correctness': result['correctness'],
                                          'stages': result['stages'], 'exit_code': code})
                write(out / 'summary.json', summary)
                print(json.dumps(summary['rounds'][-1]), flush=True)
            finally:
                git('worktree', 'remove', '--force', str(checkout))
        summary['median_p95_ms'] = {
            label: {str(n): statistics.median(s['p95_ms'] for r in summary['rounds']
                       if r['label'] == label for s in r['stages'] if s['concurrent_transactions'] == n)
                    for n in sorted({s['concurrent_transactions'] for r in summary['rounds']
                       if r['label'] == label for s in r['stages']})}
            for label in ('baseline', 'candidate')}
        all_pass = all(s['pass'] for r in summary['rounds'] for s in r['stages'])
        summary['status'] = 'COMPARISON_COMPLETE_CAPACITY_PASS' if all_pass else 'COMPARISON_COMPLETE_CAPACITY_FAILED'
        return 0 if all_pass else 1
    except Exception as exc:
        summary.update(status='COMPARISON_INVALID_OR_CORRECTNESS_FAILED', error_type=type(exc).__name__, error=str(exc)[:500])
        raise
    finally:
        write(out / 'summary.json', summary)
        write(out / 'SHA256.json', {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in out.rglob('*') if p.is_file() and p != out / 'SHA256.json'})

if __name__ == '__main__':
    raise SystemExit(main())
