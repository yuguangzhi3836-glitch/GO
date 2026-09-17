"""C05: two unknown-result episodes restore their own fulfillment phase."""
import pytest
from tests.test_depth33_mobility_refund_consent import booked
from test_depth21_refund_recovery import refunded_movements


def test_repeated_unknown_resolution_preserves_phase_and_cannot_restart_completed_ride():
    svc, owner, oid = booked('RIDE')
    original = svc.get(owner, oid)
    assert svc.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', 'isolated://episode-1', 'ops')['status'] == 'UNKNOWN_EXTERNAL_STATE'
    with pytest.raises(ValueError, match='ILLEGAL_STATE'):
        svc.fulfill(owner, oid, 'START', 'isolated://unknown-start')
    assert svc.admin_external_state(oid, 'CONFIRMED', 'isolated://episode-1-confirm', 'ops', 'isolated://episode-1')['status'] == 'CONFIRMED'
    assert svc.fulfill(owner, oid, 'START', 'isolated://start')['status'] == 'IN_PROGRESS'
    assert svc.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', 'isolated://episode-2', 'ops')['status'] == 'UNKNOWN_EXTERNAL_STATE'
    with pytest.raises(ValueError, match='ILLEGAL_STATE'):
        svc.fulfill(owner, oid, 'COMPLETE', 'isolated://unknown-complete')
    resumed = svc.admin_external_state(oid, 'CONFIRMED', 'isolated://episode-2-confirm', 'ops', 'isolated://episode-2')
    assert resumed['status'] == 'IN_PROGRESS'
    assert resumed['supplier_reference'] == original['supplier_reference']
    with pytest.raises(ValueError, match='ILLEGAL_STATE'):
        svc.fulfill(owner, oid, 'START', 'isolated://duplicate-start')
    assert svc.fulfill(owner, oid, 'COMPLETE', 'isolated://complete')['status'] == 'COMPLETED'
    with pytest.raises(ValueError, match='ILLEGAL_STATE'):
        svc.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', 'isolated://late', 'ops')
    with pytest.raises(ValueError, match='CANCELLABLE'):
        svc.refund_quote(owner, oid)
    assert not refunded_movements()
    events = svc.get(owner, oid)['evidence']
    assert [e['payload']['previous_status'] for e in events if e['kind'] == 'EXTERNAL_STATE_UNKNOWN'] == ['CONFIRMED', 'IN_PROGRESS']
    assert sum(e['kind'] == 'FULFILLMENT_START' for e in events) == 1
    assert sum(e['kind'] == 'FULFILLMENT_COMPLETE' for e in events) == 1
