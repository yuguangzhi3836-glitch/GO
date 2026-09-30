"""Isolated process/pool factorial experiment. Never a formal capacity gate.

Reuses the frozen correctness/workload implementation; application and formal
harness remain unchanged. Every configuration gets fresh processes and schema.
"""
from pathlib import Path
import argparse, hashlib, json, math, os, signal, subprocess, sys, threading, time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'ci/multi_instance'))
import importlib.util
_spec=importlib.util.spec_from_file_location('frozen_multi_instance_run',ROOT/'ci/multi_instance/run.py')
base=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(base)

MODE='PROCESS_POOL_ATTRIBUTION_NOT_ACCEPTANCE'
APP_TREE='6570b66bc977f89c0311d67bdc6b721cd70d4e09'
CONFIGS=((2,4),(4,2),(2,8),(4,4))

def partition(tasks,instances):
    assert instances in (2,4) and tasks
    return [tasks[i::instances] for i in range(min(instances,len(tasks)))]

class ProcessRunner(base.Runner):
    def launch(self,tasks):
        self.counter+=1;stem=self.out/f'group-{self.counter}'
        job={'tasks':tasks,'start':str(stem)+'.start','ready':str(stem)+'.ready','result':str(stem)+'.json'}
        path=Path(str(stem)+'.job');base.write(path,job)
        env=dict(os.environ,DATABASE_POOL_SIZE=os.environ['GO_PROCESS_POOL_SIZE'])
        with Path(str(stem)+'.log').open('w') as log:
            proc=subprocess.Popen([sys.executable,base.__file__,'--child',str(path)],env=env,stdout=log,stderr=subprocess.STDOUT)
        self.processes.append(proc);return proc,job
    def group(self,tasks):
        import resource
        cpu_before=resource.getrusage(resource.RUSAGE_CHILDREN)
        instances=int(os.environ['GO_PROCESS_POOL_INSTANCES'])
        jobs=[self.launch(group) for group in partition(tasks,instances)]
        stop=threading.Event(); samples=[]; sampler=None
        diagnostic=os.environ.get('GO_MULTI_DIAGNOSTIC')=='1' and all(t['op']=='ride' for t in tasks)
        if diagnostic:
            def sample():
                from sqlalchemy import create_engine,text
                engine=create_engine(os.environ['DATABASE_URL'],pool_size=1,max_overflow=0)
                try:
                    with engine.connect() as c:
                        while not stop.is_set():
                            rows=c.execute(text("select state,wait_event_type,wait_event,count(*) from pg_stat_activity where application_name=:name and pid<>pg_backend_pid() group by 1,2,3"),{'name':os.environ['GO_PROCESS_POOL_DB_NAME']}).all()
                            samples.append({'monotonic_ns':time.monotonic_ns(),'rows':[list(r) for r in rows]})
                            c.commit();stop.wait(.05)
                except Exception as exc:
                    samples.append({'error_type':type(exc).__name__})
                finally:engine.dispose()
            sampler=threading.Thread(target=sample);sampler.start()
        try:
            for p,j in jobs:base.wait_file(Path(j['ready']))
            for p,j in jobs:Path(j['start']).touch()
            rows=[]
            for p,j in jobs:
                assert p.wait(timeout=180)==0,'SERVICE_PROCESS_FAILED'
                rows+=json.loads(Path(j['result']).read_text())
            assert len({r['pid'] for r in rows})==min(instances,len(tasks))
            if all(t['op']=='ride' for t in tasks):
                cpu_after=resource.getrusage(resource.RUSAGE_CHILDREN)
                base.write(self.out/f'lifetime-cpu-{len(tasks)}.json',{'process_ids':sorted({r['pid'] for r in rows}),'cpu_seconds':cpu_after.ru_utime+cpu_after.ru_stime-cpu_before.ru_utime-cpu_before.ru_stime,'scope':'Whole service-child process lifetimes, includes imports; excludes PostgreSQL and coordinator'})
            return rows
        finally:
            stop.set()
            if sampler:
                sampler.join(20)
                assert not sampler.is_alive(),'DATABASE_SAMPLER_STUCK'
                base.write(self.out/f'postgres-waits-{len(tasks)}.json',samples)
            for p,j in jobs:
                if p.poll() is None:p.kill();p.wait()

