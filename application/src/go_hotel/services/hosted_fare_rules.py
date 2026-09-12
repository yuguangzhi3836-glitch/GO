"""Supplier-selected hotel fare snapshots and atomic isolated fee settlement.

No default commercial fee is inferred from a fare name or an old free-text offer.
All amounts come from a published snapshot, never from a customer's request.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlalchemy import select
from go_hotel.db.models import (
    HostedFareRuleVersionRow as Rule, HostedOrderFareSnapshotRow as Snapshot,
    HostedFareQuoteRow as Quote, HostedDirectRoomOfferRow as Offer,
    HostedDirectReservationRow as Reservation, HostedReservationStayRow as Stay,
    GuestStayLifecycleRow as Guest, AlipayAuthorizationRow as Authorization,
    AlipayAdjustmentApprovalRow as Approval, StayDisputeRow as Dispute)
from go_hotel.services.hosted_direct_booking import ident, now, out
from go_hotel.services.hosted_reservation_operations import aware, hosted_reservation_operations_service as ops
from go_hotel.services.alipay_safeguarded_settlement import transaction
from go_hotel.services import hosted_money as funds
from go_hotel.services.unified_money_movement import unified_money_movement_service as money
from go_hotel.services.omnichannel_payment import digest
from go_hotel.services import hotel_change_policy


def integer(value, low, high, error):
    if type(value) is not int or not low <= value <= high:raise ValueError(error)
    return value


def validated(body):
    required={'fare_family','timezone','check_in_hour','cooling_off_minutes','cancellation_tiers',
        'change_allowed','change_fee_minor','stay_credit_enabled','stay_credit_days','stay_credit_scope',
        'no_show_grace_hours','no_show_fee_basis_points'}
    if not required<=set(body) or set(body)-required-{'credit_terms'}:raise ValueError('COMPLETE_STRUCTURED_FARE_RULE_REQUIRED')
    if not isinstance(body['fare_family'],str) or not 1<=len(body['fare_family'])<=64:raise ValueError('FARE_FAMILY_REQUIRED')
    try:ZoneInfo(body['timezone'])
    except (ZoneInfoNotFoundError,TypeError,ValueError):raise ValueError('VALID_HOTEL_TIMEZONE_REQUIRED')
    for field,high in [('check_in_hour',23),('cooling_off_minutes',10080),('change_fee_minor',100000000),
        ('no_show_grace_hours',48),('no_show_fee_basis_points',10000)]:integer(body[field],0,high,'INVALID_'+field.upper())
    integer(body['stay_credit_days'],1,365,'STAY_CREDIT_MAXIMUM_365_DAYS')
    if body['stay_credit_scope']!='PROPERTY_ONLY':raise ValueError('STAY_CREDIT_PROPERTY_ONLY')
    if any(type(body[x]) is not bool for x in ['change_allowed','stay_credit_enabled']):raise ValueError('BOOLEAN_FARE_PARTICIPATION_REQUIRED')
    tiers=body['cancellation_tiers']
    if not isinstance(tiers,list) or not 1<=len(tiers)<=20:raise ValueError('CANCELLATION_TIERS_REQUIRED')
    thresholds=[];fees=[]
    for tier in tiers:
        if not isinstance(tier,dict) or set(tier)!={'min_hours','fee_basis_points'}:raise ValueError('STRUCTURED_CANCELLATION_TIER_REQUIRED')
        thresholds.append(integer(tier['min_hours'],0,8760,'INVALID_CANCELLATION_THRESHOLD'))
        fees.append(integer(tier['fee_basis_points'],0,10000,'INVALID_CANCELLATION_FEE'))
    if thresholds!=sorted(set(thresholds),reverse=True) or thresholds[-1]!=0 or fees!=sorted(fees):
        raise ValueError('ORDERED_COMPLETE_CANCELLATION_TIERS_REQUIRED')
    if 'credit_terms' in body:
        from go_hotel.services.hosted_credit_value import TERMS
        if body['credit_terms']!=TERMS:raise ValueError('VALID_STRUCTURED_CREDIT_TERMS_REQUIRED')
    return deepcopy(body)


def publish(offer_id,body,authority,actor):
    rules=validated(body)
    hotel_change_policy.require_zero_fee(rules)
    if not isinstance(authority,str) or not 1<=len(authority.strip())<=512:raise ValueError('HOTEL_RULE_AUTHORITY_REFERENCE_REQUIRED')
    with transaction() as s:
        if not s.get(Offer,offer_id,with_for_update=True):raise ValueError('HOSTED_OFFER_NOT_FOUND')
        old=s.scalar(select(Rule).where(Rule.hosted_offer_id==offer_id).order_by(Rule.version.desc()))
        rule_hash=digest(rules)
        if old and old.rule_hash==rule_hash and old.authority_reference==authority.strip():return out(old)
        row=Rule(rule_version_id=ident('hfr'),hosted_offer_id=offer_id,version=old.version+1 if old else 1,
            rules_json=rules,rule_hash=rule_hash,authority_reference=authority.strip(),published_by=actor,created_at=now())
        s.add(row);s.flush();return out(row)


def snapshot_in_session(s,r):
    """Called once by reserve; an unconfigured historic order stays unconfigured."""
    if s.get(Snapshot,r.hosted_reservation_id):return
    rule=s.scalar(select(Rule).where(Rule.hosted_offer_id==r.hosted_offer_id).order_by(Rule.version.desc()))
    if rule:
        s.add(Snapshot(hosted_reservation_id=r.hosted_reservation_id,rule_version_id=rule.rule_version_id,
            rules_json=deepcopy(rule.rules_json),rule_hash=rule.rule_hash,created_at=now()))


def locked(s,rid,account=None):
    from go_hotel.services.hosted_credit_value import lock_sources
    lock_sources(s,rid)
    stay=s.get(Stay,rid,with_for_update=True);r=s.get(Reservation,rid,with_for_update=True)
    if not stay or not r or account is not None and stay.created_by!=account:raise ValueError('RESERVATION_NOT_FOUND')
    guest=s.scalar(select(Guest).where(Guest.hosted_reservation_id==rid).with_for_update())
    a=s.scalar(select(Authorization).where(Authorization.hosted_reservation_id==rid).with_for_update())
    return r,stay,guest,a


def snapshot(s,r):
    row=s.get(Snapshot,r.hosted_reservation_id)
    if not row:raise ValueError('ORDER_FARE_SNAPSHOT_REQUIRED')
    if digest(row.rules_json)!=row.rule_hash:raise ValueError('ORDER_FARE_SNAPSHOT_HASH_MISMATCH')
    source=s.get(Rule,row.rule_version_id)
    if not source or source.hosted_offer_id!=r.hosted_offer_id or source.rule_hash!=row.rule_hash or digest(source.rules_json)!=source.rule_hash:
        raise ValueError('ORDER_FARE_SOURCE_MISMATCH')
    return row


def check_in_at(r,rules):
    return datetime.fromisoformat(r.check_in).replace(hour=rules['check_in_hour'],tzinfo=ZoneInfo(rules['timezone'])).astimezone(timezone.utc)


def revision(s,r,stay,guest,a,snap):
    return digest({'reservation':r.hosted_reservation_id,'dates':[r.check_in,r.check_out],
        'amount':r.amount_minor,'currency':r.currency,'state':stay.operational_state,
        'guest':guest.state if guest else None,'rules':snap.rule_hash,
        'authorization':out(a) if a else None,'funds':funds.summary(s,r)})


def eligible(s,r,stay,guest,a,action,snap):
    funds.require_isolated()
    if stay.operational_state!='CONFIRMED':raise ValueError('CONFIRMED_RESERVATION_REQUIRED')
    if guest and guest.state!='PRE_ARRIVAL':raise ValueError('FARE_ACTION_REQUIRES_PRE_ARRIVAL')
    if guest and s.scalar(select(Dispute).where(Dispute.stay_lifecycle_id==guest.stay_lifecycle_id,Dispute.state=='OPEN_SETTLEMENT_FROZEN')):
        raise ValueError('OPEN_FULFILLMENT_DISPUTE')
    if not a or not funds.root(s,a) or a.state!='CONTRACT_FROZEN_NOT_ALIPAY':raise ValueError('KNOWN_FROZEN_FARE_AUTHORIZATION_REQUIRED')
    funds.require_known(s,a)
    summary=funds.summary(s,r)
    if summary['held_minor']+summary.get('prepaid_credit_minor',0)!=r.amount_minor or summary['capture_minor'] or summary['refund_minor']:
        raise ValueError('UNSPENT_FARE_AUTHORIZATION_REQUIRED')
    boundary=check_in_at(r,snap.rules_json)
    deadline=boundary+timedelta(hours=snap.rules_json['no_show_grace_hours'])
    if action=='CANCEL_FOR_REFUND' and now()>=deadline:raise ValueError('CANCELLATION_WINDOW_CLOSED')
    if action=='NO_SHOW' and (not guest or now()<deadline):raise ValueError('NO_SHOW_DEADLINE_NOT_REACHED')
    return boundary,deadline


def calculate(s,r,stay,guest,a,snap,action):
    boundary,deadline=eligible(s,r,stay,guest,a,action,snap)
    rules=snap.rules_json;t=now();cooling_end=aware(r.created_at)+timedelta(minutes=rules['cooling_off_minutes'])
    if action=='NO_SHOW':fee_bps=rules['no_show_fee_basis_points'];cooling=False
    else:
        cooling=t<cooling_end and t<boundary
        hours=max(0,(boundary-t).total_seconds()/3600)
        fee_bps=0 if cooling else next(x['fee_basis_points'] for x in rules['cancellation_tiers'] if hours>=x['min_hours'])
    # Integer floor is explicit in every persisted quote; no floating-point money.
    fee=r.amount_minor*fee_bps//10000
    expiry=min(t+timedelta(minutes=10),deadline) if action=='CANCEL_FOR_REFUND' else t+timedelta(minutes=10)
    if cooling:expiry=min(expiry,cooling_end,boundary)
    if action=='CANCEL_FOR_REFUND':
        for tier in rules['cancellation_tiers']:
            edge=boundary-timedelta(hours=tier['min_hours'])
            if edge>t:expiry=min(expiry,edge)
    from go_hotel.services.hosted_credit_value import prepaid,allocation,Credit
    credit_paid=prepaid(s,r.hosted_reservation_id);prepaid_fee=min(fee,credit_paid)
    allocated=allocation(s,r.hosted_reservation_id)
    credit=s.get(Credit,allocated.credit_id) if allocated else None
    restored_credit=credit_paid-prepaid_fee
    if credit and restored_credit and aware(credit.expires_at)>t:expiry=min(expiry,aware(credit.expires_at))
    return {'action':action,'reservation_id':r.hosted_reservation_id,'rule_version_id':snap.rule_version_id,
        'rule_hash':snap.rule_hash,'currency':r.currency,'order_amount_minor':r.amount_minor,
        'cancellation_fee_minor':fee if action=='CANCEL_FOR_REFUND' else 0,
        'no_show_fee_minor':fee if action=='NO_SHOW' else 0,'fee_minor':fee,'fee_basis_points':fee_bps,
        'rounding':'FLOOR_MINOR_UNIT','cash_refund_minor':0,'authorization_release_minor':r.amount_minor-credit_paid-(fee-prepaid_fee),
        'prepaid_fee_minor':prepaid_fee,'cash_fee_minor':fee-prepaid_fee,
        'restored_credit_minor':restored_credit if credit and aware(credit.expires_at)>t else 0,
        'expired_credit_minor':restored_credit if credit and aware(credit.expires_at)<=t else 0,
        'original_credit_expires_at':aware(credit.expires_at).isoformat() if credit else None,
        'change_fee_minor':0,'fare_difference_minor':0,'retained_value_minor':0,'stay_credit_expires_at':None,
        'cooling_off_applied':cooling,'no_show_deadline':deadline.isoformat(),'expires_at':expiry.isoformat(),
        'data_mode':'SIMULATION','external_live':False}


def create_quote(rid,action,account=None):
    if action not in {'CANCEL_FOR_REFUND','NO_SHOW'}:raise ValueError('UNSUPPORTED_FARE_ACTION')
    with transaction() as s:
        r,stay,guest,a=locked(s,rid,account);snap=snapshot(s,r)
        payload=calculate(s,r,stay,guest,a,snap,action)
        row=Quote(quote_id=ident('hfq'),hosted_reservation_id=rid,action=action,
            order_revision=revision(s,r,stay,guest,a,snap),quote_json=payload,quote_hash=digest(payload),
            state='QUOTED',result_json={},expires_at=datetime.fromisoformat(payload['expires_at']),created_at=now())
        s.add(row);s.flush();return {'quote_id':row.quote_id,**payload}


def options(s,r,stay):
    snap=s.get(Snapshot,r.hosted_reservation_id)
    if not snap:return {'configured':False,'reason':'ORDER_FARE_SNAPSHOT_REQUIRED','options':[]}
    snapshot(s,r)
    guest=s.scalar(select(Guest).where(Guest.hosted_reservation_id==r.hosted_reservation_id))
    a=s.scalar(select(Authorization).where(Authorization.hosted_reservation_id==r.hosted_reservation_id))
    reason=None
    try:eligible(s,r,stay,guest,a,'CANCEL_FOR_REFUND',snap)
    except ValueError as error:reason=str(error)
    from go_hotel.services.hosted_fare_change import context as change_context
    change_reason=None
    try:change_context(s,r.hosted_reservation_id,stay.created_by,'EXTEND_STAY' if guest and guest.state=='IN_HOUSE' else 'CHANGE_DATE')
    except ValueError as error:change_reason=str(error)
    from go_hotel.services.hosted_stay_credit import conversion_context
    credit_reason=None
    try:conversion_context(s,r.hosted_reservation_id,stay.created_by)
    except ValueError as error:credit_reason=str(error)
    return {'configured':True,'rule_version_id':snap.rule_version_id,'rule_hash':snap.rule_hash,
        'rules':deepcopy(snap.rules_json),'options':[
            {'action':'CANCEL_FOR_REFUND','available':reason is None,'reason':reason},
            {'action':'EXTEND_STAY' if guest and guest.state=='IN_HOUSE' else 'CHANGE_DATE','available':change_reason is None,'reason':change_reason},
            {'action':'CONVERT_TO_CREDIT','available':credit_reason is None,'reason':credit_reason},
            {'action':'KEEP_BOOKING','available':stay.operational_state=='CONFIRMED','reason':None}]}


def checked_quote(s,rid,qid,action):
    q=s.get(Quote,qid,with_for_update=True)
    if not q or q.hosted_reservation_id!=rid or q.action!=action:raise ValueError('FARE_QUOTE_NOT_FOUND')
    if digest(q.quote_json)!=q.quote_hash:raise ValueError('FARE_QUOTE_HASH_MISMATCH')
    if q.state!='EXECUTED' and (q.state!='QUOTED' or aware(q.expires_at)<=now()):raise ValueError('FARE_QUOTE_EXPIRED_REQUOTE_REQUIRED')
    return q


def execute(rid,qid,expected_fee,currency,account=None,approval_id=None,evidence=None,actor=None):
    action='CANCEL_FOR_REFUND' if account is not None else 'NO_SHOW'
    with transaction() as s:
        r,stay,guest,a=locked(s,rid,account);q=checked_quote(s,rid,qid,action)
        if type(expected_fee) is not int or (expected_fee,currency)!=(q.quote_json['fee_minor'],r.currency):
            raise ValueError('FARE_FEE_CHANGED_RECONFIRM_REQUIRED')
        if q.state=='EXECUTED':return deepcopy(q.result_json)
        snap=snapshot(s,r);eligible(s,r,stay,guest,a,action,snap)
        if q.order_revision!=revision(s,r,stay,guest,a,snap):raise ValueError('FARE_ORDER_CHANGED_REQUOTE_REQUIRED')
        refs=['fare-quote://'+q.quote_id,'hotel-fare-rule://'+snap.rule_version_id]
        if action=='NO_SHOW':
            approval=s.get(Approval,approval_id,with_for_update=True) if approval_id else None
            if (not approval or approval.authorization_id!=a.authorization_id or approval.adjustment_type!='NO_SHOW'
                or approval.state!='APPROVED_CONTRACT_ONLY' or not approval.checker_id or approval.checker_id==approval.requester_id
                or approval.amount_minor!=expected_fee or not isinstance(evidence,str) or not 1<=len(evidence.strip())<=512):
                raise ValueError('INDEPENDENT_SNAPSHOT_NO_SHOW_APPROVAL_AND_EVIDENCE_REQUIRED')
            # The request must be for this exact quote, not a reusable generic fee.
            if approval.requester_id!=actor or approval.evidence_reference is None or q.result_json.get('approval_id')!=approval_id:
                raise ValueError('NO_SHOW_APPROVAL_QUOTE_MISMATCH')
            refs.extend(['adjustment-approval://'+approval_id,evidence.strip()])
        else:refs.append('customer-fee-consent://'+account+'/'+qid)
        payment=funds.root(s,a)
        from go_hotel.services.hosted_credit_value import return_unused,prepaid
        credit_paid=prepaid(s,rid)
        credit_result=return_unused(s,r,expected_fee,actor or account,'fare-quote://'+qid)
        cash_fee=expected_fee-credit_result['prepaid_fee_minor']
        auth=next((m for m in funds.active_movements(s,a) if m.movement_type=='AUTHORIZATION' and m.state=='CONFIRMED'),None)
        if cash_fee:
            money.create_in_session(s,payment.payment_intent_id,{'movement_type':'CAPTURE','amount_minor':cash_fee,
                'parent_movement_id':auth.money_movement_id,'mode':'CONTRACT_SIMULATOR','evidence':refs},'direct-fare-fee:'+qid,'hosted-fare')
        released=r.amount_minor-credit_paid-cash_fee
        if released:
            money.create_in_session(s,payment.payment_intent_id,{'movement_type':'RELEASE','amount_minor':released,
                'parent_movement_id':auth.money_movement_id,'mode':'CONTRACT_SIMULATOR','evidence':refs},'direct-fare-release:'+qid,'hosted-fare')
        a.state='CONTRACT_CAPTURED_NOT_ALIPAY_NOT_SETTLED' if cash_fee else 'CONTRACT_RELEASED_NOT_ALIPAY';a.updated_at=now()
        r.payment_state='CONTRACT_CREDIT_PAID' if credit_result['prepaid_fee_minor'] else 'CONTRACT_CAPTURED_NOT_ALIPAY' if cash_fee else 'NO_PAYMENT_NO_REFUND_REQUIRED'
        if action=='CANCEL_FOR_REFUND':
            stay.operational_state='CANCELLED';r.reservation_state='CANCELLED'
            if not guest:
                guest=Guest(stay_lifecycle_id=ident('gsl'),hosted_reservation_id=rid,state='CANCELLED',
                    assigned_room_reference=None,planned_check_out=r.check_out,actual_check_in_at=None,
                    actual_check_out_at=None,updated_at=now());s.add(guest)
            else:guest.state='CANCELLED';guest.updated_at=now()
        else:
            guest.state='NO_SHOW';guest.updated_at=now();r.reservation_state='NO_SHOW'
        from go_hotel.db.models import GuestStayEventRow
        s.add(GuestStayEventRow(stay_event_id=ident('gse'),stay_lifecycle_id=guest.stay_lifecycle_id,
            event_type=action+'_SETTLED',actor_id=actor or account,payload_json={'quote_id':qid,'evidence':refs},
            evidence_hash=digest(refs),occurred_at=now()))
        ops._release(s,rid);r.updated_at=stay.updated_at=now()
        result={'reservation_id':rid,'quote_id':qid,'state':r.reservation_state,'fee_captured_minor':cash_fee,'total_fee_minor':expected_fee,**credit_result,
            'authorization_released_minor':released,'cash_refund_minor':0,'currency':r.currency,
            'rule_version_id':snap.rule_version_id,'data_mode':'SIMULATION','external_live':False}
        q.state='EXECUTED';q.result_json=result
        ops._event(s,rid,action+'_SETTLED',actor or account,{'quote_id':qid,'rule_hash':snap.rule_hash,
            'fee_minor':expected_fee,'release_minor':released,'cash_refund_minor':0})
        ops._notify(s,rid,'GUEST',action+'_SETTLED',result)
        return result


def request_no_show(rid,qid,actor):
    with transaction() as s:
        r,stay,guest,a=locked(s,rid);q=checked_quote(s,rid,qid,'NO_SHOW')
        if q.state=='EXECUTED':raise ValueError('FARE_QUOTE_ALREADY_EXECUTED')
        snap=snapshot(s,r);eligible(s,r,stay,guest,a,'NO_SHOW',snap)
        if q.order_revision!=revision(s,r,stay,guest,a,snap):raise ValueError('FARE_ORDER_CHANGED_REQUOTE_REQUIRED')
        old=s.get(Approval,q.result_json.get('approval_id')) if q.result_json else None
        if old:
            if old.requester_id!=actor:raise ValueError('NO_SHOW_REQUESTER_MISMATCH')
            return out(old)
        row=Approval(adjustment_approval_id=ident('aadj'),authorization_id=a.authorization_id,adjustment_type='NO_SHOW',
            amount_minor=q.quote_json['fee_minor'],requester_id=actor,checker_id=None,evidence_reference=None,
            state='PENDING_CHECKER',created_at=now())
        s.add(row);s.flush();q.result_json={'approval_id':row.adjustment_approval_id};return out(row)


def seed_demo_rules(hotel_id):
    """Deliberate test policy only; never represented as the hotel's real policy."""
    funds.require_isolated()
    from go_hotel.db.session import SessionLocal
    from go_hotel.db.models import HostedDirectHotelRow as Hotel
    from go_hotel.services.hosted_credit_value import TERMS
    rules={'credit_terms':TERMS,'fare_family':'隔离测试标准价','timezone':'Asia/Shanghai','check_in_hour':14,
        'cooling_off_minutes':30,'cancellation_tiers':[{'min_hours':24,'fee_basis_points':0},{'min_hours':0,'fee_basis_points':5000}],
        'change_allowed':True,'change_fee_minor':0,'stay_credit_enabled':True,'stay_credit_days':365,
        'stay_credit_scope':'PROPERTY_ONLY','no_show_grace_hours':10,'no_show_fee_basis_points':10000}
    with SessionLocal() as s:
        hotel=s.get(Hotel,hotel_id)
        if not hotel or hotel.contact_json.get('inventory_data_mode')!='SIMULATION':raise ValueError('SIMULATION_HOTEL_REQUIRED')
        offers=list(s.scalars(select(Offer).where(Offer.hosted_hotel_id==hotel_id)))
        ids=[o.hosted_offer_id for o in offers if not s.scalar(select(Rule).where(Rule.hosted_offer_id==o.hosted_offer_id))]
    for oid in ids:publish(oid,rules,'isolated-test-policy://hotel-fare-v1','demo-seed')
    return {'test_rule_versions_created':len(ids)}
