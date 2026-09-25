"""Legacy rides without accepted server policy cannot start new money actions."""
from datetime import datetime, timezone
import pytest
from sqlalchemy import func, select
from go_hotel.db.models import (MobilityRideOrderRow as Order, OmnichannelPaymentIntentRow as Intent,
    OmnichannelMoneyMovementRow as Movement)
from go_hotel.db.session import SessionLocal
from go_hotel.services.omnichannel_payment import omnichannel_payment_service as payment
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge as bridge


@pytest.fixture
def legacy():
    t = datetime.now(timezone.utc)
    with SessionLocal.begin() as session:
        session.add(Order(order_id='legacy-ride', account_id='owner', status='PAYMENT_PENDING',
            pickup='A', dropoff='B', pickup_at='2026-10-01T10:00:00', vehicle_class='COMFORT',
            total_amount_minor=50000, currency='CNY', passengers=[], created_at=t, updated_at=t))
    return 'legacy-ride'


def test_consumer_payment_resolver_refuses_missing_booking_acceptance(legacy):
    with pytest.raises(ValueError, match='BOOKING_POLICY_REQUIRED'):
        payment.create_consumer_intent({'business_type': 'RIDE_ORDER', 'business_id': legacy,
            'channel_priority': ['LOCAL_MARKET']}, 'new-payment', 'owner')
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Intent)) == 0


def test_existing_intent_does_not_bypass_accepted_policy_guard(legacy, monkeypatch):
    t = datetime.now(timezone.utc)
    with SessionLocal.begin() as session:
        session.add(Intent(payment_intent_id='old-intent', business_type='RIDE_ORDER', business_id=legacy,
            payer_id='owner', payee_id='old-supplier', operation='PAY', amount_minor=50000, currency='CNY',
            channel_priority_json=['LOCAL_MARKET'], selected_channel='LOCAL_MARKET', state='READY',
            idempotency_key='old-key', automatic_fallback_allowed=False, created_at=t, updated_at=t))
    def forbidden(*args, **kwargs):
        pytest.fail('legacy intent dispatched money without accepted cancellation policy')
    monkeypatch.setattr(payment, 'execute', forbidden)
    with pytest.raises(ValueError, match='BOOKING_POLICY_REQUIRED'):
        bridge.checkout_contract('RIDE', legacy, 'owner', 'old-supplier', 'isolated://old')
    with SessionLocal() as session:
        assert session.get(Intent, 'old-intent').state == 'READY'
        assert session.get(Order, legacy).status == 'PAYMENT_PENDING'
        assert session.scalar(select(func.count()).select_from(Movement)) == 0


def test_no_refund_due_cancelled_ride_rejects_late_supplier_confirmation():
    from tests.test_c05_cancellation_policy import confirm, BODY
    from ride_cancellation_fixture import synthetic_policy, accepted_body
    from go_hotel.mobility.ride.service import ride_service
    from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service
    from go_hotel.db.models import OrderSupplierFulfillmentRow as Fulfillment
    with synthetic_policy(before=16800, after=16800):
        oid = confirm(ride_service.create('owner', accepted_body(ride_service, BODY)))
    quote = ride_service.refund_quote('owner', oid)
    ride_service.cancel('owner', oid, quote['quote_hash'])
    with SessionLocal() as session:
        row = session.scalar(select(Fulfillment).where(Fulfillment.business_id == oid))
        fid, reference = row.order_supplier_fulfillment_id, row.supplier_confirmation_reference
    with pytest.raises(ValueError, match='TERMINAL_ORDER_SUPPLIER_FACT_REJECTED'):
        order_supplier_fulfillment_service.record_supplier_fact(fid, {'state': 'SUPPLIER_CONFIRMED',
            'supplier_confirmation_reference': reference, 'evidence_reference': 'isolated://late-confirmation'})
    assert ride_service.get('owner', oid)['status'] == 'CANCELLED'
