from __future__ import annotations
from datetime import datetime, timezone
from go_hotel.services.consumer_unified_lifecycle import consumer_unified_lifecycle_service


def _life_state(native: str) -> str:
    s=str(native or '').upper()
    if s in {'TICKETED','CONFIRMED'}: return 'CONFIRMED'
    if s=='IN_PROGRESS': return 'IN_PROGRESS'
    if s in {'COMPLETED','FULFILLED'}: return 'COMPLETED'
    if s in {'REFUNDED','CANCELLED','CLOSED_BY_SUPPLIER','CONVERTED_TO_CREDIT'}: return 'CANCELLED'
    if s=='FAILED': return 'FAILED'
    if s=='UNKNOWN_EXTERNAL_STATE': return 'UNKNOWN_EXTERNAL_STATE'
    return 'PENDING'


def project_vertical_lifecycle(session, vertical: str, order, evidence_reference: str, *, facts: dict | None=None, event_type: str='VERTICAL_STATE_SYNC'):
    native=str(order.status)
    life=_life_state(native)
    paid=native not in {'PAYMENT_PENDING','PAYMENT_AUTHORIZED','PAYMENT_CONFIRMED_AWAITING_SUPPLIER','FAILED'}
    return consumer_unified_lifecycle_service.project_in_session(session,{
        'account_id':order.account_id,
        'vertical':vertical,
        'order_id':order.order_id,
        'supplier_id':getattr(order,'supplier_id',None),
        'title':f'{vertical} {order.order_id}',
        'lifecycle_state':life,
        'payment_state':'PAID' if paid else 'PENDING',
        'refund_state':'REFUND_COMPLETED' if native=='REFUNDED' else 'NOT_REQUESTED',
        'change_allowed':life=='CONFIRMED',
        'cancel_allowed':life in {'CONFIRMED','IN_PROGRESS'},
        'facts':facts or {'native_status':native},
        'evidence_reference':evidence_reference,
        'source_updated_at':datetime.now(timezone.utc),
        'event_type':event_type,
    })