def validate(folder,instances,pool,diagnostic,head):
    read=lambda name:json.loads((folder/name).read_text())
    manifest=read('SHA256.json')
    for name,digest in manifest.items():
        path=(folder/name).resolve();assert path.is_relative_to(folder.resolve())
        assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
    binding=read('binding.json'); result=read('result.json')
    assert binding['head']==head and binding['application_tree']==APP_TREE
    assert (binding['instances'],binding['pool_per_instance'])==(instances,pool)
    assert binding['diagnostic']==diagnostic and binding['max_overflow']==0
    assert binding['worker_connection_budget']==instances*pool
    assert result['mode']==binding['mode']==MODE
    assert result['correctness']=='PASS' and len(read('correctness.json')['scenarios'])==13
    assert [s['concurrent_transactions'] for s in result['stages']]==[20,100]
    assert result['status'] in ('STOPPED_AT_FAILED_TIER','EXPERIMENT_PLAN_COMPLETE_NOT_CAPACITY_ACCEPTANCE')
    assert read('exit.json')['exit_code']==(1 if result['status']=='STOPPED_AT_FAILED_TIER' else 0)
    stages=[]
    for stage in result['stages']:
        n=stage['concurrent_transactions'];rows=read(f'load-{n}.json')
        assert len(rows)==n and all(r['ok'] for r in rows)
        pids=sorted({r['pid'] for r in rows});assert len(pids)==instances and pids==stage['process_ids']
        events=sorted([(r['start_ns'],1) for r in rows]+[(r['end_ns'],-1) for r in rows])
        active=peak=0
        for _,delta in events:active+=delta;peak=max(peak,active)
        assert peak==n,'ACTUAL_OVERLAP_SHORTFALL'
        durations=sorted(r['duration_ms'] for r in rows)
        assert all(math.isclose(r['duration_ms'],(r['end_ns']-r['start_ns'])/1e6) for r in rows)
        assert stage['p95_ms']==durations[math.ceil(n*.95)-1] and stage['p99_ms']==durations[math.ceil(n*.99)-1]
        assert stage['errors']==0 and stage['sql']=='PASS'
        assert stage['pass']==(stage['p95_ms']<=5000 and stage['p99_ms']<=10000)
        if n==20:assert stage['pass'],'STOP_AT_20_FAILURE'
        facts=read(f'ride-sql-{n}.json');assert len(facts)==(20 if n==20 else 120)
        assert {r['value']['order_id'] for r in rows}<={f['order_id'] for f in facts}
        for f in facts:
            assert f['order_status']==f['trips_state']=='COMPLETED'
            assert f['attempts']==1 and f['ledger_entries']==2
            assert f['capture_amount_minor']==f['ledger_debit_minor']==f['ledger_credit_minor']==16800
        counters=[json.loads(f.read_text()) for f in folder.glob('*.resources.json')]
        counters=[c for c in counters if c['pid'] in pids];assert len(counters)==instances
        stage=dict(stage,application_cpu_seconds=sum(c['user_cpu_seconds']+c['system_cpu_seconds'] for c in counters),sum_worker_max_rss_kib=sum(c['max_rss_kib'] for c in counters))
        lifetime=read(f'lifetime-cpu-{n}.json');assert lifetime['process_ids']==pids
        stage['lifetime_cpu_seconds']=lifetime['cpu_seconds']
        if diagnostic:
            samples=read(f'postgres-waits-{n}.json');assert samples and not any('error_type' in x for x in samples)
        stages.append(stage)
    return {'instances':instances,'pool_per_instance':pool,'diagnostic':diagnostic,'schema':binding['schema'],'stages':stages,'environment':binding['environment']}

