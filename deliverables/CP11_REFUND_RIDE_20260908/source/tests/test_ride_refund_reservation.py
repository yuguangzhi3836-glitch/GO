import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import MobilityRideOrderRow, OmnichannelMoneyMovementRow as Movement, VerticalRefundOperationRow as Operation
from go_hotel.mobility.ride.service import ride_service as svc
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge
from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as supplier
from go_hotel.services.vertical_money_bridge import vertical_money_bridge


def booked(owner='ride-refund-owner'):
    order=svc.create(owner,{'offer_id':'ride_standard','pickup':'PVG','dropoff':'Bund',
        'pickup_at':'2026-09-20T10:00:00','currency':'CNY','passengers':[{'full_name':'RIDER'}]})
    oid=order['order_id'];tx=vertical_transaction_bridge.checkout_contract('RIDE',oid,owner,'test-source','isolated://ride-refund')
    supplier.record_supplier_fact(tx['supplier_fulfillment_id'],{'state':'SUPPLIER_CONFIRMED',
        'external_operation_id':'ride-op-'+oid,'supplier_confirmation_reference':'ride-'+oid,'evidence_reference':'isolated://confirmed'})
    return owner,oid


def state(oid):
    with SessionLocal() as s:return s.get(MobilityRideOrderRow,oid).status


def refunds():
    with SessionLocal() as s:return list(s.scalars(select(Movement).where(Movement.movement_type=='REFUND')))


def test_refund_reservation_blocks_pickup_before_money(monkeypatch):
    owner,oid=booked();original=vertical_money_bridge.refund;started=[]
    def during_money(*a,**kw):
        try:started.append(svc.fulfill(owner,oid,'START','isolated://pickup-race'))
        except ValueError:pass
        return original(*a,**kw)
    monkeypatch.setattr(vertical_money_bridge,'refund',during_money)
    error=None
    try:result=svc.cancel(owner,oid)
    except ValueError as exc:error=str(exc)
    assert not started,{'order_status':state(oid),'confirmed_refunds':len(refunds()),'error':error}
    assert error is None and result['status']=='REFUND_COMPLETED'
    assert state(oid)=='REFUNDED' and len(refunds())==1


def test_lost_refund_response_reserves_order_and_recovers_once(monkeypatch):
    owner,oid=booked();quote=svc.refund_quote(owner,oid);original=vertical_money_bridge.refund
    def lost(*a,**kw):original(*a,**kw);raise RuntimeError('RECEIPT_LOST')
    monkeypatch.setattr(vertical_money_bridge,'refund',lost)
    with pytest.raises(RuntimeError,match='RECEIPT_LOST'):svc.cancel(owner,oid,quote['quote_hash'])
    assert state(oid)=='REFUND_PENDING' and len(refunds())==1
    for action in ['START','COMPLETE']:
        with pytest.raises(ValueError):svc.fulfill(owner,oid,action,'isolated://must-not-fulfill')
    with pytest.raises(ValueError):svc.modify(owner,oid,'2026-09-20T11:00:00')
    with pytest.raises(ValueError):svc.admin_external_state(oid,'UNKNOWN_EXTERNAL_STATE','isolated://stale','ops')
    monkeypatch.setattr(vertical_money_bridge,'refund',original)
    first=svc.cancel(owner,oid,None,True)
    assert svc.cancel(owner,oid,quote['quote_hash'])==first
    assert state(oid)=='REFUNDED' and len(refunds())==1


def test_completed_pickup_blocks_refund_without_money():
    owner,oid=booked();quote=svc.refund_quote(owner,oid)
    svc.fulfill(owner,oid,'START','isolated://pickup')
    with pytest.raises(ValueError,match='NOT_CANCELLABLE'):svc.cancel(owner,oid,quote['quote_hash'])
    assert state(oid)=='IN_PROGRESS' and not refunds()


