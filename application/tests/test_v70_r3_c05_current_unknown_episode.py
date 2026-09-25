"""V70-R3-C05-01: fleet confirmation is scoped to the current UNKNOWN episode."""
import pytest

from tests.test_depth33_mobility_refund_consent import booked


def test_delayed_confirmation_from_previous_unknown_episode_is_rejected():
    svc, owner, oid = booked('RIDE')

    svc.admin_external_state(
        oid, 'UNKNOWN_EXTERNAL_STATE', 'isolated://episode-1', 'ops'
    )
    svc.admin_external_state(
        oid, 'CONFIRMED', 'isolated://episode-1-confirm', 'ops',
        'isolated://episode-1',
    )
    svc.fulfill(owner, oid, 'START', 'isolated://start')

    svc.admin_external_state(
        oid, 'UNKNOWN_EXTERNAL_STATE', 'isolated://episode-2', 'ops'
    )
    before = svc.get(owner, oid)
    with pytest.raises(ValueError, match='RIDE_CONFIRMATION_EPISODE_MISMATCH'):
        svc.admin_external_state(
            oid, 'CONFIRMED', 'isolated://late-episode-1-confirm', 'ops',
            'isolated://episode-1',
        )
    assert svc.get(owner, oid) == before

    recovered = svc.admin_external_state(
        oid, 'CONFIRMED', 'isolated://episode-2-confirm', 'ops',
        'isolated://episode-2',
    )
    assert recovered['status'] == 'IN_PROGRESS'


def test_confirmation_without_current_episode_identity_is_rejected():
    svc, owner, oid = booked('RIDE')
    svc.admin_external_state(
        oid, 'UNKNOWN_EXTERNAL_STATE', 'isolated://episode-current', 'ops'
    )
    before = svc.get(owner, oid)
    with pytest.raises(ValueError, match='RIDE_CONFIRMATION_EPISODE_MISMATCH'):
        svc.admin_external_state(
            oid, 'CONFIRMED', 'isolated://unbound-confirmation', 'ops'
        )
    assert svc.get(owner, oid) == before
