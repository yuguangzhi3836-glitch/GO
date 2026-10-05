"""Machine-only safety then fixed-host ABBA. Never dispatches AI or deployment.

Full transaction = real RIDE order, payment AUTH/CAPTURE, synthetic supplier fact,
service START/COMPLETE and final query. HTTP/auth/external providers are excluded,
as in the earlier service-journey experiment; this cannot prove production SLOs.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import signal
import statistics
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import uuid

from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

PROCESSES = 4
POOL = 4
BATCHES = 4


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, sort_keys=True, indent=2)); temp.replace(path)


def database_url():
    assert os.environ.get('PGDATABASE') == 'c13_lite'
    return URL.create('postgresql+psycopg', username=os.environ['PGUSER'],
        password=os.environ['PGPASSWORD'], host=os.environ['PGHOST'],
        port=int(os.environ.get('PGPORT', '5432')), database='c13_lite')


def runtime(schema, tag, pool=POOL):
    assert schema.startswith('c11_reuse_') and schema[10:].isalnum()
    url = database_url()
    os.environ['DATABASE_URL'] = url.render_as_string(hide_password=False)
    os.environ['APP_ENV'] = 'test'
    engine = create_engine(url, hide_parameters=True, pool_pre_ping=True,
        pool_size=pool, max_overflow=0, pool_timeout=30,
        connect_args={'application_name': tag, 'connect_timeout': 10,
            'options': '-csearch_path=' + schema + ' -cstatement_timeout=30000 -clock_timeout=15000'})
    from go_hotel.db import session as db
    db.engine.dispose(); db.engine = engine
    db.SessionLocal.configure(bind=engine)
    return engine


def bridge(iid):
    from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge
    return vertical_transaction_bridge.checkout_contract('FLIGHT', iid,
        'diagnostic-payer', 'isolated-source', 'isolated://reuse', 'isolated-method')


def fault_worker(spec):
    engine = runtime(spec['schema'], spec['tag'], 1)
    from go_hotel.services.unified_money_movement import unified_money_movement_service as money
    original = money.create_in_session
    connections = []; sessions = []; commits = []; fired = False

    def boundary():
        nonlocal fired
        if fired: return
        fired = True
        c = connections[-1]
        print('READY ' + json.dumps({'pid': c.connection.driver_connection.info.backend_pid,
            'movement_id': spec.get('movement_id'), 'boundary': spec['boundary'],
            'connection_reused': len(connections) == 2 and connections[0] is connections[1],
            'sessions_distinct': len(sessions) == 2 and sessions[0] is not sessions[1]}), flush=True)
        assert sys.stdin.readline().strip() == 'resume'

    def observe(s, iid, body, key, actor):
        connections.append(s.connection()); sessions.append(s)
        s.info['money_type'] = body['movement_type']
        result = original(s, iid, body, key, actor)
        if body['movement_type'] == spec['typ']:
            spec['movement_id'] = result['money_movement_id']
            if spec['boundary'] == 'before_commit': boundary()
        return result

    def committed(s):
        typ = s.info.get('money_type')
        if typ:
            commits.append(typ)
            if typ == spec['typ'] and spec['boundary'] == 'after_commit': boundary()

    money.create_in_session = observe
    event.listen(Session, 'after_commit', committed)
    invalidated = False; completed = False
    try:
        try:
            bridge(spec['iid']); completed = True
        except DBAPIError as exc:
            assert fired and exc.connection_invalidated
            invalidated = True
        assert fired
        assert invalidated or (completed and spec['typ'] == 'CAPTURE' and spec['boundary'] == 'after_commit')
        if spec['typ'] == 'CAPTURE':
            assert len(connections) == 2 and connections[0] is connections[1]
            assert sessions[0] is not sessions[1]
        assert engine.pool.checkedout() == 0
        with engine.connect() as c: assert c.scalar(text('select 1')) == 1
        print('OBSERVED ' + json.dumps({'invalidated': invalidated, 'completed': completed,
            'commits': commits, 'pool_released': engine.pool.checkedout() == 0,
            'fresh_connection': True}), flush=True)
    finally:
        event.remove(Session, 'after_commit', committed)
        money.create_in_session = original
        engine.dispose()


def safety(schema, admin, out):
    engine = runtime(schema, 'c11-reuse-safety')
    from go_hotel.db.models import (OmnichannelPaymentIntentRow as Intent,
        OmnichannelMoneyMovementRow as Movement, OmnichannelLedgerEntryRow as Ledger,
        CatalogCreditSourceRow, OrderSupplierFulfillmentRow, OrderSupplierFulfillmentEventRow,
        VerticalSourceDecisionRow)
    tables = [m.__table__ for m in (Intent, Movement, Ledger, CatalogCreditSourceRow,
        OrderSupplierFulfillmentRow, OrderSupplierFulfillmentEventRow, VerticalSourceDecisionRow)]
    Intent.metadata.create_all(engine, tables=tables)
    facts = []
    try:
        for mode in ('disconnect', 'SIGKILL'):
            for typ in ('AUTHORIZATION', 'CAPTURE'):
                for point in ('before_commit', 'after_commit'):
                    iid = 'reuse_' + uuid.uuid4().hex; tag = 'c11-reuse-' + uuid.uuid4().hex
                    now = datetime.now(timezone.utc)
                    with Session(engine) as s:
                        s.add(Intent(payment_intent_id=iid, business_type='FLIGHT_ORDER', business_id=iid,
                            payer_id='diagnostic-payer', payee_id='diagnostic-payee', operation='PAY',
                            amount_minor=1000, currency='CNY', channel_priority_json=['MOCK'], selected_channel='MOCK',
                            state='SUCCEEDED', idempotency_key=iid, created_at=now, updated_at=now)); s.commit()
                    spec = dict(schema=schema, tag=tag, iid=iid, typ=typ, boundary=point)
                    p = subprocess.Popen([sys.executable, __file__, '--fault', json.dumps(spec)],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    try:
                        with selectors.DefaultSelector() as sel:
                            sel.register(p.stdout, selectors.EVENT_READ)
                            assert sel.select(40), 'FAULT_BARRIER_TIMEOUT'
                            line = p.stdout.readline()
                        assert line.startswith('READY '), 'FAULT_WORKER_START_FAILED'
                        ready = json.loads(line[6:]); pid = ready['pid']
                        if typ == 'CAPTURE': assert ready['connection_reused'] and ready['sessions_distinct']
                        with admin.connect() as c:
                            assert c.scalar(text('select count(*) from pg_stat_activity where pid=:p '
                                'and datname=:d and application_name=:a'), dict(p=pid,d='c13_lite',a=tag)) == 1
                            if mode == 'disconnect':
                                assert c.scalar(text('select pg_terminate_backend(pid) from pg_stat_activity '
                                    'where pid=:p and datname=:d and application_name=:a'),dict(p=pid,d='c13_lite',a=tag))
                        if mode == 'SIGKILL': p.kill()
                        deadline = time.monotonic() + 10
                        while True:
                            with admin.connect() as c:
                                alive = c.scalar(text('select count(*) from pg_stat_activity where pid=:p and application_name=:a'),dict(p=pid,a=tag))
                            if not alive: break
                            assert time.monotonic() < deadline, 'BACKEND_LEAK'
                            time.sleep(.05)
                        stdout, stderr = p.communicate('resume\n' if mode == 'disconnect' else None, timeout=30)
                        if mode == 'SIGKILL':
                            assert p.returncode == -signal.SIGKILL
                            observed = {'signal':'SIGKILL'}
                        else:
                            assert p.returncode == 0, 'FAULT_WORKER_FAILED: ' + stderr[-1500:]
                            observed = json.loads(stdout.split('OBSERVED ',1)[1])
                            assert observed['pool_released'] and observed['fresh_connection']
                        key = ('flight-auth:' if typ == 'AUTHORIZATION' else 'flight-cap:') + iid
                        with Session(engine) as s:
                            before = s.scalar(select(Movement).where(Movement.idempotency_key == key))
                            assert (before is not None) == (point == 'after_commit')
                            if before: assert before.money_movement_id == ready['movement_id']
                            if typ == 'CAPTURE':
                                durable_auth = s.scalar(select(Movement).where(Movement.idempotency_key=='flight-auth:'+iid))
                                assert durable_auth is not None and durable_auth.state=='CONFIRMED'
                            ledger_before = s.scalar(select(func.count()).select_from(Ledger).where(Ledger.payment_intent_id == iid))
                            assert ledger_before == (2 if typ=='CAPTURE' and point=='after_commit' else 0)
                        recovered = bridge(iid); assert bridge(iid) == recovered
                        with ThreadPoolExecutor(max_workers=20) as pool:
                            assert all(r==recovered for r in pool.map(bridge,[iid]*20))
                        from go_hotel.services.unified_money_movement import unified_money_movement_service as money
                        with Session(engine) as s:
                            body = dict(movement_type=typ, amount_minor=999, mode='CONTRACT_SIMULATOR', evidence=['isolated://conflict'])
                            if typ == 'CAPTURE': body['parent_movement_id'] = recovered['authorization_id']
                            try:
                                money.create_in_session(s,iid,body,key,'fault'); raise AssertionError('CONFLICT_ACCEPTED')
                            except ValueError as exc: assert str(exc)=='MONEY_MOVEMENT_IDEMPOTENCY_CONFLICT'
                        with Session(engine) as s:
                            moves = s.scalars(select(Movement).where(Movement.root_payment_intent_id==iid)).all()
                            ledger = s.scalars(select(Ledger).where(Ledger.payment_intent_id==iid)).all()
                            assert len(moves)==2 and len(ledger)==2
                            assert all(m.amount_minor==1000 and m.state=='CONFIRMED' for m in moves)
                            cap = next(m for m in moves if m.movement_type=='CAPTURE')
                            assert cap.parent_movement_id==recovered['authorization_id']
                            assert {r.direction for r in ledger}=={'DEBIT','CREDIT'} and all(r.amount_minor==1000 for r in ledger)
                        assert engine.pool.checkedout()==0
                        facts.append(dict(mode=mode,operation=typ,boundary=point,status='PASS',
                            exact_candidate_path='VerticalTransactionBridge.checkout_contract',
                            connection_reused=ready['connection_reused'],observed=observed))
                        write(out/'safety.json',dict(status='RUNNING',cases=facts))
                    finally:
                        if p.poll() is None: p.kill(); p.communicate(timeout=10)
        assert len(facts)==8
        write(out/'safety.json',dict(status='PASS',cases=facts,
            limits=['known commit boundaries, not ambiguous in-flight COMMIT','socket closure, not prolonged network partition']))
    finally: engine.dispose()


def transaction(index):
    from go_hotel.api.routes.mobility import rb, RideBook, order
    from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge as b
    from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as supplier
    from go_hotel.mobility.ride.service import ride_service
    owner = 'reuse-' + index; principal = SimpleNamespace(user_id=owner)
    phases={}; start=time.perf_counter_ns(); tick=start
    body=RideBook(offer_id='ride_standard',pickup='ISOLATED_A',dropoff='ISOLATED_B',
        pickup_at=(datetime.now(timezone.utc)+timedelta(days=10)).isoformat(),passengers=[])
    created=rb(body,principal,'create-'+index)['data']; oid=created['order_id']
    phases['create_ns']=time.perf_counter_ns()-tick; tick=time.perf_counter_ns()
    payment=b.checkout_contract('RIDE',oid,owner,'ride-engineering-source','isolated://reuse/'+oid,'isolated-method')
    phases['payment_ns']=time.perf_counter_ns()-tick; tick=time.perf_counter_ns()
    supplier.record_supplier_fact(payment['supplier_fulfillment_id'],dict(state='SUPPLIER_CONFIRMED',
        external_operation_id=owner,supplier_confirmation_reference=owner,evidence_reference='isolated://supplier/'+oid))
    ride_service.fulfill(owner,oid,'START','isolated://start');ride_service.fulfill(owner,oid,'COMPLETE','isolated://complete')
    phases['fulfill_ns']=time.perf_counter_ns()-tick;tick=time.perf_counter_ns()
    result=order(oid,principal)['data']
    assert result['status']=='COMPLETED' and result['total_amount_minor']==16800 and result['currency']=='CNY'
    phases['query_ns']=time.perf_counter_ns()-tick
    return dict(index=index,order_id=oid,root=payment['payment_intent_id'],start_ns=start,end_ns=time.perf_counter_ns(),phases=phases)


def wait_file(path, processes=(), timeout=120):
    deadline=time.monotonic()+timeout
    while not path.exists():
        assert all(p.poll() is None for p in processes),'WORKER_EXITED'
        assert time.monotonic()<deadline,'WORKER_TIMEOUT'
        time.sleep(.01)


def benchmark_worker(job):
    engine=runtime(job['schema'],job['tag']);folder=Path(job['folder']);release=Path(job['release'])
    # Import the actual endpoints, but do not warm mappers or connections.
    from go_hotel.api.routes.mobility import rb
    from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge
    assert engine.pool.checkedin()==0
    write(folder/'ready.json',dict(pid=os.getpid()))
    try:
        with ThreadPoolExecutor(max_workers=job['actors']) as pool:
            for batch in range(BATCHES):
                barrier=threading.Barrier(job['actors']+1);go=threading.Event()
                def work(i):
                    barrier.wait(60); assert go.wait(120)
                    return transaction(f"{job['prefix']}-{batch}-{job['worker']}-{i}")
                futures=[pool.submit(work,i) for i in range(job['actors'])]
                barrier.wait(60);write(folder/f'{batch}.ready',{})
                wait_file(release/f'{batch}.go')
                cpu_start=time.process_time_ns();go.set()
                rows=[f.result(timeout=90) for f in futures]
                cpu=time.process_time_ns()-cpu_start
                assert engine.pool.checkedout()==0
                write(folder/f'{batch}.json',dict(rows=rows,cpu_ns=cpu,pid=os.getpid()))
    finally: engine.dispose()


def summary(rows):
    ns=sorted(r['end_ns']-r['start_ns'] for r in rows)
    events=sorted([(r['start_ns'],1) for r in rows]+[(r['end_ns'],-1) for r in rows])
    active=peak=0
    for _,delta in events:active+=delta;peak=max(active,peak)
    return dict(count=len(rows),p95_ms=ns[math.ceil(len(ns)*.95)-1]/1e6,
        p99_ms=ns[math.ceil(len(ns)*.99)-1]/1e6,peak_inflight=peak)


def verify_ledger(engine, rows):
    from go_hotel.db.models import OmnichannelMoneyMovementRow as M,OmnichannelLedgerEntryRow as L
    with Session(engine) as s:
        for row in rows:
            moves=s.scalars(select(M).where(M.root_payment_intent_id==row['root'])).all()
            ledger=s.scalars(select(L).where(L.payment_intent_id==row['root'])).all()
            assert len(moves)==2 and len(ledger)==2
            auth=next(m for m in moves if m.movement_type=='AUTHORIZATION')
            cap=next(m for m in moves if m.movement_type=='CAPTURE')
            assert cap.parent_movement_id==auth.money_movement_id
            assert all(m.amount_minor==16800 and m.state=='CONFIRMED' for m in moves)
            assert {r.direction for r in ledger}=={'DEBIT','CREDIT'}
            assert all(r.amount_minor==16800 and r.transaction_id==cap.money_movement_id for r in ledger)


def arm(n, label, source, admin, out):
    schema='c11_reuse_'+uuid.uuid4().hex;folder=out/f'{n}-{label}';folder.mkdir()
    with admin.begin() as c:c.execute(text('CREATE SCHEMA '+schema))
    engine=runtime(schema,'c11-reuse-setup');processes=[]
    from go_hotel.db.models import Base
    try:
        Base.metadata.create_all(engine)
        for w in range(PROCESSES):
            child=folder/str(w);child.mkdir()
            job=dict(schema=schema,tag=f'c11bench-{schema}-{w}',folder=str(child),release=str(folder),
                actors=n//PROCESSES,worker=w,prefix=f'{n}-{label}')
            log=(child/'worker.log').open('w')
            p=subprocess.Popen([sys.executable,__file__,'--worker',json.dumps(job)],
                env=dict(os.environ,PYTHONPATH=str(source)),stdout=log,stderr=subprocess.STDOUT)
            log.close();processes.append(p)
        for w in range(PROCESSES):wait_file(folder/str(w)/'ready.json',processes)
        results=[]
        for batch in range(BATCHES):
            for w in range(PROCESSES):wait_file(folder/str(w)/f'{batch}.ready',processes)
            write(folder/f'{batch}.go',{})
            waits=[];deadline=time.monotonic()+120
            while not all((folder/str(w)/f'{batch}.json').exists() for w in range(PROCESSES)):
                assert all(p.poll() is None or p.returncode==0 for p in processes),'WORKER_FAILED'
                assert time.monotonic()<deadline,'BATCH_TIMEOUT'
                with admin.connect() as c:
                    sample=c.execute(text("select wait_event_type,wait_event,count(*) from pg_stat_activity "
                        "where application_name like :a and state='active' group by wait_event_type,wait_event"),
                        dict(a='c11bench-'+schema+'-%')).all()
                    waits.append({'at_ns':time.perf_counter_ns(),'active_waits':[list(r) for r in sample]})
                time.sleep(.01)
            parts=[json.loads((folder/str(w)/f'{batch}.json').read_text()) for w in range(PROCESSES)]
            rows=[r for p in parts for r in p['rows']];verify_ledger(engine,rows)
            report=summary(rows)|dict(cpu_ns=sum(p['cpu_ns'] for p in parts),batch=batch,
                mode='cold' if batch==0 else 'continued',rows=rows)
            assert report['count']==n and report['peak_inflight']==n,'CONCURRENCY_NOT_REACHED'
            write(folder/f'{batch}-waits.json',waits);results.append(report)
        for p in processes:assert p.wait(20)==0
        write(folder/'result.json',results)
        return dict(concurrency=n,arm=label,source=str(source),batches=results)
    finally:
        for p in processes:
            if p.poll() is None:p.kill();p.wait()
        engine.dispose()
        with admin.begin() as c:c.execute(text('DROP SCHEMA '+schema+' CASCADE'))


def coordinator(args):
    out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True)
    baseline=Path(args.baseline).resolve();candidate=Path(args.candidate).resolve()
    assert baseline!=candidate and len(os.sched_getaffinity(0))>=4,'FIXED_4_CPU_REQUIRED'
    # Both trees differ in only the proposed production file; never apply a runtime patch.
    prod='go_hotel/services/vertical_transaction_bridge.py'
    def hashes(root):return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (root/'go_hotel').rglob('*.py')}
    a,b=hashes(baseline),hashes(candidate)
    assert set(a)==set(b) and [k for k in a if a[k]!=b[k]]==[prod],'SOURCE_SCOPE_CHANGED'
    admin=create_engine(database_url(),hide_parameters=True,pool_size=2,max_overflow=0)
    result=dict(status='RUNNING',baseline_source=a[prod],candidate_source=b[prod],
        candidate_sha=os.environ['CANDIDATE_SHA'],baseline_sha=os.environ['BASELINE_SHA'],
        config=dict(processes=PROCESSES,pool=POOL,overflow=0,batches=BATCHES,
            affinity=sorted(os.sched_getaffinity(0)),python=sys.version,host=os.uname().nodename),
        scope='RIDE service full transaction, synthetic supplier; excludes HTTP/auth/external latency',
        cold_scope='new application processes/pools, not cold PostgreSQL/OS caches',runs=[],gates=[])
    schema='c11_reuse_'+uuid.uuid4().hex
    try:
        with admin.begin() as c:
            assert c.scalar(text('select current_database()'))=='c13_lite'
            assert c.scalar(text('show server_version_num'))=='180004'
            result['postgres']=c.scalar(text('select version()'))
            c.execute(text('CREATE SCHEMA '+schema))
        try:safety(schema,admin,out)
        finally:
            with admin.begin() as c:c.execute(text('DROP SCHEMA '+schema+' CASCADE'))
        result['safety']='PASS'
        for n in (20,100):
            for label,source in [('A1',baseline),('B1',candidate),('B2',candidate),('A2',baseline)]:
                result['runs'].append(arm(n,label,source,admin,out));write(out/'result.json',result)
            for mode in ('cold','continued'):
                groups={}
                for kind in ('A','B'):
                    runs=[r for r in result['runs'] if r['concurrency']==n and r['arm'].startswith(kind)]
                    batches=[batch for r in runs for batch in r['batches'] if batch['mode']==mode]
                    rows=[row for batch in batches for row in batch['rows']]
                    groups[kind]=summary(rows)|dict(cpu_per_tx_ns=sum(b['cpu_ns'] for b in batches)/len(rows))
                cpu_ratio=groups['B']['cpu_per_tx_ns']/groups['A']['cpu_per_tx_ns']
                p95_ratio=groups['B']['p95_ms']/groups['A']['p95_ms']
                under5=all(b['p95_ms']<=5000 for r in result['runs'] if r['concurrency']==n and r['arm'].startswith('B')
                    for b in r['batches'] if b['mode']==mode)
                result['gates'].append(dict(n=n,mode=mode,baseline=groups['A'],candidate=groups['B'],
                    cpu_ratio=cpu_ratio,p95_ratio=p95_ratio,under5=under5,
                    passed=cpu_ratio<=.80 and p95_ratio<=.85 and (n!=100 or under5)))
        result['status']='PASS' if all(g['passed'] for g in result['gates']) else 'NO_GO'
    except BaseException as exc:
        result['status']='INCOMPLETE';result['error_type']=type(exc).__name__
        raise
    finally:
        write(out/'result.json',result);admin.dispose()
        print('C11_REUSE_RESULT '+json.dumps({k:v for k,v in result.items() if k!='runs'}),flush=True)
    return 0 if result['status']=='PASS' else 2


if __name__=='__main__':
    if sys.argv[1:2]==['--fault']:fault_worker(json.loads(sys.argv[2]))
    elif sys.argv[1:2]==['--worker']:benchmark_worker(json.loads(sys.argv[2]))
    elif sys.argv[1:2]==['--safety-only']:
        out=Path(sys.argv[2]).resolve();out.mkdir(parents=True,exist_ok=True)
        admin=create_engine(database_url(),hide_parameters=True)
        schema='c11_reuse_'+uuid.uuid4().hex
        try:
            with admin.begin() as c:
                assert c.scalar(text('show server_version_num'))=='180004'
                c.execute(text('CREATE SCHEMA '+schema))
            safety(schema,admin,out)
            print('C11_REUSE_SAFETY '+(out/'safety.json').read_text(),flush=True)
        finally:
            with admin.begin() as c:c.execute(text('DROP SCHEMA IF EXISTS '+schema+' CASCADE'))
            admin.dispose()
    else:
        p=argparse.ArgumentParser();p.add_argument('--baseline',required=True);p.add_argument('--candidate',required=True);p.add_argument('--out',required=True)
        sys.exit(coordinator(p.parse_args()))
