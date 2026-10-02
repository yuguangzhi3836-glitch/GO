"""Bind rental change completion to durable money, not executor return values."""
from collections import Counter
from types import SimpleNamespace
from sqlalchemy import select
from go_hotel.db.models import (
    PaymentOrderRootRow as Root, OmnichannelPaymentIntentRow as Intent,
    PaymentOrderFactBindingRow as Binding, OmnichannelMoneyMovementRow as Movement,
    OmnichannelLedgerEntryRow as Entry,
)
from go_hotel.services.vertical_money_bridge import digest
from go_hotel.services.unified_money_movement import business_ledger_account_code, digest as ledger_digest


def intent_in(s, order, business_type, business_id):
    root=s.scalar(select(Root).where(Root.business_type==business_type,Root.business_id==business_id))
    intent=s.get(Intent,root.payment_intent_id) if root else None
    if (not intent or intent.payer_id!=order.account_id or intent.currency!=order.currency
            or (intent.business_type,intent.business_id)!=(business_type,business_id)):
        raise ValueError('RENTAL_CHANGE_PAYMENT_BINDING_INVALID')
    bindings=list(s.scalars(select(Binding).where(Binding.payment_intent_id==intent.payment_intent_id)))
    if len(bindings)!=1 or (bindings[0].business_type,bindings[0].business_id,bindings[0].payer_id,
            bindings[0].payee_id,bindings[0].currency,bindings[0].amount_minor,bindings[0].legal_entity_id)!=(
            business_type,business_id,intent.payer_id,intent.payee_id,intent.currency,intent.amount_minor,root.legal_entity_id):
        raise ValueError('RENTAL_CHANGE_PAYMENT_BINDING_INVALID')
    return intent


def refund_plan_in(s, order, q, adjustment_ids):
    base=intent_in(s,order,'RENTAL_ORDER',order.order_id)
    allowed={base.payment_intent_id}
    for aid in adjustment_ids:
        extra=intent_in(s,order,'RENTAL_CHANGE',aid)
        if extra.payee_id!=base.payee_id:raise ValueError('RENTAL_CHANGE_PAYMENT_BINDING_INVALID')
        allowed.add(extra.payment_intent_id)
    plan=q.refund_plan_json
    if not isinstance(plan,list) or not plan:raise ValueError('RENTAL_CHANGE_REFUND_PLAN_INVALID')
    seen=set();total=0
    for item in plan:
        if not isinstance(item,dict):raise ValueError('RENTAL_CHANGE_REFUND_PLAN_INVALID')
        cap=s.get(Movement,item.get('capture_id')) if item.get('capture_id') else None
        amount=item.get('amount_minor')
        if (not cap or cap.state!='CONFIRMED' or cap.movement_type!='CAPTURE'
                or cap.root_payment_intent_id not in allowed
                or item.get('payment_intent_id')!=cap.root_payment_intent_id
                or cap.currency!=q.currency or type(amount) is not int or not 0<amount<=cap.amount_minor
                or cap.money_movement_id in seen
                or item.get('key')!='rental-change-refund:'+q.quote_id+':'+digest(cap.money_movement_id)[:16]):
            raise ValueError('RENTAL_CHANGE_REFUND_PLAN_INVALID')
        seen.add(cap.money_movement_id);total+=amount
    if total!=-q.difference_minor:raise ValueError('RENTAL_CHANGE_REFUND_PLAN_INVALID')


def confirmed_in(s, order, q, result, adjustment_ids):
    if q.difference_minor<0:
        from go_hotel.services.vertical_refund_recovery import _confirmed_money_in
        refund_plan_in(s,order,q,adjustment_ids)
        ids=_confirmed_money_in(s,SimpleNamespace(vertical='RENTAL',order_id=order.order_id,
            account_id=order.account_id,adjustment_ids_json=adjustment_ids,
            quote_json={'currency':q.currency,'refund_amount_minor':-q.difference_minor}),result)
        expected=Counter((x['payment_intent_id'],x['capture_id'],x['amount_minor'],x['key']) for x in q.refund_plan_json)
        rows=[s.get(Movement,mid) for mid in ids]
        observed=Counter((x.root_payment_intent_id,x.parent_movement_id,x.amount_minor,x.idempotency_key) for x in rows)
        if observed!=expected:raise ValueError('RENTAL_CHANGE_REFUND_RECEIPT_PLAN_INVALID')
        return ids
    if q.difference_minor==0:return []
    base=intent_in(s,order,'RENTAL_ORDER',order.order_id)
    intent=intent_in(s,order,'RENTAL_CHANGE',q.quote_id)
    cap=s.get(Movement,result.get('capture_id')) if result.get('capture_id') else None
    auth=s.get(Movement,cap.parent_movement_id) if cap and cap.parent_movement_id else None
    if (intent.payee_id!=base.payee_id or intent.amount_minor!=q.difference_minor
            or result.get('payment_intent_id')!=intent.payment_intent_id or not cap or not auth):
        raise ValueError('RENTAL_CHANGE_CAPTURE_NOT_CONFIRMED')
    for row,kind,key in ((auth,'AUTHORIZATION','auth'),(cap,'CAPTURE','cap')):
        if (row.state!='CONFIRMED' or row.movement_type!=kind
                or row.root_payment_intent_id!=intent.payment_intent_id
                or (row.business_type,row.business_id)!=('RENTAL_CHANGE',q.quote_id)
                or row.currency!=q.currency or row.amount_minor!=q.difference_minor
                or row.idempotency_key!=f'rental-change-{key}:{q.quote_id}'):
            raise ValueError('RENTAL_CHANGE_CAPTURE_NOT_CONFIRMED')
    entries=list(s.scalars(select(Entry).where(Entry.transaction_id==cap.money_movement_id)))
    pairs={(f'PAYMENT_CLEARING:{intent.selected_channel}','DEBIT'),
           (business_ledger_account_code(intent.business_type,intent.business_id),'CREDIT')}
    if len(entries)!=2 or {(e.account_code,e.direction) for e in entries}!=pairs or any(
            (e.payment_intent_id,e.amount_minor,e.currency,e.entry_type,e.evidence_hash)!=(
                intent.payment_intent_id,cap.amount_minor,cap.currency,'CAPTURE',ledger_digest({'movement':cap.money_movement_id})) for e in entries):
        raise ValueError('RENTAL_CHANGE_CAPTURE_NOT_CONFIRMED')
    return [cap.money_movement_id]


def completed_in(s, order, q, adjustment_ids):
    from go_hotel.services.ticket_operations import _events
    from go_hotel.services.rc20_vertical_evidence import list_vertical_evidence
    _events(s,'RENTAL',order.order_id)
    facts=[x['payload'] for x in list_vertical_evidence(s,'RENTAL',order.order_id)
           if x['kind']=='CHANGE_EXECUTED' and x['payload'].get('quote_id')==q.quote_id]
    if len(facts)!=1 or facts[0].get('difference_minor')!=q.difference_minor:
        raise ValueError('RENTAL_CHANGE_COMPLETION_EVIDENCE_INVALID')
    result=facts[0]
    if q.difference_minor>0:
        ids=result.get('money_movement_ids')
        if not isinstance(ids,list) or len(ids)!=1:raise ValueError('RENTAL_CHANGE_CAPTURE_NOT_CONFIRMED')
        intent=intent_in(s,order,'RENTAL_CHANGE',q.quote_id)
        result={'capture_id':ids[0],'payment_intent_id':intent.payment_intent_id}
    confirmed_in(s,order,q,result,adjustment_ids)
