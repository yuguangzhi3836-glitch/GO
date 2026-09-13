from concurrent.futures import ThreadPoolExecutor
from datetime import date,timedelta
from copy import deepcopy

import pytest
from sqlalchemy import select,func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import RailOrderRow,RailPrebookRow,VerticalPrebookContractRow as Contract
from go_hotel.rail.service import rail_service
from go_hotel.services import vertical_prebook_contract as contracts


def quote(quantity=2,account=None):
    offer=rail_service.search('SHA','HZH',(date.today()+timedelta(days=2)).isoformat())[0]
    return rail_service.prebook(offer['offer_id'],quantity,account)


def party(count=2):return [{'full_name':f'ISOLATED {i}','type':'ADT'} for i in range(count)]


def test_party_quote_binds_total_count_and_one_order():
    q=quote();assert q['quantity']==2 and q['total_amount_minor']==14700 and q['unit_amount_minor']==7350
    assert q['provider_inventory_reserved'] is False
    order=rail_service.create_order('owner',q['prebook_id'],party())
    assert order['total_amount_minor']==14700 and order['passenger_count']==2
    replay=rail_service.create_order('owner',q['prebook_id'],party())
    assert replay['order_id']==order['order_id']
    with SessionLocal() as s:
        assert s.get(RailPrebookRow,q['prebook_id']).status=='CONSUMED'
        assert s.get(Contract,q['prebook_id']).order_id==order['order_id']
        assert s.scalar(select(func.count()).select_from(RailOrderRow))==1


@pytest.mark.parametrize('count',[0,1,3])
def test_unquoted_party_size_cannot_change_price_at_order_creation(count):
    q=quote()
    with pytest.raises(ValueError,match='PARTY_COUNT_MISMATCH'):rail_service.create_order('owner',q['prebook_id'],party(count))
    with SessionLocal() as s:assert s.get(Contract,q['prebook_id']).state=='QUOTED'


def test_same_quote_cannot_be_reused_by_another_owner_or_changed_party():
    q=quote();rail_service.create_order('owner',q['prebook_id'],party())
    with pytest.raises(ValueError,match='CONSUMPTION_CONFLICT'):rail_service.create_order('other',q['prebook_id'],party())
    people=party();people[0]['full_name']='DIFFERENT PERSON'
    with pytest.raises(ValueError,match='CONSUMPTION_CONFLICT'):rail_service.create_order('owner',q['prebook_id'],people)


def test_issued_quote_is_private_to_its_account_before_first_consumption():
    q=quote(account='owner')
    with pytest.raises(ValueError,match='NOT_FOUND'):rail_service.create_order('other',q['prebook_id'],party())
    assert rail_service.create_order('owner',q['prebook_id'],party())['passenger_count']==2


def test_expired_quote_cannot_be_consumed_but_exact_completed_request_can_be_replayed(monkeypatch):
    q=quote();old=contracts.db_now_ms
    monkeypatch.setattr(contracts,'db_now_ms',lambda s:old(s)+700000)
    with pytest.raises(ValueError,match='EXPIRED'):rail_service.create_order('owner',q['prebook_id'],party())
    monkeypatch.setattr(contracts,'db_now_ms',old)
    order=rail_service.create_order('owner',q['prebook_id'],party())
    monkeypatch.setattr(contracts,'db_now_ms',lambda s:old(s)+700000)
    assert rail_service.create_order('owner',q['prebook_id'],party())['order_id']==order['order_id']


def test_tampered_terms_cannot_reprice_an_existing_quote():
    q=quote()
    with SessionLocal.begin() as s:
        row=s.get(Contract,q['prebook_id']);row.terms_json=dict(row.terms_json,total_amount_minor=1)
    with pytest.raises(ValueError,match='INTEGRITY'):rail_service.create_order('owner',q['prebook_id'],party())


def test_order_and_quote_consumption_roll_back_together(monkeypatch):
    from go_hotel.rail import service
    q=quote()
    def fail(*args,**kwargs):raise RuntimeError('isolated failed evidence commit')
    monkeypatch.setattr(service,'append_vertical_evidence',fail)
    with pytest.raises(RuntimeError):rail_service.create_order('owner',q['prebook_id'],party())
    with SessionLocal() as s:
        assert s.get(Contract,q['prebook_id']).state=='QUOTED'
        assert s.get(RailPrebookRow,q['prebook_id']).status=='CONFIRMED'
        assert s.scalar(select(func.count()).select_from(RailOrderRow))==0


def test_parallel_consumers_cannot_create_multiple_orders_for_one_prebook():
    q=quote()
    def consume(i):
        try:return rail_service.create_order(f'owner-{i}',q['prebook_id'],party())['order_id']
        except ValueError:return None
    with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(consume,range(8)))
    assert len([x for x in results if x])==1
    with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(RailOrderRow))==1


@pytest.mark.parametrize('person',[{'full_name':'GO Traveler'},{'full_name':' '},{'full_name':'CHILD','type':'CHD'}])
def test_placeholder_name_or_child_cannot_be_used_for_quoted_adult(person):
    q=quote(1)
    with pytest.raises(ValueError):rail_service.create_order('owner',q['prebook_id'],[person])


def test_legacy_prebook_missing_terms_is_not_backfilled_from_current_offer():
    q=quote()
    with SessionLocal.begin() as s:s.delete(s.get(Contract,q['prebook_id']))
    with pytest.raises(ValueError,match='NOT_FOUND'):rail_service.create_order('owner',q['prebook_id'],party())
