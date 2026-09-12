"""Owner-locked rental quotes and recoverable settlement for isolated acceptance."""
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from sqlalchemy import select, text
from go_hotel.core.config import settings
from go_hotel.db.models import MobilityRentalOrderRow as Order, RentalChangeQuoteRow as Quote
from go_hotel.db.session import SessionLocal
from go_hotel.domain.models import new_id
from go_hotel.services.omnichannel_payment import digest, out
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence
from go_hotel.services.vertical_lifecycle_projection import project_vertical_lifecycle
from go_hotel.services.vertical_money_bridge import vertical_money_bridge as money


def now():
    return datetime.now(UTC).replace(tzinfo=None)


def isolated():
    if settings.app_env.lower() not in {'local','test','demo'}:
        raise ValueError('SIMULATED_RENTAL_SETTLEMENT_FORBIDDEN')


@contextmanager
def transaction():
    with SessionLocal() as s:
        if s.bind.dialect.name == 'sqlite':
            s.execute(text('BEGIN IMMEDIATE'))
        try:
            yield s
            s.commit()
        except BaseException:
            s.rollback()
            raise


def owned(s, account, order_id):
    order=s.get(Order,order_id,with_for_update=True)
    if not order or order.account_id!=account:
        raise ValueError('MOBILITY_ORDER_NOT_FOUND')
    return order


def revision(order):
    return digest([order.pickup_at,order.return_at,order.total_amount_minor,order.currency,
                   order.vehicle_class,str(order.updated_at)])


def adjustment_ids(s, order_id):
    return list(s.scalars(select(Quote.quote_id).where(Quote.order_id==order_id,
        Quote.status=='EXECUTED',Quote.difference_minor>0).order_by(Quote.created_at,Quote.quote_id)))


def quote(account, order_id, pickup_at, return_at):
    from go_hotel.mobility.rental.service import rental_days
    isolated()
    days=rental_days(pickup_at,return_at)
    with transaction() as s:
        order=owned(s,account,order_id)
        if order.status!='CONFIRMED':raise ValueError('MOBILITY_ORDER_NOT_CHANGEABLE')
        old_days=rental_days(order.pickup_at,order.return_at)
        rate,remainder=divmod(order.total_amount_minor,old_days)
        if remainder or rate<=0:raise ValueError('RENTAL_RATE_RECONCILIATION_REQUIRED')
        total=days*rate
        q=Quote(quote_id=new_id('rent_chq'),order_id=order_id,old_pickup_at=order.pickup_at,
            old_return_at=order.return_at,new_pickup_at=pickup_at,new_return_at=return_at,
            old_amount_minor=order.total_amount_minor,new_amount_minor=total,
            difference_minor=total-order.total_amount_minor,daily_rate_minor=rate,currency=order.currency,
            order_revision=revision(order),status='QUOTED',refund_plan_json=[],
            expires_at=now()+timedelta(minutes=10),created_at=now(),updated_at=now())
        s.add(q);s.flush()
        return {**out(q),'rental_days':days,'change_fee_minor':0,'refund_to':'ORIGINAL_PAYMENT_METHOD',
                'data_mode':'SIMULATION','external_live':False}


def execute(account, order_id, quote_id, expected_difference_minor, currency):
    isolated()
    with transaction() as s:
        order=owned(s,account,order_id)
        q=s.get(Quote,quote_id,with_for_update=True)
        if not q or q.order_id!=order_id:raise ValueError('RENTAL_CHANGE_QUOTE_NOT_FOUND')
        if type(expected_difference_minor) is not int or (q.difference_minor,q.currency)!=(expected_difference_minor,currency):
            raise ValueError('RENTAL_CHANGE_AMOUNT_CHANGED_RECONFIRM_REQUIRED')
        if q.status=='EXECUTED':return {**out(q),'data_mode':'SIMULATION','external_live':False}
        if q.status=='QUOTED':
            if order.status!='CONFIRMED':raise ValueError('MOBILITY_ORDER_NOT_CHANGEABLE')
            if q.expires_at<=now():raise ValueError('RENTAL_CHANGE_QUOTE_EXPIRED')
            if q.order_revision!=revision(order):raise ValueError('RENTAL_CHANGE_QUOTE_STALE')
            if q.difference_minor<0:
                q.refund_plan_json=money.plan_refund('RENTAL',order_id,adjustment_ids(s,order_id),
                    -q.difference_minor,'rental-change-refund:'+quote_id)
            q.status='MONEY_PENDING';order.status='CHANGE_PENDING';order.updated_at=now()
            for other in s.scalars(select(Quote).where(Quote.order_id==order_id,Quote.status=='QUOTED',Quote.quote_id!=quote_id)):
                other.status='SUPERSEDED';other.updated_at=now()
            append_vertical_evidence(s,'RENTAL',order_id,'CHANGE_CONFIRMED_BY_CUSTOMER',order.status,
                {'quote_id':quote_id,'difference_minor':q.difference_minor,'currency':currency,'external_live':False})
            project_vertical_lifecycle(s,'RENTAL',order,'rental-change://'+quote_id)
        elif q.status!='MONEY_PENDING' or order.status!='CHANGE_PENDING':
            raise ValueError('RENTAL_CHANGE_QUOTE_NOT_EXECUTABLE')
        q.updated_at=now();difference=q.difference_minor;plan=q.refund_plan_json
    # Each money component has a durable identity. Keep the order held until all complete.
    evidence='contract-simulator://rental-change/'+quote_id
    if difference>0:
        prepared=money.prepare_adjustment('RENTAL',order_id,quote_id,difference,evidence)
        if prepared['released']:raise ValueError('RENTAL_CHANGE_RELEASED_RECONCILIATION_REQUIRED')
        movement=money.capture_adjustment('RENTAL',quote_id,difference,evidence)
        movement_ids=[movement['capture_id']]
    elif difference<0:
        movement=money.execute_refund_plan(plan,evidence)
        if movement['state']!='CONFIRMED':raise ValueError('RENTAL_REFUND_MONEY_NOT_CONFIRMED')
        movement_ids=movement['money_movement_ids']
    else:movement_ids=[]
    with transaction() as s:
        order=owned(s,account,order_id);q=s.get(Quote,quote_id,with_for_update=True)
        if q.status=='EXECUTED':return {**out(q),'data_mode':'SIMULATION','external_live':False}
        if q.status!='MONEY_PENDING' or order.status!='CHANGE_PENDING':
            raise ValueError('RENTAL_CHANGE_RECONCILIATION_REQUIRED')
        order.pickup_at=q.new_pickup_at;order.return_at=q.new_return_at
        order.total_amount_minor=q.new_amount_minor;order.status='CONFIRMED';order.updated_at=now()
        q.status='EXECUTED';q.updated_at=now()
        append_vertical_evidence(s,'RENTAL',order_id,'CHANGE_EXECUTED',order.status,
            {'quote_id':quote_id,'money_movement_ids':movement_ids,'difference_minor':difference,
             'new_pickup_at':order.pickup_at,'new_return_at':order.return_at,'external_live':False})
        project_vertical_lifecycle(s,'RENTAL',order,evidence)
        return {**out(q),'data_mode':'SIMULATION','external_live':False}
