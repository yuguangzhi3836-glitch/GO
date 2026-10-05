import asyncio
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db import models as m
from go_hotel.services import transaction_order_view as view


def booked(vertical, client):
    if vertical == 'HOTEL':
        from test_sprint1m_fare_runtime import booked_order
        from go_hotel.services import catalog_cash_fare as fare, catalog_cash_fare_execution as execution
        oid = booked_order(client)
        q = fare.cancellation_quote(oid)
        refund = lambda: asyncio.run(execution.start(oid,q['quote_id'],q['quote_hash'],True,None,'pm_success'))
    elif vertical == 'FLIGHT':
        from test_depth32_flight_refund_consent import booked as flight_booked
        from go_hotel.flight.service import flight_service as svc
        _, oid = flight_booked()
        q = svc.refund_quote('flight-consent-owner', oid)
        refund = lambda: svc.refund('flight-consent-owner',oid,q['quote_hash'])
    else:
        if vertical in {'RAIL','ATTRACTION'}:
            from test_depth21_refund_recovery import booked as vertical_booked
        else:
            from test_depth33_mobility_refund_consent import booked as vertical_booked
        svc, owner, oid = vertical_booked(vertical)
        q = svc.refund_quote(owner, oid)
        fn = svc.cancel if vertical in {'RIDE','RENTAL'} else svc.refund
        refund = lambda: fn(owner,oid,q['quote_hash'])
    with SessionLocal() as s:
        order = s.get(view.ORDERS[vertical], oid)
        fact = s.scalar(select(m.PaymentOrderFactBindingRow).where(
            m.PaymentOrderFactBindingRow.business_type == vertical + '_ORDER',
            m.PaymentOrderFactBindingRow.business_id == oid))
        return oid, order.account_id, fact.payee_id, q, refund


@pytest.mark.parametrize('vertical',list(view.ORDERS))
def test_same_order_three_scopes_final_ledger_and_refund_replay(client,vertical):
    oid, owner, supplier, quote, refund = booked(vertical,client)
    before = view.snapshot(vertical,oid,supplier_id=supplier)
    assert before['original_payment']['capture_count'] == 1
    assert before['original_payment']['refunded_minor'] == 0
    assert oid in [x['order_id'] for x in view.supplier_orders(supplier)['items']]
    assert oid not in [x['order_id'] for x in view.supplier_orders('unrelated-supplier')['items']]
    refund()
    final = view.snapshot(vertical,oid,supplier_id=supplier)
    assert final == view.snapshot(vertical,oid,account_id=owner)
    assert final == view.snapshot(vertical,oid,admin=True)
    money = final['original_payment']
    assert money['binding_state'] == 'BOUND'
    assert money['ledger_balanced'] and money['ledger_entries'] > 0
    assert money['capture_count'] == money['refund_count'] == 1
    assert money['refunded_minor'] == quote['refund_amount_minor']
    assert sum(x['amount_minor'] for x in final['refunds']) == money['refunded_minor']
    assert money['net_minor'] == money['captured_minor'] - money['refunded_minor']
    order_counts, refund_counts = view.supplier_counts(supplier)
    assert sum(order_counts.values()) == sum(refund_counts.values()) == 1
    assert view.supplier_refunds(supplier)['items'][0]['amount_minor'] == quote['refund_amount_minor']
    assert view.supplier_refunds('unrelated-supplier')['items'] == []
    refund()
    assert view.snapshot(vertical,oid,supplier_id=supplier) == final
    for scope in ({'supplier_id':'unrelated-supplier'}, {'account_id':'unrelated-consumer'}, {}):
        with pytest.raises(ValueError,match='ORDER_NOT_FOUND'):
            view.snapshot(vertical,oid,**scope)


@pytest.mark.parametrize('field,value',[('payee_id','other'),('payer_id','other'),('currency','USD')])
def test_frozen_binding_mismatch_removes_supplier_visibility(client,field,value):
    oid, owner, supplier, _, _ = booked('FLIGHT',client)
    with SessionLocal.begin() as s:
        fact=s.scalar(select(m.PaymentOrderFactBindingRow).where(m.PaymentOrderFactBindingRow.business_id==oid))
        setattr(fact,field,value)
    with pytest.raises(ValueError,match='ORDER_NOT_FOUND'):
        view.snapshot('FLIGHT',oid,supplier_id=supplier)
    assert view.supplier_orders(supplier)['items']==[]
    assert view.snapshot('FLIGHT',oid,account_id=owner)['original_payment']['binding_state']=='RECONCILIATION_REQUIRED'


def test_paginated_order_view_stays_tenant_scoped(client):
    a=booked('HOTEL',client)
    b=booked('FLIGHT',client)
    assert len(view.supplier_orders(a[2],1,0)['items'])==1
    assert view.supplier_orders(a[2],1,1)['items']==[]
    assert view.supplier_orders(None)['items']==[]
    assert view.supplier_orders(b[2])['items'][0]['order_id']==b[0]


def test_transaction_endpoints_require_authenticated_matching_role(client):
    oid, owner, supplier, _, _ = booked('FLIGHT',client)
    from go_hotel.security.service import identity_service
    username='transaction-view-supplier@example.test'
    password='Isolated-fixture-password-41'
    from tests.supplier_fixture import admit_trading_supplier
    fixture_owner = identity_service.ensure_user(username,password,'SUPPLIER_USER',supplier,['SUPPLIER_OWNER'])
    admit_trading_supplier(supplier, fixture_owner)
    base=f'/v1/supplier/transaction-orders/FLIGHT/{oid}'
    assert client.get(base).status_code==401
    assert client.post('/bff/auth/login',json={'username':username,'password':password,'expected_actor_type':'SUPPLIER_USER'}).status_code==200
    assert client.get(base).status_code==200
    assert client.get(f'/internal/v1/admin/transaction-orders/FLIGHT/{oid}').status_code==403
    assert client.get(f'/v1/consumer/transaction-orders/FLIGHT/{oid}').status_code in {401,403}
    assert client.get(f'/v1/supplier/transaction-orders/HOTEL/{oid}').status_code==404


def test_admin_hotel_refund_amount_is_real_column(client):
    oid,_,_,q,refund=booked('HOTEL',client);refund()
    from go_hotel.api.routes.operations_console import vertical_snapshot
    rows=vertical_snapshot('HOTEL',p=None)['data']['refunds']
    assert next(x for x in rows if x['order_id']==oid)['refund_amount_minor']==q['refund_amount_minor']
