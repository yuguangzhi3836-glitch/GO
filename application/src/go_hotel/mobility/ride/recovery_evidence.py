"""Recover only the ride phase recorded in an intact current evidence chain."""
from sqlalchemy import select
from go_hotel.db.models import JourneyRecoveryEvidenceChainRow as Evidence
from go_hotel.services.rc20_vertical_evidence import _stable_hash


def current_unknown_episode(session, order):
    rows = list(session.scalars(select(Evidence).where(
        Evidence.execution_id == 'rc20:RIDE:' + order.order_id).order_by(Evidence.sequence_no)))
    previous = 'GENESIS'
    for number, row in enumerate(rows, 1):
        body = row.evidence_json
        if (not isinstance(body, dict) or row.sequence_no != number
                or row.previous_hash != previous or body.get('previous_hash') != previous
                or body.get('sequence_no') != number or body.get('vertical') != 'RIDE'
                or body.get('order_id') != order.order_id or row.execution_item_id != order.order_id
                or body.get('kind') != row.evidence_kind or body.get('status') != row.observed_status
                or row.evidence_hash != _stable_hash(body)
                or row.entry_hash != _stable_hash({'evidence_hash': row.evidence_hash,
                    'previous_hash': previous, 'sequence_no': number})):
            raise ValueError('RIDE_RECOVERY_EVIDENCE_INVALID')
        previous = row.entry_hash
    if not rows or rows[-1].evidence_kind != 'EXTERNAL_STATE_UNKNOWN':
        raise ValueError('RIDE_RECOVERY_EVIDENCE_INVALID')
    latest = rows[-1]
    payload = latest.evidence_json.get('payload')
    if (latest.observed_status != 'UNKNOWN_EXTERNAL_STATE' or not isinstance(payload, dict)
            or payload.get('previous_status') not in {'CONFIRMED', 'IN_PROGRESS'}
            or len(rows) < 2 or rows[-2].observed_status != payload.get('previous_status')
            or payload.get('supplier_reference') != order.supplier_reference
            or not isinstance(payload.get('actor'), str) or not payload['actor'].strip()
            or not isinstance(payload.get('evidence_reference'), str) or not payload['evidence_reference'].strip()):
        raise ValueError('RIDE_RECOVERY_EVIDENCE_INVALID')
    return payload['previous_status'], payload['evidence_reference']


def previous_phase(session, order, confirmation_episode_reference=None):
    """Return the recoverable phase only for the current UNKNOWN episode.

    The provider/fleet confirmation must carry the exact episode reference that
    opened the current UNKNOWN state. This is correlation evidence only; it is
    not a claim of an external cryptographic signature.
    """
    phase, current_episode_reference = current_unknown_episode(session, order)
    if (not isinstance(confirmation_episode_reference, str)
            or not confirmation_episode_reference.strip()
            or confirmation_episode_reference != current_episode_reference):
        raise ValueError('RIDE_CONFIRMATION_EPISODE_MISMATCH')
    return phase
