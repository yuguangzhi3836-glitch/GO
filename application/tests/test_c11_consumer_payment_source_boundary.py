import pytest
from sqlalchemy import func, select

from go_hotel.db.models import OmnichannelPaymentIntentRow as Intent
from go_hotel.db.session import SessionLocal
from go_hotel.security.service import identity_service
from tests.test_sprint3b_rail import auth


@pytest.mark.parametrize('business_type', ['RENTAL_DEPOSIT', 'RENTAL_CHANGE', 'SUBSCRIPTION_INVOICE', 'ARBITRARY'])
def test_consumer_cannot_create_unbound_money_obligation(client, business_type):
    headers = auth(client)
    body = dict(business_type=business_type, business_id='invented', payee_id='attacker',
                operation='AUTHORIZE', amount_minor=99999, currency='USD',
                channel_priority=['LOCAL_MARKET'])
    response = client.post('/v1/payments/intents', headers=headers | {'Idempotency-Key': 'invented'}, json=body)
    assert response.status_code == 409
    assert response.json()['detail'] == 'CONSUMER_PAYMENT_SOURCE_FACT_REQUIRED'
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Intent)) == 0


@pytest.mark.parametrize('user,password', [('go_admin', 'change-me-admin'), ('supplier_owner', 'change-me-supplier')])
def test_non_consumer_cannot_use_consumer_creation_route(client, user, password):
    token = identity_service.login(user, password)['access_token']
    response = client.post('/v1/payments/intents', headers={'Authorization': 'Bearer ' + token,
        'Idempotency-Key': 'role-confusion'}, json={'business_type': 'RENTAL_DEPOSIT'})
    assert response.status_code == 403


def test_internal_subscription_creation_remains_available():
    from go_hotel.services.omnichannel_payment import omnichannel_payment_service as svc
    result = svc.create_intent(dict(business_type='SUBSCRIPTION_INVOICE', business_id='invoice',
        payee_id='GO', operation='PAY', amount_minor=100, currency='CNY',
        channel_priority=['LOCAL_MARKET']), 'internal-invoice', 'supplier')
    assert result['business_type'] == 'SUBSCRIPTION_INVOICE'


def test_supported_order_resolves_amount_currency_and_payee_from_source(client):
    from tests.test_depth20_api_fulfillment import rail_order
    from go_hotel.db.models import PaymentOrderFactBindingRow as Binding
    headers, order, _ = rail_order(client)
    from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service
    vertical_source_runtime_service.decide('RAIL', order['order_id'], [{
        'source_id': 'verified-rail', 'source_type': 'RAIL_OPERATOR_OFFICIAL',
        'authorized': True, 'available': True, 'evidence_reference': 'isolated://rail-source'}])
    response = client.post('/v1/payments/intents', headers=headers | {'Idempotency-Key': 'source-bound'},
        json={'business_type': 'RAIL_ORDER', 'business_id': order['order_id'],
              'channel_priority': ['LOCAL_MARKET'], 'amount_minor': 1, 'currency': 'USD',
              'operation': 'REFUND', 'payee_id': 'attacker', 'source_decision_id': 'forged'})
    assert response.status_code == 200, response.text
    intent = response.json()['data']
    assert intent['amount_minor'] == order['total_amount_minor']
    assert intent['currency'] == order['currency']
    assert intent['operation'] == 'PAY' and intent['payee_id'] != 'attacker'
    with SessionLocal() as session:
        binding = session.scalar(select(Binding).where(Binding.payment_intent_id == intent['payment_intent_id']))
        assert binding.source_decision_id != 'forged'
        assert binding.amount_minor == intent['amount_minor']


def test_foreign_order_cannot_be_claimed_by_supplied_payer(client):
    from tests.test_depth20_api_fulfillment import rail_order
    _, order, _ = rail_order(client)
    headers = auth(client, email='other-owner@example.com')
    response = client.post('/v1/payments/intents', headers=headers | {'Idempotency-Key': 'foreign'},
        json={'business_type': 'RAIL_ORDER', 'business_id': order['order_id'],
              'channel_priority': ['LOCAL_MARKET'], 'payer_id': order['account_id']})
    assert response.status_code == 409
    assert response.json()['detail'] == 'PAYMENT_PAYER_ORDER_MISMATCH'
