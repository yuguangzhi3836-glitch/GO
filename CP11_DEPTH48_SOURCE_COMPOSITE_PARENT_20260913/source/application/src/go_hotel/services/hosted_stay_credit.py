"""Funded conversion and property-scoped credit redemption in isolated execution."""
from copy import deepcopy
from datetime import date,datetime,timedelta
from sqlalchemy import select
from go_hotel.db.models import (
    HostedStayCreditRow as Credit,HostedCreditAllocationRow as Allocation,
    HostedFareQuoteRow as Quote,HostedDirectReservationRow as Reservation,HostedReservationStayRow as Stay,
    HostedDirectRoomOfferRow as Offer,HostedDirectHotelRow as Hotel,HostedDirectRateVariantRow as Variant,
    HostedInventoryDayRow as Inventory,HostedRateCalendarDayRow as Rate,GuestStayLifecycleRow as Guest,
    AlipayAuthorizationRow as Authorization,HostedFareRuleVersionRow as Rule)
from go_hotel.services import hosted_credit_value as value,hosted_fare_rules as fare,hosted_money as funds,hotel_change_policy,hosted_fare_value
from go_hotel.services.hosted_direct_booking import ident,out
from go_hotel.services.hosted_reservation_operations import dates,aware,hosted_reservation_operations_service as ops
from go_hotel.services.alipay_safeguarded_settlement import transaction
from go_hotel.services.omnichannel_payment import digest
from go_hotel.services.unified_money_movement import unified_money_movement_service as money


def now():return fare.now()


def conversion_context(s,rid,account):
    r,stay,guest,a=fare.locked(s,rid,account);snap=fare.snapshot(s,r);value.terms(snap)
    if value.allocation(s,rid):raise ValueError('USE_EXISTING_PROPERTY_CREDIT')
    fare.eligible(s,r,stay,guest,a,'CANCEL_FOR_REFUND',snap)
    return r,stay,guest,a,snap


def conversion_quote(rid,account):
    with transaction() as s:
        r,stay,guest,a,snap=conversion_context(s,rid,account)
        if s.scalar(select(Credit).where(Credit.original_reservation_id==rid)):raise ValueError('ORDER_ALREADY_CONVERTED_TO_CREDIT')
        timestamp=now();policy=hotel_change_policy.credit_window(r.created_at,timestamp,snap.rules_json['stay_credit_days'])
        q=Quote(quote_id=ident('hfq'),hosted_reservation_id=rid,action='CONVERT_TO_CREDIT',
            order_revision=fare.revision(s,r,stay,guest,a,snap),quote_json={},quote_hash='',state='QUOTED',result_json={},
            created_at=timestamp,expires_at=min(timestamp+timedelta(minutes=10),datetime.fromisoformat(policy['credit_expires_at']),fare.check_in_at(r,snap.rules_json)+timedelta(hours=snap.rules_json['no_show_grace_hours'])))
        retained=hosted_fare_value.basis(s,r)
        payload={'action':'CONVERT_TO_CREDIT','reservation_id':rid,'retained_value_minor':retained['current_room_value_minor'],
            **retained,
            'funding_capture_minor':r.amount_minor,'cancellation_fee_minor':0,'change_fee_minor':0,
            'cash_refund_minor':0,'currency':r.currency,'scope':'PROPERTY_ONLY','hotel_id':s.get(Offer,r.hosted_offer_id).hosted_hotel_id,
            'validity_days':snap.rules_json['stay_credit_days'],'credit_terms':value.terms(snap),
            **policy,
            'rule_version_id':snap.rule_version_id,'rule_hash':snap.rule_hash,'expires_at':aware(q.expires_at).isoformat(),
            'data_mode':'SIMULATION','external_live':False}
        q.quote_json=payload;q.quote_hash=digest(payload);s.add(q);s.flush();return {'quote_id':q.quote_id,**payload}


