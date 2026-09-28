"""Isolated PostgreSQL, independent service processes; no HTTP capacity claim.

Correctness is a prerequisite for each bounded concurrent-transaction tier.
No provider secrets are inherited. Fault injection exists only in this harness.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import platform
import signal
import socket
import subprocess
import sys
import threading
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'application'
PLAN = [20, 100, 250, 500, 1000]

def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str)+'\n')

def guard(event, args):
    if event != 'socket.connect': return
    sock, address = args
    if sock.family == socket.AF_UNIX: return
    try: allowed = ipaddress.ip_address(address[0]).is_loopback
    except ValueError: allowed = address[0] == 'localhost'
    if not allowed: raise PermissionError('ISOLATED_EXTERNAL_EGRESS_FORBIDDEN')

def wait_file(path, seconds=90):
    deadline = time.monotonic()+seconds
    while not path.exists():
        if time.monotonic()>deadline: raise TimeoutError('BARRIER_TIMEOUT')
        time.sleep(.02)

def imports():
    sys.path[:0] = [str(APP/'src'), str(APP/'tests')]
    from go_hotel.db.session import engine
    assert engine.dialect.name == 'postgresql'
    assert engine.url.database == 'go_c11_isolated'
    assert engine.url.host == '127.0.0.1'
    assert engine.url.query['options'].startswith('-csearch_path=mi_')

def action(task):
    from go_hotel.rail.service import rail_service as rail
    from go_hotel.attractions.service import attraction_service as attr
    from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge as bridge
    from go_hotel.services import vertical_capacity as capacity
    from test_depth23_capacity import order
    op=task['op']; v=task.get('vertical','RAIL'); owner=task.get('owner','owner'); oid=task.get('oid')
    svc=rail if v=='RAIL' else attr
    if op=='stock': return order(v,task['quote'],owner)
    if op=='cancel': return capacity.cancel_unpaid(v,owner,oid,rail._order if v=='RAIL' else attr.out)
    if op=='refund' or op=='crash_refund':
        if op=='crash_refund':
            from go_hotel.services import vertical_refund_recovery as recovery
            original=recovery.vertical_money_bridge.refund_with_adjustments
            def crash(*a,**kw):
                result=original(*a,**kw)
                assert result['state']=='CONFIRMED'
                Path(task['marker']).write_text('MONEY_COMMITTED')
                os._exit(71)
            recovery.vertical_money_bridge.refund_with_adjustments=crash
        return svc.refund(owner,oid)
    if op=='pay':
        if task.get('pause'):
            from go_hotel.services.omnichannel_payment import omnichannel_payment_service as payments
            target=payments if task['pause']=='after_root' else bridge
            name='select_channel' if task['pause']=='after_root' else 'checkout_contract'
            original=getattr(target,name)
            def pause(*a,**kw):
                Path(task['marker']).write_text(str(os.getpid()))
                wait_file(Path(task['release']))
                return original(*a,**kw)
            setattr(target,name,pause)
        return bridge.checkout_contract(v,oid,owner,'isolated','isolated://multi-instance')
    if op=='hotel':
        from go_hotel.services.hosted_reservation_operations import hosted_reservation_operations_service as ops
        return ops.reserve(task['slug'],task['body'],task['key'],'GO_PAGE',owner)
    if op=='ride':
        from ride_workload import transaction
        result=transaction(task['index'])
        assert result['outcome']=='SUCCESS', result
        return result
    if op=='create_replay':
        from go_hotel.api.routes.mobility import rb,RideBook
        from types import SimpleNamespace
        return rb(RideBook(**task['body']),SimpleNamespace(user_id=owner),task['key'])
    if op=='capture':
        from go_hotel.services.unified_money_movement import unified_money_movement_service as money
        return money.create(task['iid'],task['body'],task['key'],'isolated')
    raise ValueError('UNKNOWN_TEST_OPERATION')

def child(jobpath):
    imports()
    job=json.loads(jobpath.read_text())
    # Load service modules before marking all worker threads ready.
    import ride_workload
    from go_hotel.rail.service import rail_service
    from go_hotel.attractions.service import attraction_service
    tasks=job['tasks']; ready=threading.Barrier(len(tasks)+1)
    def run(task):
        ready.wait(60); wait_file(Path(job['start']))
        start=time.monotonic_ns()
        result={'task':task['op'],'pid':os.getpid(),'start_ns':start,'ok':False}
        try: result.update(ok=True,value=action(task))
        except Exception as exc:
            result.update(error_type=type(exc).__name__,code=str(exc)[:500] if isinstance(exc,(ValueError,AssertionError)) else 'SEE_ERROR_TYPE')
            if type(exc).__name__=='HTTPException': result.update(code=exc.detail,status=exc.status_code)
        result.update(end_ns=time.monotonic_ns())
        result['duration_ms']=(result['end_ns']-start)/1e6
        return result
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures=[pool.submit(run,t) for t in tasks]
        ready.wait(60); Path(job['ready']).write_text(str(os.getpid()))
        rows=[f.result() for f in futures]
    write(Path(job['result']),rows)

class Runner:
    def __init__(self,out): self.out=out; self.counter=0; self.processes=[]
    def launch(self,tasks):
        self.counter+=1; stem=self.out/f'group-{self.counter}'
        job={'tasks':tasks,'start':str(stem)+'.start','ready':str(stem)+'.ready','result':str(stem)+'.json'}
        path=Path(str(stem)+'.job');write(path,job)
        log=Path(str(stem)+'.log').open('w')
        p=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--child',str(path)],stdout=log,stderr=subprocess.STDOUT)
        log.close();self.processes.append(p)
        return p,job
    def group(self,tasks):
        jobs=[self.launch(tasks[i::2]) for i in range(min(2,len(tasks)))]
        try:
            for p,j in jobs: wait_file(Path(j['ready']))
            for p,j in jobs: Path(j['start']).touch()
            rows=[]
            for p,j in jobs:
                assert p.wait(timeout=180)==0, 'SERVICE_PROCESS_FAILED'
                rows+=json.loads(Path(j['result']).read_text())
            if len(tasks)>1: assert len({r['pid'] for r in rows})==2
            return rows
        finally:
            for p,j in jobs:
                if p.poll() is None:p.kill();p.wait()
    def one(self,task): return self.group([task])[0]
    def stop(self):
        for p in self.processes:
            if p.poll() is None:p.kill();p.wait()

def check_money():
    from sqlalchemy import select
    from go_hotel.db.session import SessionLocal
    from go_hotel.db.models import OmnichannelMoneyMovementRow as M,OmnichannelLedgerEntryRow as E
    counts={};observations=[]
    with SessionLocal() as s:
        moves=list(s.scalars(select(M))); entries=list(s.scalars(select(E)))
        for m in moves:
            counts[m.movement_type]=counts.get(m.movement_type,0)+1
            if m.state!='CONFIRMED': continue
            if m.movement_type not in ('CAPTURE','REFUND'):continue
            e=[x for x in entries if x.transaction_id==m.money_movement_id]
            assert len(e)==2 and {x.direction for x in e}=={'DEBIT','CREDIT'}, 'LEDGER_PAIR'
            assert all(x.amount_minor==m.amount_minor and x.currency==m.currency and x.payment_intent_id==m.root_payment_intent_id for x in e),'LEDGER_AMOUNT'
            parent=next(x for x in moves if x.money_movement_id==m.parent_movement_id)
            assert parent.state=='CONFIRMED' and parent.currency==m.currency
            assert parent.movement_type==('AUTHORIZATION' if m.movement_type=='CAPTURE' else 'CAPTURE')
            siblings=[x for x in moves if x.parent_movement_id==parent.money_movement_id and x.movement_type==m.movement_type and x.state=='CONFIRMED']
            assert sum(x.amount_minor for x in siblings)<=parent.amount_minor,'OVER_CAPTURE_OR_REFUND'
            observations.append({'id':m.money_movement_id,'kind':m.movement_type,'amount_minor':m.amount_minor,'debit_minor':sum(x.amount_minor for x in e if x.direction=='DEBIT'),'credit_minor':sum(x.amount_minor for x in e if x.direction=='CREDIT')})
    from test_depth23_capacity import ledger
    return {'movement_counts':counts,'allocated':ledger(),'movements':observations}

def correctness(r,out):
    from sqlalchemy import select
    from go_hotel.db.session import SessionLocal
    from go_hotel.db import models as m
    from test_depth23_capacity import rail_quote,attr_quote,order,cancel,ledger
    from test_depth21_refund_recovery import booked
    from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge as bridge
    evidence=[]
    def record(name,rows):
        evidence.append({'name':name,'rows':rows,'sql':check_money()})
        write(out/'correctness.json',{'status':'RUNNING','scenarios':evidence})
    # Distinct quotes contend for exactly the final unit in a shared bucket.
    for v,limit,quote in [('RAIL',18,rail_quote),('ATTRACTION',24,attr_quote)]:
        holders=[];remaining=limit-1
        while remaining:
            quantity=min(8,remaining)
            holders.append(order(v,quote(quantity=quantity),'stock-holder'))
            remaining-=quantity
        tasks=[{'op':'stock','vertical':v,'quote':quote(quantity=1),'owner':f'stock-{i}'} for i in range(20)]
        rows=r.group(tasks)
        record(v+'_last_unit',rows)
        assert sum(x['ok'] for x in rows)==1, 'LAST_UNIT_WINNER_COUNT'
        assert all(x['ok'] or x['code']==v+'_INVENTORY_CHANGED' for x in rows),'UNEXPECTED_STOCK_FAILURE'
        for first in holders:cancel(v,first['order_id'],'stock-holder')
        winner=next(x['value'] for x in rows if x['ok'])
        model=m.RailOrderRow if v=='RAIL' else m.AttractionOrderRow
        with SessionLocal() as s: owner=s.get(model,winner['order_id']).account_id
        cancel(v,winner['order_id'],owner);assert ledger()==0
    # Hotel availability and reservation use the real approved synthetic fixture.
    from hosted_review_support import hotel_fixture
    class Environment:
        def setenv(self,k,v):os.environ[k]=v
    hotel=hotel_fixture(Environment(),out/'media',ready=True)
    with SessionLocal.begin() as s:
        for d in s.scalars(select(m.HostedInventoryDayRow).where(m.HostedInventoryDayRow.inventory_pool_id==hotel['pool'])):
            d.capacity_total=1;d.capacity_available=1
    tasks=[{'op':'hotel','slug':hotel['slug'],'body':hotel['body'],'owner':hotel['customer'].user_id,'key':f'mi-hotel-{i}'} for i in range(20)]
    rows=r.group(tasks);record('HOTEL_last_room',rows)
    assert sum(x['ok'] for x in rows)==1,'HOTEL_LAST_ROOM_WINNER_COUNT'
    assert all(x['ok'] or ('INVENTORY' in str(x['code']) and x['error_type']=='ValueError') for x in rows),'HOTEL_UNEXPECTED_REJECTION'
    with SessionLocal() as s:
        bookings=list(s.scalars(select(m.HostedDirectReservationRow)))
        assert len(bookings)==1
        days=list(s.scalars(select(m.HostedInventoryDayRow).where(m.HostedInventoryDayRow.inventory_pool_id==hotel['pool'])))
        assert all(0<=d.capacity_available<=1 for d in days)
    # Concurrent same-key order creation and altered-payload rejection.
    from datetime import timedelta
    from go_hotel.mobility.ride.service import ride_service
    at=(datetime.now(timezone.utc)+timedelta(days=10)).isoformat()
    offer=ride_service.search('ISOLATED_A','ISOLATED_B',at,'CNY')[0]
    body={'offer_id':'ride_standard','pickup':'ISOLATED_A','dropoff':'ISOLATED_B','pickup_at':at,'currency':'CNY','passengers':[{'full_name':'SYNTHETIC'}],'cancellation_policy_hash':offer['cancellation']['policy_hash']}
    task={'op':'create_replay','body':body,'owner':'mi-replay','key':'mi-replay-key'}
    rows=r.group([task]*20);record('RIDE_create_replay',rows)
    assert any(x['ok'] for x in rows)
    assert all(x['ok'] or x.get('code',{}).get('code')=='IDEMPOTENCY_IN_PROGRESS' for x in rows)
    receipt=r.one(task);assert receipt['ok']
    assert all(not x['ok'] or x['value']==receipt['value'] for x in rows)
    conflict=r.one(dict(task,body=dict(body,dropoff='ALTERED')))
    assert not conflict['ok'] and conflict['code']['code']=='IDEMPOTENCY_CONFLICT'
    with SessionLocal() as s:assert len(list(s.scalars(select(m.MobilityRideOrderRow).where(m.MobilityRideOrderRow.account_id=='mi-replay'))))==1
    tx=bridge.checkout_contract('RIDE',receipt['value']['data']['order_id'],'mi-replay','isolated','isolated://mi')
    cap={'op':'capture','iid':tx['payment_intent_id'],'key':'ride-cap:'+receipt['value']['data']['order_id'],'body':{'movement_type':'CAPTURE','parent_movement_id':tx['authorization_id'],'mode':'CONTRACT_SIMULATOR','evidence':['isolated://mi']}}
    rows=r.group([cap]*20);record('RIDE_capture_replay',rows)
    assert all(x['ok'] and x['value']['money_movement_id']==tx['capture_id'] for x in rows)
    # Deterministic cross-process handoffs on both sides of payment-root commit.
    for v,quote in [('RAIL',rail_quote),('ATTRACTION',attr_quote)]:
        for boundary in ('before_root','after_root'):
            o=order(v,quote(),'race-owner');oid=o['order_id']
            marker=out/(v+boundary+'.paused');release=out/(v+boundary+'.release')
            p,j=r.launch([{'op':'pay','vertical':v,'owner':'race-owner','oid':oid,'pause':boundary,'marker':str(marker),'release':str(release)}])
            wait_file(Path(j['ready']));Path(j['start']).touch();wait_file(marker)
            cancelled=r.one({'op':'cancel','vertical':v,'owner':'race-owner','oid':oid})
            release.touch();assert p.wait(90)==0
            paid=json.loads(Path(j['result']).read_text())[0]
            record(v+'_'+boundary,[paid,cancelled])
            if boundary=='before_root':
                assert cancelled['ok'] and not paid['ok'] and 'NOT_PAYABLE' in str(paid['code'])
                with SessionLocal() as s:assert not list(s.scalars(select(m.OmnichannelPaymentIntentRow).where(m.OmnichannelPaymentIntentRow.business_id==oid)))
            else:
                assert paid['ok'] and not cancelled['ok'] and 'PAYMENT_ALREADY_STARTED' in str(cancelled['code'])
    # Crash after committed refund; genuine 30-second lease expiry, no clock/row editing.
    for v in ('RAIL','ATTRACTION'):
        svc,owner,oid=booked(v,'crash-'+v)
        marker=out/(v+'.money-committed')
        p,j=r.launch([{'op':'crash_refund','vertical':v,'owner':owner,'oid':oid,'marker':str(marker)}])
        wait_file(Path(j['ready']));Path(j['start']).touch()
        assert p.wait(90)==71 and marker.exists()
        task={'op':'refund','vertical':v,'owner':owner,'oid':oid}
        blocked=r.one(task)
        assert not blocked['ok'] and blocked['code']=='REFUND_ALREADY_PROCESSING'
        from go_hotel.autonomy.durable import db_now_ms
        with SessionLocal() as s:
            op=s.get(m.VerticalRefundOperationRow,(v,oid));assert op.state=='PENDING'
            remaining=max(0,(op.lease_until_ms-db_now_ms(s))/1000)
        time.sleep(remaining+.1)
        rows=r.group([task]*20);record(v+'_refund_crash_recovery',rows)
        assert any(x['ok'] for x in rows)
        assert all(x['ok'] or x['code']=='REFUND_ALREADY_PROCESSING' for x in rows)
        final=r.one(task);assert final['ok'] and final['value']['status']=='REFUND_COMPLETED'
        assert all(not x['ok'] or x['value']==final['value'] for x in rows)
        with SessionLocal() as s:
            assert s.get(m.VerticalRefundOperationRow,(v,oid)).state=='COMPLETED'
            refunds=list(s.scalars(select(m.OmnichannelMoneyMovementRow).where(m.OmnichannelMoneyMovementRow.business_id==oid,m.OmnichannelMoneyMovementRow.movement_type=='REFUND')))
            assert len(refunds)==1 and refunds[0].state=='CONFIRMED'
    write(out/'correctness.json',{'status':'PASS','scenarios':evidence})

def coordinator(out):
    imports()
    from go_hotel.db.models import Base
    from go_hotel.db.session import engine
    Base.metadata.create_all(engine)
    r=Runner(out);result={'correctness':'PENDING','stages':[],'status':'RUNNING','scope':'two independent service processes, shared PostgreSQL; not HTTP/auth/production or million-online proof'}
    try:
        correctness(r,out);result['correctness']='PASS';write(out/'result.json',result)
        from ride_workload import verify
        raw=[]
        for n in PLAN:
            rows=r.group([{'op':'ride','index':i} for i in range(len(raw),len(raw)+n)])
            write(out/f'load-{n}.json',rows)
            values=[x['value'] for x in rows if x['ok']];raw+=values
            latency=sorted(x['duration_ms'] for x in rows)
            events=sorted([(x['start_ns'],1) for x in rows]+[(x['end_ns'],-1) for x in rows])
            peak=active=0
            for _,delta in events:active+=delta;peak=max(peak,active)
            duration=(max(x['end_ns'] for x in rows)-min(x['start_ns'] for x in rows))/1e9
            stage={'concurrent_transactions':n,'transactions':len(rows),'process_ids':sorted({x['pid'] for x in rows}),'observed_peak_inflight':peak,'errors':sum(not x['ok'] for x in rows),'p95_ms':latency[math.ceil(n*.95)-1],'p99_ms':latency[math.ceil(n*.99)-1],'completed_per_second':len(values)/duration,'sql':'PENDING'}
            result['stages'].append(stage);write(out/'result.json',result)
            write(out/f'money-{n}.json',check_money())
            # Query every persisted RIDE load order, including failed/partial attempts.
            observations=verify(raw);write(out/f'ride-sql-{n}.json',observations)
            stage['sql']='PASS'
            stage['pass']=stage['errors']==0 and stage['p95_ms']<=5000 and stage['p99_ms']<=10000
            if not stage['pass']:
                result['status']='STOPPED_AT_FAILED_TIER';return 1
        result['status']='BOUNDED_SERVICE_PLAN_PASS';return 0
    except Exception as exc:
        result.update(status='FAILED',error_type=type(exc).__name__,error=str(exc)[:1000] if isinstance(exc,(AssertionError,ValueError)) else 'SEE_LOG')
        import traceback;traceback.print_exc()
        return 1
    finally:
        r.stop();write(out/'result.json',result);engine.dispose()

def main():
    p=argparse.ArgumentParser();p.add_argument('--child',type=Path);p.add_argument('--coordinator',type=Path);p.add_argument('--out',type=Path,default=ROOT/'multi-instance-evidence');args=p.parse_args()
    sys.addaudithook(guard)
    if args.child:child(args.child);return 0
    if args.coordinator:return coordinator(args.coordinator)
    from sqlalchemy import create_engine,text
    from sqlalchemy.engine import make_url
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    assert head==os.environ['EXPECTED_HEAD']
    url=make_url(os.environ['GO_MULTI_DATABASE_URL'])
    assert (url.drivername,url.host,url.port,url.username,url.database)==('postgresql+psycopg','127.0.0.1',5432,'go_ci','go_c11_isolated') and not url.query
    schema='mi_'+uuid4().hex;engine=create_engine(url);code=1
    binding={'head':head,'application_tree':subprocess.check_output(['git','rev-parse','HEAD:application'],cwd=ROOT,text=True).strip(),'schema':schema,'python':sys.version,'platform':platform.platform(),'cpu_count':os.cpu_count(),'plan':PLAN,'instances':2,'pool_per_instance':5,'max_overflow':0,'max_application_connections':15,'parent_connections':5,'p95_gate_ms':5000,'p99_gate_ms':10000,'money_mode':'CONTRACT_SIMULATOR','real_supplier':'NOT_USED','real_psp':'NOT_USED','http_auth':'NOT_TESTED','production_capacity':'NOT_ESTABLISHED'}
    try:
        with engine.begin() as c:
            binding['database_version']=c.scalar(text('select version()'));binding['max_connections']=c.scalar(text('show max_connections'))
            c.execute(text('CREATE SCHEMA '+schema))
        write(out/'binding.json',binding)
        env={k:os.environ[k] for k in ('PATH','LANG','LC_ALL','TZ') if k in os.environ}
        env.update(DATABASE_URL=url.update_query_dict({'options':'-csearch_path='+schema+' -cstatement_timeout=15000 -clock_timeout=10000 -cidle_in_transaction_session_timeout=30000','connect_timeout':'5'}).render_as_string(hide_password=False),APP_ENV='test',MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED='false',TRAVEL_INTELLIGENCE_ENABLED='false',DATABASE_POOL_SIZE='5',DATABASE_MAX_OVERFLOW='0',DATABASE_POOL_TIMEOUT_SECONDS='10',PYTHONPATH=str(APP/'src'),GO_RIDE_ISOLATED_CANCELLATION_POLICY_FILE=str(APP/'scripts/fixtures/ride-cancellation.synthetic.json'))
        with (out/'coordinator.log').open('w') as log:
            proc=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--coordinator',str(out)],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            try:code=proc.wait(timeout=1200)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait();code=124
    finally:
        with engine.begin() as c:c.execute(text('DROP SCHEMA IF EXISTS '+schema+' CASCADE'))
        engine.dispose()
        write(out/'exit.json',{'exit_code':code})
        write(out/'SHA256.json',{str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file() and p.name!='SHA256.json'})
    return code

if __name__=='__main__':raise SystemExit(main())
