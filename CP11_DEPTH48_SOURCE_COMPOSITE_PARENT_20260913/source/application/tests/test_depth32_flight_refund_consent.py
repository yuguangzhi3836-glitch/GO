import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import FlightOrderRow, FlightRefundRow, JourneyRecoveryEvidenceChainRow as Evidence
from go_hotel.flight.service import flight_service as svc
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge
from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as supplier
from go_hotel.services.vertical_money_bridge import vertical_money_bridge as money
from test_depth21_refund_recovery import refunded_movements


def booked():
    owner='flight-consent-owner'
    offer=svc.search('PVG','NRT','2026-10-10')[0]
    pre=svc.prebook(offer['offer_id'])
    order=svc.create_order(owner,pre['prebook_id'],[{'full_name':'ISOLATED ADULT','type':'ADT'}])
    oid=order['order_id']
    tx=vertical_transaction_bridge.checkout_contract('FLIGHT',oid,owner,'test-source','isolated://flight-consent')
    supplier.record_supplier_fact(tx['supplier_fulfillment_id'],{'state':'SUPPLIER_CONFIRMED',
        'external_operation_id':'op-'+oid,'supplier_confirmation_reference':'PNR-'+oid,
        'ticket_numbers':['TICKET-'+oid],'evidence_reference':'isolated://flight-confirmed'})
    assert svc.order(owner,oid)['status']=='TICKETED'
    return owner,oid


def test_flight_refund_consent_and_replay_have_one_money_identity():
    owner,oid=booked();q=svc.refund_quote(owner,oid)
    with pytest.raises(ValueError,match='RECONFIRM'):svc.refund(owner,oid,'f'*64)
    with pytest.raises(ValueError,match='NOT_FOUND'):svc.refund('other',oid,q['quote_hash'])
    assert not refunded_movements()
    first=svc.refund(owner,oid,q['quote_hash'])
    again=svc.refund(owner,oid,q['quote_hash'])
    assert first['refund_id']==again['refund_id'] and again['idempotent_replay']
    with pytest.raises(ValueError,match='RECONFIRM'):svc.refund(owner,oid,'f'*64)
    assert len(refunded_movements())==1


@pytest.mark.parametrize('change',['amount','revision'])
def test_changed_order_invalidates_old_flight_refund_quote(change):
    owner,oid=booked();q=svc.refund_quote(owner,oid)
    with SessionLocal.begin() as s:
        o=s.get(FlightOrderRow,oid)
        if change=='amount':o.total_amount_minor+=100
        else:
            from datetime import timedelta
            o.updated_at+=timedelta(seconds=1)
    with pytest.raises(ValueError,match='RECONFIRM'):svc.refund(owner,oid,q['quote_hash'])
    assert not refunded_movements()


def test_flight_timeout_keeps_frozen_consent_and_resumes_original_money_key(monkeypatch):
    owner,oid=booked();q=svc.refund_quote(owner,oid);original=money.refund_with_adjustments
    def lost(*a,**kw):
        original(*a,**kw);raise RuntimeError('AFTER_MONEY')
    monkeypatch.setattr(money,'refund_with_adjustments',lost)
    with pytest.raises(RuntimeError,match='AFTER_MONEY'):svc.refund(owner,oid,q['quote_hash'])
    assert svc.order(owner,oid)['status']=='REFUND_PENDING' and len(refunded_movements())==1
    with pytest.raises(ValueError,match='RECONFIRM'):svc.refund(owner,oid,'f'*64)
    monkeypatch.setattr(money,'refund_with_adjustments',original)
    assert svc.refund(owner,oid,q['quote_hash'])['status']=='REFUND_COMPLETED'
    assert len(refunded_movements())==1


def test_mutated_consent_record_blocks_recovery(monkeypatch):
    owner,oid=booked();q=svc.refund_quote(owner,oid)
    monkeypatch.setattr(money,'refund_with_adjustments',lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('OFFLINE')))
    with pytest.raises(RuntimeError):svc.refund(owner,oid,q['quote_hash'])
    with SessionLocal.begin() as s:
        op=s.scalar(select(Evidence).where(Evidence.execution_id=='rc20:FLIGHT:'+oid,Evidence.evidence_kind=='REFUND_CONSENT_FROZEN'))
        body=dict(op.evidence_json);body['payload']={**body['payload'],'refund_id':'other'};op.evidence_json=body
    with pytest.raises(ValueError,match='INTEGRITY'):svc.refund(owner,oid,q['quote_hash'])
    assert not refunded_movements()


def test_historical_pending_refund_does_not_invent_consent(monkeypatch):
    owner,oid=booked();q=svc.refund_quote(owner,oid)
    # Reproduce a legacy pending row without removing or rewriting evidence.
    from go_hotel.flight.service import now
    with SessionLocal.begin() as s:
        o=s.get(FlightOrderRow,oid);o.status='REFUND_PENDING';o.updated_at=now()
        s.add(FlightRefundRow(refund_id='legacy-refund',order_id=oid,refund_fee_minor=q['refund_fee_minor'],
            refund_amount_minor=q['refund_amount_minor'],currency=q['currency'],status='REFUND_PENDING',created_at=now()))
    with pytest.raises(ValueError,match='HISTORICAL_CONSENT'):svc.refund(owner,oid,q['quote_hash'])
    assert svc.refund(owner,oid)['status']=='REFUND_COMPLETED'
    assert len(refunded_movements())==1