def convert(rid,account,qid,expected_value,currency):
    with transaction() as s:
        r,stay,guest,a=fare.locked(s,rid,account);q=fare.checked_quote(s,rid,qid,'CONVERT_TO_CREDIT')
        if type(expected_value) is not int or (expected_value,currency)!=(q.quote_json['retained_value_minor'],r.currency):raise ValueError('CREDIT_VALUE_CHANGED_RECONFIRM_REQUIRED')
        if q.state=='EXECUTED':return deepcopy(q.result_json)
        r,stay,guest,a,snap=conversion_context(s,rid,account)
        policy=hotel_change_policy.credit_window(r.created_at,q.created_at,snap.rules_json['stay_credit_days'])
        if any(q.quote_json.get(k)!=v for k,v in policy.items()):raise ValueError('HOTEL_CHANGE_POLICY_REQUOTE_REQUIRED')
        if now()>=datetime.fromisoformat(policy['credit_expires_at']):raise ValueError('HOTEL_CHANGE_ONE_YEAR_VALIDITY_EXCEEDED')
        if q.order_revision!=fare.revision(s,r,stay,guest,a,snap):raise ValueError('FARE_ORDER_CHANGED_REQUOTE_REQUIRED')
        if s.scalar(select(Credit).where(Credit.original_reservation_id==rid)):raise ValueError('ORDER_ALREADY_CONVERTED_TO_CREDIT')
        retained=hosted_fare_value.basis(s,r)
        if any(q.quote_json.get(k)!=v for k,v in retained.items()):raise ValueError('FARE_VALUE_POLICY_REQUOTE_REQUIRED')
        payment=funds.root(s,a);auth=next(x for x in funds.active_movements(s,a) if x.movement_type=='AUTHORIZATION' and x.state=='CONFIRMED')
        refs=['credit-conversion-quote://'+qid,'customer-retained-value-consent://'+account+'/'+qid,'hotel-fare-rule://'+snap.rule_version_id]
        capture=money.create_in_session(s,payment.payment_intent_id,{'movement_type':'CAPTURE','amount_minor':expected_value,
            'parent_movement_id':auth.money_movement_id,'mode':'CONTRACT_SIMULATOR','evidence':refs},'direct-credit-funding:'+qid,'hosted-credit')
        hosted_fare_value.capture_forfeiture(s,r,a,refs)
        c=Credit(credit_id=ident('hsc'),original_reservation_id=rid,account_id=account,
            hosted_hotel_id=q.quote_json['hotel_id'],currency=currency,source_capture_id=capture['money_movement_id'],
            issued_minor=expected_value,available_minor=0,state='ACTIVE',ledger_head_hash=None,
            expires_at=datetime.fromisoformat(q.quote_json['credit_expires_at']),created_at=now(),updated_at=now())
        s.add(c);s.flush();value.event(s,c,'ISSUED',expected_value,rid,refs,account)
        a.state='CONTRACT_CAPTURED_NOT_ALIPAY_NOT_SETTLED';a.updated_at=now()
        r.reservation_state=stay.operational_state='CONVERTED_TO_CREDIT';r.payment_state='CONTRACT_CAPTURED_NOT_ALIPAY';r.updated_at=stay.updated_at=now()
        if guest:guest.state='CONVERTED_TO_CREDIT';guest.updated_at=now()
        else:
            guest=Guest(stay_lifecycle_id=ident('gsl'),hosted_reservation_id=rid,state='CONVERTED_TO_CREDIT',
                assigned_room_reference=None,planned_check_out=r.check_out,actual_check_in_at=None,actual_check_out_at=None,updated_at=now());s.add(guest)
        ops._release(s,rid)
        result={'reservation_id':rid,'quote_id':qid,'credit':value.public(c),'state':'CONVERTED_TO_CREDIT',
            'funding_capture_minor':r.amount_minor,**retained,'cash_refund_minor':0,'currency':currency,'data_mode':'SIMULATION','external_live':False}
        q.state='EXECUTED';q.result_json=result
        ops._event(s,rid,'STAY_CREDIT_CREATED',account,{'credit_id':c.credit_id,'quote_id':qid,'source_capture_id':c.source_capture_id,'rule_hash':snap.rule_hash})
        ops._notify(s,rid,'GUEST','STAY_CREDIT_CREATED',result);return result


