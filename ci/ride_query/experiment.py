"""Safety-gated, same-host ABBA. Frozen workload; four processes/pool4 throughout."""
from pathlib import Path
import hashlib
import importlib.util
import json
import math
import os
import shutil
import statistics
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
BASELINE='a6361b9376ab59f05616338b8245ac4e2976dec3'
BASELINE_TREE='6570b66bc977f89c0311d67bdc6b721cd70d4e09'
FOLDERS=('ci/multi_instance','ci/process_pool','ci/journey_latency','ci/ride_query')
spec=importlib.util.spec_from_file_location('ride_query_round',Path(__file__).with_name('round.py'))
round_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(round_module)
sys.path.insert(0,str(ROOT/'ci/journey_latency'))
from verify import verify_journey

def write(path,value):
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')

def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()

def evaluate(rounds):
    assert [r['label'] for r in rounds]==['baseline','candidate','candidate','baseline']
    fields=('application_cpu_seconds','lifetime_cpu_seconds','p95_ms','p99_ms','sum_worker_max_rss_kib')
    for r in rounds:
        assert [s['concurrent_transactions'] for s in r['stages']]==[20,100]
        for s in r['stages']:
            assert s['errors']==0 and s['sql']=='PASS'
            assert s['observed_peak_inflight']==s['observed_peak_executing']==s['concurrent_transactions']
            assert all(isinstance(s[k],(int,float)) and not isinstance(s[k],bool) and math.isfinite(s[k]) and s[k]>0 for k in fields)
        assert r['stages'][0]['pass'], '20_ACTOR_GATE_FAILED'
    medians={label:{k:statistics.median(r['stages'][1][k] for r in rounds if r['label']==label) for k in fields} for label in ('baseline','candidate')}
    ratios={k:medians['candidate'][k]/medians['baseline'][k] for k in fields}
    limits={'application_cpu_seconds':.8,'lifetime_cpu_seconds':.8,'p95_ms':.85,'p99_ms':1.,'sum_worker_max_rss_kib':1.1}
    return {'medians':medians,'ratios':ratios,'limits':limits,
        'meets_budget':all(ratios[k]<=limit for k,limit in limits.items()),
        'candidate_100_pass':all(r['stages'][1]['pass'] for r in rounds if r['label']=='candidate'),
        'adoption_authorized':False}

def run_round(checkout,out,sha,tree,diagnostic=False):
    env=dict(os.environ,EXPECTED_HEAD=sha,EXPECTED_APPLICATION_TREE=tree)
    args=[sys.executable,str(checkout/'ci/ride_query/round.py'),'--instances','4','--pool','4','--out',str(out)]
    if diagnostic:args.append('--diagnostic')
    with out.with_suffix('.log').open('w') as log:
        code=subprocess.call(args,cwd=checkout,env=env,stdout=log,stderr=subprocess.STDOUT)
    round_module.pp.APP_TREE=tree
    result=round_module.pp.validate(out,4,4,diagnostic,sha)
    assert code==json.loads((out/'exit.json').read_text())['exit_code']
    return result

