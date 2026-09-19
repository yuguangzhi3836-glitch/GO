"""Fail closed unless the rental's intact chain proves its current UNKNOWN episode.

This uses the ride recovery contract: a correlation reference is scoped to one
order and one episode. It is not proof of an external provider signature.
"""
from sqlalchemy import select

from go_hotel.db.models import JourneyRecoveryEvidenceChainRow as Evidence
from go_hotel.services.rc20_vertical_evidence import _stable_hash


def validated_chain(session, order):
    rows = list(session.scalars(select(Evidence).where(
        Evidence.execution_id == 'rc20:RENTAL:' + order.order_id).order_by(Evidence.sequence_no)))
    previous = 'GENESIS'
    for number, row in enumerate(rows, 1):
        body = row.evidence_json
        if (not isinstance(body, dict) or row.sequence_no != number
                or row.previous_hash != previous or body.get('previous_hash') != previous
                or body.get('sequence_no') != number or body.get('vertical') != 'RENTAL'
                or body.get('order_id') != order.order_id or row.execution_item_id != order.order_id
                or body.get('kind') != row.evidence_kind or body.get('status') != row.observed_status
                or row.evidence_hash != _stable_hash(body)
                or row.entry_hash != _stable_hash({'evidence_hash': row.evidence_hash,
                    'previous_hash': previous, 'sequence_no': number})):
            raise ValueError('RENTAL_RECOVERY_EVIDENCE_INVALID')
        previous = row.entry_hash
    if not rows or rows[-1].observed_status != order.status:
        raise ValueError('RENTAL_RECOVERY_EVIDENCE_INVALID')
    return rows


def reject_reused_unknown_episode(session, order, episode_reference):
    if not isinstance(episode_reference, str) or not episode_reference.strip():
        raise ValueError('RENTAL_UNKNOWN_EPISODE_REFERENCE_REQUIRED')
    for row in validated_chain(session, order):
        payload = row.evidence_json.get('payload')
        if (row.evidence_kind == 'EXTERNAL_STATE_UNKNOWN' and isinstance(payload, dict)
                and payload.get('evidence_reference') == episode_reference):
            raise ValueError('RENTAL_UNKNOWN_EPISODE_REFERENCE_REUSED')


def previous_phase(session, order, confirmation_episode_reference):
    rows = validated_chain(session, order)
    latest = rows[-1]
    payload = latest.evidence_json.get('payload')
    if (latest.evidence_kind != 'EXTERNAL_STATE_UNKNOWN'
            or latest.observed_status != 'UNKNOWN_EXTERNAL_STATE' or not isinstance(payload, dict)
            or payload.get('previous_status') not in {'CONFIRMED', 'IN_PROGRESS'}
            or len(rows) < 2 or rows[-2].observed_status != payload.get('previous_status')
            or payload.get('supplier_reference') != order.supplier_reference
            or not isinstance(payload.get('actor'), str) or not payload['actor'].strip()
            or not isinstance(payload.get('evidence_reference'), str) or not payload['evidence_reference'].strip()):
        raise ValueError('RENTAL_RECOVERY_EVIDENCE_INVALID')
    if (not isinstance(confirmation_episode_reference, str)
            or not confirmation_episode_reference.strip()
            or confirmation_episode_reference != payload['evidence_reference']):
        raise ValueError('RENTAL_CONFIRMATION_EPISODE_MISMATCH')
    return payload['previous_status']