def main():
    p=argparse.ArgumentParser();p.add_argument('--coordinator',type=Path);p.add_argument('--instances',type=int,choices=(2,4));p.add_argument('--pool',type=int,choices=(2,4,8));p.add_argument('--diagnostic',action='store_true');p.add_argument('--out',type=Path);args=p.parse_args()
    sys.addaudithook(base.guard)
    if args.coordinator:
        base.Runner=ProcessRunner
        code=base.coordinator(args.coordinator)
        result=json.loads((args.coordinator/'result.json').read_text())
        result.update(mode=MODE,scope='Isolated synthetic cold service actors; factorial attribution only, not HTTP or capacity acceptance')
        base.write(args.coordinator/'result.json',result);return code
    if (args.instances,args.pool) not in CONFIGS or args.out is None:p.error('Explicit supported factorial configuration and output required')
    if args.out.resolve()==(ROOT/'multi-instance-evidence').resolve():p.error('Formal evidence directory is forbidden')
    from sqlalchemy import create_engine,text
    from sqlalchemy.engine import make_url
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    assert head==os.environ['EXPECTED_HEAD']
    assert subprocess.check_output(['git','rev-parse','HEAD:application'],cwd=ROOT,text=True).strip()==APP_TREE
    assert not subprocess.check_output(['git','diff','HEAD','--','application'],cwd=ROOT)
    url=make_url(os.environ['GO_MULTI_DATABASE_URL'])
    assert (url.drivername,url.host,url.port,url.username,url.database)==('postgresql+psycopg','127.0.0.1',5432,'go_ci','go_c11_isolated') and not url.query
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    schema='mi_'+uuid4().hex;db_name='process_pool_'+schema
    engine=create_engine(url,pool_size=1,max_overflow=0);code=1
    from importlib.metadata import distributions
    environment={'python':sys.version,'cpu_count':os.cpu_count(),'affinity':sorted(os.sched_getaffinity(0)),'packages':{d.metadata['Name']:d.version for d in distributions() if d.metadata.get('Name')}}
    try:
        with engine.begin() as c:
            environment['database_version']=c.scalar(text('select version()'))
            c.execute(text('CREATE SCHEMA '+schema))
        base.write(out/'binding.json',{'head':head,'application_tree':APP_TREE,'schema':schema,'instances':args.instances,'pool_per_instance':args.pool,'worker_connection_budget':args.instances*args.pool,'max_overflow':0,'diagnostic':args.diagnostic,'mode':MODE,'plan':[20,100],'p95_gate_ms':5000,'p99_gate_ms':10000,'switch_interval_ms':5,'environment':environment,'database_sampler_connections':1 if args.diagnostic else 0,'scope':'cold synthetic service actors, not HTTP; PostgreSQL CPU excluded from application CPU'})
        env={k:os.environ[k] for k in ('PATH','LANG','LC_ALL','TZ') if k in os.environ}
        env.update(GO_PROCESS_POOL_INSTANCES=str(args.instances),GO_PROCESS_POOL_DB_NAME=db_name,GO_MULTI_POOL_EXPERIMENT='1',GO_MULTI_SWITCH_INTERVAL_MS='5',GO_MULTI_DIAGNOSTIC='1' if args.diagnostic else '0',GO_MULTI_ADMISSION_LIMIT='0',DATABASE_URL=url.update_query_dict({'options':'-csearch_path='+schema+' -cstatement_timeout=15000 -clock_timeout=10000 -cidle_in_transaction_session_timeout=30000','connect_timeout':'5','application_name':db_name}).render_as_string(hide_password=False),APP_ENV='test',MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED='false',TRAVEL_INTELLIGENCE_ENABLED='false',DATABASE_POOL_SIZE=str(args.pool),DATABASE_MAX_OVERFLOW='0',DATABASE_POOL_TIMEOUT_SECONDS='10',PYTHONPATH=str(ROOT/'application/src'),GO_RIDE_ISOLATED_CANCELLATION_POLICY_FILE=str(ROOT/'application/scripts/fixtures/ride-cancellation.synthetic.json'))
        env['GO_PROCESS_POOL_SIZE']=str(args.pool)
        env['DATABASE_POOL_SIZE']='5'  # coordinator held constant across variants
        with (out/'coordinator.log').open('w') as log:
            proc=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--coordinator',str(out)],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            try:code=proc.wait(timeout=1200)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait();code=124
    finally:
        with engine.begin() as c:c.execute(text('DROP SCHEMA IF EXISTS '+schema+' CASCADE'))
        engine.dispose();base.write(out/'exit.json',{'exit_code':code})
        base.write(out/'SHA256.json',{str(f.relative_to(out)):hashlib.sha256(f.read_bytes()).hexdigest() for f in out.rglob('*') if f.is_file() and f.name!='SHA256.json'})
    return code

if __name__=='__main__':raise SystemExit(main())
