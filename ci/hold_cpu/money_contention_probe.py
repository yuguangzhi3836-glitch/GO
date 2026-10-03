"""Bounded historical-source money SQL fixture; isolated local PostgreSQL only."""
import argparse, hashlib, json, os, platform, statistics, subprocess, sys, uuid
from pathlib import Path
from datetime import datetime, timezone

parser=argparse.ArgumentParser()
parser.add_argument('--app-root', required=True)
parser.add_argument('--output', required=True)
parser.add_argument('--rounds',type=int,default=3)
args=parser.parse_args()
assert 1<=args.rounds<=23
app=Path(args.app_root).resolve()
def git(*a):
    return subprocess.check_output(['git','-C',str(app),*a],text=True).strip()
expected='6570b66bc977f89c0311d67bdc6b721cd70d4e09'
assert git('rev-parse','HEAD:application')==expected
assert not git('diff','HEAD','--','application'), 'modified application'
sys.path.insert(0,str(app/'application/src'))
# Override ambient configuration before importing application; real service uses fixture sessions.
os.environ['DATABASE_URL']='sqlite:///:memory:'
from sqlalchemy import create_engine, event, select, text, func
from sqlalchemy.orm import sessionmaker
import sqlalchemy, psycopg
from go_hotel.db.models import (OmnichannelPaymentIntentRow as Intent,
    OmnichannelMoneyMovementRow as Movement, OmnichannelLedgerEntryRow as Ledger,
    CatalogCreditSourceRow as Source, OrderSupplierFulfillmentRow as Fulfillment,
    OrderSupplierFulfillmentEventRow as FulfillmentEvent)
from go_hotel.services import unified_money_movement as money

# Dedicated disposable container from Codespace recovery; never accept a remote URL.
info=json.loads(subprocess.check_output(['docker','inspect','go-call-sql-pg-20261003'],text=True))[0]
assert info['Config']['Labels'].get('go.scope')=='isolated-diagnostic'
assert info['NetworkSettings']['Ports']['5432/tcp']==[{'HostIp':'127.0.0.1','HostPort':'55436'}]
url='postgresql+psycopg://go_ci:isolated_diagnostic_only@127.0.0.1:55436/go_c11_isolated'
schema='money_contention_'+uuid.uuid4().hex
admin=create_engine(url)
with admin.begin() as c:
    c.execute(text('CREATE SCHEMA '+schema))
engine=create_engine(url,pool_size=2,max_overflow=0,pool_pre_ping=True,
    connect_args={'options':'-c search_path='+schema+' -c statement_timeout=10000 -c lock_timeout=3000'})
tables=[Intent,Movement,Ledger,Source,Fulfillment,FulfillmentEvent]
for model in tables:
    model.__table__.create(engine)
sessions=sessionmaker(bind=engine,expire_on_commit=False,autoflush=False)
money.SessionLocal=sessions
service=money.UnifiedMoneyMovementService()
import threading, time
from concurrent.futures import ThreadPoolExecutor
local=threading.local()
records=[]
samples=[]
observe_errors=[]
active={}
guard=threading.Lock()
stop=threading.Event()
observed_block=threading.Event()
origin=time.monotonic()
def clock():return time.monotonic()-origin
def checkout(dbapi,record,proxy):
    row=getattr(local,'row',None)
    if row is not None:
        row['pid']=dbapi.info.backend_pid;row['checkout']=clock()
        with guard:active[row['pid']]=row['call_id']
def checkin(dbapi,record):
    row=getattr(local,'row',None)
    if row is not None:
        row['checkin']=clock()
        with guard:active.pop(row.get('pid'),None)
def before(conn,cursor,statement,parameters,context,many):
    row=getattr(local,'row',None)
    if row is not None:
        local.sql_start=clock()
        local.sql_fp=hashlib.sha256(statement.encode()).hexdigest()
def after(conn,cursor,statement,parameters,context,many):
    row=getattr(local,'row',None)
    if row is not None:
        row['sql'].append(dict(ordinal=len(row['sql'])+1,start=local.sql_start,
            end=clock(),fingerprint=local.sql_fp,executemany=bool(many)))
for target,name,fn in [(engine,'checkout',checkout),(engine,'checkin',checkin),
                       (engine,'before_cursor_execute',before),(engine,'after_cursor_execute',after)]:
    event.listen(target,name,fn)

# One independent observer connection; never consumes a business pool slot.
observer=create_engine(url,pool_size=1,max_overflow=0,isolation_level='AUTOCOMMIT',
    connect_args={'connect_timeout':2,'options':'-c statement_timeout=1000'})
