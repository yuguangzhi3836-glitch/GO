"""Bounded historical-source money SQL fixture; isolated local PostgreSQL only."""
import argparse, hashlib, json, os, platform, statistics, subprocess, sys, uuid
from pathlib import Path
from datetime import datetime, timezone

parser=argparse.ArgumentParser()
parser.add_argument('--app-root', required=True)
parser.add_argument('--output', required=True)
args=parser.parse_args()
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
from call_sql import CallSQL

# Dedicated disposable container from Codespace recovery; never accept a remote URL.
info=json.loads(subprocess.check_output(['docker','inspect','go-call-sql-pg-20261003'],text=True))[0]
assert info['Config']['Labels'].get('go.scope')=='isolated-diagnostic'
assert info['NetworkSettings']['Ports']['5432/tcp']==[{'HostIp':'127.0.0.1','HostPort':'55436'}]
url='postgresql+psycopg://go_ci:isolated_diagnostic_only@127.0.0.1:55436/go_c11_isolated'
schema='money_sample_'+uuid.uuid4().hex
admin=create_engine(url)
with admin.begin() as c:
    c.execute(text('CREATE SCHEMA '+schema))
engine=create_engine(url,pool_size=1,max_overflow=0,pool_pre_ping=True,
    connect_args={'options':'-c search_path='+schema+' -c statement_timeout=10000 -c lock_timeout=3000'})
tables=[Intent,Movement,Ledger,Source,Fulfillment,FulfillmentEvent]
for model in tables:
    model.__table__.create(engine)
sessions=sessionmaker(bind=engine,expire_on_commit=False,autoflush=False)
money.SessionLocal=sessions
service=money.UnifiedMoneyMovementService()
catalog={}
execution_batches={}
probe=CallSQL(engine)
def catalog_sql(conn,cursor,statement,parameters,context,many):
    current=probe._current()
    if current is not None:
        execution_batches.setdefault(current['call_id'],[]).append({'executemany':bool(many),'parameter_sets':len(parameters) if many else 1})
        catalog[hashlib.sha256(statement.encode()).hexdigest()]=' '.join(statement.split())
event.listen(engine,'before_cursor_execute',catalog_sql)
def create_pair(n):
    iid='sample-'+str(n)
    t=money.now()
    with sessions.begin() as s:
        s.add(Intent(payment_intent_id=iid,business_type='RIDE_ORDER',business_id=iid,
            payer_id='guest',payee_id='supplier',operation='PAY',amount_minor=100,
            currency='CNY',channel_priority_json=['LOCAL_MARKET'],selected_channel='LOCAL_MARKET',
            state='SUCCEEDED',idempotency_key='intent:'+iid,automatic_fallback_allowed=False,
            created_at=t,updated_at=t))
        s.add(Fulfillment(order_supplier_fulfillment_id='fill:'+iid,payment_intent_id=iid,
            business_type='RIDE_ORDER',business_id=iid,supplier_id='supplier',
            supplier_idempotency_key='supplier:'+iid,state='PAYMENT_CONFIRMED_AWAITING_MONEY_GRAPH',
            evidence_reference='isolated://money',created_at=t,updated_at=t))
    def body(kind,parent=None,amount=100):
        return dict(movement_type=kind,amount_minor=amount,parent_movement_id=parent,
            mode='CONTRACT_SIMULATOR',evidence=['isolated://money'])
    auth=body('AUTHORIZATION')
    with probe.call('fresh_AUTH'):
        a=service.create(iid,auth,'auth:'+iid,'isolated-test')
    cap=body('CAPTURE',a['money_movement_id'])
    with probe.call('fresh_CAPTURE'):
        b=service.create(iid,cap,'cap:'+iid,'isolated-test')
    with probe.call('replay_AUTH'):
        a2=service.create(iid,auth,'auth:'+iid,'isolated-test')
    with probe.call('replay_CAPTURE'):
        b2=service.create(iid,cap,'cap:'+iid,'isolated-test')
    assert a2==a and b2==b
    try:
        with probe.call('conflict'):
            service.create(iid,body('CAPTURE',a['money_movement_id'],101),'cap:'+iid,'isolated-test')
    except ValueError as exc:
        assert str(exc)=='MONEY_MOVEMENT_IDEMPOTENCY_CONFLICT'
    else:
        raise AssertionError('conflict accepted')
    with sessions() as s:
        moves=s.scalars(select(Movement).where(Movement.root_payment_intent_id==iid)).all()
        ledger=s.scalars(select(Ledger).where(Ledger.payment_intent_id==iid)).all()
        f=s.get(Fulfillment,'fill:'+iid)
        events=s.scalars(select(FulfillmentEvent).where(FulfillmentEvent.order_supplier_fulfillment_id=='fill:'+iid)).all()
        assert len(moves)==2 and all(x.state=='CONFIRMED' for x in moves)
        assert len(ledger)==2 and {x.direction:x.amount_minor for x in ledger}=={'DEBIT':100,'CREDIT':100}
        assert f.state=='CAPTURE_CONFIRMED_READY_FOR_SUPPLIER' and len(events)==1

