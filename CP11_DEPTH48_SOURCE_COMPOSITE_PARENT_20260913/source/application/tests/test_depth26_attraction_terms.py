"""After-sales must use a consumed contract belonging to the actual order."""
import pytest
from sqlalchemy import select
from go_hotel.db.models import VerticalPrebookContractRow as Contract, AttractionOrderRow as Order
from go_hotel.db.session import SessionLocal
from test_depth21_refund_recovery import booked, refunded_movements


@pytest.mark.parametrize('field,value',[
    ('owner_id','another-owner'),('state','QUOTED'),('consumed_hash',None),('consumed_ms',None),
])
def test_contract_binding_rejects_refund_before_any_money(field,value):
    svc,owner,oid=booked('ATTRACTION')
    with SessionLocal.begin() as s:
        row=s.scalar(select(Contract).where(Contract.order_id==oid))
        setattr(row,field,value)
    with pytest.raises(ValueError,match='LEGACY_TERMS_REVIEW_REQUIRED'):
        svc.refund(owner,oid)
    assert refunded_movements()==[]
    with SessionLocal() as s:assert s.get(Order,oid).status=='CONFIRMED'


@pytest.mark.parametrize('field,value',[
    ('quantity',3),('attendees',[{'full_name':'only-one'}]),('product_id','tokyo_concert'),('currency','USD'),
])
def test_order_terms_mismatch_blocks_change_and_refund(field,value):
    svc,owner,oid=booked('ATTRACTION')
    with SessionLocal.begin() as s:setattr(s.get(Order,oid),field,value)
    with pytest.raises(ValueError,match='ORDER_TERMS_INTEGRITY_INVALID'):
        svc.refund_quote(owner,oid)
    with pytest.raises(ValueError,match='ORDER_TERMS_INTEGRITY_INVALID'):
        svc.change_quote(owner,oid,'2026-09-16')
    assert refunded_movements()==[]
