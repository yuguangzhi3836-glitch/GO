"""Isolated 5/1/1/5-ms worker scheduling experiment, never capacity acceptance."""
from pathlib import Path
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
ORDER = (5, 1, 1, 5)
MODE = 'THREAD_SWITCH_EXPERIMENT_NOT_ACCEPTANCE'


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def read(path):
    return json.loads(path.read_text())


def validate_round(folder, requested, head, tree, code):
    """Check raw evidence, not just the coordinator's summary labels."""
    manifest=read(folder/'SHA256.json')
    assert manifest and all(hashlib.sha256((folder/p).read_bytes()).hexdigest()==h
                           for p,h in manifest.items()), 'EVIDENCE_DIGEST_MISMATCH'
    binding=read(folder/'binding.json'); result=read(folder/'result.json')
    assert binding['head']==head and binding['application_tree']==tree
    assert binding['experiment_mode']==result['mode']==MODE
    assert binding['worker_switch_interval_ms']==requested
    assert math.isclose(binding['coordinator_switch_interval_ms'],5)
    assert math.isclose(result['coordinator_switch_interval_ms'],5)
    assert binding['plan']==[20,100] and binding['instances']==2
    assert binding['pool_per_instance']==5 and binding['max_overflow']==0
    assert binding['admission_active_per_instance']==0
    assert binding['p95_gate_ms']==5000 and binding['p99_gate_ms']==10000
    assert binding['diagnostic_instrumentation'] is False
    correctness=read(folder/'correctness.json')
    assert result['correctness']==correctness['status']=='PASS'
    assert len(correctness['scenarios'])==13
    assert [s['concurrent_transactions'] for s in result['stages']]==[20,100]
    assert result['status'] in ('STOPPED_AT_FAILED_TIER','EXPERIMENT_PLAN_COMPLETE_NOT_CAPACITY_ACCEPTANCE')
    assert code==read(folder/'exit.json')['exit_code']==(1 if result['status']=='STOPPED_AT_FAILED_TIER' else 0)
    jobs=list(folder.glob('group-*.job'))
    assert jobs
    for path in jobs:
        runtime=read(folder/(Path(read(path)['result']).name+'.runtime.json'))
        assert runtime['phase']=='BEFORE_THREADS' and runtime['coordinator_unchanged']
        assert math.isclose(runtime['worker_switch_interval_ms'],requested)
    resources=[]
    total=0
    for stage in result['stages']:
        n=stage['concurrent_transactions']; total+=n
        rows=read(folder/f'load-{n}.json')
        assert len(rows)==stage['transactions']==n and all(r['ok'] for r in rows)
        pids=sorted({r['pid'] for r in rows})
        assert len(pids)==2 and pids==stage['process_ids']
        assert all(math.isclose(r['worker_switch_interval_ms'],requested) for r in rows)
        assert all(math.isclose(r['duration_ms'],(r['end_ns']-r['start_ns'])/1e6) for r in rows)
        latency=sorted(r['duration_ms'] for r in rows)
        assert latency[math.ceil(n*.95)-1]==stage['p95_ms']
        assert latency[math.ceil(n*.99)-1]==stage['p99_ms']
        assert stage['errors']==0 and stage['sql']=='PASS'
        assert stage['pass']==(stage['p95_ms']<=5000 and stage['p99_ms']<=10000)
        if n==20:assert stage['pass'], 'CONTROL_20_FAILED'
        else:assert stage['pass']==(result['status']=='EXPERIMENT_PLAN_COMPLETE_NOT_CAPACITY_ACCEPTANCE')
        facts=read(folder/f'ride-sql-{n}.json')
        assert len(facts)==total
        assert {r['value']['order_id'] for r in rows} <= {f['order_id'] for f in facts}
        for fact in facts:
            assert fact['order_status']==fact['trips_state']=='COMPLETED'
            assert fact['attempts']==1 and fact['ledger_entries']==2
            assert fact['capture_amount_minor']==fact['ledger_debit_minor']==fact['ledger_credit_minor']==16800
        counters=[read(p) for p in folder.glob('group-*.resources.json') if read(p)['pid'] in pids]
        assert len(counters)==2 and sorted(c['pid'] for c in counters)==pids
        assert all(math.isclose(c['worker_switch_interval_ms'],requested) for c in counters)
        resources.append({'concurrent_transactions':n,'processes':counters})
    return {'worker_switch_interval_ms':requested,'head':head,'application_tree':tree,
        'environment':{k:binding[k] for k in ('cpu_count','cpu_model','database_version','installed_packages','python','instances','max_connections','psycopg_implementation')},
        'schema':binding['schema'],'correctness':result['correctness'],
        'status':result['status'],'stages':result['stages'],'resources':resources,'exit_code':code}


def main():
    head=os.environ['EXPECTED_HEAD']
    out=ROOT/'multi-thread-switch-evidence';out.mkdir(exist_ok=False)
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()==head
    tree=subprocess.check_output(['git','rev-parse','HEAD:application'],cwd=ROOT,text=True).strip()
    summary={'head':head,'application_tree':tree,'order_ms':ORDER,
        'harness_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (ROOT/'ci/multi_instance').glob('*.py')},
        'per_call_profiling':False,'process_boundary_counters':True,
        'scope':'Same-runner two-process PostgreSQL experiment; all service children use requested interval, coordinator unchanged. Full cold synthetic RIDE actors, pool 5, zero overflow. No HTTP, real supplier/PSP or production capacity acceptance.',
        'rounds':[],'status':'RUNNING'}
    write(out/'summary.json',summary)
    try:
        for number,interval in enumerate(ORDER,1):
            folder=out/f'{number}-switch-{interval}ms'
            code=subprocess.call([sys.executable,str(ROOT/'ci/multi_instance/run.py'),
                '--out',str(folder),'--experimental-switch-interval-ms',str(interval)],cwd=ROOT)
            row=validate_round(folder,interval,head,tree,code)
            row['number']=number;summary['rounds'].append(row)
            write(out/'summary.json',summary)
            print(json.dumps({'number':number,'interval_ms':interval,'stages':row['stages']}),flush=True)
        rounds=summary['rounds']
        assert all(r['environment']==rounds[0]['environment'] for r in rounds),'ENVIRONMENT_CHANGED'
        assert len({r['schema'] for r in rounds})==4,'SCHEMA_REUSED'
        summary['p95_ms']={str(interval):{str(n):{
            'median':statistics.median(values),'min':min(values),'max':max(values)}
            for n in (20,100)
            for values in [[s['p95_ms'] for r in rounds if r['worker_switch_interval_ms']==interval
                            for s in r['stages'] if s['concurrent_transactions']==n]]}
            for interval in (5,1)}
        summary['status']='COMPARISON_COMPLETE_EXPERIMENT_ONLY'
        return 0
    except Exception as exc:
        summary.update(status='COMPARISON_INVALID_OR_CORRECTNESS_FAILED',error_type=type(exc).__name__,error=str(exc)[:300])
        raise
    finally:
        write(out/'summary.json',summary)
        write(out/'SHA256.json',{str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in out.rglob('*') if p.is_file() and p!=out/'SHA256.json'})


if __name__=='__main__':raise SystemExit(main())
