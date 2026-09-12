import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from copy import deepcopy
import pytest
from sqlalchemy import select, func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (OrderRow, OrderChangeRow, RefundRow, CatalogCashFareClaimRow as Claim,
    CatalogCashFareOperationRow as Operation, CatalogCashFareQuoteRow as Quote,
    OmnichannelMoneyMovementRow as Movement, PaymentOrderRootRow as Root,
    CatalogOrderFareSnapshotRow as Snapshot, CatalogFareRuleVersionRow as Version)
from go_hotel.services import catalog_cash_fare as fare, catalog_cash_fare_execution as execution
from go_hotel.services import catalog_fare_snapshot as rules, catalog_stay_credit as credit
from go_hotel.services import catalog_supplier_remedy as remedy
from go_hotel.services.hosted_money import money
from go_hotel.connectors.mock_hotel import connector
from test_sprint1m_fare_runtime import booked_order

def day(n): return (datetime.now(timezone.utc).date() + timedelta(days=n)).isoformat()
def run(awaitable): return asyncio.run(awaitable)
def change_quote(oid, delta, n=50):
    connector.date_price_delta[day(n)] = delta
    return run(fare.change_quote(oid, day(n), day(n+4)))
def execute(oid, q, token='pm_success'):
    return run(execution.start(oid,q['quote_id'],q['quote_hash'],True,None,token))
def reconcile(oid, result): return run(execution.reconcile(oid,result['operation_id']))
def moves(oid, typ):
    with SessionLocal() as s:
        roots=remedy.roots(s,s.get(OrderRow,oid))
        return s.scalars(select(Movement).where(Movement.root_payment_intent_id.in_([r.payment_intent_id for r in roots]),Movement.movement_type==typ)).all()

def test_two_higher_changes_charge_only_remaining_difference_and_refund_each_capture(client):
    oid=booked_order(client)
    q1=change_quote(oid,80000);r1=execute(oid,q1)
    assert r1['status']=='CONFIRMED' and r1['amount_paid_minor']==90000
    q2=change_quote(oid,120000,60)
    assert q2['old_value_minor']==1523200 and q2['fare_difference_minor']==40000 and q2['amount_due_minor']==50000
    assert execute(oid,q2)['status']=='CONFIRMED'
    q=fare.cancellation_quote(oid)
    assert q['gross_paid_minor']==1583200 and q['paid_change_fees_minor']==20000
    result=execute(oid,q)
    assert result['refund']['amount_minor']==1583200 and result['refund']['status']=='COMPLETED'
    refunds=moves(oid,'REFUND');caps=moves(oid,'CAPTURE')
    assert len(refunds)==3 and {r.parent_movement_id:r.amount_minor for r in refunds}=={c.money_movement_id:c.amount_minor for c in caps}
    with SessionLocal() as s:
        # A legacy original-payment receipt never pretends to cover the change roots.
        assert s.scalar(select(func.sum(RefundRow.amount_minor)).where(RefundRow.order_id==oid))==1443200
    assert execute(oid,q)['operation_id']==result['operation_id'] and connector.cancel_calls==1

def test_high_low_high_forfeits_lower_difference_without_future_offset(client):
    oid=booked_order(client)
    for delta,n,due in [(80000,50,90000),(-43200,60,10000),(100000,70,153200)]:
        q=change_quote(oid,delta,n);assert q['amount_due_minor']==due
        assert execute(oid,q)['status']=='CONFIRMED'
    assert not moves(oid,'REFUND')
    q=fare.cancellation_quote(oid)
    assert q['current_room_value_minor']==1543200 and q['paid_change_fees_minor']==30000
    assert q['paid_amount_minor']==1696400 and q['forfeited_change_value_minor']==123200
    assert q['refund_amount_minor']==1573200
    conversion=credit.conversion_quote(oid)
    assert conversion['credit_value_minor']==1573200
    assert conversion['cash_change_forfeiture']['excluded_minor']==123200

def test_prior_partial_refund_reduces_current_cancel_basis_and_budget(client):
    oid=booked_order(client)
    fare.cancellation_quote(oid)
    cap=moves(oid,'CAPTURE')[0]
    money.create(cap.root_payment_intent_id,{'movement_type':'REFUND','parent_movement_id':cap.money_movement_id,
        'amount_minor':43200,'mode':'CONTRACT_SIMULATOR','evidence':['simulation://prior-refund']},'prior-refund','test')
    q=fare.cancellation_quote(oid)
    assert q['prior_refund_minor']==43200 and q['refund_amount_minor']==1400000
    execute(oid,q)
    assert sum(x.amount_minor for x in moves(oid,'REFUND'))==1443200

