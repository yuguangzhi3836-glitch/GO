"""External trip money stays validated and separate from cancellation."""
from uuid import uuid4

import pytest

from go_hotel.services.consumer_unified_lifecycle import consumer_unified_lifecycle_service as svc


def event(account, event_id, at, **overrides):
    body = {
        'provider': 'CTRIP', 'external_order_id': 'cancel-refund-1',
        'vertical': 'HOTEL', 'title': 'Hotel',
        'source_event_id': event_id, 'source_updated_at': at,
        'evidence_reference': f'provider-event://{event_id}',
        'lifecycle_state': 'CANCELLED', 'payment_state': 'PAID',
        'refund_state': 'REFUND_PROCESSING',
        'facts': {'amount_minor': 169900, 'currency': 'CNY'},
    }
    body.update(overrides)
    return svc.import_external_order(account, body, trusted_provider=True, adapter_id='ctrip-orders-v1')


@pytest.mark.parametrize('amount', [-1, True, False, 1.5, '169900', None, {'minor': 169900}, [169900]])
@pytest.mark.parametrize('trusted', [False, True])
def test_invalid_external_amount_never_creates_trip(amount, trusted):
    account = f'invalid-money-{uuid4().hex}'
    with pytest.raises(ValueError, match='EXTERNAL_ORDER_AMOUNT_INVALID'):
        if trusted:
            event(account, 'invalid', '2026-09-18T10:00:00Z', facts={'amount_minor': amount})
        else:
            svc.import_external_order(account, {'provider': 'CTRIP', 'external_order_id': 'invalid',
                'vertical': 'HOTEL', 'facts': {'amount_minor': amount}})
    assert svc.list(account) == []


@pytest.mark.parametrize('facts', [{}, {'amount_minor': 0}, {'amount_minor': 169900, 'currency': 'CNY'}])
def test_absent_or_nonnegative_integer_amount_is_preserved(facts):
    account = f'valid-money-{uuid4().hex}'
    row = event(account, 'valid', '2026-09-18T10:00:00Z', facts=facts)
    for key, value in facts.items():
        assert row['facts_json'][key] == value
    assert ('amount_minor' in row['facts_json']) == ('amount_minor' in facts)


def test_invalid_new_money_event_preserves_prior_projection_and_event_count():
    account = f'preserve-money-{uuid4().hex}'
    initial = event(account, 'initial', '2026-09-18T10:00:00Z')
    before = svc.detail(account, initial['consumer_unified_lifecycle_id'])
    with pytest.raises(ValueError, match='EXTERNAL_ORDER_AMOUNT_INVALID'):
        event(account, 'invalid-next', '2026-09-18T11:00:00Z',
              payment_state='REFUNDED', refund_state='REFUND_COMPLETED', facts={'amount_minor': -169900})
    assert svc.detail(account, initial['consumer_unified_lifecycle_id']) == before


def test_cancelled_trip_retains_pending_refund_until_provider_completion():
    account = f'cancel-money-{uuid4().hex}'
    cancelled = event(account, 'cancelled', '2026-09-18T10:00:00Z')
    assert cancelled['lifecycle_state'] == 'CANCELLED'
    assert cancelled['payment_state'] == 'PAID'
    assert cancelled['refund_state'] == 'REFUND_PROCESSING'
    detail = svc.detail(account, cancelled['consumer_unified_lifecycle_id'])
    assert detail['item']['refund_state'] == 'REFUND_PROCESSING'
    completed = event(account, 'refund-done', '2026-09-18T11:00:00Z',
                      payment_state='REFUNDED', refund_state='REFUND_COMPLETED')
    assert completed['lifecycle_state'] == 'CANCELLED'
    assert completed['refund_state'] == 'REFUND_COMPLETED'
    replay = event(account, 'refund-done', '2026-09-18T11:00:00Z',
                   payment_state='REFUNDED', refund_state='REFUND_COMPLETED')
    old = event(account, 'delayed-processing', '2026-09-18T10:30:00Z')
    assert replay['stale_ignored'] is old['stale_ignored'] is True
    assert old['refund_state'] == 'REFUND_COMPLETED'
    assert len(svc.detail(account, completed['consumer_unified_lifecycle_id'])['events']) == 2
