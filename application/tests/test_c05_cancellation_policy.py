from copy import deepcopy
from datetime import datetime, UTC
from unittest.mock import patch
import pytest
from sqlalchemy import select, func

from go_hotel.db.session import SessionLocal
from go_hotel.db.models import MobilityRideOrderRow, JourneyRecoveryEvidenceChainRow as Evidence, MobilityRefundRow
from go_hotel.mobility.ride.service import ride_service as svc
from go_hotel.mobility.ride import cancellation_policy as policies
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge
from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as supplier
from ride_cancellation_fixture import envelope, synthetic_policy, accepted_body


BODY = {'offer_id': 'ride_standard', 'pickup': 'PVG', 'dropoff': 'Bund',
        'pickup_at': '2030-01-01T12:00:00Z', 'currency': 'CNY', 'passengers': [{'full_name': 'TEST'}]}


def confirm(order):
    oid = order['order_id']
    tx = vertical_transaction_bridge.checkout_contract('RIDE', oid, 'owner', 'isolated', 'isolated://policy-test')
    supplier.record_supplier_fact(tx['supplier_fulfillment_id'], {'state': 'SUPPLIER_CONFIRMED',
        'external_operation_id': 'confirm-' + oid, 'supplier_confirmation_reference': 'S-' + oid,
        'evidence_reference': 'isolated://confirmed'})
    return oid


def test_default_missing_source_never_publishes_tariff_or_creates_payable_order():
    quoted = svc.search('PVG', 'Bund', BODY['pickup_at'])
    assert all(x['cancellation']['state'] == 'POLICY_UNAVAILABLE' for x in quoted)
    assert all('late_fee_minor' not in x['cancellation'] for x in quoted)
    with pytest.raises(ValueError, match='POLICY_UNAVAILABLE'):
        svc.create('owner', BODY)
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(MobilityRideOrderRow)) == 0
        assert s.scalar(select(func.count()).select_from(Evidence)) == 0


@pytest.mark.parametrize('accept', [None, '', '0' * 64])
def test_policy_requires_exact_explicit_booking_acceptance(accept):
    with synthetic_policy(before=123, after=456):
        with pytest.raises(ValueError, match='ACCEPTANCE_REQUIRED'):
            svc.create('owner', BODY | {'cancellation_policy_hash': accept})


def test_changed_policy_requires_requote_before_booking():
    with synthetic_policy(version='v1'):
        body = accepted_body(svc, BODY)
    with synthetic_policy(version='v2'):
        with pytest.raises(ValueError, match='ACCEPTANCE_REQUIRED'):
            svc.create('owner', body)


@pytest.mark.parametrize('changed', [{'pickup': 'OTHER'}, {'pickup_at': '2030-01-02T12:00:00Z'}, {'offer_id': 'ride_premium'}])
def test_acceptance_binds_selected_offer_amount_and_journey(changed):
    with synthetic_policy():
        body = accepted_body(svc, BODY)
        with pytest.raises(ValueError, match='ACCEPTANCE_REQUIRED'):
            svc.create('owner', body | changed)


@pytest.mark.parametrize('delta,expected', [(-1, 123), (0, 456), (1, 456)])
def test_search_booking_and_refund_use_frozen_policy_at_cutoff(delta, expected):
    with synthetic_policy(before=123, after=456):
        body = accepted_body(svc, BODY)
        order = svc.create('owner', body)
    oid = confirm(order)
    cutoff = int(datetime(2030, 1, 1, 11, tzinfo=UTC).timestamp() * 1000)
    # Source has disappeared. The accepted booking policy still governs.
    with patch.object(policies, 'db_now_ms', return_value=cutoff + delta):
        q = svc.refund_quote('owner', oid)
    assert q['fee_minor'] == expected
    assert q['cancellation_policy_hash'] == body['cancellation_policy_hash']
    assert q['cancellation_policy_version'] == 'synthetic-test-v1'
    with patch.object(policies, 'db_now_ms', return_value=cutoff + delta):
        result = svc.cancel('owner', oid, q['quote_hash'])
    assert result['refund_amount_minor'] == 16800 - expected
    assert svc.cancel('owner', oid, q['quote_hash']) == result


def test_refund_crossing_cutoff_requires_new_explicit_consent():
    with synthetic_policy(before=123, after=456):
        oid = confirm(svc.create('owner', accepted_body(svc, BODY)))
    cutoff = int(datetime(2030, 1, 1, 11, tzinfo=UTC).timestamp() * 1000)
    with patch.object(policies, 'db_now_ms', return_value=cutoff - 1):
        q = svc.refund_quote('owner', oid)
    with patch.object(policies, 'db_now_ms', return_value=cutoff):
        with pytest.raises(ValueError, match='RECONFIRM'):
            svc.cancel('owner', oid, q['quote_hash'])
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(MobilityRefundRow)) == 0


