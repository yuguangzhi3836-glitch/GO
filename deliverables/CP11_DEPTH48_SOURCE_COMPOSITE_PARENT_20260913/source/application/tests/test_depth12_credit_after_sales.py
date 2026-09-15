from datetime import datetime,timezone,timedelta
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import FareRuleRow,CatalogCreditContractRow,StayCreditRow,OrderRow
from go_hotel.services import catalog_stay_credit as credit,catalog_credit_after_sales as after,catalog_credit_value as value
from go_hotel.services.unified_money_movement import unified_money_movement_service as money
from go_hotel.connectors.mock_hotel import connector
from test_depth12_catalog_credit import convert,redeem,run,dates,net
from test_sprint1m_fare_runtime import booked_order


def cancel(oid):
    q=after.cancellation_quote(oid)
    return q,run(after.cancel(oid,q['quote_id'],q['quote_hash'],True,'owner'))


def test_customer_cancel_refunds_only_supplement_and_restores_credit_without_extending(client):
    original,cid,_=convert(client);q,r=redeem(cid,156_800);expiry=credit.get_credit(cid)['expires_at']
    cq,cancelled=cancel(r['order_id'])
    assert cancelled['status']=='CANCELLED' and cancelled['cash_refund_minor']==156_800 and cancelled['restored_credit_minor']==1_443_200
    assert not [m for m in net(original) if m.movement_type=='REFUND']
    assert [m.amount_minor for m in net(r['order_id']) if m.movement_type=='REFUND']==[156_800]
    assert credit.get_credit(cid)['available_minor']==1_443_200 and credit.get_credit(cid)['expires_at']==expiry
    count=connector.cancel_calls
    assert run(after.cancel(r['order_id'],cq['quote_id'],cq['quote_hash'],True,'owner'))['status']=='CANCELLED' and connector.cancel_calls==count
    _,again=redeem(cid,0,days=120);assert again['status']=='REDEEMED'
    with SessionLocal() as s:value.checked(s,cid)


def test_lower_price_forfeiture_is_preserved_after_customer_cancellation(client):
    _,cid,_=convert(client);_,r=redeem(cid,-43_200)
    _,cancelled=cancel(r['order_id'])
    assert cancelled['restored_credit_minor']==1_400_000 and cancelled['cash_refund_minor']==0
    assert credit.get_credit(cid)['available_minor']==1_400_000
    q,again=redeem(cid,0,days=120)
    assert q['amount_due_minor']==43_200 and again['applied_minor']==1_400_000
    with SessionLocal() as s:value.checked(s,cid)


def test_customer_cancellation_uses_accepted_tiers_even_if_supplier_rule_changes(client):
    _,cid,_=convert(client);ci,co=dates(3);connector.date_price_delta[ci]=156_800
    q=run(credit.redemption_quote(cid,ci,co));r=run(credit.redeem(cid,q['quote_id'],q['quote_hash'],True,'pm_success','owner'))
    from catalog_fare_helpers import publish_for_order
    publish_for_order(credit.get_credit(cid)['original_order_id'],cancellation_tiers=[{'min_hours':0,'fee_basis_points':10000}])
    cq,cancelled=cancel(r['order_id'])
    assert cq['fee_percent'] in {20,50} and cq['fee_minor']<1_600_000
    assert cancelled['restored_credit_minor']==1_443_200-cq['fee_minor'] and cancelled['cash_refund_minor']==156_800
    with SessionLocal() as s:value.checked(s,cid)


def test_cash_refund_failure_keeps_credit_unavailable_until_atomic_retry(client,monkeypatch):
    _,cid,_=convert(client);_,r=redeem(cid,156_800);cq=after.cancellation_quote(r['order_id']);original=money._post
    def fail(s,i,m):
        if m.movement_type=='REFUND':raise RuntimeError('refund ledger failed')
        return original(s,i,m)
    monkeypatch.setattr(money,'_post',fail)
    with pytest.raises(RuntimeError,match='refund ledger'):run(after.cancel(r['order_id'],cq['quote_id'],cq['quote_hash'],True,'owner'))
    assert credit.get_credit(cid)['available_minor']==0 and not [m for m in net(r['order_id']) if m.movement_type=='REFUND']
    count=connector.cancel_calls;monkeypatch.setattr(money,'_post',original)
    assert run(after.reconcile(r['order_id'],'owner'))['available_credit_minor']==1_443_200 and connector.cancel_calls==count


def test_customer_cancel_unknown_response_queries_before_restoring(client,monkeypatch):
    _,cid,_=convert(client);_,r=redeem(cid);cq=after.cancellation_quote(r['order_id']);original=connector.cancel
    async def lost(confirmation):await original(confirmation);raise TimeoutError('lost cancel')
    monkeypatch.setattr(connector,'cancel',lost)
    unknown=run(after.cancel(r['order_id'],cq['quote_id'],cq['quote_hash'],True,'owner'))
    assert unknown['state']=='UNKNOWN_CANCEL' and unknown['available_credit_minor']==0
    before=connector.cancel_calls
    assert run(after.reconcile(r['order_id'],'owner'))['available_credit_minor']==1_443_200 and connector.cancel_calls==before


def test_restored_credit_after_expiry_does_not_gain_a_new_year(client,monkeypatch):
    from go_hotel.services import catalog_fare_snapshot as fare
    original_rules=fare.demo_rules
    monkeypatch.setattr(fare,'demo_rules',lambda:{**original_rules(),'stay_credit_days':1})
    oid=booked_order(client)
    q=credit.conversion_quote(oid);c=run(credit.convert(oid,q['quote_id'],q['quote_hash'],True,'owner'));cid=c['stay_credit_id']
    rq=run(credit.redemption_quote(cid,*dates(1)));r=run(credit.redeem(cid,rq['quote_id'],rq['quote_hash'],True,'pm_success','owner'))
    cq=after.cancellation_quote(r['order_id']);expiry=datetime.fromisoformat(c['expires_at'])
    # Cancellation was sent before expiry; a later recovery must keep the original cutoff.
    original=connector.cancel
    async def lost(confirmation):await original(confirmation);raise TimeoutError('late result')
    monkeypatch.setattr(connector,'cancel',lost)
    assert run(after.cancel(r['order_id'],cq['quote_id'],cq['quote_hash'],True,'owner'))['state']=='UNKNOWN_CANCEL'
    monkeypatch.setattr(value,'now',lambda:expiry+timedelta(seconds=1));monkeypatch.setattr(after,'now',lambda:expiry+timedelta(seconds=1))
    final=run(after.reconcile(r['order_id'],'owner'))
    assert final['available_credit_minor']==0 and credit.get_credit(cid)['status']=='EXPIRED'
    with SessionLocal() as s:value.checked(s,cid)
