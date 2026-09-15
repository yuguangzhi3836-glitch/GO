from concurrent.futures import ThreadPoolExecutor
from datetime import date,timedelta
from copy import deepcopy

import pytest
from sqlalchemy import select,func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import AttractionOrderRow,VerticalPrebookContractRow as Contract
from go_hotel.attractions.service import attraction_service as svc,CATALOG
from go_hotel.services import vertical_prebook_contract as contracts


def quoted(quantity=2,product='tokyo_skytree',session=None):
    day=(date.today()+timedelta(days=2)).isoformat();q=svc.prebook(product,day,quantity,session_time=session)
    return q,{'prebook_id':q['prebook_id'],'offer_id':product,'visit_date':day,'session_time':q['session_time'],
        'quantity':quantity,'currency':'CNY','attendees':[{'full_name':f'ISOLATED {i}'} for i in range(quantity)]}


def test_persisted_quote_binds_session_party_and_locked_total():
    q,b=quoted(session='17:00');order=svc.create_order('owner',b)
    assert order['quantity']==2 and order['total_amount_minor']==36000 and order['session_time']=='17:00'
    assert order['voucher_code'] is None
    assert svc.create_order('owner',b)['order_id']==order['order_id']
    with SessionLocal() as s:assert s.get(Contract,q['prebook_id']).order_id==order['order_id']


def test_unquoted_order_and_unlisted_session_are_rejected():
    q,b=quoted();b.pop('prebook_id')
    with pytest.raises(ValueError,match='PREBOOK_REQUIRED'):svc.create_order('owner',b)
    with pytest.raises(ValueError,match='SESSION_INVALID'):quoted(session='03:17')


@pytest.mark.parametrize('field,value',[('quantity',1),('currency','USD'),('visit_date','2030-01-01'),('session_time','03:17'),('offer_id','teamlab_planets')])
def test_client_cannot_change_quote_terms(field,value):
    q,b=quoted();b[field]=value
    with pytest.raises(ValueError,match='PREBOOK_(BODY|SESSION)_MISMATCH'):svc.create_order('owner',b)
    with SessionLocal() as s:assert s.get(Contract,q['prebook_id']).state=='QUOTED'


def test_quantity_and_attendees_must_match():
    q,b=quoted();b['attendees']=b['attendees'][:1]
    with pytest.raises(ValueError,match='PARTY_COUNT_MISMATCH'):svc.create_order('owner',b)


def test_cross_account_and_changed_person_cannot_reuse_consumed_quote():
    q,b=quoted();svc.create_order('owner',b)
    with pytest.raises(ValueError,match='CONSUMPTION_CONFLICT'):svc.create_order('other',b)
    changed=deepcopy(b);changed['attendees'][0]['full_name']='DIFFERENT'
    with pytest.raises(ValueError,match='CONSUMPTION_CONFLICT'):svc.create_order('owner',changed)


def test_current_inventory_is_rechecked_before_order_creation(monkeypatch):
    q,b=quoted();monkeypatch.setitem(CATALOG['tokyo_skytree'],'inventory',1)
    with pytest.raises(ValueError,match='INVENTORY_CHANGED'):svc.create_order('owner',b)


def test_locked_price_and_refund_terms_do_not_change_with_catalog(monkeypatch):
    q,b=quoted();monkeypatch.setitem(CATALOG['tokyo_skytree'],'price',99999)
    monkeypatch.setitem(CATALOG['tokyo_skytree'],'refundable',False)
    order=svc.create_order('owner',b)
    assert order['total_amount_minor']==36000
    with SessionLocal.begin() as s:s.get(AttractionOrderRow,order['order_id']).status='CONFIRMED'
    assert svc.refund_quote('owner',order['order_id'])['refund_amount_minor']==36000


def test_expired_quote_cannot_be_consumed(monkeypatch):
    q,b=quoted();now=contracts.db_now_ms;monkeypatch.setattr(contracts,'db_now_ms',lambda s:now(s)+700000)
    with pytest.raises(ValueError,match='EXPIRED'):svc.create_order('owner',b)


def test_parallel_consumption_makes_one_order():
    q,b=quoted()
    def consume(i):
        try:return svc.create_order('owner',b)['order_id']
        except ValueError:return None
    with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(consume,range(6)))
    assert None not in results and len(set(results))==1
    with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(AttractionOrderRow))==1


def test_failed_evidence_rolls_back_contract_and_order(monkeypatch):
    from go_hotel.attractions import service
    q,b=quoted()
    def fail(*args,**kw):raise RuntimeError('isolated failure')
    monkeypatch.setattr(service,'append_vertical_evidence',fail)
    with pytest.raises(RuntimeError):svc.create_order('owner',b)
    with SessionLocal() as s:
        assert s.get(Contract,q['prebook_id']).state=='QUOTED'
        assert s.scalar(select(func.count()).select_from(AttractionOrderRow))==0


def test_declared_child_cannot_use_an_adult_product_quote():
    q,b=quoted(1);b['attendees'][0]['type']='CHD'
    with pytest.raises(ValueError,match='CHILD_FARE'):svc.create_order('owner',b)
