"""Uninstrumented ABBA candidate budget; original formal gate remains authoritative."""
from pathlib import Path
import hashlib
import json
import math
import os
import shutil
import statistics
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
BASELINE='ae2c3f99c8a455f7f60dab5c967a7af71b75536f'
sys.path.insert(0,str(ROOT/'ci/multi_instance'))
from thread_switch_experiment import validate_round

def write(path,data):
    path.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')

def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()

def evaluate(rounds):
    if [r.get('label') for r in rounds] != ['baseline','candidate','candidate','baseline']:
        raise ValueError('Four complete ABBA rounds required')
    for r in rounds:
        for field in ('cpu_seconds','cpu_lifetime_seconds','p95_ms','p99_ms','max_worker_rss_kib'):
            value=r.get(field)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
                raise ValueError('Invalid measured metric: '+field)
    medians={label:{field:statistics.median(r[field] for r in rounds if r['label']==label)
                    for field in ('cpu_seconds','cpu_lifetime_seconds','p95_ms','p99_ms','max_worker_rss_kib')}
             for label in ('baseline','candidate')}
    ratios={k:medians['candidate'][k]/medians['baseline'][k] for k in medians['baseline']}
    limits={'cpu_seconds':.80,'cpu_lifetime_seconds':.80,'p95_ms':.85,'p99_ms':1.0,'max_worker_rss_kib':1.10}
    ranges={label:{field:{'min':min(r[field] for r in rounds if r['label']==label),
            'max':max(r[field] for r in rounds if r['label']==label)} for field in limits}
            for label in ('baseline','candidate')}
    pairs=[{field:rounds[c][field]/rounds[b][field] for field in limits}
           for b,c in ((0,1),(3,2))]
    return {'medians':medians,'ratios':ratios,'limits':limits,'ranges':ranges,'paired_ratios':pairs,
            'adoption_authorized':False,'review_required':['Exclude costs moved before CPU measurement window',
            'Inspect per-round variation; two rounds per label are screening only',
            'Verify transaction semantics and pass the separate original formal staircase'],
            'meets_budget':all(ratios[k]<=v for k,v in limits.items())}

