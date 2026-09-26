import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal, engine
from go_hotel.db.models import (VerticalRefundOperationRow as Operation, RailOrderRow, AttractionOrderRow,
    RailRefundRow, AttractionRefundRow, OmnichannelMoneyMovementRow as Movement, RailChangeQuoteRow)
from go_hotel.rail.service import rail_service
from go_hotel.attractions.service import attraction_service
from go_hotel.services import vertical_refund_recovery as recovery
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge
from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as supplier


def booked(vertical, owner='refund-owner'):
    if vertical == 'RAIL':
        offer=rail_service.search('SHA','HZH','2026-09-15')[0]
        q=rail_service.prebook(offer['offer_id'],2)
        order=rail_service.create_order(owner,q['prebook_id'],[{'full_name':'A'},{'full_name':'B'}])
        rail_service.checkout(owner,order['order_id'],'isolated')
        service=rail_service
    else:
        q=attraction_service.prebook('tokyo_skytree','2026-09-15',2)
        order=attraction_service.create_order(owner,{'prebook_id':q['prebook_id'],'offer_id':'tokyo_skytree',
            'visit_date':'2026-09-15','quantity':2,'attendees':[{'full_name':'A'},{'full_name':'B'}]})
        service=attraction_service
    tx=vertical_transaction_bridge.checkout_contract(vertical,order['order_id'],owner,'test-source','isolated://refund')
    supplier.record_supplier_fact(tx['supplier_fulfillment_id'],{'state':'SUPPLIER_CONFIRMED',
        'external_operation_id':'op-'+order['order_id'],'supplier_confirmation_reference':'booking-'+order['order_id'],
        'ticket_numbers':['T-A','T-B'],'voucher_code':'V-'+order['order_id'],'evidence_reference':'isolated://confirmed'})
    return service,owner,order['order_id']


def row_state(vertical,oid):
    with SessionLocal() as s:
        return s.get(RailOrderRow if vertical=='RAIL' else AttractionOrderRow,oid).status


def refunded_movements():
    with SessionLocal() as s:return list(s.scalars(select(Movement).where(Movement.movement_type=='REFUND')))


@pytest.mark.parametrize('vertical',['RAIL','ATTRACTION'])
def test_refund_retry_returns_same_receipt_and_one_money_movement(vertical):
    svc,owner,oid=booked(vertical)
    first=svc.refund(owner,oid)
    assert svc.refund(owner,oid)==first
    assert len(refunded_movements())==1
    with SessionLocal() as s:
        op=s.get(Operation,(vertical,oid))
        assert op.state=='COMPLETED' and op.attempt==1 and op.lease_token is None
        model=RailRefundRow if vertical=='RAIL' else AttractionRefundRow
        assert len(list(s.scalars(select(model).where(model.order_id==oid))))==1
    with pytest.raises(ValueError,match='NOT_FOUND'):svc.refund('other-owner',oid)


@pytest.mark.parametrize('vertical',['RAIL','ATTRACTION'])
def test_money_confirmed_then_order_commit_failure_recovers_without_refund_resend(vertical,monkeypatch):
    svc,owner,oid=booked(vertical)
    original=recovery.project_vertical_lifecycle
    def fail(s,v,o,*args,**kw):
        if o.status=='REFUNDED':raise RuntimeError('CRASH_AFTER_MONEY')
        return original(s,v,o,*args,**kw)
    monkeypatch.setattr(recovery,'project_vertical_lifecycle',fail)
    with pytest.raises(RuntimeError,match='CRASH_AFTER_MONEY'):svc.refund(owner,oid)
    assert row_state(vertical,oid)=='REFUND_PENDING'
    assert len(refunded_movements())==1
    monkeypatch.setattr(recovery,'project_vertical_lifecycle',original)
    assert svc.refund(owner,oid)['status']=='REFUND_COMPLETED'
    assert len(refunded_movements())==1