def main():
    head=os.environ['EXPECTED_HEAD'];assert git('rev-parse','HEAD')==head
    assert git('rev-parse',BASELINE+':application')==BASELINE_TREE
    safety=json.loads((ROOT/'ride-query-qualification/safety.json').read_text())
    assert safety['head']==head and safety['application_tree']==git('rev-parse',head+':application')
    assert safety['regressions']==250 and safety['boundary_tests']==15 and safety['status']=='PASS'
    for name,digest in safety['junit_sha256'].items():
        assert hashlib.sha256((ROOT/'ride-query-qualification'/name).read_bytes()).hexdigest()==digest
    out=ROOT/'ride-query-evidence';out.mkdir(exist_ok=False)
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in FOLDERS
        for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and 'evidence' not in p.parts}
    order=[('baseline',BASELINE),('candidate',head),('candidate',head),('baseline',BASELINE)]
    summary={'head':head,'baseline':BASELINE,'baseline_application_tree':BASELINE_TREE,
        'candidate_application_tree':git('rev-parse',head+':application'),'configuration':{'instances':4,'pool':4,'overflow':0,'tiers':[20,100]},
        'harness_sha256':hashes,'safety':safety,'rounds':[],'status':'RUNNING','acceptance':False,
        'scope':'Synthetic service actors on one 4-vCPU host. Cold + three continued bursts per operation. Not HTTP, real PSP or production capacity; original 2-vCPU acceptance remains FAIL.'}
    write(out/'summary.json',summary)
    try:
        for number,(label,sha) in enumerate(order,1):
            checkout=ROOT/f'ride-query-worktree-{number}'
            git('worktree','add','--detach',str(checkout),sha)
            try:
                for folder in FOLDERS:
                    target=checkout/folder
                    if target.exists():shutil.rmtree(target)
                    shutil.copytree(ROOT/folder,target,ignore=shutil.ignore_patterns('__pycache__','evidence'))
                actual={str(p.relative_to(checkout)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in FOLDERS for p in (checkout/folder).rglob('*') if p.is_file()}
                assert actual==hashes,'HARNESS_MISMATCH'
                assert not git('-C',str(checkout),'diff','HEAD','--','application'),'APPLICATION_CHANGED'
                tree=git('rev-parse',sha+':application')
                row=run_round(checkout,out/f'{number}-{label}',sha,tree)
                row.update(number=number,label=label)
                # Retain main results even if a supplementary batch fails later.
                summary['rounds'].append(row);write(out/'summary.json',summary)
                assert row['stages'][0]['pass'],'20_ACTOR_GATE_FAILED'
                journey=out/f'{number}-{label}-journey'
                with journey.with_suffix('.log').open('w') as log:
                    subprocess.run([sys.executable,str(checkout/'ci/journey_latency/measure.py'),'--instances-per-operation','4','--pool-per-instance','4','--application-tree',tree,'--out',str(journey)],env=dict(os.environ,EXPECTED_HEAD=sha),cwd=checkout,stdout=log,stderr=subprocess.STDOUT,check=True)
                row['journey']=verify_journey(journey,sha,tree,4,4)
                diagnostic=out/f'{number}-{label}-diagnostic'
                row['diagnostic']=run_round(checkout,diagnostic,sha,tree,True)
                row['diagnostic_excluded_from_budget']=True
                write(out/'summary.json',summary)
                print(json.dumps({'round':number,'label':label,'stages':row['stages']}),flush=True)
            finally:git('worktree','remove','--force',str(checkout))
        assert all(r['environment']==summary['rounds'][0]['environment'] for r in summary['rounds'])
        assert len({r['schema'] for r in summary['rounds']})==4
        assert len({r['journey']['schema'] for r in summary['rounds']})==4
        assert all(r['journey']['environment']==summary['rounds'][0]['journey']['environment'] for r in summary['rounds'])
        summary['budget']=evaluate(summary['rounds'])
        if not summary['budget']['meets_budget']:
            summary['status']='REJECT_BUDGET_NOT_MET';return 1
        if not summary['budget']['candidate_100_pass']:
            summary['status']='REJECT_100_ACTOR_P95';return 1
        summary['formal_repetitions']=[]
        for number in (1,2):
            row=run_round(ROOT,out/f'formal-{number}',head,summary['candidate_application_tree'])
            summary['formal_repetitions'].append(row);write(out/'summary.json',summary)
            if not all(s['pass'] for s in row['stages']):
                summary['status']='REJECT_FIXED_4X4_REVALIDATION';return 1
        summary['status']='PASS_FIXED_4X4_SYNTHETIC_SCOPE_NOT_RELEASE';return 0
    except Exception as exc:
        summary.update(status='INVALID_OR_INCOMPLETE_NOT_ACCEPTED',error_type=type(exc).__name__)
        raise
    finally:
        write(out/'summary.json',summary)
        write(out/'SHA256.json',{str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file() and p!=out/'SHA256.json'})

if __name__=='__main__':raise SystemExit(main())
