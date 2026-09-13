from concurrent.futures import ThreadPoolExecutor
from threading import Barrier,Event
import os,subprocess,sys
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal,engine
from go_hotel.db.models import VerticalCapacityBucketRow as Bucket,VerticalCapacityClaimRow as Claim,OmnichannelMoneyMovementRow as Movement
from go_hotel.services import vertical_capacity as cap
from go_hotel.rail.service import rail_service as rail
from go_hotel.attractions.service import attraction_service as attr
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge as bridge
from test_depth21_refund_recovery import booked


def rail_quote(date='2026-09-15',quantity=2,seat=0):
    offer=rail.search('SHA','HZH',date)[seat]
    return rail.prebook(offer['offer_id'],quantity)


def attr_quote(date='2026-09-15',quantity=2,session='16:00'):
    return attr.prebook('tokyo_skytree',date,quantity,session_time=session)


def order(vertical,quote,owner='owner'):
    qty=quote['terms']['quantity'] if 'terms' in quote else quote['quantity']
    people=[{'full_name':f'Person {i}'} for i in range(qty)]
    if vertical=='RAIL':return rail.create_order(owner,quote['prebook_id'],people)
    terms=quote.get('terms',quote)
    return attr.create_order(owner,{'prebook_id':quote['prebook_id'],'offer_id':'tokyo_skytree',
        'visit_date':terms['visit_date'],'session_time':terms['session_time'],'quantity':qty,'attendees':people})


def cancel(vertical,oid,owner='owner'):
    return cap.cancel_unpaid(vertical,owner,oid,rail._order if vertical=='RAIL' else attr.out)


def ledger():
    with SessionLocal() as s:
        buckets=list(s.scalars(select(Bucket)));claims=list(s.scalars(select(Claim)))
        for b in buckets:
            assert b.allocated==sum(x.quantity for x in claims if x.bucket_id==b.bucket_id and x.state=='ALLOCATED')
            assert 0<=b.allocated<=b.capacity
        return sum(b.allocated for b in buckets)


@pytest.mark.parametrize('vertical,quantity,expected',[('RAIL',9,2),('ATTRACTION',12,2)])
def test_concurrent_distinct_quotes_share_one_capacity(vertical,quantity,expected):
    quotes=[rail_quote(quantity=quantity) if vertical=='RAIL' else attr_quote(quantity=quantity) for _ in range(3)]
    ready=Barrier(3)
    def book(i):
        ready.wait(10)
        try:return order(vertical,quotes[i],f'owner-{i}')
        except ValueError as e:return str(e)
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(book,range(3)))
    assert len([x for x in results if isinstance(x,dict)])==expected,results
    assert len([x for x in results if x==vertical+'_INVENTORY_CHANGED'])==1
    assert ledger()==expected*quantity
    if vertical=='RAIL':assert rail.search('SHA','HZH','2026-09-15')[0]['inventory_left']==0
    else:assert attr.search('东京','2026-09-15')[0]['inventory_by_session']['16:00']==0


@pytest.mark.parametrize('vertical',['RAIL','ATTRACTION'])
def test_cancel_unpaid_releases_once_and_blocks_later_payment(vertical):
    q=rail_quote() if vertical=='RAIL' else attr_quote();o=order(vertical,q)
    assert ledger()==2
    with pytest.raises(ValueError,match='NOT_FOUND'):cancel(vertical,o['order_id'],'intruder')
    first=cancel(vertical,o['order_id']);assert first['status']=='CANCELLED'
    assert cancel(vertical,o['order_id'])==first and ledger()==0
    with pytest.raises(ValueError,match='NOT_PAYABLE'):
        bridge.checkout_contract(vertical,o['order_id'],'owner','isolated','isolated://cancelled')
    assert ledger()==0
    with SessionLocal() as s:assert not list(s.scalars(select(Movement)))


@pytest.mark.parametrize('vertical',['RAIL','ATTRACTION'])
def test_payment_started_cannot_release_capacity(vertical):
    q=rail_quote() if vertical=='RAIL' else attr_quote();o=order(vertical,q)
    bridge.checkout_contract(vertical,o['order_id'],'owner','isolated','isolated://payment')
    with pytest.raises(ValueError):cancel(vertical,o['order_id'])
    assert ledger()==2