def test_simultaneous_refund_uses_one_lease_and_original_receipt(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    owner,oid=booked();q=svc.refund_quote(owner,oid);original=vertical_money_bridge.refund
    entered,finish=Event(),Event()
    def slow(*a,**kw):entered.set();assert finish.wait(10);return original(*a,**kw)
    monkeypatch.setattr(vertical_money_bridge,'refund',slow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        task=pool.submit(svc.cancel,owner,oid,q['quote_hash'])
        try:
            assert entered.wait(10)
            with pytest.raises(ValueError,match='ALREADY_PROCESSING'):svc.cancel(owner,oid,q['quote_hash'])
        finally:finish.set()
        assert task.result()['status']=='REFUND_COMPLETED'
    assert len(refunds())==1


def test_process_exit_after_money_resumes_existing_operation():
    import os,subprocess,sys
    from go_hotel.db.session import engine
    from go_hotel.core.config import settings
    owner,oid=booked()
    code='''import os
from go_hotel.mobility.ride.service import ride_service
from go_hotel.services.vertical_money_bridge import vertical_money_bridge
original=vertical_money_bridge.refund
def crash(*a,**kw):
 original(*a,**kw)
 os._exit(73)
vertical_money_bridge.refund=crash
ride_service.cancel(os.environ['RIDE_OWNER'],os.environ['RIDE_ID'])
'''
    env={**os.environ,'DATABASE_URL':str(engine.url),'APP_ENV':settings.app_env,'PYTHONPATH':os.path.abspath('src'),'RIDE_OWNER':owner,'RIDE_ID':oid}
    p=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,timeout=30)
    assert p.returncode==73,p.stderr.decode()
    assert state(oid)=='REFUND_PENDING' and len(refunds())==1
    with pytest.raises(ValueError,match='ALREADY_PROCESSING'):svc.cancel(owner,oid,None,True)
    with SessionLocal.begin() as s:s.get(Operation,('RIDE',oid)).lease_until_ms=1
    assert svc.cancel(owner,oid,None,True)['status']=='REFUND_COMPLETED'
    assert len(refunds())==1


def test_public_ride_cancel_requires_exact_quote_and_recovery_cannot_start(client):
    from tests.test_refund_consent import auth
    owner,h=auth(client,'ride-api');_,oid=booked(owner)
    base='/v1/mobility/orders/'+oid
    assert client.post(base+'/cancel',headers=h).status_code==422
    assert client.post(base+'/refund-progress/reconcile',headers=h).status_code==404
    q=client.get(base+'/refund-quote',headers=h).json()['data']
    svc.modify(owner,oid,'2026-09-20T11:00:00')
    assert client.post(base+'/cancel',headers=h,json={'expected_quote_hash':q['quote_hash']}).status_code==409
    assert not refunds()
    q=client.get(base+'/refund-quote',headers=h).json()['data']
    accepted=client.post(base+'/cancel',headers=h,json={'expected_quote_hash':q['quote_hash']})
    assert accepted.status_code==200,accepted.text
    progress=client.get(base+'/refund-progress',headers=h)
    assert progress.json()['data']['status']=='COMPLETED'
    assert client.post(base+'/refund-progress/reconcile',headers=h).status_code==200
    _,other=auth(client,'ride-other')
    assert client.get(base+'/refund-progress',headers=other).status_code==404
    assert client.post(base+'/refund-progress/reconcile',headers=other).status_code==404
    assert len(refunds())==1


@pytest.mark.no_db
def test_migration_keeps_prior_refunds_and_blocks_ride_history_loss(tmp_path,monkeypatch):
    import sqlite3
    from alembic import command
    from alembic.config import Config
    from go_hotel.core.config import settings
    db=tmp_path/'ride-refunds.sqlite3';url='sqlite+pysqlite:///'+str(db)
    monkeypatch.setattr(settings,'database_url',url)
    config=Config('alembic.ini');config.set_main_option('sqlalchemy.url',url)
    command.stamp(config,'0127_vertical_prebook_contract');command.upgrade(config,'0130_vertical_capacity')
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO vertical_refund_operation (vertical,order_id,account_id,state,quote_json,adjustment_ids_json,request_hash,lease_until_ms,attempt,created_ms) VALUES ('RAIL','old','owner','PENDING','{}','[]','unchanged',0,0,0)")
    command.upgrade(config,'0131_ride_refund_operation');command.downgrade(config,'0130_vertical_capacity');command.upgrade(config,'0131_ride_refund_operation')
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT request_hash FROM vertical_refund_operation WHERE order_id='old'").fetchone()[0]=='unchanged'
        c.execute("INSERT INTO vertical_refund_operation (vertical,order_id,account_id,state,quote_json,adjustment_ids_json,request_hash,lease_until_ms,attempt,created_ms) VALUES ('RIDE','ride','owner','PENDING','{}','[]','keep',0,0,0)")
    with pytest.raises(RuntimeError,match='DATA_PRESENT'):command.downgrade(config,'0130_vertical_capacity')
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT version_num FROM alembic_version').fetchone()[0]=='0131_ride_refund_operation'
        assert c.execute('SELECT count(*) FROM vertical_refund_operation').fetchone()[0]==2


@pytest.mark.parametrize('fleet_state',['DISPATCHED','UNKNOWN','HOLD'])
def test_unresolved_fleet_change_blocks_refund(fleet_state):
    from tests.test_depth19_ride_sync import authority,seed_ride,proposal
    from go_hotel.db.models import RideFlightAdjustmentRow
    auth=authority();ride,identity=seed_ride(auth);aid=proposal(auth,ride,identity)
    with SessionLocal.begin() as s:s.get(RideFlightAdjustmentRow,aid).status=fleet_state
    with pytest.raises(ValueError,match='FLEET_RECONCILIATION_REQUIRED'):svc.refund_quote('u19',ride['order_id'])
    with pytest.raises(ValueError,match='FLEET_RECONCILIATION_REQUIRED'):svc.cancel('u19',ride['order_id'])
    assert state(ride['order_id'])=='CONFIRMED' and not refunds()


def test_completed_legacy_receipt_is_returned_without_new_authorization():
    owner,oid=booked();first=svc.cancel(owner,oid)
    # Reproduce the pre-journal schema state using the actual immutable receipt.
    with SessionLocal.begin() as s:s.delete(s.get(Operation,('RIDE',oid)))
    assert svc.cancel(owner,oid)==first
    with SessionLocal() as s:assert s.get(Operation,('RIDE',oid)) is None
    assert len(refunds())==1


def test_local_commit_failure_after_money_recovers(monkeypatch):
    from go_hotel.services import vertical_refund_recovery as recovery
    owner,oid=booked();original=recovery.project_vertical_lifecycle
    def fail(s,v,o,*a,**kw):
        if v=='RIDE' and o.status=='REFUNDED':raise RuntimeError('LOCAL_COMMIT_FAILED')
        return original(s,v,o,*a,**kw)
    monkeypatch.setattr(recovery,'project_vertical_lifecycle',fail)
    with pytest.raises(RuntimeError,match='LOCAL_COMMIT_FAILED'):svc.cancel(owner,oid)
    assert state(oid)=='REFUND_PENDING' and len(refunds())==1
    monkeypatch.setattr(recovery,'project_vertical_lifecycle',original)
    assert svc.cancel(owner,oid,None,True)['status']=='REFUND_COMPLETED'
    assert len(refunds())==1


def test_fabricated_money_confirmation_cannot_cancel_ride(monkeypatch):
    owner,oid=booked()
    monkeypatch.setattr(vertical_money_bridge,'refund_with_adjustments',lambda *a,**kw:{'state':'CONFIRMED','money_movement_id':'absent'})
    with pytest.raises(ValueError,match='MONEY_NOT_CONFIRMED'):svc.cancel(owner,oid)
    assert state(oid)=='REFUND_PENDING' and not refunds()


def test_public_cancel_denies_foreign_or_absent_orders_without_server_error(client):
    from tests.test_refund_consent import auth
    owner,h=auth(client,'ride-access');_,oid=booked(owner)
    _,other=auth(client,'ride-access-other')
    body={'expected_quote_hash':svc.refund_quote(owner,oid)['quote_hash']}
    foreign=client.post('/v1/mobility/orders/'+oid+'/cancel',headers=other,json=body)
    missing=client.post('/v1/mobility/orders/absent/cancel',headers=h,json=body)
    assert foreign.status_code==missing.status_code==404
    assert foreign.json()['detail']==missing.json()['detail']=='MOBILITY_ORDER_NOT_FOUND'
    assert client.post('/v1/mobility/orders/'+oid+'/cancel',json=body).status_code==401
    assert state(oid)=='CONFIRMED' and not refunds()