@pytest.mark.parametrize('vertical',['RAIL','ATTRACTION'])
def test_concurrent_refund_has_one_executor_and_blocks_change_or_redeem(vertical,monkeypatch):
    svc,owner,oid=booked(vertical)
    q=svc.change_quote(owner,oid,'2026-09-16')
    entered=Event();finish=Event();original=recovery.vertical_money_bridge.refund_with_adjustments
    def paused(*args,**kw):
        entered.set();assert finish.wait(10)
        return original(*args,**kw)
    monkeypatch.setattr(recovery.vertical_money_bridge,'refund_with_adjustments',paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        task=pool.submit(svc.refund,owner,oid)
        try:
            assert entered.wait(10)
            with pytest.raises(ValueError,match='ALREADY_PROCESSING'):svc.refund(owner,oid)
            with pytest.raises(ValueError):svc.execute_change(owner,oid,q['quote_id'])
            if vertical=='ATTRACTION':
                with pytest.raises(ValueError):svc.redeem(owner,oid,'isolated://entry')
        finally:finish.set()
        assert task.result()['status']=='REFUND_COMPLETED'
    assert len(refunded_movements())==1


@pytest.mark.parametrize('vertical',['RAIL','ATTRACTION'])
def test_unknown_money_remains_pending_and_cannot_change(vertical,monkeypatch):
    svc,owner,oid=booked(vertical)
    monkeypatch.setattr(recovery.vertical_money_bridge,'refund_with_adjustments',lambda *a,**kw:{'state':'UNKNOWN_EXTERNAL_STATE'})
    with pytest.raises(ValueError,match='MONEY_NOT_CONFIRMED'):svc.refund(owner,oid)
    assert row_state(vertical,oid)=='REFUND_PENDING'
    with pytest.raises(ValueError):svc.change_quote(owner,oid,'2026-09-16')
    assert not refunded_movements()


@pytest.mark.parametrize('vertical',['RAIL','ATTRACTION'])
def test_fabricated_confirmation_cannot_complete_refund(vertical,monkeypatch):
    svc,owner,oid=booked(vertical)
    monkeypatch.setattr(recovery.vertical_money_bridge,'refund_with_adjustments',lambda *a,**kw:{'state':'CONFIRMED','money_movement_id':'absent'})
    with pytest.raises(ValueError,match='MONEY_NOT_CONFIRMED'):svc.refund(owner,oid)
    assert row_state(vertical,oid)=='REFUND_PENDING'


@pytest.mark.parametrize('vertical',['RAIL','ATTRACTION'])
def test_refund_receipt_for_another_order_cannot_complete_this_order(vertical,monkeypatch):
    svc,owner,oid=booked(vertical)
    svc2,owner2,oid2=booked(vertical,'different-owner')
    svc2.refund(owner2,oid2)
    mid=refunded_movements()[0].money_movement_id
    monkeypatch.setattr(recovery.vertical_money_bridge,'refund_with_adjustments',lambda *a,**kw:{'state':'CONFIRMED','money_movement_id':mid})
    with pytest.raises(ValueError,match='MONEY_NOT_CONFIRMED'):svc.refund(owner,oid)
    assert row_state(vertical,oid)=='REFUND_PENDING'


@pytest.mark.parametrize('vertical',['RAIL','ATTRACTION'])
def test_process_exit_after_money_can_resume_only_after_lease_expiry(vertical):
    svc,owner,oid=booked(vertical)
    code='''import os
from go_hotel.services import vertical_refund_recovery as r
from go_hotel.rail.service import rail_service
from go_hotel.attractions.service import attraction_service
original=r.vertical_money_bridge.refund_with_adjustments
def crash(*a,**kw):
 original(*a,**kw)
 os._exit(71)
r.vertical_money_bridge.refund_with_adjustments=crash
(rail_service if os.environ['CASE_VERTICAL']=='RAIL' else attraction_service).refund(os.environ['CASE_OWNER'],os.environ['CASE_ORDER'])
'''
    env={**os.environ,'PYTHONPATH':os.path.abspath('src'),'DATABASE_URL':engine.url.render_as_string(hide_password=False),
        'CASE_VERTICAL':vertical,'CASE_OWNER':owner,'CASE_ORDER':oid}
    proc=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,timeout=30)
    assert proc.returncode==71,proc.stderr.decode()
    assert row_state(vertical,oid)=='REFUND_PENDING' and len(refunded_movements())==1
    with pytest.raises(ValueError,match='ALREADY_PROCESSING'):svc.refund(owner,oid)
    # Advance the isolated persisted lease, not wall-clock sleep or a production clock.
    with SessionLocal.begin() as s:s.get(Operation,(vertical,oid)).lease_until_ms=1
    assert svc.refund(owner,oid)['status']=='REFUND_COMPLETED'
    assert len(refunded_movements())==1


