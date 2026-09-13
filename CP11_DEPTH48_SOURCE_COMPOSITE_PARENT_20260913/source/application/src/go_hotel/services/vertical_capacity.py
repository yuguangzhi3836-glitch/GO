"""Shared isolated capacity. Quotes observe; orders allocate in their transaction.

Uncertain supplier outcomes never release capacity. Unpaid orders conservatively
retain allocation until cancellation or expiration is coordinated with checkout.
"""
from sqlalchemy import select, exists, func
from go_hotel.autonomy.durable import digest, db_now_ms, insert_once
from go_hotel.db.models import VerticalCapacityBucketRow as Bucket, VerticalCapacityClaimRow as Claim

RAIL_LIMITS = {'SECOND_CLASS':18, 'FIRST_CLASS':8, 'BUSINESS_CLASS':3}


def rail_resource(journey):
    # Conservatively share the whole train/date/class, including overlapping
    # station pairs. Segment reuse needs an actual provider seat map.
    return {'train_no':journey['train_no'].strip().upper(), 'travel_date':journey['travel_date'],
            'seat_class':journey['seat_class']}


def attraction_resource(product_id,visit_date,session_time):
    return {'product_id':product_id, 'visit_date':visit_date, 'session_time':session_time}


def _bucket(s,vertical,resource,limit):
    if vertical not in {'RAIL','ATTRACTION'} or type(limit) is not int or limit < 0:
        raise ValueError('CAPACITY_TERMS_INVALID')
    key=digest({'vertical':vertical,'resource':resource})
    insert_once(s,Bucket,{'bucket_id':key,'vertical':vertical,'resource_json':resource,
                        'capacity':limit,'allocated':0},['bucket_id'])
    row=s.get(Bucket,key,with_for_update=True)
    if row.vertical!=vertical or row.resource_json!=resource:
        raise ValueError('CAPACITY_IDENTITY_INVALID')
    # Catalog capacity is the authoritative simulator ceiling, not a new
    # allotment on every search. Changes cannot undercut existing allocations.
    if row.capacity!=limit:
        if row.allocated>limit:raise ValueError('CAPACITY_RECONCILIATION_REQUIRED')
        row.capacity=limit
    _reject_untracked_orders(s,vertical,resource)
    return row


def _reject_untracked_orders(s,vertical,resource):
    # Deployment must reconcile existing orders explicitly. Starting a new
    # counter at zero must never make already-sold legacy seats appear free.
    from go_hotel.db.models import RailOrderRow, AttractionOrderRow
    model=RailOrderRow if vertical=='RAIL' else AttractionOrderRow
    tracked=exists(select(Claim.order_id).where(Claim.vertical==vertical,
        Claim.order_id==model.order_id,Claim.state=='ALLOCATED'))
    query=select(model.order_id).where(model.status.notin_(['CANCELLED','REFUNDED','FAILED','CLOSED_BY_SUPPLIER']),~tracked)
    if vertical=='RAIL':
        query=query.where(func.upper(model.current_journey['train_no'].as_string())==resource['train_no'],
            model.current_journey['travel_date'].as_string()==resource['travel_date'],
            model.current_journey['seat_class'].as_string()==resource['seat_class'])
    else:
        query=query.where(model.product_id==resource['product_id'],model.visit_date==resource['visit_date'],
                          model.session_time==resource['session_time'])
    if s.scalar(query.limit(1)):
        raise ValueError('CAPACITY_LEGACY_ORDER_REVIEW_REQUIRED')


def available_in(s,vertical,resource,limit):
    row=_bucket(s,vertical,resource,limit)
    return row.capacity-row.allocated


def reserve_in(s,vertical,order_id,slot,resource,limit,quantity):
    if type(quantity) is not int or quantity<=0:raise ValueError('CAPACITY_QUANTITY_INVALID')
    row=_bucket(s,vertical,resource,limit)
    claim=s.get(Claim,(vertical,order_id,slot),with_for_update=True)
    if claim:
        if claim.bucket_id!=row.bucket_id or claim.quantity!=quantity or claim.state!='ALLOCATED':
            raise ValueError('CAPACITY_CLAIM_CONFLICT')
        return claim
    if row.capacity-row.allocated<quantity:raise ValueError(vertical+'_INVENTORY_CHANGED')
    row.allocated+=quantity
    claim=Claim(vertical=vertical,order_id=order_id,slot=slot,bucket_id=row.bucket_id,quantity=quantity,
                state='ALLOCATED',created_ms=db_now_ms(s),released_ms=None)
    s.add(claim);s.flush()
    return claim


