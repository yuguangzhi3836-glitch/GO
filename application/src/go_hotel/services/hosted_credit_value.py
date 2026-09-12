"""Property-only prepaid credit and its append-only value subledger.

The subledger allocates an existing cash capture; it never fabricates another
cash capture or a GO wallet balance.
"""
from datetime import timedelta
from sqlalchemy import select
from go_hotel.db.models import (
    HostedStayCreditRow as Credit,HostedCreditAllocationRow as Allocation,
    HostedCreditValueEventRow as Event,HostedCreditRefundPlanRow as Plan,
    HostedDirectReservationRow as Reservation,HostedReservationStayRow as Stay,
    HostedDirectRoomOfferRow as Offer,OmnichannelMoneyMovementRow as Movement,
    OmnichannelPaymentIntentRow as Intent,RefundEligibilityRow as Refund)
from go_hotel.services.hosted_direct_booking import ident,out
from go_hotel.services.hosted_reservation_operations import aware
from go_hotel.services.omnichannel_payment import digest

TERMS={'validity_basis':'CHECK_IN_BY_EXPIRY','unused_value_on_cancellation':'RESTORE_SAME_CREDIT',
    'unused_value_on_partial_fulfillment':'RESTORE_SAME_CREDIT','cash_refund_policy':'INDEPENDENT_DISPUTE_ONLY','unused_credit_refund_deadline':'BEFORE_ORIGINAL_EXPIRY'}


def now():
    from go_hotel.services.hosted_fare_rules import now as clock
    return clock()


def terms(snapshot):
    if not snapshot.rules_json.get('stay_credit_enabled'):raise ValueError('STAY_CREDIT_NOT_ENABLED')
    if snapshot.rules_json.get('credit_terms')!=TERMS:raise ValueError('COMPLETE_ORDER_CREDIT_TERMS_REQUIRED')
    return TERMS.copy()


def lock_sources(s,rid):
    allocation=s.get(Allocation,rid)
    credit=s.get(Credit,allocation.credit_id) if allocation else s.scalar(select(Credit).where(Credit.original_reservation_id==rid))
    if credit:
        s.get(Stay,credit.original_reservation_id,with_for_update=True)
        s.get(Reservation,credit.original_reservation_id,with_for_update=True)
        return s.get(Credit,credit.credit_id,with_for_update=True,populate_existing=True)
    return None


