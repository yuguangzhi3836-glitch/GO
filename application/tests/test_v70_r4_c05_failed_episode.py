"""V70-R4-C05-01: every terminal fleet decision is current-episode bound."""
import pytest

from go_hotel.db.models import MobilityRideOrderRow
from go_hotel.db.session import SessionLocal
from go_hotel.mobility.ride.recovery_evidence import current_unknown_episode
from tests.test_depth33_mobility_refund_consent import booked


def episode_for(order_id):
    with SessionLocal() as session:
        _, episode = current_unknown_episode(
            session, session.get(MobilityRideOrderRow, order_id)
        )
    return episode


def test_delayed_failed_decision_cannot_terminate_new_unknown_episode():
    svc, owner, oid = booked("RIDE")
    svc.admin_external_state(
        oid, "UNKNOWN_EXTERNAL_STATE", "isolated://episode-1", "ops"
    )
    first = episode_for(oid)
    svc.admin_external_state(
        oid, "CONFIRMED", "isolated://episode-1-confirm", "ops", first
    )
    svc.fulfill(owner, oid, "START", "isolated://start")
    svc.admin_external_state(
        oid, "UNKNOWN_EXTERNAL_STATE", "isolated://episode-2", "ops"
    )
    second = episode_for(oid)
    assert second != first

    before = svc.get(owner, oid)
    with pytest.raises(ValueError, match="RIDE_CONFIRMATION_EPISODE_MISMATCH"):
        svc.admin_external_state(
            oid, "FAILED", "isolated://late-failure", "ops", first
        )
    assert svc.get(owner, oid) == before

    failed = svc.admin_external_state(
        oid, "FAILED", "isolated://current-failure", "ops", second
    )
    assert failed["status"] == "FAILED"


def test_failed_decision_without_episode_identity_is_rejected():
    svc, owner, oid = booked("RIDE")
    svc.admin_external_state(
        oid, "UNKNOWN_EXTERNAL_STATE", "isolated://current", "ops"
    )
    before = svc.get(owner, oid)
    with pytest.raises(ValueError, match="RIDE_CONFIRMATION_EPISODE_MISMATCH"):
        svc.admin_external_state(
            oid, "FAILED", "isolated://unbound-failure", "ops"
        )
    assert svc.get(owner, oid) == before


def test_unknown_episode_reference_cannot_be_reused_on_same_order():
    svc, owner, oid = booked('RIDE')
    reference = 'isolated://reused-episode'
    svc.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', reference, 'ops')
    svc.admin_external_state(oid, 'CONFIRMED', 'isolated://confirm', 'ops', reference)
    before = svc.get(owner, oid)
    with pytest.raises(ValueError, match='RIDE_UNKNOWN_EPISODE_REFERENCE_REUSED'):
        svc.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', reference, 'ops')
    assert svc.get(owner, oid) == before


def test_same_episode_reference_is_allowed_for_different_orders():
    first, _, first_id = booked('RIDE')
    second, _, second_id = booked('RIDE')
    reference = 'isolated://supplier-correlation'
    assert first.admin_external_state(first_id, 'UNKNOWN_EXTERNAL_STATE', reference, 'ops')['status'] == 'UNKNOWN_EXTERNAL_STATE'
    assert second.admin_external_state(second_id, 'UNKNOWN_EXTERNAL_STATE', reference, 'ops')['status'] == 'UNKNOWN_EXTERNAL_STATE'