def price_redemption(s,c,offer_id,start,end,adults,children):
    try:cin=date.fromisoformat(start);cout=date.fromisoformat(end)
    except (ValueError,TypeError):raise ValueError('VALID_STAY_DATES_REQUIRED')
    if cin<date.today() or not 1<=(cout-cin).days<=30:raise ValueError('VALID_STAY_DATES_REQUIRED')
    if type(adults) is not int or type(children) is not int or adults<1 or children<0:raise ValueError('INVALID_OCCUPANCY_OR_STAY_LENGTH')
    offer=s.get(Offer,offer_id,with_for_update=True)
    if not offer or offer.hosted_hotel_id!=c.hosted_hotel_id or offer.currency!=c.currency:raise ValueError('STAY_CREDIT_ORIGINAL_PROPERTY_AND_CURRENCY_REQUIRED')
    hotel=s.get(Hotel,offer.hosted_hotel_id);variant=s.scalar(select(Variant).where(Variant.hosted_offer_id==offer_id))
    if offer.state!='ACTIVE' or not variant or variant.state!='ACTIVE' or hotel.contact_json.get('inventory_data_mode')!='SIMULATION' or variant.payment_mode!='CONTRACT_SIMULATOR':raise ValueError('ISOLATED_HOTEL_RATE_REQUIRED')
    rule=s.scalar(select(Rule).where(Rule.hosted_offer_id==offer_id).order_by(Rule.version.desc()))
    if not rule:raise ValueError('REDEMPTION_FARE_RULE_REQUIRED')
    if digest(rule.rules_json)!=rule.rule_hash:raise ValueError('FARE_RULE_SOURCE_HASH_MISMATCH')
    fare.validated(rule.rules_json)
    from zoneinfo import ZoneInfo
    arrival=datetime.fromisoformat(start).replace(hour=rule.rules_json['check_in_hour'],tzinfo=ZoneInfo(rule.rules_json['timezone']))
    if arrival>aware(c.expires_at):raise ValueError('CREDIT_CHECK_IN_MUST_BE_WITHIN_VALIDITY')
    nights=[];advance=(cin-date.today()).days
    for day in dates(cin,cout):
        ds=day.isoformat();rate=s.scalar(select(Rate).where(Rate.rate_variant_id==variant.rate_variant_id,Rate.stay_date==ds).with_for_update())
        inv=s.scalar(select(Inventory).where(Inventory.inventory_pool_id==variant.inventory_pool_id,Inventory.stay_date==ds).with_for_update())
        if not rate or not inv:raise ValueError('DATED_ARI_NOT_CONFIGURED')
        if rate.sale_state!='OPEN' or inv.sale_state!='OPEN' or inv.capacity_available<1:raise ValueError('NO_DATED_INVENTORY')
        if not rate.min_stay<=(cout-cin).days<=rate.max_stay or not rate.advance_min_days<=advance<=rate.advance_max_days:raise ValueError('STAY_OR_ADVANCE_RESTRICTION_FAILED')
        if adults>rate.max_adults or children>rate.max_children:raise ValueError('OCCUPANCY_OR_EXTRA_BED_RESTRICTION_FAILED')
        nights.append({'stay_date':ds,'price_minor':rate.price_minor,'inventory_day_id':inv.inventory_day_id})
    return offer,hotel,rule,nights


