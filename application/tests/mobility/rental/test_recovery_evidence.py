"""C04: rental unknown-state recovery must use intact same-episode evidence."""
from copy import deepcopy

import pytest
from sqlalchemy import delete, select

from go_hotel.db.models import JourneyRecoveryEvidenceChainRow as Evidence, MobilityRentalOrderRow
from go_hotel.db.session import SessionLocal
from go_hotel.services.rc20_vertical_evidence import _stable_hash
from tests.test_depth33_mobility_refund_consent import booked


@pytest.mark.parametrize('phase', ['CONFIRMED', 'IN_PROGRESS'])
@pytest.mark.parametrize('fault', ['missing_last', 'missing_all', 'payload_corruption', 'invalid_phase', 'contradictory_phase'])
def test_missing_or_corrupt_unknown_evidence_does_not_restore_rental(phase, fault):
    svc, owner, oid = booked('RENTAL')
    if phase == 'IN_PROGRESS':
        svc.fulfill(owner, oid, 'PICKUP', 'isolated://pickup')
    svc.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', 'isolated://unknown', 'ops')
    with SessionLocal.begin() as session:
        query = select(Evidence).where(Evidence.execution_id == 'rc20:RENTAL:' + oid).order_by(Evidence.sequence_no)
        rows = list(session.scalars(query))
        latest = rows[-1]
        assert latest.evidence_kind == 'EXTERNAL_STATE_UNKNOWN'
        if fault == 'missing_last':
            session.delete(latest)
        elif fault == 'missing_all':
            session.execute(delete(Evidence).where(Evidence.execution_id == 'rc20:RENTAL:' + oid))
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
    with pytest.raises(ValueError, match='RENTAL_RECOVERY_EVIDENCE_INVALID'):
        svc.admin_external_state(oid, 'CONFIRMED', 'isolated://unproven-recovery', 'ops')
    assert svc.get(owner, oid) == before
    with SessionLocal() as session:
        assert session.get(MobilityRentalOrderRow, oid).status == 'UNKNOWN_EXTERNAL_STATE'


def test_repeated_unknown_resolution_preserves_rental_phase_per_episode():
    svc, owner, oid = booked('RENTAL')
    original = svc.get(owner, oid)
    assert svc.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', 'isolated://episode-1', 'ops')['status'] == 'UNKNOWN_EXTERNAL_STATE'
    with pytest.raises(ValueError, match='ILLEGAL_STATE'):
        svc.fulfill(owner, oid, 'PICKUP', 'isolated://unknown-pickup')
    assert svc.admin_external_state(oid, 'CONFIRMED', 'isolated://episode-1-confirm', 'ops')['status'] == 'CONFIRMED'
    assert svc.fulfill(owner, oid, 'PICKUP', 'isolated://pickup')['status'] == 'IN_PROGRESS'
    assert svc.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', 'isolated://episode-2', 'ops')['status'] == 'UNKNOWN_EXTERNAL_STATE'
    with pytest.raises(ValueError, match='ILLEGAL_STATE'):
        svc.fulfill(owner, oid, 'RETURN', 'isolated://unknown-return')
    resumed = svc.admin_external_state(oid, 'CONFIRMED', 'isolated://episode-2-confirm', 'ops')
    assert resumed['status'] == 'IN_PROGRESS'
    assert resumed['supplier_reference'] == original['supplier_reference']
    with pytest.raises(ValueError, match='ILLEGAL_STATE'):
        svc.fulfill(owner, oid, 'PICKUP', 'isolated://duplicate-pickup')
    assert svc.fulfill(owner, oid, 'RETURN', 'isolated://return')['status'] == 'COMPLETED'
    with pytest.raises(ValueError, match='ILLEGAL_STATE'):
        svc.admin_external_state(oid, 'UNKNOWN_EXTERNAL_STATE', 'isolated://late', 'ops')
    events = svc.get(owner, oid)['evidence']
    assert [e['payload']['previous_status'] for e in events if e['kind'] == 'EXTERNAL_STATE_UNKNOWN'] == ['CONFIRMED', 'IN_PROGRESS']
    assert sum(e['kind'] == 'FULFILLMENT_PICKUP' for e in events) == 1
    assert sum(e['kind'] == 'FULFILLMENT_RETURN' for e in events) == 1