@pytest.mark.parametrize('vertical',['RAIL','ATTRACTION'])
def test_refund_only_releases_after_confirmed_money(vertical,monkeypatch):
    svc,owner,oid=booked(vertical)
    from go_hotel.services import vertical_refund_recovery as r
    original=r.vertical_money_bridge.refund_with_adjustments
    def offline(*a,**kw):raise RuntimeError('offline')
    monkeypatch.setattr(r.vertical_money_bridge,'refund_with_adjustments',offline)
    with pytest.raises(RuntimeError):svc.refund(owner,oid)
    assert ledger()==2
    monkeypatch.setattr(r.vertical_money_bridge,'refund_with_adjustments',original)
    svc.refund(owner,oid);assert ledger()==0
    svc.refund(owner,oid);assert ledger()==0


@pytest.mark.parametrize('decision',['TICKETED','FAILED'])
def test_rail_change_holds_both_dates_until_result_then_releases_correct_pool(decision):
    svc,owner,oid=booked('RAIL');old=svc.order(owner,oid)
    q=svc.change_quote(owner,oid,'2026-09-16');svc.execute_change(owner,oid,q['quote_id'])
    assert ledger()==4
    svc.admin_external_state(oid,decision,'isolated://change','ops','NEW' if decision=='TICKETED' else None,['A-new','B-new'] if decision=='TICKETED' else [],q['quote_id'])
    assert ledger()==2
    with SessionLocal() as s:
        active=list(s.scalars(select(Claim).where(Claim.order_id==oid,Claim.state=='ALLOCATED')))
        assert len(active)==1
        resource=s.get(Bucket,active[0].bucket_id).resource_json
        assert resource['travel_date']==('2026-09-16' if decision=='TICKETED' else old['journey']['travel_date'])
    svc.refund(owner,oid);assert ledger()==0


def test_attraction_change_and_redemption_retain_current_session_capacity():
    svc,owner,oid=booked('ATTRACTION')
    q=svc.change_quote(owner,oid,'2026-09-16','17:00');svc.execute_change(owner,oid,q['quote_id'])
    assert ledger()==4
    svc.admin_external_state(oid,'CONFIRMED','isolated://change','ops','NEW','V-NEW')
    assert ledger()==2
    assert attr.search('东京','2026-09-15')[0]['inventory_by_session']['16:00']==24
    assert attr.search('东京','2026-09-16')[0]['inventory_by_session']['17:00']==22
    svc.redeem(owner,oid,'isolated://entry');assert ledger()==2


def test_attraction_same_session_change_does_not_double_reserve():
    svc,owner,oid=booked('ATTRACTION');q=svc.change_quote(owner,oid,'2026-09-15','16:00')
    svc.execute_change(owner,oid,q['quote_id']);assert ledger()==2
    svc.admin_external_state(oid,'CONFIRMED','isolated://same','ops','NEW','NEW-V');assert ledger()==2
    svc.refund(owner,oid);assert ledger()==0


def test_date_and_session_pools_are_isolated():
    order('ATTRACTION',attr_quote(quantity=24));order('ATTRACTION',attr_quote(quantity=24,session='17:00'))
    order('ATTRACTION',attr_quote(date='2026-09-16',quantity=24));assert ledger()==72


def test_same_prebook_replay_does_not_allocate_twice():
    q=rail_quote();a=order('RAIL',q);b=order('RAIL',q)
    assert a==b and ledger()==2


def test_train_capacity_is_shared_across_overlapping_station_queries():
    q=rail_quote(quantity=9);order('RAIL',q)
    offers=rail.search('SHA','NJH','2026-09-15')
    assert offers[0]['inventory_left']==9


@pytest.mark.no_db
def test_migration_blocks_allocated_history_loss(tmp_path,monkeypatch):
    import sqlite3
    from alembic import command
    from alembic.config import Config
    from go_hotel.core.config import settings
    db=tmp_path/'capacity.db';url='sqlite+pysqlite:///'+str(db)
    monkeypatch.setattr(settings,'database_url',url)
    cfg=Config('alembic.ini');cfg.set_main_option('sqlalchemy.url',url)
    command.stamp(cfg,'0129_rail_change_resolution');command.upgrade(cfg,'0130_vertical_capacity')
    command.downgrade(cfg,'0129_rail_change_resolution');command.upgrade(cfg,'0130_vertical_capacity')
    with sqlite3.connect(db) as s:
        s.execute("INSERT INTO vertical_capacity_bucket VALUES ('b','RAIL','{}',2,2)")
        s.execute("INSERT INTO vertical_capacity_claim VALUES ('RAIL','o','ORIGINAL','b',2,'ALLOCATED',0,NULL)")
    with pytest.raises(RuntimeError,match='DATA_PRESENT'):command.downgrade(cfg,'0129_rail_change_resolution')
    with sqlite3.connect(db) as s:assert s.execute('SELECT allocated FROM vertical_capacity_bucket').fetchone()[0]==2


