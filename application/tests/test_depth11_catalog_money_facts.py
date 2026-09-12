import asyncio
from datetime import datetime,timedelta,timezone
import pytest
from sqlalchemy import select,delete
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (OrderRow,PaymentRow,PaymentOrderRootRow as Root,PaymentOrderFactBindingRow as Binding,
    OmnichannelPaymentIntentRow as Intent,OmnichannelMoneyMovementRow as Movement,OmnichannelLedgerEntryRow as Ledger,
    CatalogSupplierRemedyRow as Plan,RefundRow,ConsumerProfileRow)
from tests.test_depth11_catalog_supplier_remedy import booked_order,approved,configure,run,remedy,money,bridge,connector,movements
from go_hotel.fare.service import fare_service


def remove_only_payment_import(oid):
    """Keep the captured payment source; inject loss of its derived money import."""
    with SessionLocal.begin() as s:
        root=s.scalar(select(Root).where(Root.business_type=='HOTEL_ORDER',Root.business_id==oid));iid=root.payment_intent_id
        for model,field in [(Ledger,Ledger.payment_intent_id),(Movement,Movement.root_payment_intent_id),(Binding,Binding.payment_intent_id),(Root,Root.payment_intent_id),(Intent,Intent.payment_intent_id)]:s.execute(delete(model).where(field==iid))


def test_bridge_import_uses_recorded_payment_amount_and_atomic_rollback(client,monkeypatch):
    oid,paid=booked_order(client,'bridge-atomic');remove_only_payment_import(oid)
    with SessionLocal.begin() as s:s.get(OrderRow,oid).total_amount_minor=paid+500000
    post=money._post
    def fail(s,i,m):
        post(s,i,m)
        if m.movement_type=='CAPTURE':raise RuntimeError('capture import interrupted')
    monkeypatch.setattr(money,'_post',fail)
    with pytest.raises(RuntimeError):bridge.ensure_original_root(oid)
    with SessionLocal() as s:
        assert not s.scalars(select(Root).where(Root.business_type=='HOTEL_ORDER',Root.business_id==oid)).all()
        assert not s.scalars(select(Ledger)).all()
        assert s.scalar(select(PaymentRow).where(PaymentRow.order_id==oid)).amount_minor==paid
    monkeypatch.setattr(money,'_post',post);iid=bridge.ensure_original_root(oid)
    with SessionLocal() as s:
        assert s.get(Intent,iid).amount_minor==paid
        assert len(s.scalars(select(Ledger)).all())==2
    assert bridge.ensure_original_root(oid)==iid


def test_unknown_payment_fact_blocks_supplier_request_before_cancel(client):
    oid,paid=booked_order(client,'unknown-payment')
    with SessionLocal.begin() as s:
        root=s.scalar(select(Root).where(Root.business_type=='HOTEL_ORDER',Root.business_id==oid))
        s.scalar(select(Movement).where(Movement.root_payment_intent_id==root.payment_intent_id,Movement.movement_type=='CAPTURE')).state='EXTERNAL_EXECUTOR_REQUIRED'
    with pytest.raises(ValueError,match='RECONCILIATION'):remedy.request(oid,'sup_mock','NO_ROOM',[],'maker')
    assert connector.cancel_calls==0
    with SessionLocal() as s:assert not s.scalars(select(Plan)).all()


def changed_order(client,ident='multi'):
    oid,paid=booked_order(client,ident)
    ci=(datetime.now(timezone.utc)+timedelta(days=35)).date().isoformat();co=(datetime.now(timezone.utc)+timedelta(days=39)).date().isoformat()
    connector.date_price_delta[ci]=100000
    q=asyncio.run(fare_service.change_quote(oid,ci,co));asyncio.run(fare_service.change(oid,q['change_quote_id'],'pm_success'))
    return oid,paid,q['amount_due_minor'],ci,co


def test_supplier_fault_refunds_captured_change_difference_from_its_own_root(client):
    oid,paid,extra,ci,co=changed_order(client,'difference')
    assert extra>0
    c=approved(oid);assert c['actual_paid_minor']==c['refund_due_minor']==paid+extra
    configure('sup_mock',paid+extra);d=run(c);assert d['state']=='COMPLETED'
    with SessionLocal() as s:
        plan=s.get(Plan,c['case_id']);assert len(plan.refund_lines_json)==2
        for line in plan.refund_lines_json:
            refund=s.scalar(select(Movement).where(Movement.idempotency_key=='catalog-fault-refund:'+c['case_id']+':'+line['capture_id']))
            assert refund.parent_movement_id==line['capture_id'] and refund.amount_minor==line['amount_minor']
        # Only the original payment is mirrored in the legacy PaymentRow-based table.
        assert len(s.scalars(select(RefundRow).where(RefundRow.order_id==oid)).all())==1
        assert s.get(OrderRow,oid).status=='CANCELLED'


def test_second_source_refund_failure_rolls_back_both_sources_and_resumes(client,monkeypatch):
    oid,paid,extra,ci,co=changed_order(client,'multi-fault');c=approved(oid);configure('sup_mock',paid+extra);post=money._post;seen=[]
    def fail(s,i,m):
        post(s,i,m)
        if m.movement_type=='REFUND':
            seen.append(m.money_movement_id)
            if len(seen)==2:raise RuntimeError('second original source interrupted')
    monkeypatch.setattr(money,'_post',fail)
    with pytest.raises(RuntimeError):run(c)
    with SessionLocal() as s:assert not s.scalars(select(Movement).where(Movement.movement_type=='REFUND')).all()
    monkeypatch.setattr(money,'_post',post);assert run(c)['state']=='COMPLETED' and connector.cancel_calls==1
    with SessionLocal() as s:assert len(s.scalars(select(Movement).where(Movement.movement_type=='REFUND')).all())==2
