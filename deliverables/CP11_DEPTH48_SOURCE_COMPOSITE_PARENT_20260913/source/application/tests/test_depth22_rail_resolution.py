import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal, engine
from go_hotel.db.models import RailOrderRow, RailChangeQuoteRow, RailChangeResolutionRow as Resolution, OmnichannelMoneyMovementRow as Movement
from go_hotel.services import rail_change_resolution as recovery
from test_depth21_refund_recovery import booked


def pending():
    svc,owner,oid=booked('RAIL');old=svc.order(owner,oid)
    q=svc.change_quote(owner,oid,'2026-09-16');svc.execute_change(owner,oid,q['quote_id'])
    return svc,owner,oid,q['quote_id'],old


def resolve(c,decision='TICKETED'):
    return c[0].admin_external_state(c[2],decision,'isolated://resolution','ops',
        'CHANGED' if decision=='TICKETED' else None,['NEW-A','NEW-B'] if decision=='TICKETED' else [],c[3])


def count(kind):
    with SessionLocal() as s:return len(list(s.scalars(select(Movement).where(Movement.movement_type==kind))))


def check_money(decision):
    assert count('CAPTURE')==(2 if decision=='TICKETED' else 1)
    assert count('RELEASE')==(0 if decision=='TICKETED' else 1)


@pytest.mark.parametrize('decision',['TICKETED','FAILED'])
def test_exact_replay_and_conflicting_decision(decision):
    c=pending();first=resolve(c,decision)
    assert resolve(c,decision)==first
    with pytest.raises(ValueError,match='CONFLICT'):resolve(c,'FAILED' if decision=='TICKETED' else 'TICKETED')
    assert first['status']=='TICKETED'
    assert first['total_amount_minor']==c[4]['total_amount_minor']+(7000 if decision=='TICKETED' else 0)
    check_money(decision)
    with SessionLocal() as s:assert s.get(Resolution,c[3]).attempt==1


@pytest.mark.parametrize('decision',['TICKETED','FAILED'])
def test_commit_failure_after_money_recovers(decision,monkeypatch):
    c=pending();original=recovery._event
    def fail(s,o,kind,*a,**kw):
        if kind in {'CHANGE_RECONCILED_TO_TICKETED','CHANGE_FAILED_RESTORED_TICKETED'}:raise RuntimeError('AFTER_MONEY')
        return original(s,o,kind,*a,**kw)
    monkeypatch.setattr(recovery,'_event',fail)
    with pytest.raises(RuntimeError,match='AFTER_MONEY'):resolve(c,decision)
    assert c[0].order(c[1],c[2])['status']=='UNKNOWN_EXTERNAL_STATE'
    with pytest.raises(ValueError):c[0].refund(c[1],c[2])
    with pytest.raises(ValueError):c[0].change_quote(c[1],c[2],'2026-09-17')
    monkeypatch.setattr(recovery,'_event',original)
    assert resolve(c,decision)['status']=='TICKETED';check_money(decision)


@pytest.mark.parametrize('decision',['TICKETED','FAILED'])
def test_concurrent_opposite_decision_never_dispatches_money(decision,monkeypatch):
    c=pending();entered=Event();finish=Event()
    method='capture_adjustment' if decision=='TICKETED' else 'release_adjustment'
    original=getattr(recovery.vertical_money_bridge,method)
    def pause(*a,**kw):
        entered.set();assert finish.wait(10);return original(*a,**kw)
    monkeypatch.setattr(recovery.vertical_money_bridge,method,pause)
    with ThreadPoolExecutor(max_workers=2) as pool:
        task=pool.submit(resolve,c,decision)
        try:
            assert entered.wait(10)
            with pytest.raises(ValueError,match='CONFLICT'):resolve(c,'FAILED' if decision=='TICKETED' else 'TICKETED')
            with pytest.raises(ValueError,match='ALREADY_PROCESSING'):resolve(c,decision)
        finally:finish.set()
        assert task.result()['status']=='TICKETED'
    check_money(decision)


