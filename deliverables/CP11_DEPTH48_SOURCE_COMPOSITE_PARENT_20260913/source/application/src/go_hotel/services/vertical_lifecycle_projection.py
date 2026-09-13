from __future__ import annotations
from datetime import datetime, timezone
from go_hotel.services.consumer_unified_lifecycle import consumer_unified_lifecycle_service
from sqlalchemy import select
from go_hotel.db.models import OrderSupplierFulfillmentRow as Fulfillment, OmnichannelPaymentIntentRow as Intent, PaymentOrderRootRow as Root


def _life_state(native: str) -> str:
    s=str(native or '').upper()
    if s in {'TICKETED','CONFIRMED','REFUND_PENDING','CHANGE_PENDING'}: return 'CONFIRMED'
    if s=='IN_PROGRESS': return 'IN_PROGRESS'
    if s in {'COMPLETED','FULFILLED'}: return 'COMPLETED'
    if s in {'REFUNDED','CANCELLED','CLOSED_BY_SUPPLIER','CONVERTED_TO_CREDIT'}: return 'CANCELLED'
    if s=='FAILED': return 'FAILED'
    if s=='UNKNOWN_EXTERNAL_STATE': return 'UNKNOWN_EXTERNAL_STATE'
    return 'PENDING'


def project_vertical_lifecycle(session, vertical: str, order, evidence_reference: str, *, facts: dict | None=None, event_type: str='VERTICAL_STATE_SYNC'):
    native=str(order.status)
    life=_life_state(native)
    paid=not (facts or {}).get('unpaid',False) and native not in {'PAYMENT_PENDING','PAYMENT_AUTHORIZED','PAYMENT_CONFIRMED_AWAITING_SUPPLIER','FAILED'}
    supplier_id = getattr(order, 'supplier_id', None)
    if vertical != 'HOTEL':
        supplier_id = session.scalar(select(Fulfillment.supplier_id).join(Intent,
            Intent.payment_intent_id == Fulfillment.payment_intent_id).join(Root,
            Root.payment_intent_id == Intent.payment_intent_id).where(
            Root.business_type == vertical + '_ORDER', Root.business_id == order.order_id,
            Intent.business_type == Root.business_type, Intent.business_id == Root.business_id,
            Intent.payer_id == order.account_id, Intent.payee_id == Fulfillment.supplier_id,
            Fulfillment.business_type == Root.business_type, Fulfillment.business_id == Root.business_id))
    return consumer_unified_lifecycle_service.project_in_session(session,{
        'account_id':order.account_id,
        'vertical':vertical,
        'order_id':order.order_id,
        'supplier_id':supplier_id,
        'title':f'{vertical} {order.order_id}',
        'lifecycle_state':life,
        'payment_state':'PAID' if paid else 'PENDING',
        'refund_state':'REFUND_COMPLETED' if native=='REFUNDED' else 'REFUND_PROCESSING' if native=='REFUND_PENDING' else 'NOT_REQUESTED',
        'change_allowed':life=='CONFIRMED' and native not in {'REFUND_PENDING','CHANGE_PENDING'},
        'cancel_allowed':life in {'CONFIRMED','IN_PROGRESS'} and native not in {'REFUND_PENDING','CHANGE_PENDING'},
        'facts':facts or {'native_status':native},
        'evidence_reference':evidence_reference,
        'source_updated_at':datetime.now(timezone.utc),
        'event_type':event_type,
    })