def observe():
    try:
        with observer.connect() as c:
            while not stop.is_set():
                with guard:ids=dict(active)
                if ids:
                    sample_start=clock()
                    rows=c.execute(text('SELECT pid,state,wait_event_type,wait_event,pg_blocking_pids(pid) AS blockers FROM pg_stat_activity WHERE pid=ANY(:pids)'),{'pids':list(ids)}).mappings().all()
                    for item in rows:
                        row=dict(item);row.update(t=clock(),sample_start=sample_start,call_id=ids.get(row['pid']))
                        samples.append(row)
                        if row['blockers']:observed_block.set()
                stop.wait(.001)
    except Exception as exc:
        observe_errors.append(type(exc).__name__)

def body(amount,parent):
    return dict(movement_type='CAPTURE',amount_minor=amount,parent_movement_id=parent,
                mode='CONTRACT_SIMULATOR',evidence=['isolated://contention-probe'])
def setup(iid):
    t=money.now()
    with sessions.begin() as s:
        s.add(Intent(payment_intent_id=iid,business_type='RIDE_ORDER',business_id=iid,
            payer_id='guest',payee_id='supplier',operation='PAY',amount_minor=100,currency='CNY',
            channel_priority_json=['LOCAL_MARKET'],selected_channel='LOCAL_MARKET',state='SUCCEEDED',
            idempotency_key='intent:'+iid,automatic_fallback_allowed=False,created_at=t,updated_at=t))
        s.add(Fulfillment(order_supplier_fulfillment_id='fill:'+iid,payment_intent_id=iid,
            business_type='RIDE_ORDER',business_id=iid,supplier_id='supplier',supplier_idempotency_key='supplier:'+iid,
            state='PAYMENT_CONFIRMED_AWAITING_MONEY_GRAPH',evidence_reference='isolated://money',created_at=t,updated_at=t))
    b=dict(movement_type='AUTHORIZATION',amount_minor=100,mode='CONTRACT_SIMULATOR',evidence=['isolated://contention-probe'])
    # Real AUTH commits before concurrent CAPTURE; no merging commit boundaries.
    return service.create(iid,b,'auth:'+iid,'isolated-test')['money_movement_id']

def call(label,iid,key,amount,parent,barrier=None):
    if barrier:barrier.wait(timeout=10)
    row=dict(call_id=label,start=clock(),sql=[])
    local.row=row
    try:
        result=service.create(iid,body(amount,parent),key,'isolated-test')
        row['returned']=clock();row['outcome']='committed'
        return result
    except Exception as exc:
        row['outcome']='error';row['error_type']=type(exc).__name__
        raise
    finally:
        row['end']=clock();records.append(row);local.row=None

def verify(iid,captures):
    with sessions() as s:
        moves=s.scalars(select(Movement).where(Movement.root_payment_intent_id==iid)).all()
        ledger=s.scalars(select(Ledger).where(Ledger.payment_intent_id==iid)).all()
        ev=s.scalars(select(FulfillmentEvent).where(FulfillmentEvent.order_supplier_fulfillment_id=='fill:'+iid)).all()
        assert len(moves)==1+captures and all(x.state=='CONFIRMED' for x in moves)
        auths=[x for x in moves if x.movement_type=='AUTHORIZATION']
        caps=[x for x in moves if x.movement_type=='CAPTURE']
        assert len(auths)==1 and auths[0].amount_minor==100 and auths[0].parent_movement_id is None
        assert len(caps)==captures
        for cap in caps:
            assert cap.amount_minor==(50 if captures==2 else 100)
            assert cap.parent_movement_id==auths[0].money_movement_id
            entries=[x for x in ledger if x.transaction_id==cap.money_movement_id]
            assert len(entries)==2 and {x.direction for x in entries}=={'DEBIT','CREDIT'}
            assert all(x.amount_minor==cap.amount_minor and x.entry_type=='CAPTURE' and x.currency=='CNY' for x in entries)
        assert sum(x.amount_minor for x in moves if x.movement_type=='CAPTURE')==100
        assert len(ledger)==2*captures
        assert sum(x.amount_minor for x in ledger if x.direction=='DEBIT')==100
        assert sum(x.amount_minor for x in ledger if x.direction=='CREDIT')==100
        assert len(ev)==1 and s.get(Fulfillment,'fill:'+iid).state=='CAPTURE_CONFIRMED_READY_FOR_SUPPLIER'

