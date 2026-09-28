"""Durable per-passenger flight coupons, priced only from accepted server fares.

The native order is the serialization lock. Historical orders without an exact
allocation remain readable but require review before using partial operations.
"""
from copy import deepcopy
from sqlalchemy import select
from sqlalchemy.orm import object_session
from go_hotel.db.models import FlightCouponRow as Coupon, FlightChangeQuoteRow, FlightChangePlanRow, FlightCouponRefundRow
from go_hotel.domain.models import new_id


def rows(s, order):
    return list(s.scalars(select(Coupon).where(Coupon.order_id == order.order_id)
        .order_by(Coupon.leg_index, Coupon.passenger_index)))


def snapshot(c):
    return {k: deepcopy(getattr(c,k)) for k in ('coupon_id','account_id','order_id','leg_index',
        'passenger_index','state','version','ticket_number','supplier_reference','currency',
        'paid_amount_minor','refunded_amount_minor','leg_json','change_policy','refund_policy')}


def ledger(s, order):
    items=rows(s,order)
    if (len(items)!=len(order.passengers)*len(order.current_itinerary) or not items
            or any(c.account_id!=order.account_id or c.currency!=order.currency for c in items)
            or sum(c.paid_amount_minor for c in items)!=order.total_amount_minor):
        raise ValueError('FLIGHT_COUPON_ALLOCATION_REVIEW_REQUIRED')
    return items


def create_in(s, order, offer):
    count=len(order.passengers)
    pending=[]
    for li, leg in enumerate(order.current_itinerary):
        amount=leg.get('unit_total_amount_minor')
        if type(amount) is not int or amount<0:raise ValueError('FLIGHT_COUPON_ALLOCATION_INVALID')
        policies=[]
        for kind in ('change_policy','refund_policy'):
            policy=deepcopy(leg.get(kind,getattr(offer,kind) if len(order.current_itinerary)==1 else {}))
            fee=policy.get('fee_minor',0)
            if type(fee) is not int or fee<0 or fee%count:raise ValueError('FLIGHT_COUPON_POLICY_ALLOCATION_INVALID')
            policies.append({**policy,'fee_minor':fee//count,'price_basis':'PER_COUPON'})
        for pi in range(count):
            pending.append(Coupon(coupon_id=new_id('flt_cpn'),order_id=order.order_id,account_id=order.account_id,
                leg_index=li,passenger_index=pi,state='UNISSUED',version=0,ticket_number=None,
                supplier_reference=None,currency=order.currency,paid_amount_minor=amount,refunded_amount_minor=0,
                leg_json=deepcopy(leg),change_policy=policies[0],refund_policy=policies[1]))
    if sum(c.paid_amount_minor for c in pending)!=order.total_amount_minor:
        raise ValueError('FLIGHT_COUPON_ALLOCATION_INVALID')
    s.add_all(pending);s.flush()


def issue_in(s, order):
    items=rows(s,order)
    if not items:return  # No invented allocation for pre-migration historical rows.
    ledger(s,order)
    if len(order.ticket_numbers)!=len(items):raise ValueError('FLIGHT_COUPON_TICKET_INVALID')
    for c,ticket in zip(items,order.ticket_numbers):
        if c.state!='UNISSUED':raise ValueError('FLIGHT_COUPON_ALREADY_ISSUED')
        c.state='ISSUED';c.ticket_number=ticket;c.supplier_reference=order.pnr;c.version+=1


def selected(items, ids, *, leg_index=None):
    if (not isinstance(ids,list) or not ids or any(not isinstance(x,str) for x in ids)
            or len(set(ids))!=len(ids)):
        raise ValueError('FLIGHT_COUPON_SELECTION_INVALID')
    found=[c for c in items if c.coupon_id in ids]
    if len(found)!=len(ids) or any(c.state!='ISSUED' or (leg_index is not None and c.leg_index!=leg_index) for c in found):
        raise ValueError('FLIGHT_COUPON_SELECTION_INVALID')
    return found


def public_in(s, order):
    items=rows(s,order)
    pending=set()
    if order.status=='UNKNOWN_EXTERNAL_STATE':
        for q in s.scalars(select(FlightChangeQuoteRow).where(FlightChangeQuoteRow.order_id==order.order_id,
                FlightChangeQuoteRow.status.in_(['AUTHORIZATION_PENDING','PENDING_SUPPLIER']))):
            p=s.get(FlightChangePlanRow,q.quote_id)
            if p:
                pending.update(i for change in p.plan_json['changes'] for i in change.get('coupon_ids',[]))
    scoped_refund = order.status == 'REFUND_PENDING' and any(
        r.state == 'PREPARED' for r in s.scalars(select(FlightCouponRefundRow).where(
            FlightCouponRefundRow.order_id == order.order_id)))
    available = order.status == 'TICKETED' or bool(pending) or scoped_refund
    def display_state(c):
        if c.coupon_id in pending:
            return 'CHANGE_PENDING'
        if c.state == 'ISSUED' and not available:
            return 'REFUND_PENDING' if order.status == 'REFUND_PENDING' else order.status
        return c.state
    return [{**snapshot(c), 'state': display_state(c),
        'passenger_name': order.passengers[c.passenger_index]['full_name'],
        'leg': deepcopy(c.leg_json),
        'usable': available and c.state == 'ISSUED' and c.coupon_id not in pending} for c in items]



def public(order):
    s=object_session(order)
    return public_in(s,order) if s else []


def refund_all_in(s,order,refund_amount):
    items=rows(s,order)
    if not items:return
    ledger(s,order)
    amounts=[max(0,c.paid_amount_minor-c.refund_policy.get('fee_minor',0)) for c in items]
    if any(c.state!='ISSUED' for c in items) or sum(amounts)!=refund_amount:
        raise ValueError('FLIGHT_COUPON_REFUND_ALLOCATION_INVALID')
    for c,amount in zip(items,amounts):
        c.state='REFUNDED';c.refunded_amount_minor=amount;c.version+=1