def test_second_refund_failure_rolls_back_all_and_resumes_after_cancelled(client,monkeypatch):
    oid=booked_order(client);execute(oid,change_quote(oid,80000))
    q=fare.cancellation_quote(oid);original=money.create_in_session;calls=[]
    def fail(s,i,b,key,actor):
        if b['movement_type']=='REFUND':
            calls.append(key)
            if len(calls)==2:raise ValueError('SIMULATED_SECOND_REFUND_LEDGER_FAILURE')
        return original(s,i,b,key,actor)
    with monkeypatch.context() as m:
        m.setattr(money,'create_in_session',fail)
        with pytest.raises(ValueError,match='SECOND_REFUND'):execute(oid,q)
    result=fare.status(oid)
    assert result['state']=='REFUND_PENDING' and not moves(oid,'REFUND')
    with SessionLocal() as s:
        assert s.get(OrderRow,oid).status=='CANCELLED'
        assert s.scalar(select(func.count()).select_from(RefundRow))==0
    assert reconcile(oid,result)['refund']['status']=='COMPLETED'
    assert connector.cancel_calls==1 and len(moves(oid,'REFUND'))==2

@pytest.mark.parametrize('action',['CANCEL','CHANGE'])
def test_supplier_reply_loss_queries_confirmed_result_without_redispatch(client,monkeypatch,action):
    oid=booked_order(client)
    q=fare.cancellation_quote(oid) if action=='CANCEL' else change_quote(oid,80000)
    method='cancel' if action=='CANCEL' else 'change'
    original=getattr(connector,method)
    async def lost(*args,**kwargs):
        await original(*args,**kwargs);raise TimeoutError('REPLY_LOST')
    monkeypatch.setattr(connector,method,lost)
    result=execute(oid,q)
    assert result['state']=='UNKNOWN_SUPPLIER'
    assert execute(oid,q)['state']=='UNKNOWN_SUPPLIER'
    done=reconcile(oid,result)
    assert done['state']=='COMPLETED'
    assert (connector.cancel_calls if action=='CANCEL' else connector.change_calls)==1
    assert reconcile(oid,result)['state']=='COMPLETED'

def test_unknown_change_keeps_authorization_and_blocks_other_money_and_business_paths(client):
    oid=booked_order(client);q=change_quote(oid,80000);connector.ambiguous_change=True
    result=execute(oid,q)
    assert result['state']=='UNKNOWN_SUPPLIER'
    for _ in range(2): assert reconcile(oid,result)['state']=='UNKNOWN_SUPPLIER'
    assert connector.change_calls==1 and not moves(oid,'RELEASE')
    with pytest.raises(ValueError):fare.cancellation_quote(oid)
    with pytest.raises(ValueError):credit.conversion_quote(oid)
    with pytest.raises(ValueError):remedy.request(oid,'sup_mock','NO_ROOM',['simulation://fault'],'supplier')
    cap=moves(oid,'CAPTURE')[0]
    with pytest.raises(ValueError,match='CASH_FARE_FUNDS_RESERVED'):
        money.create(cap.root_payment_intent_id,{'movement_type':'REFUND','parent_movement_id':cap.money_movement_id,
            'amount_minor':1,'mode':'CONTRACT_SIMULATOR','evidence':['simulation://bypass']},'bypass-refund','test')

def test_definitive_change_rejection_releases_only_its_authorization(client):
    oid=booked_order(client);q=change_quote(oid,80000);connector.fail_change=True
    result=execute(oid,q)
    assert result['state']=='UNKNOWN_SUPPLIER'
    done=reconcile(oid,result)
    assert done['state']=='REJECTED' and len(moves(oid,'RELEASE'))==1
    with SessionLocal() as s:assert s.get(OrderRow,oid).status=='CONFIRMED' and not s.get(Claim,oid)
    assert connector.change_calls==1