@pytest.mark.parametrize('decision',['TICKETED','FAILED'])
def test_process_exit_after_money_recovers(decision):
    c=pending()
    code='''import os
from go_hotel.services import rail_change_resolution as r
from go_hotel.rail.service import rail_service
state=os.environ['DECISION']
method='capture_adjustment' if state=='TICKETED' else 'release_adjustment'
original=getattr(r.vertical_money_bridge,method)
def crash(*a,**kw):
 original(*a,**kw)
 os._exit(72)
setattr(r.vertical_money_bridge,method,crash)
rail_service.admin_external_state(os.environ['ORDER'],state,'isolated://resolution','ops','CHANGED' if state=='TICKETED' else None,['NEW-A','NEW-B'] if state=='TICKETED' else [],os.environ['QUOTE'])
'''
    env={**os.environ,'DATABASE_URL':str(engine.url),'PYTHONPATH':os.path.abspath('src'),'ORDER':c[2],'QUOTE':c[3],'DECISION':decision}
    p=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,timeout=30)
    assert p.returncode==72,p.stderr.decode()
    with pytest.raises(ValueError,match='ALREADY_PROCESSING'):resolve(c,decision)
    with SessionLocal.begin() as s:s.get(Resolution,c[3]).lease_until_ms=1
    assert resolve(c,decision)['status']=='TICKETED';check_money(decision)


def test_prior_replay_cannot_modify_next_change():
    c=pending();first=resolve(c)
    q=c[0].change_quote(c[1],c[2],'2026-09-18');c[0].execute_change(c[1],c[2],q['quote_id'])
    assert resolve(c)==first
    assert c[0].order(c[1],c[2])['status']=='UNKNOWN_EXTERNAL_STATE'
    with SessionLocal() as s:assert s.get(RailChangeQuoteRow,q['quote_id']).status=='PENDING_SUPPLIER'
    assert count('CAPTURE')==2


@pytest.mark.parametrize('mutation',['ticket','quote','owner','hash'])
def test_frozen_identity_cannot_be_replaced(mutation,monkeypatch):
    c=pending();original=recovery.vertical_money_bridge.capture_adjustment
    def offline(*a,**kw):raise RuntimeError('offline')
    monkeypatch.setattr(recovery.vertical_money_bridge,'capture_adjustment',offline)
    with pytest.raises(RuntimeError):resolve(c)
    monkeypatch.setattr(recovery.vertical_money_bridge,'capture_adjustment',original)
    if mutation=='ticket':
        with pytest.raises(ValueError,match='CONFLICT'):
            c[0].admin_external_state(c[2],'TICKETED','isolated://resolution','ops','CHANGED',['REPLACE-A','REPLACE-B'],c[3])
    else:
        with SessionLocal.begin() as s:
            if mutation=='quote':s.get(RailChangeQuoteRow,c[3]).total_due_minor+=1
            elif mutation=='owner':s.get(RailOrderRow,c[2]).account_id='intruder'
            else:s.get(Resolution,c[3]).request_hash='changed'
        with pytest.raises(ValueError,match='INVALID'):resolve(c)
    assert count('CAPTURE')==1


@pytest.mark.parametrize('decision',['TICKETED','FAILED'])
def test_fabricated_money_stays_pending(decision,monkeypatch):
    c=pending();method='capture_adjustment' if decision=='TICKETED' else 'release_adjustment'
    monkeypatch.setattr(recovery.vertical_money_bridge,method,lambda *a,**kw:{'capture_id':'missing','release_id':'missing'})
    with pytest.raises(ValueError,match='MONEY_NOT_CONFIRMED'):resolve(c,decision)
    assert c[0].order(c[1],c[2])['status']=='UNKNOWN_EXTERNAL_STATE'
    with SessionLocal() as s:assert s.get(Resolution,c[3]).state=='PENDING'


def test_stale_worker_cannot_commit(monkeypatch):
    c=pending();original=recovery.vertical_money_bridge.capture_adjustment
    def expire(*a,**kw):
        result=original(*a,**kw)
        with SessionLocal.begin() as s:
            row=s.get(Resolution,c[3]);row.lease_token='new-worker';row.lease_until_ms=1
        return result
    monkeypatch.setattr(recovery.vertical_money_bridge,'capture_adjustment',expire)
    with pytest.raises(ValueError,match='LEASE_LOST'):resolve(c)
    assert c[0].order(c[1],c[2])['status']=='UNKNOWN_EXTERNAL_STATE'
    monkeypatch.setattr(recovery.vertical_money_bridge,'capture_adjustment',original)
    assert resolve(c)['status']=='TICKETED';assert count('CAPTURE')==2


