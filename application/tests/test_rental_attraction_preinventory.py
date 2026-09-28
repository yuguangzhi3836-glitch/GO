"""Concrete preinventory boundaries; all money and suppliers remain isolated."""
import pytest
from sqlalchemy import select
from go_hotel.db.models import AttractionOrderRow, AttractionChangeQuoteRow, OmnichannelMoneyMovementRow
from go_hotel.db.session import SessionLocal
from go_hotel.attractions.service import CATALOG
from go_hotel.core.config import settings
from tests.test_depth21_refund_recovery import booked
from tests.test_ticket_operations_runtime import login


def money():
    with SessionLocal() as s:
        return [(m.money_movement_id,m.state,m.amount_minor,m.currency,m.movement_type) for m in
                s.scalars(select(OmnichannelMoneyMovementRow).order_by(OmnichannelMoneyMovementRow.money_movement_id))]


def test_supplier_closure_refunds_even_customer_nonrefundable_policy(monkeypatch):
    monkeypatch.setitem(CATALOG['tokyo_skytree'],'refundable',False)
    svc,owner,oid=booked('ATTRACTION')
    assert svc.refund_quote(owner,oid)['refund_amount_minor']==0
    svc.admin_external_state(oid,'CLOSED_BY_SUPPLIER','isolated://closure','ops')
    quote=svc.refund_quote(owner,oid)
    assert quote['reason']=='SUPPLIER_CLOSED' and quote['refund_amount_minor']==36000
    receipt=svc.refund(owner,oid,quote['quote_hash'])
    before=money()
    assert svc.refund(owner,oid,quote['quote_hash'])==receipt
    assert money()==before
    assert sum(x[2] for x in before if x[1]=='CONFIRMED' and x[4]=='CAPTURE')==36000
    assert sum(x[2] for x in before if x[1]=='CONFIRMED' and x[4]=='REFUND')==36000
    with pytest.raises(ValueError,match='ATTRACTION_RECONCILIATION_NOT_REQUIRED'):
        svc.admin_external_state(oid,'CONFIRMED','isolated://late','ops','LATE','LATE')
    assert money()==before and svc.get(owner,oid)['status']=='REFUNDED'


def test_older_attraction_quote_cannot_override_completed_change():
    svc,owner,oid=booked('ATTRACTION')
    first=svc.change_quote(owner,oid,'2026-09-16')
    stale=svc.change_quote(owner,oid,'2026-09-17')
    svc.execute_change(owner,oid,first['quote_id'])
    svc.admin_external_state(oid,'CONFIRMED','isolated://changed','ops','NEXT','NEXT',first['quote_id'])
    before=svc.get(owner,oid),money()
    with pytest.raises(ValueError,match='ATTRACTION_CHANGE_QUOTE_STALE_REQUOTE_REQUIRED'):
        svc.execute_change(owner,oid,stale['quote_id'])
    assert (svc.get(owner,oid),money())==before


def test_quote_target_tampering_cannot_change_capacity_or_order():
    svc,owner,oid=booked('ATTRACTION')
    quote=svc.change_quote(owner,oid,'2026-09-16')
    with SessionLocal.begin() as s:
        s.get(AttractionChangeQuoteRow,quote['quote_id']).new_session_time='17:00'
    before=svc.get(owner,oid),svc.search('东京','2026-09-16'),money()
    with pytest.raises(ValueError,match='ATTRACTION_CHANGE_QUOTE_STALE_REQUOTE_REQUIRED'):
        svc.execute_change(owner,oid,quote['quote_id'])
    assert (svc.get(owner,oid),svc.search('东京','2026-09-16'),money())==before


@pytest.mark.parametrize('path',['attractions','mobility'])
def test_readonly_admin_cannot_submit_external_state(client,monkeypatch,path):
    monkeypatch.setattr(settings,'mfa_required_for_admin',False)
    svc,owner,oid=booked('ATTRACTION')
    before=svc.get(owner,oid),money()
    response=client.post(f'/internal/v1/admin/{path}/orders/{oid}/external-state',headers=login('READ_ONLY'),
        json={'state':'UNKNOWN_EXTERNAL_STATE','evidence_reference':'isolated://readonly'})
    assert response.status_code==403
    assert (svc.get(owner,oid),money())==before


def test_confirmation_requires_actual_voucher_identity():
    svc,owner,oid=booked('ATTRACTION')
    svc.admin_external_state(oid,'UNKNOWN_EXTERNAL_STATE','isolated://unknown','ops')
    with SessionLocal.begin() as s:
        o=s.get(AttractionOrderRow,oid);o.voucher_code=None;o.supplier_reference=None
    before=svc.get(owner,oid),money()
    with pytest.raises(ValueError,match='ATTRACTION_RECONCILIATION_VOUCHER_REQUIRED'):
        svc.admin_external_state(oid,'CONFIRMED','isolated://incomplete','ops')
    assert (svc.get(owner,oid),money())==before
    assert svc.admin_external_state(oid,'CONFIRMED','isolated://proof','ops','VALID','VALID')['voucher_code']=='VALID'
