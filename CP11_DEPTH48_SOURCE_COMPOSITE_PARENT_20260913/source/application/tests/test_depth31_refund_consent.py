import pytest
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import RailOrderRow, AttractionOrderRow
from go_hotel.api.refund_confirmation import RefundConfirmation
from test_depth21_refund_recovery import booked, refunded_movements

@pytest.mark.parametrize('vertical',['RAIL','ATTRACTION'])
def test_confirmed_refund_binds_owner_order_terms_and_replay(vertical):
    svc,owner,oid=booked(vertical)
    q=svc.refund_quote(owner,oid)
    assert len(q['quote_hash'])==64
    with pytest.raises(ValueError,match='RECONFIRM'):
        svc.refund(owner,oid,'f'*64)
    assert not refunded_movements()
    with pytest.raises(ValueError,match='NOT_FOUND'):
        svc.refund('another-owner',oid,q['quote_hash'])
    first=svc.refund(owner,oid,q['quote_hash'])
    assert svc.refund(owner,oid,q['quote_hash'])==first
    assert len(refunded_movements())==1
    with pytest.raises(ValueError,match='RECONFIRM'):
        svc.refund(owner,oid,'f'*64)
    assert len(refunded_movements())==1

@pytest.mark.parametrize('vertical',['RAIL','ATTRACTION'])
def test_quote_is_rechecked_inside_order_lock_before_money(vertical):
    svc,owner,oid=booked(vertical)
    q=svc.refund_quote(owner,oid)
    with SessionLocal() as s:
        o=s.get(RailOrderRow if vertical=='RAIL' else AttractionOrderRow,oid)
        o.total_amount_minor+=100
        s.commit()
    with pytest.raises(ValueError,match='RECONFIRM|CONTRACT'):
        svc.refund(owner,oid,q['quote_hash'])
    assert not refunded_movements()

@pytest.mark.parametrize('body',[{}, {'quote_hash':'a'*64,'confirmed':False}, {'quote_hash':'a'*64,'confirmed':'true'}, {'quote_hash':'a'*63,'confirmed':True}, {'quote_hash':'a'*64,'confirmed':True,'extra':1}])
def test_confirmed_endpoint_body_is_strict(body):
    with pytest.raises(ValueError):RefundConfirmation.model_validate(body)