def test_rail_change_reserves_order_before_authorization_and_resumes_after_crash(monkeypatch):
    svc,owner,oid=booked('RAIL');q=svc.change_quote(owner,oid,'2026-09-16')
    original=recovery.vertical_money_bridge.prepare_adjustment
    def crash(*args,**kw):
        original(*args,**kw);raise RuntimeError('AUTHORIZATION_COMMITTED')
    monkeypatch.setattr(recovery.vertical_money_bridge,'prepare_adjustment',crash)
    with pytest.raises(RuntimeError,match='AUTHORIZATION_COMMITTED'):svc.execute_change(owner,oid,q['quote_id'])
    assert row_state('RAIL',oid)=='CHANGE_PENDING'
    with pytest.raises(ValueError,match='NOT_REFUNDABLE'):svc.refund(owner,oid)
    monkeypatch.setattr(recovery.vertical_money_bridge,'prepare_adjustment',original)
    assert svc.execute_change(owner,oid,q['quote_id'])['status']=='UNKNOWN_EXTERNAL_STATE'
    assert svc.execute_change(owner,oid,q['quote_id'])['status']=='UNKNOWN_EXTERNAL_STATE'
    with SessionLocal() as s:
        assert len(list(s.scalars(select(Movement).where(Movement.movement_type=='AUTHORIZATION'))))==2
        assert s.get(RailChangeQuoteRow,q['quote_id']).status=='PENDING_SUPPLIER'


def test_mutated_frozen_quote_is_rejected_before_more_money_moves(monkeypatch):
    svc,owner,oid=booked('RAIL');original=recovery.vertical_money_bridge.refund_with_adjustments
    monkeypatch.setattr(recovery.vertical_money_bridge,'refund_with_adjustments',lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('offline')))
    with pytest.raises(RuntimeError):svc.refund(owner,oid)
    with SessionLocal.begin() as s:
        row=s.get(Operation,('RAIL',oid));row.quote_json=dict(row.quote_json,refund_amount_minor=1)
    monkeypatch.setattr(recovery.vertical_money_bridge,'refund_with_adjustments',original)
    with pytest.raises(ValueError,match='INTEGRITY'):svc.refund(owner,oid)
    assert not refunded_movements()


@pytest.mark.no_db
def test_migration_roundtrip_preserves_prior_history_and_blocks_journal_loss(tmp_path,monkeypatch):
    from alembic import command
    from alembic.config import Config
    from go_hotel.core.config import settings
    db=tmp_path/'recovery.sqlite3';url='sqlite+pysqlite:///'+str(db)
    monkeypatch.setattr(settings,'database_url',url)
    config=Config('alembic.ini');config.set_main_option('sqlalchemy.url',url)
    with sqlite3.connect(db) as c:c.execute('CREATE TABLE old_record (id TEXT)');c.execute("INSERT INTO old_record VALUES ('keep')")
    command.stamp(config,'0127_vertical_prebook_contract');command.upgrade(config,'0128_vertical_refund_recovery')
    command.downgrade(config,'0127_vertical_prebook_contract');command.upgrade(config,'0128_vertical_refund_recovery')
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO vertical_refund_operation (vertical,order_id,account_id,state,quote_json,adjustment_ids_json,request_hash,lease_until_ms,attempt,created_ms) VALUES ('RAIL','order','owner','PENDING','{}','[]','hash',0,0,0)")
    with pytest.raises(RuntimeError,match='DATA_PRESENT'):command.downgrade(config,'0127_vertical_prebook_contract')
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT id FROM old_record').fetchone()[0]=='keep'
        assert c.execute('SELECT version_num FROM alembic_version').fetchone()[0]=='0128_vertical_refund_recovery'
        assert c.execute('SELECT count(*) FROM vertical_refund_operation').fetchone()[0]==1
