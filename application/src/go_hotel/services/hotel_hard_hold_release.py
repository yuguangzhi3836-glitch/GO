from __future__ import annotations

from go_hotel.connectors.registry import registry
from go_hotel.domain.models import Event, new_id, now_utc
from go_hotel.repositories.sql import repo


def _cancel_released_hold(session, order_row, prebook_row, account_id: str, order_id: str, connector_id: str):
    order_row.status = 'CANCELLED'; order_row.version += 1; order_row.updated_at = now_utc()
    repo._append_event_and_outbox(session, Event(new_id('evt'), 'UNPAID_ORDER_CANCELLED', 'HOTEL_ORDER', order_id,
        {'account_id': account_id, 'inventory_held': True, 'hold_type': prebook_row.hold_type,
         'connector_id': connector_id, 'connector_hold_release': 'RELEASED', 'release': 'AGENT'}))
    session.flush()
    return {'order_id': order_id, 'status': 'CANCELLED', 'connector_hold_release': 'RELEASED',
            'connector_id': connector_id, 'prebook_id': prebook_row.prebook_id}


async def release_locked(session, order_row, prebook_row, account_id: str, order_id: str):
    """Release a connector-native hard prebook hold before local cancellation.

    Caller owns the native hotel order row lock. The connector must advertise an
    idempotent hard-hold release contract. An ambiguous result is reconciled by
    connector lookup; UNKNOWN never becomes a local cancellation.
    """
    offer = repo.get_offer(prebook_row.offer_id)
    if not offer or not offer.connector_id: raise ValueError('HOTEL_HARD_HOLD_CONNECTOR_REQUIRED')
    connector = registry.get(offer.connector_id)
    caps = connector.metadata.capabilities
    if not (caps.hard_inventory_hold and caps.hard_hold_release and caps.idempotent_hard_hold_release):
        raise ValueError('HOTEL_HARD_HOLD_CONNECTOR_RELEASE_NOT_CERTIFIED')
    key = 'agent-hard-hold-release:' + order_id
    result = await connector.lookup_prebook_hold(prebook_row.prebook_id, key)
    if result == 'RELEASED':
        return _cancel_released_hold(session, order_row, prebook_row, account_id, order_id, offer.connector_id)
    try:
        result = await connector.release_prebook_hold(prebook_row.prebook_id, key)
    except TimeoutError:
        result = await connector.lookup_prebook_hold(prebook_row.prebook_id, key)
    if result != 'RELEASED':
        raise ValueError('HOTEL_HARD_HOLD_RELEASE_RECONCILIATION_REQUIRED')
    return _cancel_released_hold(session, order_row, prebook_row, account_id, order_id, offer.connector_id)
