"""Confirmed capture/refund facts across the original flight and its changes."""
from sqlalchemy import select,or_,and_
from sqlalchemy.orm import object_session
from go_hotel.db.models import (PaymentOrderRootRow as Root,PaymentOrderFactBindingRow as Binding,
    OmnichannelPaymentIntentRow as Intent,OmnichannelMoneyMovementRow as Movement,
    OmnichannelLedgerEntryRow as Entry,FlightChangeQuoteRow as Quote)


def read(order):
    unknown={'verified':False,'currency':order.currency,'captured_minor':None,'refunded_minor':None,'net_minor':None}
    s=object_session(order)
    if s is None:return unknown
    qids=select(Quote.quote_id).where(Quote.order_id==order.order_id)
    roots=list(s.scalars(select(Root).where(or_(and_(Root.business_type=='FLIGHT_ORDER',Root.business_id==order.order_id),
        and_(Root.business_type=='FLIGHT_CHANGE',Root.business_id.in_(qids))))))
    if not roots:
        return {'verified':True,'currency':order.currency,'captured_minor':0,'refunded_minor':0,'net_minor':0,'has_pending':False} if order.status=='PAYMENT_PENDING' else unknown
    base=[r for r in roots if r.business_type=='FLIGHT_ORDER']
    if len(base)!=1:return unknown
    quotes=list(s.scalars(select(Quote).where(Quote.order_id==order.order_id)))
    root_quotes={r.business_id for r in roots if r.business_type=='FLIGHT_CHANGE'}
    if any(q.total_due_minor>0 and q.status not in {'QUOTED','EXPIRED'} and q.quote_id not in root_quotes for q in quotes):return unknown
    captured=refunded=0;pending=False
    for root in roots:
        i=s.get(Intent,root.payment_intent_id)
        bindings=list(s.scalars(select(Binding).where(Binding.payment_intent_id==root.payment_intent_id)))
        if not i or len(bindings)!=1:return unknown
        b=bindings[0]
        if (i.business_type,i.business_id,i.payer_id,i.currency)!=(root.business_type,root.business_id,order.account_id,order.currency):return unknown
        if (b.business_type,b.business_id,b.payer_id,b.payee_id,b.currency,b.amount_minor)!=(i.business_type,i.business_id,i.payer_id,i.payee_id,i.currency,i.amount_minor):return unknown
        moves=list(s.scalars(select(Movement).where(Movement.root_payment_intent_id==i.payment_intent_id)))
        byid={m.money_movement_id:m for m in moves}
        caps=[m for m in moves if m.state=='CONFIRMED' and m.movement_type=='CAPTURE']
        refs=[m for m in moves if m.state=='CONFIRMED' and m.movement_type=='REFUND']
        for m in caps+refs:
            if (m.business_type,m.business_id,m.currency)!=(i.business_type,i.business_id,order.currency) or m.amount_minor<0:return unknown
            entries=list(s.scalars(select(Entry).where(Entry.transaction_id==m.money_movement_id)))
            if len(entries)!=2 or {e.direction for e in entries}!={'DEBIT','CREDIT'} or any(
                (e.payment_intent_id,e.amount_minor,e.currency,e.entry_type)!=(i.payment_intent_id,m.amount_minor,order.currency,m.movement_type) for e in entries):return unknown
            if m.movement_type=='REFUND' and m.parent_movement_id not in {c.money_movement_id for c in caps}:return unknown
            if m.movement_type=='CAPTURE' and m.parent_movement_id:
                auth=byid.get(m.parent_movement_id)
                if not auth or auth.state!='CONFIRMED' or auth.movement_type!='AUTHORIZATION' or auth.currency!=order.currency or auth.amount_minor<m.amount_minor:return unknown
        if sum(c.amount_minor for c in caps)>i.amount_minor:return unknown
        if any(sum(r.amount_minor for r in refs if r.parent_movement_id==c.money_movement_id)>c.amount_minor for c in caps):return unknown
        captured+=sum(c.amount_minor for c in caps);refunded+=sum(r.amount_minor for r in refs)
        pending |= any(m.state not in {'CONFIRMED','FAILED','REJECTED','CANCELLED'} for m in moves)
    return {'verified':True,'currency':order.currency,'captured_minor':captured,'refunded_minor':refunded,'net_minor':captured-refunded,'has_pending':pending}