def test_payment_decline_does_not_send_change_and_cannot_be_replayed_as_success(client):
    oid=booked_order(client);q=change_quote(oid,80000)
    result=execute(oid,q,'pm_decline')
    assert result['state']=='PAYMENT_DECLINED' and connector.change_calls==0
    assert len(moves(oid,'AUTHORIZATION'))==1  # Only original booking authorization.
    with pytest.raises(ValueError,match='REQUEST_CONFLICT'):execute(oid,q,'pm_success')

def test_capture_failure_keeps_confirmed_supplier_change_and_requires_payment_consent(client):
    oid=booked_order(client);q=change_quote(oid,80000)
    result=execute(oid,q,'pm_capture_fail')
    assert result['state']=='CAPTURE_PENDING' and result['payment_retry_allowed']
    assert reconcile(oid,result)['state']=='CAPTURE_PENDING'
    with pytest.raises(ValueError,match='CONSENT_REQUIRED'):
        execution.retry_payment(oid,result['operation_id'],q['quote_hash'],False,'pm_success')
    done=execution.retry_payment(oid,result['operation_id'],q['quote_hash'],True,'pm_success')
    assert done['state']=='COMPLETED' and connector.change_calls==1 and len(moves(oid,'CAPTURE'))==2

def test_capture_ledger_failure_resumes_without_reauthorizing_or_rechanging(client,monkeypatch):
    oid=booked_order(client);q=change_quote(oid,80000);original=money.create_in_session
    def fail(s,i,b,key,actor):
        if b['movement_type']=='CAPTURE':raise ValueError('SIMULATED_CAPTURE_LEDGER_FAILURE')
        return original(s,i,b,key,actor)
    with monkeypatch.context() as m:
        m.setattr(money,'create_in_session',fail)
        with pytest.raises(ValueError,match='CAPTURE_LEDGER'):execute(oid,q)
    result=fare.status(oid)
    assert result['state']=='CAPTURE_PENDING'
    assert reconcile(oid,result)['state']=='COMPLETED'
    assert connector.change_calls==1 and len(moves(oid,'AUTHORIZATION'))==2 and len(moves(oid,'CAPTURE'))==2

def test_authorization_ledger_failure_keeps_accepted_plan_and_resumes_once(client,monkeypatch):
    oid=booked_order(client);q=change_quote(oid,80000);original=money.create_in_session
    def fail(s,i,b,key,actor):
        if b['movement_type']=='AUTHORIZATION':raise ValueError('SIMULATED_AUTHORIZATION_LEDGER_FAILURE')
        return original(s,i,b,key,actor)
    with monkeypatch.context() as m:
        m.setattr(money,'create_in_session',fail)
        with pytest.raises(ValueError,match='AUTHORIZATION_LEDGER'):execute(oid,q)
    result=fare.status(oid)
    assert result['state']=='AUTH_PENDING' and connector.change_calls==0 and len(moves(oid,'AUTHORIZATION'))==1
    assert reconcile(oid,result)['state']=='COMPLETED'
    assert connector.change_calls==1 and len(moves(oid,'AUTHORIZATION'))==2

def test_query_confirmation_for_different_dates_cannot_complete_this_change(client,monkeypatch):
    oid=booked_order(client);q=change_quote(oid,80000);connector.ambiguous_change=True
    result=execute(oid,q)
    async def wrong(key):
        return {'status':'CONFIRMED','confirmation':'other-booking','check_in':day(99),'check_out':day(100),'original_confirmation':'other-original'}
    monkeypatch.setattr(connector,'lookup_change',wrong)
    assert reconcile(oid,result)['state']=='UNKNOWN_SUPPLIER'
    assert len(moves(oid,'CAPTURE'))==1 and not moves(oid,'RELEASE')

def test_four_competing_change_quotes_have_one_claim_and_one_additional_capture(client):
    oid=booked_order(client)
    quotes=[change_quote(oid,80000,n) for n in range(50,54)]
    def attempt(q):
        try:return execute(oid,q)
        except ValueError as e:return str(e)
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(attempt,quotes))
    assert sum(isinstance(x,dict) and x['state']=='COMPLETED' for x in results)==1
    assert connector.change_calls==1 and len(moves(oid,'CAPTURE'))==2