def checked(s,cid,account=None):
    probe=s.get(Credit,cid)
    if not probe or account is not None and probe.account_id!=account:raise ValueError('STAY_CREDIT_NOT_FOUND')
    s.get(Stay,probe.original_reservation_id,with_for_update=True)
    s.get(Reservation,probe.original_reservation_id,with_for_update=True)
    c=s.get(Credit,cid,with_for_update=True,populate_existing=True)
    capture=s.get(Movement,c.source_capture_id)
    intent=s.get(Intent,capture.root_payment_intent_id) if capture else None
    if not capture or capture.movement_type!='CAPTURE' or capture.state!='CONFIRMED' or not intent or (intent.payer_id,intent.payee_id,intent.currency)!=(c.account_id,c.hosted_hotel_id,c.currency) or capture.amount_minor!=c.issued_minor:
        raise ValueError('STAY_CREDIT_FUNDING_FACT_MISMATCH')
    from go_hotel.db.models import AlipayAuthorizationRow
    from go_hotel.services import hosted_money
    source_authorization=s.scalar(select(AlipayAuthorizationRow).where(AlipayAuthorizationRow.hosted_reservation_id==c.original_reservation_id))
    if not source_authorization:raise ValueError('STAY_CREDIT_SOURCE_AUTHORIZATION_REQUIRED')
    hosted_money.require_known(s,source_authorization)
    events=list(s.scalars(select(Event).where(Event.credit_id==cid).order_by(Event.generation)))
    previous=None;balance=0
    for number,e in enumerate(events,1):
        balance+=e.delta_minor
        payload=[cid,number,e.event_type,e.delta_minor,balance,e.reservation_id,e.evidence_json,e.actor_id,previous]
        if e.generation!=number or e.previous_hash!=previous or e.event_hash!=digest(payload) or e.balance_after_minor!=balance or not 0<=balance<=c.issued_minor:
            raise ValueError('STAY_CREDIT_VALUE_LEDGER_MISMATCH')
        previous=e.event_hash
    if c.available_minor!=balance or c.ledger_head_hash!=previous:raise ValueError('STAY_CREDIT_VALUE_LEDGER_MISMATCH')
    spent=sum(x.amount_minor for x in s.scalars(select(Movement).where(Movement.parent_movement_id==c.source_capture_id,Movement.movement_type.in_(['REFUND','COMPENSATION']),Movement.state=='CONFIRMED')))
    if c.available_minor>c.issued_minor-spent:raise ValueError('STAY_CREDIT_EXCEEDS_REMAINING_SOURCE_FUNDS')
    assigned=forfeited=credited_refunds=0
    for a in s.scalars(select(Allocation).where(Allocation.credit_id==cid)):
        own=[e for e in events if e.reservation_id==a.hosted_reservation_id]
        debited=-sum(e.delta_minor for e in own if e.event_type=='ALLOCATED')
        lost=-sum(e.delta_minor for e in own if e.event_type=='LOWER_PRICE_FORFEITED')
        restored=sum(e.delta_minor for e in own if e.event_type in {'UNUSED_VALUE_RESTORED','UNUSED_FULFILLMENT_RESTORED'})
        retained=prepaid(s,a.hosted_reservation_id)
        if (debited,lost,restored)!=(a.applied_minor,a.forfeited_minor,a.restored_minor) or min(a.applied_minor,a.forfeited_minor,a.restored_minor,a.fulfilled_minor,a.fee_consumed_minor)<0 or retained+a.restored_minor!=a.applied_minor:
            raise ValueError('STAY_CREDIT_ALLOCATION_LEDGER_MISMATCH')
        if a.state not in {'ACTIVE','SETTLED','CANCELLED','REFUND_RESERVED','REFUNDED'}:raise ValueError('STAY_CREDIT_ALLOCATION_STATE_INVALID')
        assigned+=retained;forfeited+=a.forfeited_minor
        for p in s.scalars(select(Plan).where(Plan.hosted_reservation_id==a.hosted_reservation_id)):
            if digest(p.plan_json)!=p.plan_hash:raise ValueError('CREDIT_REFUND_PLAN_MISMATCH')
            e=s.get(Refund,p.refund_eligibility_id)
            if e and e.decision=='REFUND_CONFIRMED_SIMULATION':credited_refunds+=sum(x['amount_minor'] for x in p.plan_json if x['kind']=='CREDIT' and x['credit_id']==cid)
    expired=-sum(e.delta_minor for e in events if e.event_type=='EXPIRED')
    if c.available_minor+assigned-credited_refunds+forfeited+expired+spent!=c.issued_minor:
        raise ValueError('STAY_CREDIT_SOURCE_VALUE_CONSERVATION_FAILED')
    return c


def event(s,c,kind,delta,rid,evidence,actor):
    if type(delta) is not int or not evidence:raise ValueError('CREDIT_VALUE_EVENT_EVIDENCE_REQUIRED')
    previous=s.scalar(select(Event).where(Event.credit_id==c.credit_id).order_by(Event.generation.desc()))
    number=previous.generation+1 if previous else 1;balance=c.available_minor+delta
    if not 0<=balance<=c.issued_minor:raise ValueError('CREDIT_VALUE_BUDGET_EXCEEDED')
    prior=previous.event_hash if previous else None
    if prior!=c.ledger_head_hash:raise ValueError('STAY_CREDIT_VALUE_LEDGER_MISMATCH')
    hash_value=digest([c.credit_id,number,kind,delta,balance,rid,evidence,actor,prior])
    row=Event(event_id=ident('hcve'),credit_id=c.credit_id,generation=number,event_type=kind,
        delta_minor=delta,balance_after_minor=balance,reservation_id=rid,evidence_json=evidence,
        previous_hash=prior,event_hash=hash_value,actor_id=actor,created_at=now())
    s.add(row);c.available_minor=balance;c.ledger_head_hash=hash_value;c.updated_at=now();s.flush();return row


def active(c):
    if aware(c.expires_at)<=now():raise ValueError('STAY_CREDIT_EXPIRED')
    if c.state!='ACTIVE' or c.available_minor<=0:raise ValueError('STAY_CREDIT_NOT_AVAILABLE')


