"""A local claim receipt must not outrank the provider's actual event clock."""
from datetime import datetime, timezone

import pytest

from go_hotel.services import consumer_unified_lifecycle as module

svc = module.consumer_unified_lifecycle_service
CLAIM = {'provider': 'CTRIP', 'external_order_id': 'claim-clock-1', 'vertical': 'HOTEL'}


@pytest.fixture
def pending(monkeypatch):
    monkeypatch.setattr(module, 'now', lambda: datetime(2026, 9, 19, 12, tzinfo=timezone.utc))
    return svc.import_external_order('claim-clock-user', CLAIM)


def provider_event(event='confirmed', at='2026-09-18T10:00:00Z', account='claim-clock-user', **changes):
    payload = CLAIM | {
        'title': 'Provider hotel', 'source_event_id': event,
        'source_updated_at': at, 'evidence_reference': f'provider-event://{event}',
        'lifecycle_state': 'CONFIRMED', 'payment_state': 'PAID',
        'refund_state': 'NOT_REQUESTED', 'facts': {'amount_minor': 88000, 'currency': 'CNY'},
    } | changes
    return svc.import_external_order(account, payload, trusted_provider=True, adapter_id='ctrip-orders-v1')


@pytest.mark.parametrize('source_time', ['2026-09-18T10:00:00Z', '2026-09-19T12:00:00Z'])
def test_first_provider_fact_promotes_pending_claim_even_if_not_newer(pending, source_time):
    result = provider_event(at=source_time)
    assert result['consumer_unified_lifecycle_id'] == pending['consumer_unified_lifecycle_id']
    assert result['stale_ignored'] is False
    assert result['lifecycle_state'] == 'CONFIRMED'
    assert result['payment_state'] == 'PAID'
    assert result['facts_json']['source_verification'] == 'OFFICIAL_PROVIDER'
    assert datetime.fromisoformat(result['source_updated_at']).replace(tzinfo=timezone.utc) == datetime.fromisoformat(source_time.replace('Z', '+00:00'))
    assert len(svc.detail('claim-clock-user', result['consumer_unified_lifecycle_id'])['events']) == 2


def test_promoted_order_uses_provider_clock_for_following_events(pending):
    provider_event()
    cancelled = provider_event('cancelled', '2026-09-18T11:00:00Z', lifecycle_state='CANCELLED', refund_state='REFUND_PROCESSING')
    assert cancelled['stale_ignored'] is False
    assert cancelled['payment_state'] == 'PAID'
    assert cancelled['refund_state'] == 'REFUND_PROCESSING'
    old = provider_event('late-old', '2026-09-18T10:30:00Z')
    replay = provider_event('cancelled', '2026-09-18T11:00:00Z', lifecycle_state='CANCELLED', refund_state='REFUND_PROCESSING')
    assert old['stale_ignored'] is replay['stale_ignored'] is True
    assert old['lifecycle_state'] == 'CANCELLED'
    assert len(svc.detail('claim-clock-user', pending['consumer_unified_lifecycle_id'])['events']) == 3


def test_manual_reimport_cannot_downgrade_promoted_money_or_status(pending):
    confirmed = provider_event()
    again = svc.import_external_order('claim-clock-user', CLAIM | {'facts': {'amount_minor': 1}})
    assert again['stale_ignored'] is True
    assert again['facts_json'] == confirmed['facts_json']
    assert again['payment_state'] == 'PAID'
    assert again['lifecycle_state'] == 'CONFIRMED'


def test_generic_projection_cannot_opt_into_provider_upgrade_using_payload(pending):
    result = svc.project({
        'account_id': 'claim-clock-user', 'order_id': pending['order_id'], 'vertical': 'HOTEL',
        'title': 'Forged', 'lifecycle_state': 'CONFIRMED', 'payment_state': 'PAID',
        'refund_state': 'NOT_REQUESTED', 'evidence_reference': 'forged://event',
        'source_updated_at': '2026-09-18T10:00:00Z', 'allow_external_verification_upgrade': True,
        'facts': {'source_verification': 'OFFICIAL_PROVIDER', 'transaction_platform': 'CTRIP',
                  'source_adapter_id': 'ctrip-orders-v1'},
    })
    assert result['stale_ignored'] is True
    assert result['lifecycle_state'] == 'MANUAL_REVIEW'
    assert len(svc.detail('claim-clock-user', pending['consumer_unified_lifecycle_id'])['events']) == 1


def test_provider_fact_for_other_consumer_does_not_promote_claim(pending):
    other = provider_event(account='another-consumer')
    assert other['consumer_unified_lifecycle_id'] != pending['consumer_unified_lifecycle_id']
    unchanged = svc.detail('claim-clock-user', pending['consumer_unified_lifecycle_id'])
    assert unchanged['item']['lifecycle_state'] == 'MANUAL_REVIEW'
    assert len(unchanged['events']) == 1


def test_wrong_adapter_cannot_promote_claim(pending):
    with pytest.raises(ValueError, match='TRUSTED_OTA_ADAPTER_REQUIRED'):
        svc.import_external_order('claim-clock-user', CLAIM, trusted_provider=True, adapter_id='booking-orders-v1')
    assert svc.detail('claim-clock-user', pending['consumer_unified_lifecycle_id'])['item']['lifecycle_state'] == 'MANUAL_REVIEW'
