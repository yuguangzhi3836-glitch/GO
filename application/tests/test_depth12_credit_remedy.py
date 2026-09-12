import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import CatalogCreditAllocationRow as Allocation,OmnichannelMoneyMovementRow as Movement,OrderRow,CatalogCreditValueEventRow as Journal
from go_hotel.services import catalog_credit_value as value,catalog_stay_credit as svc,catalog_supplier_remedy as remedy
from go_hotel.services.unified_money_movement import unified_money_movement_service as money
from go_hotel.connectors.mock_hotel import connector
from test_depth12_catalog_credit import convert,redeem,run,net
from test_depth11_catalog_supplier_remedy import approved,configure


def test_supplier_cancel_returns_applied_credit_and_cash_to_each_original_capture(client):
    original,cid,_=convert(client);q,r=redeem(cid,156_800)
    case=approved(r['order_id']);configure('sup_mock',1_600_000)
    assert case['actual_paid_minor']==case['refund_due_minor']==case['compensation_due_minor']==1_600_000
    finished=run(remedy.execute(case['case_id'],case['decision_hash']))
    assert finished['state']=='COMPLETED'
    assert [m.amount_minor for m in net(original) if m.movement_type=='REFUND']==[1_443_200]
    assert [m.amount_minor for m in net(r['order_id']) if m.movement_type=='REFUND']==[156_800]
    with SessionLocal() as s:
        c,p=value.checked(s,cid);a=s.get(Allocation,r['order_id'])
        assert p.available_minor==0 and a.state=='REFUNDED' and a.refunded_minor==1_443_200
    before=connector.cancel_calls
    assert run(remedy.execute(case['case_id'],case['decision_hash']))['state']=='COMPLETED'
    assert connector.cancel_calls==before


def test_lower_price_forfeiture_is_not_refunded_or_double_compensated(client):
    original,cid,_=convert(client);_,r=redeem(cid,-43_200)
    case=approved(r['order_id']);configure('sup_mock',1_400_000)
    assert case['actual_paid_minor']==1_400_000
    assert run(remedy.execute(case['case_id'],case['decision_hash']))['state']=='COMPLETED'
    assert [m.amount_minor for m in net(original) if m.movement_type=='REFUND']==[1_400_000]
    with SessionLocal() as s:value.checked(s,cid)
    assert svc.get_credit(cid)['available_minor']==0


def test_second_refund_failure_rolls_back_credit_and_cash_as_one_stage(client,monkeypatch):
    original,cid,_=convert(client);_,r=redeem(cid,156_800)
    case=approved(r['order_id']);configure('sup_mock',1_600_000)
    original_create=money.create_in_session;count=0
    def fail_second(s,i,b,k,a):
        nonlocal count
        if b['movement_type']=='REFUND':
            count+=1
            if count==2:raise RuntimeError('second refund lost')
        return original_create(s,i,b,k,a)
    monkeypatch.setattr(money,'create_in_session',fail_second)
    with pytest.raises(RuntimeError,match='second refund'):run(remedy.execute(case['case_id'],case['decision_hash']))
    assert not [m for oid in [original,r['order_id']] for m in net(oid) if m.movement_type=='REFUND']
    with SessionLocal() as s:
        value.checked(s,cid);assert s.get(Allocation,r['order_id']).state=='REFUND_RESERVED'
    calls=connector.cancel_calls;monkeypatch.setattr(money,'create_in_session',original_create)
    assert run(remedy.execute(case['case_id'],case['decision_hash']))['state']=='COMPLETED' and connector.cancel_calls==calls


def test_conversion_activation_failure_can_resume_after_supplier_cancel(client,monkeypatch):
    from test_sprint1m_fare_runtime import booked_order
    oid=booked_order(client);q=svc.conversion_quote(oid);original=value.journal
    def fail(s,c,p,kind,*args):
        if kind=='ISSUED':raise RuntimeError('value ledger interruption')
        return original(s,c,p,kind,*args)
    monkeypatch.setattr(value,'journal',fail)
    with pytest.raises(RuntimeError,match='ledger interruption'):run(svc.convert(oid,q['quote_id'],q['quote_hash'],True,'owner'))
    from go_hotel.db.models import StayCreditRow
    with SessionLocal() as s:
        c=s.scalar(select(StayCreditRow).where(StayCreditRow.original_order_id==oid));cid=c.stay_credit_id
        assert c.status=='CANCEL_PENDING' and s.get(OrderRow,oid).status=='CONFIRMED'
    monkeypatch.setattr(value,'journal',original)
    assert run(svc.reconcile_conversion(cid,'owner'))['status']=='ACTIVE' and connector.cancel_calls==1


def test_capture_ledger_failure_rolls_back_capture_but_keeps_confirmed_supplier_for_resume(client,monkeypatch):
    _,cid,_=convert(client);original=money._post
    def fail(s,i,m):
        if i.business_type=='CREDIT_DIFF' and m.movement_type=='CAPTURE':raise RuntimeError('capture ledger interrupted')
        return original(s,i,m)
    monkeypatch.setattr(money,'_post',fail)
    with pytest.raises(RuntimeError,match='capture ledger'):redeem(cid,156_800)
    with SessionLocal() as s:a=s.scalar(select(Allocation).where(Allocation.credit_id==cid));oid=a.order_id;assert a.state=='CAPTURE_PENDING'
    assert not [m for m in net(oid) if m.movement_type=='CAPTURE']
    calls=connector.book_calls;monkeypatch.setattr(money,'_post',original)
    assert run(svc.resume_redemption(oid,'owner'))['status']=='REDEEMED' and connector.book_calls==calls
    with SessionLocal() as s:value.checked(s,cid)


def test_altered_allocation_cannot_move_forfeited_value_into_refundable_value(client):
    _,cid,_=convert(client);_,r=redeem(cid,-43_200)
    with SessionLocal.begin() as s:
        a=s.get(Allocation,r['order_id']);a.applied_minor+=43_200;a.forfeited_minor=0
    with pytest.raises(ValueError,match='AMOUNT_MISMATCH'):approved(r['order_id'])


def test_customer_restored_credit_then_supplier_refund_preserves_original_forfeiture(client):
    from test_depth12_credit_after_sales import cancel
    original,cid,_=convert(client);_,first=redeem(cid,-43_200)
    cancel(first['order_id'])
    assert svc.get_credit(cid)['available_minor']==1_400_000
    _,second=redeem(cid,0,days=120)
    assert second['applied_minor']==1_400_000 and second['amount_due_minor']==43_200
    case=approved(second['order_id']);configure('sup_mock',1_443_200)
    assert run(remedy.execute(case['case_id'],case['decision_hash']))['state']=='COMPLETED'
    assert [m.amount_minor for m in net(original) if m.movement_type=='REFUND']==[1_400_000]
    assert [m.amount_minor for m in net(second['order_id']) if m.movement_type=='REFUND']==[43_200]
    with SessionLocal() as s:
        _,p=value.checked(s,cid);assert p.available_minor==0
        assert s.get(Allocation,first['order_id']).forfeited_minor==43_200
    assert svc.get_credit(cid)['available_minor']==0