for n in range(23):
    create_pair(n)
snapshot=probe.snapshot()
assert snapshot['valid'],snapshot['errors']
for row in snapshot['calls']:
    batches=execution_batches[row['call_id']]
    assert len(batches)==len(row['sql'])
    for q,b in zip(row['sql'],batches):
        q.update(b)
warmup=snapshot['calls'][:15]
measured=snapshot['calls'][15:]
expected_counts={'fresh_AUTH':5,'fresh_CAPTURE':9,'replay_AUTH':2,'replay_CAPTURE':2,'conflict':2}
for row in snapshot['calls']:
    assert len(row['sql'])==expected_counts[row['scenario']], (row['scenario'],len(row['sql']))
    assert len(row['leases'])==1
    assert row['outcome']==('error' if row['scenario']=='conflict' else 'returned')
    assert not any(x['failed'] for x in row['sql']+row['transactions'])
    assert sum(x['operation']=='commit' for x in row['transactions'])==(row['scenario']!='conflict')
def stats(values):
    values=sorted(v*1000 for v in values)
    return {'mean_ms':statistics.mean(values),'p50_ms':statistics.median(values),
        'p95_ms':values[max(0,__import__('math').ceil(.95*len(values))-1)],'max_ms':max(values)}
summary={}
for label in expected_counts:
    rows=[r for r in measured if r['scenario']==label]
    summary[label]={'calls':len(rows),'sql_per_call':expected_counts[label],
        'wall':stats([r['wall_seconds'] for r in rows]),
        'lease':stats([sum(r['leases']) for r in rows]),
        'sql_total':stats([sum(q['seconds'] for q in r['sql']) for r in rows]),
        'transaction_total':stats([sum(q['seconds'] for q in r['transactions']) for r in rows]),
        'ordered_sql':[]}
    for i in range(expected_counts[label]):
        fps={r['sql'][i]['fingerprint'] for r in rows}
        assert len(fps)==1
        summary[label]['ordered_sql'].append({'ordinal':i+1,'fingerprint':fps.pop(),
            **stats([r['sql'][i]['seconds'] for r in rows])})
with engine.connect() as c:
    counts={m.__tablename__:c.scalar(select(func.count()).select_from(m)) for m in tables}
    indexes=c.execute(text('SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname=:schema ORDER BY tablename,indexname'),{'schema':schema}).mappings().all()
    plan=c.execute(text('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT * FROM '+Source.__tablename__+' WHERE payment_intent_id=:iid'),{'iid':'sample-22'}).scalar()
    version=c.scalar(text('SHOW server_version'))
probe.close()
event.remove(engine,'before_cursor_execute',catalog_sql)
engine.dispose();admin.dispose()
result={'scope':'isolated rebuilt serial RIDE_ORDER fixture, historical application; not ABBA/load/release evidence',
    'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'time_utc':datetime.now(timezone.utc).isoformat(),'app_head':git('rev-parse','HEAD'),
    'app_tree':expected,'probe_head':subprocess.check_output(['git','-C',str(Path(__file__).resolve().parent),'rev-parse','HEAD'],text=True).strip(),
    'python':platform.python_version(),'sqlalchemy':sqlalchemy.__version__,'psycopg':psycopg.__version__,
    'postgres':version,'cpus':os.cpu_count(),'schema':schema,'table_counts':counts,
    'indexes':[dict(x) for x in indexes],'source_guard_explain':plan,
    'warmup_calls':warmup,'measurement':{**snapshot,'calls':measured},
    'sql_catalog':catalog,'summary':summary,
    'limitations':['3 warmup pairs then 20 measured pairs; initial warmup retained separately',
    'No historical data restored; source table empty; no table-scale or contention conclusion',
    'Client cursor timer excludes fetch/materialization and includes observer overhead',
    'Lease spans checkout through checkin, includes commit/rollback; pure pool queue unmeasured',
    'pre_ping before checkout excluded from cursor/lease; wall includes entire create wrapper',
    'Six model-created tables, not full Alembic schema; no product code or locks changed']}
p=Path(args.output);p.parent.mkdir(parents=True,exist_ok=True)
p.write_text(json.dumps(result,indent=2)+'\n')
print('VALID',snapshot['valid'],'MEASURED',len(measured),'SQL',sum(len(r['sql']) for r in measured))
for label,s in summary.items():
    print(label,'SQL',s['sql_per_call'],'SQL_ms',round(s['sql_total']['mean_ms'],4),
        'lease_ms',round(s['lease']['mean_ms'],4),'wall_ms',round(s['wall']['mean_ms'],4))
print('EVIDENCE',str(p),'SHA256',hashlib.sha256(p.read_bytes()).hexdigest())