def redemption_quote(cid,account,offer_id,start,end,adults=1,children=0):
    funds.require_isolated()
    with transaction() as s:
        c=value.checked(s,cid,account);value.active(c)
        offer,hotel,rule,nights=price_redemption(s,c,offer_id,start,end,adults,children)
        total=sum(n['price_minor'] for n in nights);applied=min(total,c.available_minor);due=max(total-c.available_minor,0);forfeited=max(c.available_minor-total,0)
        payload={'action':'REDEEM_CREDIT','credit_id':cid,'hosted_offer_id':offer_id,'hotel_id':c.hosted_hotel_id,
            'check_in':start,'check_out':end,'adults':adults,'children':children,'new_amount_minor':total,
            'available_credit_minor':c.available_minor,'applied_credit_minor':applied,'forfeited_difference_minor':forfeited,
            'amount_due_minor':due,'cash_refund_minor':0,'remaining_credit_minor':0,'currency':c.currency,'scope':'PROPERTY_ONLY',
            'fare_rule':{'rules':deepcopy(rule.rules_json),'rule_hash':rule.rule_hash,'rule_version_id':rule.rule_version_id},
            'nights':nights,'target_rule_hash':rule.rule_hash,'credit_ledger_hash':c.ledger_head_hash,
            'credit_expires_at':aware(c.expires_at).isoformat(),'expires_at':min(now()+timedelta(minutes=10),aware(c.expires_at)).isoformat(),
            'data_mode':'SIMULATION','external_live':False}
        q=Quote(quote_id=ident('hfq'),hosted_reservation_id=c.original_reservation_id,action='REDEEM_CREDIT',
            order_revision=c.ledger_head_hash,quote_json=payload,quote_hash=digest(payload),state='QUOTED',result_json={},
            expires_at=datetime.fromisoformat(payload['expires_at']),created_at=now())
        s.add(q);s.flush();return {'quote_id':q.quote_id,**payload}


def booking_consent(s,account,traveler_id,consent_id):
    from go_hotel.db.models import ProfileConsentRow
    from go_hotel.services.personal_travel_vault import now as actual_now
    c=s.get(ProfileConsentRow,consent_id,with_for_update=True,populate_existing=True)
    t=actual_now()
    if not c or (c.user_id,c.traveler_id,c.purpose,c.consent_type,c.status)!=(account,traveler_id,'HOTEL_BOOKING','SENSITIVE_DATA_RELEASE','ACTIVE') or c.revoked_at or not c.expires_at or not aware(c.granted_at)<=t<aware(c.expires_at) or not {'LEGAL_NAME','MOBILE'}.issubset(c.scope_json):
        raise ValueError('CURRENT_TRAVELER_HOTEL_CONSENT_REQUIRED')
    return c