def test_missing_booking_snapshot_holds_legacy_order_and_refund_without_rewriting():
    with synthetic_policy():
        oid = confirm(svc.create('owner', accepted_body(svc, BODY)))
    # Represent a historical order that never had a cancellation acceptance.
    with SessionLocal.begin() as s:
        for row in s.scalars(select(Evidence).where(Evidence.execution_id == 'rc20:RIDE:' + oid)):
            s.delete(row)
    assert svc.get('owner', oid)['cancellation']['state'] == 'POLICY_UNAVAILABLE'
    with pytest.raises(ValueError, match='BOOKING_POLICY_REQUIRED'):
        svc.refund_quote('owner', oid)
    with pytest.raises(ValueError, match='BOOKING_POLICY_REQUIRED'):
        svc.cancel('owner', oid)
    assert svc.get('owner', oid)['status'] == 'CONFIRMED'


def test_source_hash_mismatch_is_rejected():
    source = envelope(); source['raw_sha256'] = '0' * 64
    with patch.object(policies, 'resolve_policy', return_value=source):
        with pytest.raises(ValueError, match='SOURCE_INVALID'):
            svc.search('PVG', 'Bund', BODY['pickup_at'])


def test_booking_snapshot_tamper_is_not_a_new_tariff():
    with synthetic_policy():
        oid = confirm(svc.create('owner', accepted_body(svc, BODY)))
    with SessionLocal.begin() as s:
        row = s.scalar(select(Evidence).where(Evidence.execution_id == 'rc20:RIDE:' + oid, Evidence.evidence_kind == policies.KIND))
        payload = deepcopy(row.evidence_json); payload['payload']['terms']['policy']['after_fee_minor'] = 999
        row.evidence_json = payload
    with pytest.raises(ValueError, match='INTEGRITY'):
        svc.refund_quote('owner', oid)


def test_isolated_fixture_is_rejected_outside_isolated_environment(monkeypatch):
    from go_hotel.core.config import settings
    monkeypatch.setattr(settings, 'app_env', 'staging')
    with synthetic_policy():
        with pytest.raises(ValueError, match='LIVE_PROVIDER_ACCEPTANCE_REQUIRED'):
            svc.search('PVG', 'Bund', BODY['pickup_at'])


def test_full_fee_cancels_without_zero_money_or_false_refund_projection(monkeypatch):
    from go_hotel.services.vertical_money_bridge import vertical_money_bridge as money
    from go_hotel.db.models import OmnichannelMoneyMovementRow as Movement, ConsumerUnifiedLifecycleRow as Life
    with synthetic_policy(before=16800, after=16800):
        oid = confirm(svc.create('owner', accepted_body(svc, BODY)))
    q = svc.refund_quote('owner', oid)
    assert q['refund_amount_minor'] == 0
    monkeypatch.setattr(money, 'refund', lambda *a, **kw: pytest.fail('zero refund must not dispatch money'))
    result = svc.cancel('owner', oid, q['quote_hash'])
    assert result['outcome'] == 'NO_REFUND_DUE' and result['refund_performed'] is False
    assert result['status'] == 'NO_REFUND_DUE'
    assert svc.cancel('owner', oid, q['quote_hash']) == result
    assert svc.get('owner', oid)['status'] == 'CANCELLED'
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(Movement).where(Movement.movement_type == 'REFUND')) == 0
        row = s.scalar(select(Life).where(Life.order_id == oid))
        assert row.refund_state != 'REFUND_COMPLETED' and row.lifecycle_state == 'CANCELLED' and row.payment_state == 'PAID'
        refund = s.scalar(select(MobilityRefundRow).where(MobilityRefundRow.order_id == oid))
        assert refund.status == 'NO_REFUND_DUE'


def test_completed_historical_refund_readback_does_not_require_new_booking_policy(monkeypatch):
    from go_hotel.services.vertical_money_bridge import vertical_money_bridge as money
    with synthetic_policy():
        oid = confirm(svc.create('owner', accepted_body(svc, BODY)))
    q = svc.refund_quote('owner', oid)
    first = svc.cancel('owner', oid, q['quote_hash'])
    with SessionLocal.begin() as s:
        for row in s.scalars(select(Evidence).where(Evidence.execution_id == 'rc20:RIDE:' + oid)):
            s.delete(row)
    monkeypatch.setattr(money, 'refund', lambda *a, **kw: pytest.fail('completed result must not dispatch'))
    assert svc.cancel('owner', oid) == first


def test_naive_modification_is_rejected_without_changing_confirmed_pickup():
    with synthetic_policy():
        oid = confirm(svc.create('owner', accepted_body(svc, BODY)))
    before = svc.get('owner', oid)
    with pytest.raises(ValueError, match='TIME_INVALID'):
        svc.modify('owner', oid, '2030-01-01T13:00:00')
    assert svc.get('owner', oid) == before
