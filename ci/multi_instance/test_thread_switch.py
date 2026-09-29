"""Fail-closed experiment boundaries; no application/database needed."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parent))
import run
from thread_switch_experiment import MODE, validate_round


def test_default_keeps_interpreter_and_full_plan(monkeypatch):
    monkeypatch.delenv('GO_MULTI_SWITCH_INTERVAL_MS',raising=False)
    original=sys.getswitchinterval()
    assert run.configure_worker_switch_interval() is None
    assert sys.getswitchinterval()==original
    assert run.plan_for(0)==[20,100,250,500,1000]
    assert run.plan_for(0,switch_experiment=True)==[20,100]


@pytest.mark.parametrize('interval',[1,5])
def test_fresh_child_applies_requested_interval(interval):
    script="import os,run,sys,json; os.environ['GO_MULTI_SWITCH_INTERVAL_MS']=sys.argv[1]; observed=run.configure_worker_switch_interval(); print(json.dumps([observed,sys.getswitchinterval()*1000]))"
    output=subprocess.check_output([sys.executable,'-c',script,str(interval)],cwd=Path(run.__file__).parent,text=True)
    assert json.loads(output)==pytest.approx([interval,interval])


@pytest.mark.parametrize('interval',['0','2','-1','1.0'])
def test_invalid_child_interval_fails_before_mutation(monkeypatch,interval):
    original=sys.getswitchinterval()
    monkeypatch.setenv('GO_MULTI_SWITCH_INTERVAL_MS',interval)
    with pytest.raises(ValueError,match='INVALID_SWITCH_EXPERIMENT_INTERVAL'):
        run.configure_worker_switch_interval()
    assert sys.getswitchinterval()==original


@pytest.mark.parametrize('extra',[
    [],['--out',str(run.ROOT/'multi-instance-evidence'/'..'/'multi-instance-evidence')],
    ['--out','experiment','--diagnostic'],
    ['--out','experiment','--pool-comparison-control'],
    ['--out','experiment','--experimental-pool-size','10'],
    ['--out','experiment','--admission-active-per-instance','2'],
])
def test_mixed_or_normal_output_rejected_before_database_access(extra):
    result=subprocess.run([sys.executable,str(run.__file__),'--experimental-switch-interval-ms','1',*extra],text=True,capture_output=True)
    assert result.returncode==2
    assert 'experiment' in result.stderr and 'Traceback' not in result.stderr


def evidence(folder):
    """Minimal raw two-tier example for evidence verifier mutation tests."""
    def put(name,value):
        (folder/name).write_text(json.dumps(value))
    binding=dict(head='head',application_tree='tree',experiment_mode=MODE,
        worker_switch_interval_ms=1,coordinator_switch_interval_ms=5,
        plan=[20,100],instances=2,pool_per_instance=5,max_overflow=0,
        admission_active_per_instance=0,p95_gate_ms=5000,p99_gate_ms=10000,
        diagnostic_instrumentation=False,schema='mi_test')
    binding.update({k:'fixture' for k in ('cpu_count','cpu_model','database_version','installed_packages','python','max_connections','psycopg_implementation')})
    put('binding.json',binding)
    put('correctness.json',{'status':'PASS','scenarios':[{}]*13})
    put('exit.json',{'exit_code':1})
    facts=[];stages=[]
    for n in (20,100):
        pids=[n,n+1];latency=2000 if n==20 else 8000
        rows=[dict(pid=pids[i%2],ok=True,start_ns=1,end_ns=1+latency*1000000,duration_ms=latency,
                   worker_switch_interval_ms=1,value={'order_id':f'{n}-{i}'}) for i in range(n)]
        for row in rows:
            facts.append(dict(order_id=row['value']['order_id'],order_status='COMPLETED',trips_state='COMPLETED',
                attempts=1,ledger_entries=2,capture_amount_minor=16800,ledger_debit_minor=16800,ledger_credit_minor=16800))
        put(f'load-{n}.json',rows);put(f'ride-sql-{n}.json',facts)
        stages.append(dict(concurrent_transactions=n,transactions=n,process_ids=pids,
            p95_ms=latency,p99_ms=latency,errors=0,sql='PASS',**{'pass':n==20}))
        for pid in pids:
            put(f'group-{pid}.job',{'result':f'/original/ci/path/group-{pid}.json'})
            put(f'group-{pid}.json.runtime.json',dict(pid=pid,phase='BEFORE_THREADS',coordinator_unchanged=True,worker_switch_interval_ms=1))
            put(f'group-{pid}.json.resources.json',dict(pid=pid,worker_switch_interval_ms=1))
    put('result.json',dict(correctness='PASS',mode=MODE,stages=stages,status='STOPPED_AT_FAILED_TIER',coordinator_switch_interval_ms=5))
    return put


def manifest(folder):
    (folder/'SHA256.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest()
        for p in folder.iterdir() if p.name!='SHA256.json'}))


def test_relocated_complete_evidence_validates(tmp_path):
    evidence(tmp_path);manifest(tmp_path)
    row=validate_round(tmp_path,1,'head','tree',1)
    assert row['correctness']=='PASS' and row['status']=='STOPPED_AT_FAILED_TIER'


@pytest.mark.parametrize('change',['digest','worker_interval','percentile','money','correctness','exit_code','skipped_tier'])
def test_tampered_or_incomplete_evidence_rejected(tmp_path,change):
    put=evidence(tmp_path);manifest(tmp_path)
    if change in ('digest','worker_interval'):
        path=tmp_path/'load-100.json';rows=json.loads(path.read_text());rows[0]['worker_switch_interval_ms']=5;put(path.name,rows)
    elif change=='money':
        path=tmp_path/'ride-sql-100.json';rows=json.loads(path.read_text());rows[0]['ledger_credit_minor']=1;put(path.name,rows)
    elif change=='exit_code':put('exit.json',{'exit_code':0})
    elif change=='correctness':put('correctness.json',{'status':'FAIL','scenarios':[{}]*13})
    else:
        data=json.loads((tmp_path/'result.json').read_text())
        if change=='percentile':data['stages'][1]['p95_ms']=4999
        else:data['stages'].pop()
        put('result.json',data)
    if change!='digest':manifest(tmp_path)
    with pytest.raises(AssertionError):validate_round(tmp_path,1,'head','tree',1)