@pytest.mark.no_db
def test_migration_retains_nonempty_journal(tmp_path,monkeypatch):
    import sqlite3
    from alembic import command
    from alembic.config import Config
    from go_hotel.core.config import settings
    db=tmp_path/'resolution.db';url='sqlite+pysqlite:///'+str(db)
    monkeypatch.setattr(settings,'database_url',url)
    config=Config('alembic.ini');config.set_main_option('sqlalchemy.url',url)
    command.stamp(config,'0128_vertical_refund_recovery');command.upgrade(config,'0129_rail_change_resolution')
    command.downgrade(config,'0128_vertical_refund_recovery');command.upgrade(config,'0129_rail_change_resolution')
    with sqlite3.connect(db) as s:
        s.execute("INSERT INTO rail_change_resolution (quote_id,order_id,account_id,actor_id,state,request_json,terms_json,request_hash,lease_until_ms,attempt,created_ms) VALUES ('q','o','a','ops','PENDING','{}','{}','hash',0,0,0)")
    with pytest.raises(RuntimeError,match='DATA_PRESENT'):command.downgrade(config,'0128_vertical_refund_recovery')
    with sqlite3.connect(db) as s:
        assert s.execute('SELECT count(*) FROM rail_change_resolution').fetchone()[0]==1
        assert s.execute('SELECT version_num FROM alembic_version').fetchone()[0]=='0129_rail_change_resolution'


def test_quote_id_required_when_delayed_response_is_ambiguous():
    c=pending();resolve(c)
    q=c[0].change_quote(c[1],c[2],'2026-09-18');c[0].execute_change(c[1],c[2],q['quote_id'])
    with pytest.raises(ValueError,match='QUOTE_ID_REQUIRED'):
        c[0].admin_external_state(c[2],'TICKETED','isolated://resolution','ops','CHANGED',['NEW-A','NEW-B'])
    assert c[0].order(c[1],c[2])['status']=='UNKNOWN_EXTERNAL_STATE'
    assert count('CAPTURE')==2


def test_money_receipt_from_other_order_rejected(monkeypatch):
    c=pending();other=pending();resolve(other)
    with SessionLocal() as s:
        from go_hotel.db.models import PaymentOrderRootRow
        root=s.scalar(select(PaymentOrderRootRow).where(PaymentOrderRootRow.business_id==other[3]))
        cap=s.scalar(select(Movement).where(Movement.root_payment_intent_id==root.payment_intent_id,Movement.movement_type=='CAPTURE'))
        mid=cap.money_movement_id
    monkeypatch.setattr(recovery.vertical_money_bridge,'capture_adjustment',lambda *a,**kw:{'capture_id':mid})
    with pytest.raises(ValueError,match='MONEY_NOT_CONFIRMED'):resolve(c)
    assert c[0].order(c[1],c[2])['status']=='UNKNOWN_EXTERNAL_STATE'


def test_quote_id_from_other_order_cannot_dispatch_money():
    c=pending();other=pending()
    with pytest.raises(ValueError,match='QUOTE_INVALID'):
        c[0].admin_external_state(c[2],'TICKETED','isolated://resolution','ops','CHANGED',['NEW-A','NEW-B'],other[3])
    assert count('CAPTURE')==2


def test_admin_route_requires_auth_and_conflicts_are_409(client):
    from go_hotel.api.routes.rail import wrap
    from fastapi import HTTPException
    response=client.post('/internal/v1/admin/rail/orders/absent/external-state',json={'state':'TICKETED','evidence_reference':'e','quote_id':'q'})
    assert response.status_code in {401,403}
    def conflict():raise ValueError('RAIL_RESOLUTION_CONFLICT')
    with pytest.raises(HTTPException) as error:wrap(conflict)
    assert error.value.status_code==409