def release_in(s,vertical,order_id,slot):
    # All callers already hold the order lock. Acquire bucket before claim so
    # reservation/release follow the same cross-order lock order.
    old=s.get(Claim,(vertical,order_id,slot))
    if not old:return False  # Never invent a capacity reservation for legacy orders.
    row=s.get(Bucket,old.bucket_id,with_for_update=True)
    claim=s.get(Claim,(vertical,order_id,slot),with_for_update=True,populate_existing=True)
    if claim.state=='RELEASED':return False
    if row.allocated<claim.quantity:raise ValueError('CAPACITY_LEDGER_INVALID')
    row.allocated-=claim.quantity;claim.state='RELEASED';claim.released_ms=db_now_ms(s)
    s.flush();return True


def release_all_in(s,vertical,order_id):
    # Canonical bucket lock order avoids deadlock when swaps release two pools.
    claims=list(s.scalars(select(Claim).where(Claim.vertical==vertical,Claim.order_id==order_id,
                     Claim.state=='ALLOCATED').order_by(Claim.bucket_id,Claim.slot)))
    for claim in claims:release_in(s,vertical,order_id,claim.slot)


def prepare_change_in(s,vertical,order_id,quote_id,resource,limit,quantity):
    active=list(s.scalars(select(Claim).where(Claim.vertical==vertical,Claim.order_id==order_id,
                     Claim.state=='ALLOCATED',Claim.slot!=quote_id)))
    if len(active)!=1:raise ValueError('CAPACITY_LEGACY_ORDER_REVIEW_REQUIRED')
    key=digest({'vertical':vertical,'resource':resource})
    # A same-session amendment keeps its existing seats; do not double reserve.
    if active[0].bucket_id==key:
        if active[0].quantity!=quantity:raise ValueError('CAPACITY_PARTY_INVALID')
        return
    reserve_in(s,vertical,order_id,quote_id,resource,limit,quantity)


def complete_change_in(s,vertical,order_id,quote_id,succeeded):
    target=s.get(Claim,(vertical,order_id,quote_id))
    if not target:return  # Same-session change or pre-capacity historical order.
    if not succeeded:
        release_in(s,vertical,order_id,quote_id);return
    claims=list(s.scalars(select(Claim).where(Claim.vertical==vertical,Claim.order_id==order_id,
                     Claim.state=='ALLOCATED',Claim.slot!=quote_id).order_by(Claim.bucket_id,Claim.slot)))
    for claim in claims:release_in(s,vertical,order_id,claim.slot)


def cancel_unpaid(vertical,account,order_id,output):
    from go_hotel.db.models import RailOrderRow, AttractionOrderRow, OmnichannelPaymentIntentRow
    from go_hotel.db.session import SessionLocal
    from go_hotel.autonomy.durable import transaction
    from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence
    from go_hotel.services.vertical_lifecycle_projection import project_vertical_lifecycle
    models={'RAIL':RailOrderRow,'ATTRACTION':AttractionOrderRow}
    if vertical not in models:raise ValueError('CAPACITY_VERTICAL_INVALID')
    with transaction(SessionLocal) as s:
        o=s.get(models[vertical],order_id,with_for_update=True)
        if not o or o.account_id!=account:raise ValueError(vertical+'_ORDER_NOT_FOUND')
        if o.status=='CANCELLED':return output(o)
        if o.status!='PAYMENT_PENDING':raise ValueError('UNPAID_CANCELLATION_NOT_ALLOWED')
        if s.scalar(select(OmnichannelPaymentIntentRow.payment_intent_id).where(
                OmnichannelPaymentIntentRow.business_type==vertical+'_ORDER',
                OmnichannelPaymentIntentRow.business_id==order_id)):
            raise ValueError('PAYMENT_ALREADY_STARTED_RECONCILIATION_REQUIRED')
        from go_hotel.services.vertical_reservation_expiry import cancelled_in
        cancelled_in(s,vertical,o)
        release_all_in(s,vertical,order_id)
        from datetime import datetime,UTC
        o.status='CANCELLED';o.updated_at=datetime.now(UTC).replace(tzinfo=None)
        evidence='unpaid-cancel://'+order_id
        append_vertical_evidence(s,vertical,order_id,'UNPAID_ORDER_CANCELLED',o.status,{'account_id':account})
        project_vertical_lifecycle(s,vertical,o,evidence,facts={'unpaid':True,'capacity_released':True})
        return output(o)