@pytest.mark.parametrize('vertical',['RAIL','ATTRACTION'])
def test_legacy_orders_are_not_silently_ignored(vertical):
    q=rail_quote() if vertical=='RAIL' else attr_quote();o=order(vertical,q)
    with SessionLocal.begin() as s:
        c=s.get(Claim,(vertical,o['order_id'],'ORIGINAL'));b=s.get(Bucket,c.bucket_id)
        b.allocated=0;s.delete(c)
    with pytest.raises(ValueError,match='LEGACY_ORDER_REVIEW_REQUIRED'):
        rail.search('SHA','HZH','2026-09-15') if vertical=='RAIL' else attr.search('东京','2026-09-15')


def test_order_commit_failure_rolls_back_capacity(monkeypatch):
    q=rail_quote()
    import go_hotel.rail.service as module
    original=module.append_vertical_evidence
    def crash(*a,**kw):raise RuntimeError('before_commit')
    monkeypatch.setattr(module,'append_vertical_evidence',crash)
    with pytest.raises(RuntimeError):order('RAIL',q)
    assert ledger()==0
    monkeypatch.setattr(module,'append_vertical_evidence',original)
    order('RAIL',q);assert ledger()==2


def test_capacity_survives_process_exit():
    q=rail_quote()
    code='''import os
from go_hotel.rail.service import rail_service
rail_service.create_order('owner',os.environ['PREBOOK'],[{'full_name':'Person 0'},{'full_name':'Person 1'}])
os._exit(73)
'''
    env={**os.environ,'DATABASE_URL':str(engine.url),'PYTHONPATH':os.path.abspath('src'),'PREBOOK':q['prebook_id']}
    p=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,timeout=30)
    assert p.returncode==73,p.stderr.decode()
    assert ledger()==2
    order('RAIL',q);assert ledger()==2


def test_started_payment_wins_race_against_unpaid_cancellation(monkeypatch):
    q=rail_quote();o=order('RAIL',q)
    from go_hotel.services.omnichannel_payment import omnichannel_payment_service as payments
    entered=Event();finish=Event();original=payments.select_channel
    def pause(*a,**kw):
        entered.set();assert finish.wait(10);return original(*a,**kw)
    monkeypatch.setattr(payments,'select_channel',pause)
    with ThreadPoolExecutor(max_workers=2) as pool:
        task=pool.submit(bridge.checkout_contract,'RAIL',o['order_id'],'owner','isolated','isolated://race')
        try:
            assert entered.wait(10)
            with pytest.raises(ValueError,match='PAYMENT_ALREADY_STARTED'):cancel('RAIL',o['order_id'])
            assert ledger()==2
        finally:finish.set()
        assert task.result()['capture_id']


def test_attraction_change_cannot_reserve_full_target():
    svc,owner,oid=booked('ATTRACTION')
    order('ATTRACTION',attr_quote(date='2026-09-16',quantity=24),'full-owner')
    q=svc.change_quote(owner,oid,'2026-09-16')
    with pytest.raises(ValueError,match='INVENTORY_CHANGED'):svc.execute_change(owner,oid,q['quote_id'])
    assert svc.get(owner,oid)['status']=='CONFIRMED' and ledger()==26


def test_rail_change_target_full_rejects_before_supplemental_authorization():
    cases=[]
    from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as supplier
    for date in ['2026-09-14','2026-09-15']:
        q=rail_quote(date=date,quantity=2,seat=2);o=order('RAIL',q)
        tx=bridge.checkout_contract('RAIL',o['order_id'],'owner','isolated','isolated://capacity')
        supplier.record_supplier_fact(tx['supplier_fulfillment_id'],{'state':'SUPPLIER_CONFIRMED','external_operation_id':o['order_id'],
            'supplier_confirmation_reference':o['order_id'],'ticket_numbers':['A-'+o['order_id'],'B-'+o['order_id']],'evidence_reference':'isolated://confirmation'})
        change=rail.change_quote('owner',o['order_id'],'2026-09-16','BUSINESS_CLASS');cases.append((o,change))
    rail.execute_change('owner',cases[0][0]['order_id'],cases[0][1]['quote_id'])
    with SessionLocal() as s:before=len(list(s.scalars(select(Movement))))
    with pytest.raises(ValueError,match='INVENTORY_CHANGED'):
        rail.execute_change('owner',cases[1][0]['order_id'],cases[1][1]['quote_id'])
    with SessionLocal() as s:assert len(list(s.scalars(select(Movement))))==before
    assert ledger()==6
