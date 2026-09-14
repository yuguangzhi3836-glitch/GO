"""C11 isolated process acceptance. PG URL never enters logs or pytest conftest.

Default requires GO_C11_RUNTIME_DATABASE_URL for loopback go_c11_isolated.
--sqlite-smoke creates a new temporary database and never satisfies the PG gate.
"""
import argparse
from datetime import date,datetime,timedelta,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback
from uuid import uuid4
from xml.etree.ElementTree import Element,SubElement,ElementTree
from sqlalchemy import create_engine,text,select
from sqlalchemy.engine import make_url


def main():
    p=argparse.ArgumentParser();p.add_argument('--evidence-dir',required=True);p.add_argument('--sqlite-smoke',action='store_true');args=p.parse_args()
    root=Path(__file__).resolve().parents[2]
    output=Path(args.evidence_dir).resolve();output.mkdir(parents=True,exist_ok=True)
    execution={'task_id':'V70-R2-C11-03','source_anchor':'fef9c748adb77d37ba5d4dc4fa4662eb668303a1',
        'source_commit':os.getenv('GO_C11_SOURCE_COMMIT','UNSPECIFIED'),'started_at':datetime.now(timezone.utc).isoformat(),
        'python':sys.version,'status':'RUNNING','workers':'normal subprocesses','C14':'PENDING','C13':'PENDING'}
    source=['src/go_hotel/api/idempotency.py','src/go_hotel/repositories/sql.py','src/go_hotel/api/routes/flight.py',
        'src/go_hotel/flight/service.py','src/go_hotel/flight/payment_recovery.py','src/go_hotel/services/mutation_boundary.py',
        'ci/next_depth/c11_postgres.py','ci/next_depth/c11_process_actor.py']
    execution['source_files']=[{'path':f,'sha256':hashlib.sha256((root/f).read_bytes()).hexdigest()} for f in source]
    def save(): (output/'execution.json').write_text(json.dumps(execution,indent=2)+'\n')
    schema=None;base=None;cases=[];suite=Element('testsuite',name='c11_isolated_process')
    if args.sqlite_smoke:
        work=Path(tempfile.mkdtemp(prefix='c11-process-'));database='sqlite+pysqlite:///'+str(work/'database.db')
        execution.update(database_backend='sqlite',postgres_gate='HOLD_NOT_POSTGRES')
    else:
        raw=os.getenv('GO_C11_RUNTIME_DATABASE_URL')
        if not raw:
            execution.update(status='HOLD',reason='ISOLATED_POSTGRES_URL_NOT_SUPPLIED');save();return 2
        url=make_url(raw)
        if url.get_backend_name()!='postgresql' or url.host not in {'127.0.0.1','localhost','::1'} or url.database!='go_c11_isolated':
            execution.update(status='HOLD',reason='ISOLATED_LOOPBACK_DATABASE_REQUIRED');save();return 2
        schema='c11_'+uuid4().hex
        base=create_engine(url,connect_args={'connect_timeout':5})
        try:
            with base.begin() as connection:
                execution['postgres_server_version']=connection.scalar(text('SHOW server_version'))
                connection.execute(text('CREATE SCHEMA '+schema))
        except Exception as exc:
            execution.update(status='HOLD',reason='ISOLATED_POSTGRES_UNAVAILABLE',error_type=type(exc).__name__);save();return 2
        database=url.update_query_dict({'options':'-csearch_path='+schema}).render_as_string(hide_password=False)
        execution.update(database_backend='postgresql',isolated_schema=schema)
    os.environ.update(DATABASE_URL=database,APP_ENV='test',PYTHONDONTWRITEBYTECODE='1')
    env=os.environ.copy();env['PYTHONPATH']=str(root/'src')
    sys.path.insert(0,str(root/'src'))
    from go_hotel.db.session import engine,SessionLocal
    from go_hotel.db.models import (Base,FlightOfferRow as Offer,FlightPrebookRow as Prebook,FlightOrderRow as Order,
        FlightChangeQuoteRow as Quote,IdempotencyRow as Claim,PaymentOrderRootRow as Root,
        OmnichannelPaymentIntentRow as Intent,OmnichannelPaymentAttemptRow as Attempt,
        OmnichannelMoneyMovementRow as Movement,OrderSupplierFulfillmentRow as Fulfillment)
    from go_hotel.flight.service import flight_service as flights
    from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as supplier
    actor=root/'ci/next_depth/c11_process_actor.py'
    def command(op,oid,qid,key,pause=None,barrier=None,fault=False):
        cmd=[sys.executable,str(actor),'--operation',op,'--order',oid,'--quote',qid,'--key',key]
        if pause:cmd+=['--pause',pause,'--barrier',str(barrier)]
        if fault:cmd+=['--fault']
        return cmd
    def collect(process,label):
        stdout,_=process.communicate(timeout=35)
        (output/(label+'.log')).write_text(stdout)
        assert process.returncode==0,(label,process.returncode,stdout[-1500:])
        return json.loads(stdout.strip().splitlines()[-1])
    def launch(cmd):return subprocess.Popen(cmd,cwd=root,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    def run(op,oid,qid,key,label,**kw):return collect(launch(command(op,oid,qid,key,**kw)),label)
    def fixture(op,label):
        # Seed immutable input rows directly. This does not exercise unrelated
        # prebook/create-order clocks, whose legacy PG coverage is outside C11.
        offer=flights.search('PVG','NRT',(date.today()+timedelta(days=10)).isoformat())[0]
        oid='c11o_'+uuid4().hex;pid='c11p_'+uuid4().hex;now=datetime.now(timezone.utc)
        with SessionLocal.begin() as s:
            s.add(Prebook(prebook_id=pid,offer_id=offer['offer_id'],total_amount_minor=offer['total_amount_minor'],currency='CNY',status='CONFIRMED',price_locked=True,inventory_confirmed=True,expires_at=now+timedelta(hours=1),created_at=now))
            s.add(Order(order_id=oid,account_id='c11-process-owner',prebook_id=pid,status='PAYMENT_PENDING',total_amount_minor=offer['total_amount_minor'],currency='CNY',passengers=[{'full_name':'C11 PROCESS','type':'ADT'}],ticket_numbers=[],current_itinerary=offer['segments'],created_at=now,updated_at=now))
        qid=''
        if op=='change':
            assert run('checkout',oid,'','seed-'+label,label+'-seed')['http']==200
            with SessionLocal() as s:
                iid=s.scalar(select(Root.payment_intent_id).where(Root.business_id==oid))
                fid=s.scalar(select(Fulfillment.order_supplier_fulfillment_id).where(Fulfillment.payment_intent_id==iid))
            supplier.record_supplier_fact(fid,{'state':'SUPPLIER_CONFIRMED','external_operation_id':label,'supplier_confirmation_reference':'C11PNR','ticket_numbers':['C11TICKET'],'evidence_reference':'isolated://c11-process'})
            qid=flights.change_quote('c11-process-owner',oid,(date.today()+timedelta(days=12)).isoformat())['quote_id']
        return oid,qid
    def observe(op,oid,qid,label):
        rid=qid or oid;operation='FLIGHT_CHECKOUT' if op=='checkout' else 'FLIGHT_EXECUTE_CHANGE'
        with SessionLocal() as s:
            ids=[r.payment_intent_id for r in s.scalars(select(Root).where(Root.business_id==rid))]
            money=[{'id':m.money_movement_id,'root':m.root_payment_intent_id,'type':m.movement_type,'state':m.state,'amount':m.amount_minor,'currency':m.currency,'key':m.idempotency_key,'parent':m.parent_movement_id} for m in s.scalars(select(Movement).where(Movement.business_id==rid).order_by(Movement.movement_type))]
            attempts=[a.payment_attempt_id for a in s.scalars(select(Attempt).where(Attempt.payment_intent_id.in_(ids)))]
            claims=[{'operation':c.operation,'key':c.idempotency_key,'resource':c.resource_id,'code':c.response_code,'body':c.response_body} for c in s.scalars(select(Claim).where(Claim.resource_id==rid))]
            result={'root_ids':ids,'money':money,'attempt_ids':attempts,'claims':claims,'order_status':s.get(Order,oid).status,'quote_status':s.get(Quote,qid).status if qid else None}
        (output/(label+'-sql.json')).write_text(json.dumps(result,indent=2)+'\n');return result
    def wait_ready(process,barrier):
        until=time.monotonic()+30
        while not Path(str(barrier)+'.ready').exists():
            if process.poll() is not None:raise AssertionError('actor exited before committed barrier: '+process.communicate()[0][-1500:])
            if time.monotonic()>until:raise TimeoutError('committed barrier not reached')
            time.sleep(.02)
    save()
    try:
        Base.metadata.create_all(engine)
        for op in ['checkout','change']:
            for scenario in ['same_key','different_key','recover','kill_before_bridge','kill_after_money']:
                label=op+'-'+scenario;case=SubElement(suite,'testcase',name=label);started=time.monotonic();active=None
                try:
                    oid,qid=fixture(op,label);key='request-'+label;barrier=output/label
                    pause='after_money' if scenario in {'recover','kill_after_money'} else 'before_bridge'
                    active=launch(command(op,oid,qid,key,pause,barrier,fault=scenario=='recover'))
                    wait_ready(active,barrier)
                    before=observe(op,oid,qid,label+'-before')
                    if scenario=='recover':
                        assert collect(active,label+'-first')['http']!=200;active=None
                        result=run(op,oid,qid,key,label+'-recover');assert result['http']==200
                        after=observe(op,oid,qid,label+'-after')
                        assert after['money']==before['money'] and after['root_ids']==before['root_ids']
                    elif scenario.startswith('kill_'):
                        active.kill();stdout,_=active.communicate(timeout=10)
                        (output/(label+'-killed.log')).write_text(stdout+'\nexit='+str(active.returncode)+'\n');assert active.returncode<0;active=None
                        assert run(op,oid,qid,key,label+'-restart')['http']==409
                        assert run(op,oid,qid,key+'-other',label+'-other')['http']==409
                        after=observe(op,oid,qid,label+'-after')
                        assert after['money']==before['money'] and after['root_ids']==before['root_ids']
                        assert any(c['operation'].startswith('RESOURCE:') and c['body'].get('status')=='RUNNING' for c in after['claims'])
                    else:
                        second=key if scenario=='same_key' else key+'-other'
                        assert run(op,oid,qid,second,label+'-second')['http']==409
                        Path(str(barrier)+'.release').write_text('release\n')
                        result=collect(active,label+'-first');active=None;assert result['http']==200
                        assert run(op,oid,qid,second,label+'-replay')==result
                        after=observe(op,oid,qid,label+'-after')
                        assert len(after['root_ids'])==1
                        assert len(after['money'])==(2 if op=='checkout' else 1)
                        assert len(after['attempt_ids'])==(1 if op=='checkout' else 0)
                    cases.append({'case':label,'status':'PASS','duration_seconds':time.monotonic()-started})
                except Exception:
                    failure=traceback.format_exc();SubElement(case,'failure',message='process acceptance failed').text=failure
                    (output/(label+'-failure.log')).write_text(failure);cases.append({'case':label,'status':'FAIL'})
                finally:
                    if active is not None and active.poll() is None:active.kill();active.communicate(timeout=10)
                    case.set('time',str(time.monotonic()-started))
    except Exception:
        execution['setup_error']=traceback.format_exc();cases.append({'case':'setup','status':'FAIL'})
    finally:
        engine.dispose()
        if schema:
            with base.begin() as connection:connection.execute(text('DROP SCHEMA '+schema+' CASCADE'))
            base.dispose()
    failures=sum(c['status']=='FAIL' for c in cases)
    suite.set('tests',str(len(cases)));suite.set('failures',str(failures));ElementTree(suite).write(output/'junit.xml',encoding='utf-8',xml_declaration=True)
    (output/'results.json').write_text(json.dumps(cases,indent=2)+'\n')
    execution.update(finished_at=datetime.now(timezone.utc).isoformat(),status='TEST_FAILED' if failures else 'EVIDENCE_READY',tests=len(cases),failures=failures,
        hard_death_auto_recovery='HOLD: RUNNING is never automatically stolen; tests prove no duplicate execution')
    save();print(json.dumps({'status':execution['status'],'tests':len(cases),'failures':failures,'backend':execution['database_backend']}))
    return 1 if failures else 0

if __name__=='__main__':raise SystemExit(main())