thread=threading.Thread(target=observe,daemon=True);thread.start()
failure=None
try:
    # Positive control ONLY: known root lock blocks a real CAPTURE business call.
    iid='calibration';parent=setup(iid)
    with sessions() as blocker,ThreadPoolExecutor(1) as pool:
        blocker.scalar(select(Intent).where(Intent.payment_intent_id==iid).with_for_update())
        blocker_pid=blocker.connection().connection.driver_connection.info.backend_pid
        observed_block.clear()
        future=pool.submit(call,'calibration',iid,'cap:'+iid,100,parent)
        try:
            assert observed_block.wait(2),'observer failed to detect held root lock'
        finally:blocker.rollback()
        future.result(timeout=10)
    assert any(x['call_id']=='calibration' and blocker_pid in x['blockers'] for x in samples)
    verify(iid,1)
    # Natural cases do not deliberately hold locks or pause inside transactions.
    for n in range(args.rounds):
        for kind in ['different_root','same_root_new_keys','same_root_same_key']:
            a=kind+'-'+str(n);b=a+'-other' if kind=='different_root' else a
            pa=setup(a);pb=setup(b) if b!=a else pa
            amount=50 if kind=='same_root_new_keys' else 100
            ka='cap:'+a;kb=ka if kind=='same_root_same_key' else 'cap:'+b+':two'
            barrier=threading.Barrier(2)
            with ThreadPoolExecutor(2) as pool:
                f1=pool.submit(call,f'{kind}:{n}:0',a,ka,amount,pa,barrier)
                f2=pool.submit(call,f'{kind}:{n}:1',b,kb,amount,pb,barrier)
                r1=f1.result(timeout=15);r2=f2.result(timeout=15)
            assert (r1['money_movement_id']==r2['money_movement_id'])==(kind=='same_root_same_key')
            verify(a,2 if kind=='same_root_new_keys' else 1)
            if b!=a:verify(b,1)
    assert not observe_errors,observe_errors
    assert all('checkout' in r and 'checkin' in r for r in records)
except Exception as exc:
    failure=type(exc).__name__
    raise
finally:
    stop.set();thread.join(timeout=5)
    observer_alive=thread.is_alive()
    if observer_alive:
        failure=failure or 'ObserverShutdownTimeout'
    elif observe_errors:
        failure=failure or 'ObserverFailure'
    # Do not iterate a list that a failed-to-stop observer can still mutate.
    sample_snapshot=[] if observer_alive else list(samples)
    with admin.connect() as c:version=c.scalar(text('SHOW server_version'))
    result=dict(scope='bounded two-business-connection CAPTURE contention diagnostic; not load/ABBA/production',
        success=failure is None,failure_type=failure,app_head=git('rev-parse','HEAD'),app_tree=expected,
        runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),schema=schema,
        python=platform.python_version(),sqlalchemy=sqlalchemy.__version__,psycopg=psycopg.__version__,
        postgres=version,pool_size=2,max_overflow=0,rounds=args.rounds,
        observer_errors=[] if observer_alive else list(observe_errors),
        calls=records,wait_samples=sample_snapshot,observer_alive_after_join=observer_alive,
        calibration_blocker_pid=locals().get('blocker_pid'),
        limitations=['CAPTURE only measured; AUTH separately committed in setup',
            'bounded diagnostic rounds, not warmed performance comparison; synthetic six-table fixture',
            '1ms requested sampling interval is not guaranteed; missing lock samples do not prove no waiting',
            'one independent observer connection in addition to two business connections',
            'pool pre-ping/acquisition before checkout not separated into pure queue',
            'client SQL wall excludes fetch/materialization; overhead present; not server CPU',
            'same-root new-key uses two half captures; other cases use full capture; not equal-work performance A/B',
            'calibration artificial blocking is excluded from natural-group inference'])
    by_id={r['call_id']:r for r in records}
    for sample in sample_snapshot:
        r=by_id.get(sample['call_id'],{})
        sample['lease_window_valid']=(r.get('checkout',float('inf'))<=sample['sample_start'] and sample['t']<=r.get('checkin',float('-inf')))
    p=Path(args.output);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(result,indent=2)+'\n')
    engine.dispose();admin.dispose()
    if not observer_alive:observer.dispose()
    print('EVIDENCE',str(p),'SUCCESS',result['success'],'CALLS',len(records),'WAIT_SAMPLES',len(sample_snapshot),flush=True)
    if observer_alive:raise RuntimeError('ObserverShutdownTimeout')
    if observe_errors:raise RuntimeError('ObserverFailure')