def public(c):
    state='EXPIRED' if c.state=='ACTIVE' and aware(c.expires_at)<=now() else c.state
    return {'credit_id':c.credit_id,'original_reservation_id':c.original_reservation_id,
        'hosted_hotel_id':c.hosted_hotel_id,'issued_minor':c.issued_minor,
        'available_minor':0 if state=='EXPIRED' else c.available_minor,'currency':c.currency,'state':state,
        'scope':'PROPERTY_ONLY','expires_at':aware(c.expires_at).isoformat(),'data_mode':'SIMULATION','external_live':False}


def allocation(s,rid):return s.get(Allocation,rid)


def prepaid(s,rid):
    a=allocation(s,rid)
    return a.applied_minor if a and a.state in {'ACTIVE','REFUND_RESERVED','REFUNDED'} else a.fulfilled_minor if a and a.state=='SETTLED' else a.fee_consumed_minor if a else 0


def summary(s,rid):
    a=allocation(s,rid)
    source=s.scalar(select(Credit).where(Credit.original_reservation_id==rid))
    return {'issued_credit':public(source) if source else None,
        'applied_credit':{'credit_id':a.credit_id,'applied_minor':a.applied_minor,'forfeited_minor':a.forfeited_minor,
            'fulfilled_minor':a.fulfilled_minor,'fee_consumed_minor':a.fee_consumed_minor,'restored_minor':a.restored_minor,'state':a.state,
            'expires_at':aware(s.get(Credit,a.credit_id).expires_at).isoformat()} if a else None,
        'prepaid_minor':prepaid(s,rid)}


def refund_basis(s,r,cash_captured):
    c=s.scalar(select(Credit).where(Credit.original_reservation_id==r.hosted_reservation_id))
    if c:return c.available_minor if c.state=='ACTIVE' and aware(c.expires_at)>now() else 0
    return cash_captured+prepaid(s,r.hosted_reservation_id)


def return_unused(s,r,fee,actor,reference):
    a=allocation(s,r.hosted_reservation_id)
    if not a:return {'prepaid_fee_minor':0,'restored_credit_minor':0,'expired_credit_minor':0}
    if a.state not in {'ACTIVE','SETTLED'}:raise ValueError('CREDIT_ALLOCATION_ALREADY_CLOSED')
    c=checked(s,a.credit_id);consumed=min(fee,a.applied_minor);remaining=a.applied_minor-consumed
    a.fee_consumed_minor=consumed;a.restored_minor=remaining;a.state='CANCELLED'
    if consumed:event(s,c,'FARE_FEE_CONSUMED',0,r.hosted_reservation_id,[reference,{'fee_minor':consumed}],actor)
    if remaining:event(s,c,'UNUSED_VALUE_RESTORED',remaining,r.hosted_reservation_id,[reference],actor)
    expired=0
    if aware(c.expires_at)<=now():
        expired=c.available_minor
        if expired:event(s,c,'EXPIRED',-expired,None,[reference],actor)
        c.state='EXPIRED'
    elif c.state!='FROZEN_REFUND':c.state='ACTIVE' if c.available_minor else 'ALLOCATED'
    return {'prepaid_fee_minor':consumed,'restored_credit_minor':remaining if not expired else 0,'expired_credit_minor':expired}


def settle_allocation(s,r,fulfilled,actor,evidence):
    a=allocation(s,r.hosted_reservation_id)
    if not a:return
    if a.state=='SETTLED':return
    if a.state!='ACTIVE':raise ValueError('CREDIT_ALLOCATION_ALREADY_CLOSED')
    c=checked(s,a.credit_id);consumed=min(fulfilled,a.applied_minor);remaining=a.applied_minor-consumed
    a.fulfilled_minor=consumed;a.restored_minor=remaining;a.state='SETTLED'
    event(s,c,'FULFILLMENT_CONSUMED',0,r.hosted_reservation_id,[*evidence,{'fulfilled_minor':consumed}],actor)
    if remaining:event(s,c,'UNUSED_FULFILLMENT_RESTORED',remaining,r.hosted_reservation_id,evidence,actor)
    if aware(c.expires_at)<=now():
        if c.available_minor:event(s,c,'EXPIRED',-c.available_minor,None,evidence,actor)
        c.state='EXPIRED'
    elif c.state!='FROZEN_REFUND':c.state='ACTIVE' if c.available_minor else 'ALLOCATED'


def reconciliation_required(s,rid):
    a=allocation(s,rid)
    c=s.get(Credit,a.credit_id) if a else s.scalar(select(Credit).where(Credit.original_reservation_id==rid))
    if not c:return False
    try:checked(s,c.credit_id)
    except ValueError:return True
    return False
