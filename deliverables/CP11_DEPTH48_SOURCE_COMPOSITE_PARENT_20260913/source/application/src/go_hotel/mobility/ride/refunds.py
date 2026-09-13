"""Freeze ride refund and consent before money; preserve the original money key."""
from datetime import UTC,datetime
from sqlalchemy import select
from go_hotel.autonomy.durable import transaction
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import MobilityRideOrderRow as Order, MobilityRefundRow as Refund
from go_hotel.domain.models import new_id
from go_hotel.services import refund_consent, mobility_refund_consent as consent
from go_hotel.services.vertical_money_bridge import vertical_money_bridge as money
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence
from go_hotel.services.vertical_lifecycle_projection import project_vertical_lifecycle

def now():return datetime.now(UTC).replace(tzinfo=None)

def owned(s,account,oid):
    o=s.get(Order,oid,with_for_update=True)
    if not o or o.account_id!=account:raise ValueError('MOBILITY_ORDER_NOT_FOUND')
    return o

def terms(o):
    if o.status!='CONFIRMED':raise ValueError('MOBILITY_ORDER_NOT_CANCELLABLE')
    return refund_consent.bind('RIDE',o,{'order_id':o.order_id,'fee_minor':0,
        'refund_amount_minor':o.total_amount_minor,'currency':o.currency,'refund_to':'ORIGINAL_PAYMENT_METHOD'})

def quote(account,oid):
    with transaction(SessionLocal) as s:return terms(owned(s,account,oid))

def cancel(account,oid,accepted_hash=None):
    def result(r):return {'refund_id':r.refund_id,'order_id':oid,'status':r.status,
        'refund_amount_minor':r.refund_amount_minor,'currency':r.currency}
    with transaction(SessionLocal) as s:
        o=owned(s,account,oid)
        r=s.scalar(select(Refund).where(Refund.vertical=='RIDE',Refund.order_id==oid).order_by(Refund.created_at.desc()))
        if r:
            consent.existing(s,o,r,accepted_hash,'RIDE')
            if r.status=='REFUND_COMPLETED':
                if o.status!='REFUNDED':raise ValueError('MOBILITY_REFUND_RECONCILIATION_REQUIRED')
                return result(r)
            if r.status!='REFUND_PENDING' or o.status!='REFUND_PENDING':raise ValueError('MOBILITY_REFUND_RECONCILIATION_REQUIRED')
        else:
            q=terms(o);refund_consent.verify(q,accepted_hash)
            r=Refund(refund_id=new_id('mob_ref'),order_id=oid,vertical='RIDE',fee_minor=q['fee_minor'],
                refund_amount_minor=q['refund_amount_minor'],currency=q['currency'],status='REFUND_PENDING',
                settlement_plan_json=[],created_at=now())
            consent.freeze(s,o,r,q,accepted_hash,'RIDE')
            s.add(r);o.status='REFUND_PENDING';o.updated_at=now()
            append_vertical_evidence(s,'RIDE',oid,'REFUND_REQUESTED',o.status,{'refund_id':r.refund_id,'refund_amount_minor':r.refund_amount_minor})
            project_vertical_lifecycle(s,'RIDE',o,'ride-refund-pending://'+oid)
        rid=r.refund_id;amount=r.refund_amount_minor
    # Ambiguous outcomes remain pending. No new refund key on retry.
    movement=money.refund('RIDE',oid,amount,'ride-refund://'+oid,'ride-refund:'+oid)
    if movement['state']!='CONFIRMED':raise ValueError('MOBILITY_REFUND_MONEY_NOT_CONFIRMED')
    with transaction(SessionLocal) as s:
        o=owned(s,account,oid);r=s.get(Refund,rid,with_for_update=True)
        consent.existing(s,o,r,accepted_hash,'RIDE')
        if r.status=='REFUND_COMPLETED':return result(r)
        if o.status!='REFUND_PENDING' or r.status!='REFUND_PENDING':raise ValueError('MOBILITY_REFUND_RECONCILIATION_REQUIRED')
        # Confirm the ledger receipt belongs to this owner, root, currency and amount.
        from types import SimpleNamespace
        from go_hotel.services.vertical_refund_recovery import _confirmed_money_in
        _confirmed_money_in(s,SimpleNamespace(vertical='RIDE',order_id=oid,account_id=account,
            adjustment_ids_json=[],quote_json={'currency':r.currency,'refund_amount_minor':amount}),movement)
        r.status='REFUND_COMPLETED';o.status='REFUNDED';o.updated_at=now()
        facts={'refund_id':rid,'refund_amount_minor':amount,'money_movement_id':movement['money_movement_id']}
        append_vertical_evidence(s,'RIDE',oid,'REFUND_COMPLETED',o.status,facts)
        project_vertical_lifecycle(s,'RIDE',o,'refund:'+rid,facts=facts)
        return result(r)
