"""Bounded isolated transaction-write evidence; never a production SLA claim.

Uses actual RIDE create-order/idempotency, payment/money services, simulated
supplier facts and fulfillment. It does not test HTTP transport/auth, OTA/PSP,
multi-node capacity, or AI-team liveness. PostgreSQL evidence requires the
existing disposable loopback go_c11_isolated database; SQLite is smoke only.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from uuid import uuid4
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
WALL_LIMIT_SECONDS = 240
PLAN = [(1, 4), (4, 16), (8, 32)]


def guard(event, args):
    if event != 'socket.connect':
        return
    sock, address = args
    if sock.family == socket.AF_UNIX:
        return
    try:
        allowed = ipaddress.ip_address(address[0]).is_loopback
    except ValueError:
        allowed = address[0] == 'localhost'
    if not allowed:
        raise PermissionError('C12_ISOLATED_EXTERNAL_EGRESS_FORBIDDEN')


def summary(values):
    ordered = sorted(values)
    return {name: ordered[max(0, math.ceil(q*len(ordered))-1)] if ordered else None
            for name,q in [('p50_ms',.5),('p95_ms',.95),('p99_ms',.99)]}


def validate_url(raw):
    from sqlalchemy.engine import make_url
    url = make_url(raw)
    if (url.drivername != 'postgresql+psycopg' or
            url.host not in {'127.0.0.1','localhost','::1'} or
            url.database != 'go_c11_isolated' or url.username != 'go_ci' or
            url.port not in (None,5432) or url.query):
        raise ValueError('C12_DISPOSABLE_LOOPBACK_PG_REQUIRED')
    return url


def write_json(path, value):
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')


def worker(out, smoke):
    sys.addaudithook(guard)
    from sqlalchemy.engine import make_url
    selected=make_url(os.environ.get('DATABASE_URL',''))
    if smoke:
        target=Path(selected.database or '').resolve()
        assert selected.drivername=='sqlite+pysqlite' and target.parent==out
        assert target.name.startswith('smoke-') and not target.exists(), 'FRESH_SMOKE_DATABASE_REQUIRED'
    else:
        validate_url(selected.set(query={}).render_as_string(hide_password=False))
        schema=os.environ.get('C12_CAPACITY_SCHEMA','')
        assert schema.startswith('c12_capacity_') and len(schema)==45
        assert all(c in '0123456789abcdef' for c in schema[13:])
        assert selected.query=={'options':'-csearch_path='+schema+' -cstatement_timeout=5000 -clock_timeout=3000 -cidle_in_transaction_session_timeout=15000','connect_timeout':'5'}
    sys.path.insert(0,str(ROOT/'src'))
    from sqlalchemy import select
    from go_hotel.db.session import engine, SessionLocal
    from go_hotel.db.models import (Base, MobilityRideOrderRow as Order,
        PaymentOrderRootRow as Root, OmnichannelPaymentIntentRow as Intent,
        OmnichannelPaymentAttemptRow as Attempt, OmnichannelMoneyMovementRow as Movement,
        OmnichannelLedgerEntryRow as Ledger, OrderSupplierFulfillmentRow as Fulfillment,
        ConsumerUnifiedLifecycleRow as Lifecycle)
    from go_hotel.api.routes.mobility import rb, RideBook
    from go_hotel.mobility.ride.service import ride_service
    from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge
    from go_hotel.services.unified_money_movement import unified_money_movement_service as money
    from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as supplier

    if not smoke and engine.dialect.name!='postgresql':
        raise ValueError('POSTGRESQL_ENGINE_REQUIRED')
    Base.metadata.create_all(engine)
    plan = [(1,2)] if smoke else PLAN
    prefix='c12-'+uuid4().hex[:12]
    raw=[]
    batches=[]
    observations=[]
    active=0
    peak=0
    counter_lock=threading.Lock()

    def transaction(index):
        nonlocal active,peak
        started=time.perf_counter()
        with counter_lock:
            active+=1;peak=max(peak,active)
        owner=prefix+'-'+str(index)
        principal=SimpleNamespace(user_id=owner)
        key=owner+'-create'
        record={'index':index,'owner':owner,'outcome':'FAIL','phase':'create_order'}
        try:
            pickup_at=(datetime.now(timezone.utc)+timedelta(days=10)).isoformat()
            offer=ride_service.search('ISOLATED_A','ISOLATED_B',pickup_at,'CNY')[0]
            body=RideBook(offer_id='ride_standard',pickup='ISOLATED_A',dropoff='ISOLATED_B',
                pickup_at=pickup_at,currency='CNY',
                cancellation_policy_hash=offer.get('cancellation',{}).get('policy_hash'),
                passengers=[{'full_name':'ISOLATED CAPACITY TEST'}])
            response=rb(body,principal,key)
            oid=response['data']['order_id'];record['order_id']=oid
            assert rb(body,principal,key)==response, 'CREATE_REPLAY_CHANGED'
            record['phase']='payment_capture'
            tx=vertical_transaction_bridge.checkout_contract('RIDE',oid,owner,
                'ride-engineering-source','isolated://c12/'+oid,'isolated-method')
            assert tx['state']=='PAYMENT_CONFIRMED_AWAITING_SUPPLIER'
            assert tx['supplier_fulfillment_id'], 'FULFILLMENT_MISSING'
            iid=tx['payment_intent_id']
            record['phase']='concurrent_money_replay'
            cap_body={'movement_type':'CAPTURE','parent_movement_id':tx['authorization_id'],
                      'mode':'CONTRACT_SIMULATOR','evidence':['isolated://c12/replay']}
            def replay(_):
                replay_barrier.wait(timeout=10)
                return money.create(iid,cap_body,'ride-cap:'+oid,'c12-capacity')['money_movement_id']
            replay_barrier=threading.Barrier(2)
            with ThreadPoolExecutor(max_workers=2) as pool:
                captures=list(pool.map(replay,range(2)))
            assert captures==[tx['capture_id']]*2, 'DUPLICATE_CAPTURE_EFFECT'
            try:
                money.create(iid,cap_body|{'amount_minor':16801},'ride-cap:'+oid,'c12-capacity')
            except ValueError as exc:
                assert str(exc)=='MONEY_MOVEMENT_IDEMPOTENCY_CONFLICT'
            else:
                raise AssertionError('CHANGED_AMOUNT_REPLAY_ACCEPTED')
            record['phase']='simulated_supplier_and_fulfillment'
            supplier.record_supplier_fact(tx['supplier_fulfillment_id'],{
                'state':'SUPPLIER_CONFIRMED','external_operation_id':owner+'-supplier',
                'supplier_confirmation_reference':owner,
                'evidence_reference':'isolated://c12/synthetic-supplier/'+oid})
            ride_service.fulfill(owner,oid,'START','isolated://c12/start/'+oid)
            ride_service.fulfill(owner,oid,'COMPLETE','isolated://c12/complete/'+oid)
            record.update(outcome='SUCCESS',phase='completed',payment_intent_id=iid)
        except Exception as exc:
            # Do not render SQLAlchemy exception strings: they may contain URLs.
            record.update(error_type=type(exc).__name__,error_code=str(exc)[:180]
                          if isinstance(exc,(AssertionError,ValueError)) else 'SEE_PHASE')
            if type(exc).__name__=='HTTPException':
                record['http_status']=exc.status_code
                record['error_code']=str(exc.detail)[:180]
        record['duration_ms']=(time.perf_counter()-started)*1000
        with counter_lock:active-=1
        return record

    offset=0
    for concurrency,count in plan:
        peak=0
        start=time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            rows=list(pool.map(transaction,range(offset,offset+count)))
        elapsed=time.perf_counter()-start
        raw.extend(rows)
        write_json(out/'raw-transactions.json',raw)
        succeeded=sum(r['outcome']=='SUCCESS' for r in rows)
        batches.append({'concurrency':concurrency,'transactions':count,'completed':succeeded,
            'failed':count-succeeded,'failure_rate':(count-succeeded)/count,
            'elapsed_seconds':elapsed,'completed_transactions_per_second':succeeded/elapsed,
            'transaction_latency':summary([r['duration_ms'] for r in rows]),
            'latency_population':'all transactions including failures; includes nested replay checks',
            'max_extra_replay_threads':2*concurrency,'observed_peak_inflight_transactions':peak})
        offset+=count
        if succeeded!=count:
            break  # A lower tier failure prevents advancing to a higher tier.

    failures=[r for r in raw if r['outcome']!='SUCCESS']
    capacity={'batches':batches,'planned_transactions':sum(n for _,n in plan),
        'executed_transactions':len(raw),'failed_transactions':len(failures),
        'invariants':'NOT_COMPLETED','postgres_gate':'NOT_PROVEN_SQLITE_SMOKE' if smoke else 'PENDING_INVARIANTS',
        'production_sla':'NOT_ESTABLISHED','scope':'RIDE service transaction writes with CONTRACT_SIMULATOR and synthetic supplier facts'}
    write_json(out/'capacity.json',capacity)
    with SessionLocal() as session:
        orders=list(session.scalars(select(Order).where(Order.account_id.like(prefix+'%'))))
        # Include partial/failed orders so a failed request cannot hide effects.
        assert len(orders)==len(raw), 'CREATED_ORDER_COUNT_MISMATCH'
        assert len({r['order_id'] for r in raw if 'order_id' in r})==len(raw), 'ORDER_ID_COLLISION'
        for order in orders:
            roots=list(session.scalars(select(Root).where(Root.business_type=='RIDE_ORDER',Root.business_id==order.order_id)))
            assert len(roots)==1, 'PAYMENT_ROOT_COUNT'
            iid=roots[0].payment_intent_id
            intent=session.get(Intent,iid)
            attempts=list(session.scalars(select(Attempt).where(Attempt.payment_intent_id==iid)))
            moves=list(session.scalars(select(Movement).where(Movement.root_payment_intent_id==iid)))
            entries=list(session.scalars(select(Ledger).where(Ledger.payment_intent_id==iid)))
            fills=list(session.scalars(select(Fulfillment).where(Fulfillment.payment_intent_id==iid)))
            life=list(session.scalars(select(Lifecycle).where(Lifecycle.order_id==order.order_id,Lifecycle.vertical=='RIDE')))
            assert order.status=='COMPLETED' and order.total_amount_minor==16800 and order.currency=='CNY'
            assert intent.state=='SUCCEEDED' and intent.payer_id==order.account_id
            assert intent.amount_minor==16800 and intent.currency=='CNY'
            assert len(attempts)==1 and attempts[0].state=='SUCCEEDED', 'PAYMENT_ATTEMPT_COUNT_OR_STATE'
            assert len(moves)==2 and {m.movement_type for m in moves}=={'AUTHORIZATION','CAPTURE'}
            assert all(m.amount_minor==16800 and m.currency=='CNY' and m.state=='CONFIRMED'
                       and m.business_id==order.order_id and m.business_type=='RIDE_ORDER' for m in moves)
            auth=next(m for m in moves if m.movement_type=='AUTHORIZATION')
            cap=next(m for m in moves if m.movement_type=='CAPTURE')
            assert cap.parent_movement_id==auth.money_movement_id and auth.parent_movement_id is None
            assert len(entries)==2 and {e.direction for e in entries}=={'DEBIT','CREDIT'}
            assert all(e.transaction_id==cap.money_movement_id and e.entry_type=='CAPTURE'
                       and e.amount_minor==16800 and e.currency=='CNY' for e in entries)
            assert len(fills)==1 and fills[0].state=='SUPPLIER_CONFIRMED'
            assert len(life)==1 and life[0].account_id==order.account_id and life[0].payment_state=='PAID'
            assert life[0].lifecycle_state=='COMPLETED', 'TRIPS_NOT_COMPLETED'
            observations.append({'order_id':order.order_id,'order_status':order.status,
                'payment_root_id':iid,'attempts':len(attempts),'money_movement_ids':[m.money_movement_id for m in moves],
                'capture_amount_minor':cap.amount_minor,'currency':'CNY','ledger_entries':len(entries),
                'ledger_debit_minor':16800,'ledger_credit_minor':16800,'trips_state':life[0].lifecycle_state})
    write_json(out/'sql-observations.json',observations)
    capacity.update(invariants='PASS' if not failures and len(raw)==sum(n for _,n in plan) else 'FAIL',
        postgres_gate='NOT_PROVEN_SQLITE_SMOKE' if smoke else 'EVIDENCE_READY')
    write_json(out/'capacity.json',capacity)
    engine.dispose()
    return 1 if failures or len(raw)!=sum(n for _,n in plan) else 0


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence-dir',required=True)
    p.add_argument('--sqlite-smoke',action='store_true')
    p.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    args=p.parse_args()
    out=Path(args.evidence_dir).resolve();out.mkdir(parents=True,exist_ok=True)
    if args.worker:
        try:
            return worker(out,args.sqlite_smoke)
        except Exception as exc:
            failure={'error_type':type(exc).__name__,'phase':'worker_setup_or_sql_invariants',
                'code':str(exc)[:180] if isinstance(exc,(AssertionError,ValueError)) else 'SEE_RAW_TRANSACTION_PHASES'}
            write_json(out/'worker-failure.json',failure)
            print(json.dumps(failure))
            return 1
    sys.addaudithook(guard)
    from sqlalchemy import create_engine,text
    run={'schema':'go.c12.bounded.transaction.capacity.v1','started_at':datetime.now(timezone.utc).isoformat(),
        'status':'RUNNING','python':sys.version,'platform':platform.platform(),'cpu_count':os.cpu_count(),
        'plan':PLAN,'wall_limit_seconds':WALL_LIMIT_SECONDS,'statement_timeout_ms':5000,'lock_timeout_ms':3000,
        'production_sla':'NOT_ESTABLISHED','hong_kong':'NOT_ACCESSED','real_suppliers':'NOT_USED','real_psp':'NOT_USED',
        'http_transport_auth':'NOT_TESTED','team_liveness':'NOT_TESTED','source_commit':os.getenv('GO_C11_SOURCE_COMMIT','UNSPECIFIED')}
    run['harness_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    run['source_files']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for relative in ['src/go_hotel/api/routes/mobility.py','src/go_hotel/api/idempotency.py',
            'src/go_hotel/mobility/ride/service.py','src/go_hotel/mobility/ride/cancellation_policy.py',
            'src/go_hotel/services/vertical_transaction_bridge.py','src/go_hotel/services/omnichannel_payment.py',
            'src/go_hotel/services/unified_money_movement.py','src/go_hotel/services/order_supplier_fulfillment.py',
            'src/go_hotel/services/vertical_lifecycle_projection.py','src/go_hotel/services/consumer_unified_lifecycle.py']
        if (p:=ROOT/relative).is_file()}
    base=None;schema=None;rc=1;started=time.monotonic()
    try:
        if args.sqlite_smoke:
            database='sqlite+pysqlite:///'+str(out/('smoke-'+uuid4().hex+'.db'))
            run.update(backend='sqlite',postgres_gate='NOT_PROVEN_SQLITE_SMOKE')
        else:
            actual_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT.parent,text=True).strip()
            actual_tree=subprocess.check_output(['git','rev-parse','HEAD:application'],cwd=ROOT.parent,text=True).strip()
            assert run['source_commit']==actual_commit, 'SOURCE_COMMIT_BINDING_MISMATCH'
            run.update(gate_commit=actual_commit,application_git_tree=actual_tree,
                prior_gate='existing workflow verify_source.py and verify_alignment.py')
            url=validate_url(os.environ.get('GO_C11_RUNTIME_DATABASE_URL',''))
            base=create_engine(url,connect_args={'connect_timeout':5,'options':'-cstatement_timeout=5000 -clock_timeout=3000'})
            schema='c12_capacity_'+uuid4().hex
            with base.begin() as conn:
                run['postgres_server_version']=conn.scalar(text('SHOW server_version'))
                run['postgres_max_connections']=conn.scalar(text('SHOW max_connections'))
                run['postgres_transaction_isolation']=conn.scalar(text('SHOW default_transaction_isolation'))
                run['postgres_shared_buffers']=conn.scalar(text('SHOW shared_buffers'))
                conn.execute(text('CREATE SCHEMA '+schema))
            database=url.update_query_dict({'options':'-csearch_path='+schema+' -cstatement_timeout=5000 -clock_timeout=3000 -cidle_in_transaction_session_timeout=15000','connect_timeout':'5'}).render_as_string(hide_password=False)
            run.update(backend='postgresql',isolated_schema=schema)
        # Explicit clean environment: never inherit external provider credentials.
        env={k:os.environ[k] for k in ('PATH','LANG','LC_ALL','TZ') if k in os.environ}
        env.update(DATABASE_URL=database,APP_ENV='test',MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED='false',
            PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(ROOT/'src'))
        if schema:env['C12_CAPACITY_SCHEMA']=schema
        # Reuse the shared explicit synthetic fixture; never invent a tariff.
        fixture=ROOT/'scripts/fixtures/ride-cancellation.synthetic.json'
        assert fixture.is_file(), 'EXPLICIT_SYNTHETIC_POLICY_FIXTURE_REQUIRED'
        run['synthetic_policy_sha256']=hashlib.sha256(fixture.read_bytes()).hexdigest()
        (out/'synthetic-policy.json').write_bytes(fixture.read_bytes())
        env['GO_RIDE_ISOLATED_CANCELLATION_POLICY_FILE']=str(fixture)
        command=[sys.executable,'-B',str(Path(__file__).resolve()),'--worker','--evidence-dir',str(out)]
        if args.sqlite_smoke: command.append('--sqlite-smoke')
        with (out/'worker.log').open('w') as log:
            proc=subprocess.Popen(command,env=env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            try:rc=proc.wait(timeout=WALL_LIMIT_SECONDS)
            except subprocess.TimeoutExpired:
                proc.kill();proc.wait(timeout=10);run['failure']='HARD_WALL_TIMEOUT';rc=124
        run['status']='SMOKE_ONLY' if rc==0 and args.sqlite_smoke else 'EVIDENCE_READY' if rc==0 else 'FAILED'
    except Exception as exc:
        run.update(status='FAILED',error_type=type(exc).__name__,failure='SETUP_OR_ISOLATION_FAILURE')
    finally:
        if base is not None and schema:
            try:
                with base.begin() as conn:conn.execute(text('DROP SCHEMA IF EXISTS '+schema+' CASCADE'))
            except Exception as exc:run.update(cleanup_error=type(exc).__name__,status='FAILED');rc=1
            base.dispose()
        if args.sqlite_smoke:
            for generated in out.glob('smoke-*.db*'):
                if generated.is_file():generated.unlink()
        run.update(exit_code=rc,duration_seconds=time.monotonic()-started,finished_at=datetime.now(timezone.utc).isoformat())
        write_json(out/'execution.json',run)
        suite=ET.Element('testsuite',name='c12_bounded_transaction_capacity',tests='1',failures='0' if rc==0 else '1')
        case=ET.SubElement(suite,'testcase',name='isolated_transaction_write_invariants',time=str(run['duration_seconds']))
        if rc:ET.SubElement(case,'failure',message=run['status']).text='See execution.json and worker.log'
        ET.ElementTree(suite).write(out/'junit.xml',encoding='utf-8',xml_declaration=True)
        write_json(out/'SHA256.json',{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir()) if p.is_file() and p.suffix in {'.json','.xml','.log'} and p.name!='SHA256.json'})
    print(json.dumps({'status':run['status'],'exit_code':rc,'postgres_gate':run.get('postgres_gate','SEE_EXECUTION')}))
    return rc


if __name__=='__main__':
    raise SystemExit(main())
