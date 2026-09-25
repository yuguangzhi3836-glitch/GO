"""C05-02: missing or damaged recovery evidence must not invent a ride phase."""
from copy import deepcopy
import pytest
from sqlalchemy import select, delete
from go_hotel.db.models import JourneyRecoveryEvidenceChainRow as Evidence, MobilityRideOrderRow
from go_hotel.db.session import SessionLocal
from go_hotel.services.rc20_vertical_evidence import _stable_hash
from tests.test_depth33_mobility_refund_consent import booked


@pytest.mark.parametrize('phase', ['CONFIRMED', 'IN_PROGRESS'])
@pytest.mark.parametrize('fault', ['missing_last', 'missing_all', 'payload_corruption', 'invalid_phase', 'contradictory_phase'])
def test_missing_or_corrupt_unknown_evidence_does_not_restore_ride(phase, fault):
    svc, owner, oid = booked('RIDE')
    if phase == 'IN_PROGRESS':
        svc.fulfill(owner, oid, 'START', 'isolated://start')
    svc.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', 'isolated://unknown', 'ops')
    with SessionLocal.begin() as session:
        query = select(Evidence).where(Evidence.execution_id == 'rc20:RIDE:' + oid).order_by(Evidence.sequence_no)
        rows = list(session.scalars(query))
        latest = rows[-1]
        assert latest.evidence_kind == 'EXTERNAL_STATE_UNKNOWN'
        if fault == 'missing_last':
            session.delete(latest)
        elif fault == 'missing_all':
            session.execute(delete(Evidence).where(Evidence.execution_id == 'rc20:RIDE:' + oid))
        else:
            body = deepcopy(latest.evidence_json)
            body['payload']['previous_status'] = 'CONFIRMED' if phase == 'IN_PROGRESS' else 'IN_PROGRESS'
            if fault in {'invalid_phase', 'contradictory_phase'}:
                if fault == 'invalid_phase':
                    body['payload']['previous_status'] = 'COMPLETED'
                latest.evidence_hash = _stable_hash(body)
                latest.entry_hash = _stable_hash({'evidence_hash': latest.evidence_hash,
                    'previous_hash': latest.previous_hash, 'sequence_no': latest.sequence_no})
            latest.evidence_json = body
    before = svc.get(owner, oid)
    with pytest.raises(ValueError, match='RIDE_RECOVERY_EVIDENCE_INVALID'):
        svc.admin_external_state(oid, 'CONFIRMED', 'isolated://unproven-recovery', 'ops')
    assert svc.get(owner, oid) == before
    with SessionLocal() as session:
        assert session.get(MobilityRideOrderRow, oid).status == 'UNKNOWN_EXTERNAL_STATE'

def test_corrupt_historical_execution_binding_blocks_new_unknown_episode():
    """An evidence row bound to another order cannot be extended as this order's chain."""
    svc, owner, oid = booked('RIDE')
    with SessionLocal.begin() as session:
        first = session.scalar(select(Evidence).where(
            Evidence.execution_id == 'rc20:RIDE:' + oid).order_by(Evidence.sequence_no))
        assert first is not None
        first.execution_item_id = 'ride_ord_other'
    before = svc.get(owner, oid)
    with pytest.raises(ValueError, match='RIDE_RECOVERY_EVIDENCE_INVALID'):
        svc.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', 'isolated://new-episode', 'ops')
    assert svc.get(owner, oid) == before
    with SessionLocal() as session:
        assert session.get(MobilityRideOrderRow, oid).status == 'CONFIRMED'