def redeem(cid,account,qid,expected_due,currency,guest_name,guest_contact,profile_release=None):
    funds.require_isolated()
    with transaction() as s:
        c=value.checked(s,cid,account)
        if profile_release:booking_consent(s,account,profile_release['traveler_id'],profile_release['consent_id'])
        q=fare.checked_quote(s,c.original_reservation_id,qid,'REDEEM_CREDIT');p=q.quote_json
        if p['credit_id']!=cid:raise ValueError('STAY_CREDIT_QUOTE_NOT_FOUND')
        if type(expected_due) is not int or (expected_due,currency)!=(p['amount_due_minor'],c.currency):raise ValueError('CREDIT_VALUE_CHANGED_RECONFIRM_REQUIRED')
        fingerprint=digest([guest_name,guest_contact,(profile_release or {}).get('traveler_id')])
        if q.state=='EXECUTED':
            if q.result_json.get('guest_fingerprint')!=fingerprint:raise ValueError('CREDIT_REDEMPTION_IDEMPOTENCY_CONFLICT')
            return {k:v for k,v in q.result_json.items() if k!='guest_fingerprint'}
        value.active(c)
        if c.ledger_head_hash!=q.order_revision or c.available_minor!=p['available_credit_minor']:raise ValueError('CREDIT_VALUE_CHANGED_REQUOTE_REQUIRED')
        offer,hotel,rule,nights=price_redemption(s,c,p['hosted_offer_id'],p['check_in'],p['check_out'],p['adults'],p['children'])
        if nights!=p['nights'] or rule.rule_hash!=p['target_rule_hash']:raise ValueError('DATED_RATE_CHANGED_REQUOTE_REQUIRED')
        reservation=ops.reserve(hotel.page_slug,{'hosted_offer_id':offer.hosted_offer_id,'check_in':p['check_in'],'check_out':p['check_out'],
            'adults':p['adults'],'children':p['children'],'guest_name':guest_name,'guest_contact':guest_contact,
            'expected_total_minor':p['new_amount_minor'],'expected_fare_rule_hash':p['target_rule_hash']},'credit-redemption:'+qid,'GO_PAGE',account,_session=s)
        rid=reservation['hosted_reservation_id'];r=s.get(Reservation,rid);stay=s.get(Stay,rid)
        s.add(Allocation(hosted_reservation_id=rid,credit_id=cid,quote_id=qid,applied_minor=p['applied_credit_minor'],
            forfeited_minor=p['forfeited_difference_minor'],fee_consumed_minor=0,restored_minor=0,state='ACTIVE',created_at=now()))
        value.event(s,c,'ALLOCATED',-p['applied_credit_minor'],rid,['credit-redemption-quote://'+qid],account)
        if p['forfeited_difference_minor']:value.event(s,c,'LOWER_PRICE_FORFEITED',-p['forfeited_difference_minor'],rid,['credit-redemption-quote://'+qid],account)
        c.state='ALLOCATED'
        a=Authorization(authorization_id=ident('aauth'),hosted_reservation_id=rid,amount_minor=expected_due,currency=currency,
            state='CONTRACT_FROZEN_NOT_ALIPAY',external_invoked=False,external_authorization_reference=None,
            settlement_eligible=False,idempotency_key='credit-redemption-auth:'+qid,updated_at=now());s.add(a);s.flush()
        funds.ensure_authorization(s,r,stay,a,p['applied_credit_minor'])
        r.reservation_state='HOTEL_CONFIRMED_AWAITING_ALIPAY_ONBOARDING';stay.operational_state='CONFIRMED'
        r.payment_state='CONTRACT_CREDIT_AND_AUTHORIZED';r.hotel_confirmation_reference='credit-simulation:'+qid;r.updated_at=stay.updated_at=now()
        result={'credit_id':cid,'reservation_id':rid,'quote_id':qid,'state':'CONFIRMED','amount_due_minor':expected_due,
            'applied_credit_minor':p['applied_credit_minor'],'forfeited_difference_minor':p['forfeited_difference_minor'],
            'amount_minor':r.amount_minor,'currency':currency,'data_mode':'SIMULATION','external_live':False}
        q.state='EXECUTED';q.result_json={**result,'guest_fingerprint':fingerprint}
        ops._event(s,rid,'STAY_CREDIT_REDEEMED',account,{'credit_id':cid,'quote_id':qid,'source_capture_id':c.source_capture_id,**({'profile_release':profile_release} if profile_release else {})})
        funds.project(s,s.get(Reservation,c.original_reservation_id),'STAY_CREDIT_REDEEMED')
        ops._notify(s,rid,'GUEST','STAY_CREDIT_REDEEMED',result);return result


def list_credits(account):
    from go_hotel.db.session import SessionLocal
    with SessionLocal() as s:
        items=[]
        for c in s.scalars(select(Credit).where(Credit.account_id==account).order_by(Credit.created_at.desc())):
            item=value.public(c);hotel=s.get(Hotel,c.hosted_hotel_id)
            blocked=value.reconciliation_required(s,c.original_reservation_id)
            item.update(hotel_name=hotel.supplier_name if hotel else '原预订酒店',hotel_slug=hotel.page_slug if hotel else None,
                reconciliation_required=blocked,can_redeem=not blocked and item['state']=='ACTIVE' and item['available_minor']>0)
            items.append(item)
        return items


def expire():
    funds.require_isolated()
    with transaction() as s:
        ids=list(s.scalars(select(Credit.credit_id).where(Credit.state=='ACTIVE',Credit.expires_at<=now())))
        count=0
        for cid in ids:
            c=value.checked(s,cid)
            if c.state!='ACTIVE' or aware(c.expires_at)>now():continue
            if c.available_minor:value.event(s,c,'EXPIRED',-c.available_minor,None,['credit-expiry://'+cid],'SYSTEM')
            c.state='EXPIRED';count+=1;funds.project(s,s.get(Reservation,c.original_reservation_id),'STAY_CREDIT_EXPIRED')
        return {'expired_count':count}