def test_expired_quote_and_changed_money_facts_never_dispatch(client,monkeypatch):
    oid=booked_order(client);q=change_quote(oid,80000)
    with monkeypatch.context() as m:
        m.setattr(execution,'now',lambda:datetime.fromisoformat(q['expires_at'])+timedelta(seconds=1))
        with pytest.raises(ValueError,match='QUOTE_EXPIRED'):execute(oid,q)
    cap=moves(oid,'CAPTURE')[0]
    money.create(cap.root_payment_intent_id,{'movement_type':'REFUND','parent_movement_id':cap.money_movement_id,
        'amount_minor':100,'mode':'CONTRACT_SIMULATOR','evidence':['simulation://prior']},'prior','test')
    with pytest.raises(ValueError,match='QUOTE_STALE'):execute(oid,q)
    assert connector.change_calls==0

def test_quote_tampering_and_wrong_action_do_not_claim_order(client):
    oid=booked_order(client);q=change_quote(oid,80000)
    with pytest.raises(ValueError,match='OWN_CASH_FARE_QUOTE_REQUIRED'):
        run(execution.start(oid,q['quote_id'],q['quote_hash'],True,None,action='CANCEL'))
    with SessionLocal.begin() as s:
        row=s.get(Quote,q['quote_id']);row.payload_json={**row.payload_json,'amount_due_minor':1}
    with pytest.raises(ValueError,match='INTEGRITY_REQUIRED'):execute(oid,q)
    with SessionLocal() as s:assert not s.get(Claim,oid)

def test_lost_inventory_is_rejected_and_reconciled_without_charging(client):
    oid=booked_order(client);q=change_quote(oid,80000);connector.inventory_available=False
    result=execute(oid,q)
    assert result['state']=='UNKNOWN_SUPPLIER'
    assert reconcile(oid,result)['state']=='REJECTED'
    assert len(moves(oid,'CAPTURE'))==1

def test_historical_rule_without_fee_refund_policy_is_not_retroactively_invented(client,monkeypatch):
    original=rules.demo_rules
    def old_rules():
        b=original();b.pop('cash_cancellation_value_basis');return b
    monkeypatch.setattr(rules,'demo_rules',old_rules)
    oid=booked_order(client)
    assert fare.cancellation_quote(oid)['refund_amount_minor']==1443200
    with pytest.raises(ValueError,match='HISTORICAL_CHANGE_FEE'):change_quote(oid,80000)

def test_zero_or_negative_repriced_room_is_not_offered(client):
    oid=booked_order(client)
    with pytest.raises(ValueError,match='POSITIVE_CHANGE_ROOM_VALUE_REQUIRED'):change_quote(oid,-1443200)

def test_new_change_after_partial_refund_requires_room_value_allocation(client):
    oid=booked_order(client);fare.cancellation_quote(oid);cap=moves(oid,'CAPTURE')[0]
    money.create(cap.root_payment_intent_id,{'movement_type':'REFUND','parent_movement_id':cap.money_movement_id,
        'amount_minor':10000,'mode':'CONTRACT_SIMULATOR','evidence':['simulation://prior']},'prior-partial','test')
    with pytest.raises(ValueError,match='REFUNDED_ROOM_VALUE_RECONCILIATION_REQUIRED'):change_quote(oid,80000)

def test_lower_change_cancellation_cannot_refund_or_spend_the_forfeited_difference(client):
    oid=booked_order(client);execute(oid,change_quote(oid,-43200))
    q=fare.cancellation_quote(oid)
    assert q['forfeited_change_value_minor']==43200 and q['refund_amount_minor']==1410000
    result=execute(oid,q)
    assert result['state']=='COMPLETED'
    assert sum(x.amount_minor for x in moves(oid,'REFUND'))==1410000
    cap=moves(oid,'CAPTURE')[0]
    with pytest.raises(ValueError,match='CASH_FARE_FUNDS_RESERVED'):
        money.create(cap.root_payment_intent_id,{'movement_type':'REFUND','parent_movement_id':cap.money_movement_id,
            'amount_minor':1,'mode':'CONTRACT_SIMULATOR','evidence':['simulation://revive-forfeit']},'forfeit-bypass','test')

def test_rejected_quote_can_be_replaced_by_new_customer_quote(client):
    oid=booked_order(client);q=change_quote(oid,80000);connector.fail_change=True
    assert reconcile(oid,execute(oid,q))['state']=='REJECTED'
    connector.fail_change=False
    assert execute(oid,change_quote(oid,100000,70))['state']=='COMPLETED'
    assert fare.cancellation_quote(oid)['paid_change_fees_minor']==10000