def main():
    head=os.environ['EXPECTED_HEAD'];assert git('rev-parse','HEAD')==head
    order=[('baseline',BASELINE),('candidate',head),('candidate',head),('baseline',BASELINE)]
    out=ROOT/'cpu-candidate-evidence';out.mkdir(exist_ok=False)
    folders=('ci/multi_instance','ci/cpu_hotspots','ci/journey_latency')
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in folders for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    summary={'comparison_head':head,'baseline':BASELINE,'candidate':head,'order':[x[0] for x in order],
        'harness_sha256':hashes,'instrumentation':False,'rounds':[],'status':'RUNNING',
        'scope':'Same runner, packages and PostgreSQL. Fresh schema/processes, complete cold RIDE actors, 13 correctness scenarios each round. Fixed default 5ms switch interval, pool5/overflow0. CPU reports both post-import transaction work and whole worker lifetime including imports; both must reduce by 20%. RSS is maximum worker lifetime high water; no capacity acceptance.'}
    try:
        if git('rev-parse',BASELINE+':application')==git('rev-parse',head+':application'):
            summary['status']='NO_APPLICATION_CANDIDATE_NOT_EVALUATED'
            summary['budget']=None
            return 0
        config=json.loads((ROOT/'ci/cpu_candidate.json').read_text())
        runtime_tree=git('rev-parse',head+':application')
        if config.get('candidate_application_tree')!=runtime_tree:
            summary['status']='CANDIDATE_NOT_ARMED_NOT_EVALUATED'
            summary['budget']=None
            return 0
        if not git('diff','--name-only',BASELINE,head,'--','application/src','application/pyproject.toml','application/alembic'):
            summary['status']='NO_RUNTIME_CHANGE_NOT_EVALUATED'
            summary['budget']=None
            return 0
        for number,(label,sha) in enumerate(order,1):
            checkout=ROOT/f'cpu-candidate-worktree-{number}';git('worktree','add','--detach',str(checkout),sha)
            try:
                for folder in folders:
                    target=checkout/folder
                    if target.exists():shutil.rmtree(target)
                    shutil.copytree(ROOT/folder,target,ignore=shutil.ignore_patterns('__pycache__'))
                assert not git('-C',str(checkout),'diff','--name-only','HEAD','--','application')
                copied={str(p.relative_to(checkout)):hashlib.sha256(p.read_bytes()).hexdigest()
                    for folder in folders for p in (checkout/folder).rglob('*') if p.is_file()}
                assert copied==hashes
                folder=out/f'{number}-{label}'
                code=subprocess.call([sys.executable,str(checkout/'ci/cpu_hotspots/probe.py'),
                    '--experimental-switch-interval-ms','5','--out',str(folder)],
                    env=dict(os.environ,EXPECTED_HEAD=sha),cwd=checkout)
                tree=git('rev-parse',sha+':application')
                checked=validate_round(folder,5,sha,tree,code)
                resources=checked['resources'][-1]['processes']
                assert not list(folder.glob('*.thread-cpu.json'))
                stage=checked['stages'][-1]
                for resource in resources:
                    for field in ('user_cpu_seconds','system_cpu_seconds','max_rss_kib'):
                        value=resource[field]
                        assert math.isfinite(value) and value>=0, 'INVALID_CPU_RESOURCE'
                assert sorted(r['pid'] for r in resources)==stage['process_ids']
                lifetime=[json.loads(p.read_text()) for p in folder.glob('*.lifetime-cpu.json')]
                lifetime=[x for x in lifetime if x['pid'] in stage['process_ids']]
                assert len(lifetime)==2 and sorted(x['pid'] for x in lifetime)==stage['process_ids']
                assert all(math.isfinite(x['cpu_seconds']) and x['cpu_seconds']>0 for x in lifetime)
                round=checked|{'number':number,'label':label,'resources':resources,
                    'cpu_seconds':sum(r['user_cpu_seconds']+r['system_cpu_seconds'] for r in resources),
                    'cpu_lifetime_seconds':sum(r['cpu_seconds'] for r in lifetime),
                    'max_worker_rss_kib':max(r['max_rss_kib'] for r in resources),
                    'p95_ms':stage['p95_ms'],'p99_ms':stage['p99_ms']}
                journey=out/f'{number}-{label}-journey'
                subprocess.run([sys.executable,str(checkout/'ci/journey_latency/measure.py'),
                    '--out',str(journey),'--application-tree',tree],
                    env=dict(os.environ,EXPECTED_HEAD=sha),cwd=checkout,check=True)
                from journey_latency.verify import verify_journey
                round['journey']=verify_journey(journey,sha,tree)
                summary['rounds'].append(round);write(out/'summary.json',summary)
                print(json.dumps({k:v for k,v in round.items() if k not in ('environment','resources')}),flush=True)
            finally:git('worktree','remove','--force',str(checkout))
        assert all(r['environment']==summary['rounds'][0]['environment'] for r in summary['rounds'])
        assert len({r['schema'] for r in summary['rounds']})==4, 'SCHEMA_REUSED'
        assert len({r['journey']['schema'] for r in summary['rounds']})==4
        assert all(r['journey']['environment']==summary['rounds'][0]['journey']['environment'] for r in summary['rounds'])
        summary['budget']=evaluate(summary['rounds'])
        summary['status']='CANDIDATE_BUDGET_MET_NOT_CAPACITY_ACCEPTANCE' if summary['budget']['meets_budget'] else 'CANDIDATE_BUDGET_NOT_MET'
        return 0 if summary['budget']['meets_budget'] else 1
    except Exception as exc:
        summary['status']='INVALID_COMPARISON_NOT_EVALUATED'
        summary['error']=type(exc).__name__+': '+str(exc)
        raise
    finally:
        write(out/'summary.json',summary)
        write(out/'SHA256.json',{str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in out.rglob('*') if p.is_file() and p!=out/'SHA256.json'})

if __name__=='__main__':raise SystemExit(main())
