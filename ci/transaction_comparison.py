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
BASELINE = 'e109af4dc4ae84f27f63d0104aa42c8d6b64b34d'
# Resolve to the immutable PR head supplied by Actions, then record that SHA
# in every round. Both applications use the identical uninstrumented harness.
CANDIDATE = os.environ['EXPECTED_HEAD']
ORDER = [('baseline', BASELINE), ('candidate', CANDIDATE),
         ('candidate', CANDIDATE), ('baseline', BASELINE)]

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()

def write(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')

def evaluate(rounds):
    """A failed baseline is valid comparative evidence, never candidate acceptance."""
    if len(rounds)!=4 or [r['label'] for r in rounds]!=['baseline','candidate','candidate','baseline']:
        raise ValueError('ABBA_ORDER_REQUIRED')
    metrics={}; reasons=[]
    for n in (20,100):
        groups={label:[s for r in rounds if r['label']==label for s in r['stages'] if s['concurrent_transactions']==n] for label in ('baseline','candidate')}
        for label,stages in groups.items():
            if len(stages)!=2 or any(s['errors'] or s['sql']!='PASS' or s.get('application_process_cpu_seconds',0)<=0 or s.get('startup_cpu_seconds',-1)<0 for s in stages):
                raise ValueError('COMPLETE_BOUND_CPU_SQL_EVIDENCE_REQUIRED')
        baseline,candidate=groups['baseline'],groups['candidate']
        base_p95=statistics.median(s['p95_ms'] for s in baseline)
        cand_p95=statistics.median(s['p95_ms'] for s in candidate)
        # Include imports, so moving CPU across the ready barrier cannot meet a budget.
        base_cpu=statistics.median(s['application_process_cpu_seconds']+s['startup_cpu_seconds'] for s in baseline)
        cand_cpu=statistics.median(s['application_process_cpu_seconds']+s['startup_cpu_seconds'] for s in candidate)
        cpu_reduction=1-cand_cpu/base_cpu;p95_reduction=1-cand_p95/base_p95
        capacity_pass=all(s['p95_ms']<=5000 and s['p99_ms']<=10000 and s['pass'] for s in candidate)
        budget_pass=cpu_reduction>=.20 and p95_reduction>=.15
        metrics[str(n)]={'baseline_median_p95_ms':base_p95,'candidate_median_p95_ms':cand_p95,
            'baseline_median_application_cpu_seconds_including_startup':base_cpu,
            'candidate_median_application_cpu_seconds_including_startup':cand_cpu,
            'cpu_reduction':cpu_reduction,'p95_reduction':p95_reduction,
            'candidate_capacity_pass':capacity_pass,'optimization_budget_pass':budget_pass}
        if not capacity_pass:reasons.append(str(n)+':CANDIDATE_CAPACITY_FAILED')
        if not budget_pass:reasons.append(str(n)+':OPTIMIZATION_BUDGET_FAILED')
    return {'decision':'NO_GO' if reasons else 'GO_FOR_NEXT_REVIEW_NOT_RELEASE','tiers':metrics,'reasons':reasons}

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
               'scope': 'Same runner/dependencies/PostgreSQL; fresh schema and service processes per round. Fixed cold service ABBA 20/100 with unchanged 2x5 pool configuration; not sustained, HTTP or production acceptance.',
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
                code = subprocess.call([sys.executable, str(target / 'run.py'), '--comparison-20-100', '--out', str(folder)], env=env, cwd=checkout)
                binding = json.loads((folder / 'binding.json').read_text())
                result = json.loads((folder / 'result.json').read_text())
                assert binding['head'] == sha
                assert binding['application_tree'] == git('rev-parse', sha + ':application')
                assert binding['diagnostic_instrumentation'] is False
                assert result['correctness'] == 'PASS', 'CORRECTNESS_FAILURE_STOPS_COMPARISON'
                assert result['status'] in ('STOPPED_AT_FAILED_TIER', 'EXPERIMENT_PLAN_COMPLETE_NOT_CAPACITY_ACCEPTANCE')
                assert code == (0 if result['status'] == 'EXPERIMENT_PLAN_COMPLETE_NOT_CAPACITY_ACCEPTANCE' else 1)
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
        summary['verdict']=evaluate(summary['rounds'])
        summary['status']='COMPARISON_COMPLETE_'+summary['verdict']['decision']
        return 0 if summary['verdict']['decision']=='GO_FOR_NEXT_REVIEW_NOT_RELEASE' else 1
    except Exception as exc:
        summary.update(status='COMPARISON_INVALID_OR_CORRECTNESS_FAILED', error_type=type(exc).__name__, error=str(exc)[:500])
        raise
    finally:
        write(out / 'summary.json', summary)
        write(out / 'SHA256.json', {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in out.rglob('*') if p.is_file() and p != out / 'SHA256.json'})

if __name__ == '__main__':
    raise SystemExit(main())
