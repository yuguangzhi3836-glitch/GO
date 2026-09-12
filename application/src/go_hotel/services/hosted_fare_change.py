"""Dated changes and extensions with a retained price floor and atomic reauthorization."""
from copy import deepcopy
from datetime import date,datetime,timedelta
from sqlalchemy import select,update
from go_hotel.db.models import (HostedFareQuoteRow as Quote,HostedFareFundingRow as Funding,
    HostedReservationNightRow as Night,HostedInventoryDayRow as Inventory,HostedRateCalendarDayRow as Rate,
    HostedDirectRateVariantRow as Variant,HostedDirectRoomOfferRow as Offer,
    OmnichannelPaymentIntentRow as Intent,PaymentOrderRootRow as Root,PaymentOrderFactBindingRow as Binding,
    VerticalSourceDecisionRow as Source)
from go_hotel.services import hosted_fare_rules as fare,hosted_money as funds
from go_hotel.services.hosted_direct_booking import ident,out
from go_hotel.services.hosted_reservation_operations import dates,aware,hosted_reservation_operations_service as ops
from go_hotel.services.alipay_safeguarded_settlement import transaction
from go_hotel.services.omnichannel_payment import digest,legal_entity
from go_hotel.services.unified_money_movement import unified_money_movement_service as money
from go_hotel.services import hotel_change_policy


def now():return fare.now()

def context(s,rid,account,action):
    funds.require_isolated()
    r,stay,guest,a=fare.locked(s,rid,account);snap=fare.snapshot(s,r)
    if stay.operational_state!='CONFIRMED' or not snap.rules_json['change_allowed']:raise ValueError('FARE_CHANGE_NOT_ALLOWED')
    if action=='EXTEND_STAY':
        if not guest or guest.state!='IN_HOUSE':raise ValueError('EXTENSION_REQUIRES_IN_HOUSE')
    elif action=='CHANGE_DATE':
        if guest and guest.state!='PRE_ARRIVAL' or now()>=fare.check_in_at(r,snap.rules_json):raise ValueError('DATE_CHANGE_REQUIRES_PRE_ARRIVAL')
    else:raise ValueError('UNSUPPORTED_FARE_ACTION')
    if not a or not funds.root(s,a) or a.state!='CONTRACT_FROZEN_NOT_ALIPAY':raise ValueError('KNOWN_FROZEN_FARE_AUTHORIZATION_REQUIRED')
    funds.require_known(s,a);summary=funds.summary(s,r)
    if summary['held_minor']+summary.get('prepaid_credit_minor',0)!=r.amount_minor or summary['capture_minor'] or summary['refund_minor']:raise ValueError('UNSPENT_FARE_AUTHORIZATION_REQUIRED')
    from go_hotel.db.models import StayDisputeRow as Dispute
    if guest and s.scalar(select(Dispute).where(Dispute.stay_lifecycle_id==guest.stay_lifecycle_id,Dispute.state=='OPEN_SETTLEMENT_FROZEN')):raise ValueError('OPEN_FULFILLMENT_DISPUTE')
    return r,stay,guest,a,snap


def priced(s,r,stay,action,start,end):
    try:cin=date.fromisoformat(start);cout=date.fromisoformat(end)
    except (TypeError,ValueError):raise ValueError('VALID_STAY_DATES_REQUIRED')
    if not 1<=(cout-cin).days<=30:raise ValueError('STAY_LENGTH_1_TO_30_NIGHTS_REQUIRED')
    if action=='EXTEND_STAY':
        if start!=r.check_in or end<=r.check_out or date.fromisoformat(r.check_out)<date.today():raise ValueError('VALID_DATED_EXTENSION_REQUIRED')
    elif cin<date.today() or (start,end)==(r.check_in,r.check_out):raise ValueError('NEW_STAY_DATES_REQUIRED')
    offer=s.get(Offer,r.hosted_offer_id,with_for_update=True)
    variant=s.scalar(select(Variant).where(Variant.hosted_offer_id==offer.hosted_offer_id))
    if offer.state!='ACTIVE' or not variant or variant.state!='ACTIVE':raise ValueError('ACTIVE_HOSTED_OFFER_REQUIRED')
    held={n.stay_date:n for n in s.scalars(select(Night).where(Night.hosted_reservation_id==r.hosted_reservation_id,Night.state=='HELD'))}
    nights=[]
    for day in dates(cin,cout):
        ds=day.isoformat()
        if action=='EXTEND_STAY' and ds<r.check_out:
            if ds not in held:raise ValueError('ORIGINAL_HELD_INVENTORY_REQUIRED')
            n=held[ds];nights.append({'stay_date':ds,'inventory_day_id':n.inventory_day_id,'price_minor':n.price_minor});continue
        rate=s.scalar(select(Rate).where(Rate.rate_variant_id==variant.rate_variant_id,Rate.stay_date==ds).with_for_update())
        inv=s.scalar(select(Inventory).where(Inventory.inventory_pool_id==variant.inventory_pool_id,Inventory.stay_date==ds).with_for_update())
        if not rate or not inv:raise ValueError('DATED_ARI_NOT_CONFIGURED')
        if rate.sale_state!='OPEN' or inv.sale_state!='OPEN' or inv.capacity_available+(1 if ds in held else 0)<1:raise ValueError('NO_DATED_INVENTORY')
        advance=(cin-date.today()).days if action=='CHANGE_DATE' else (date.fromisoformat(r.check_out)-date.today()).days
        if not rate.min_stay<=(cout-cin).days<=rate.max_stay or not rate.advance_min_days<=advance<=rate.advance_max_days:raise ValueError('STAY_OR_ADVANCE_RESTRICTION_FAILED')
        if stay.adults>rate.max_adults or stay.children>rate.max_children or stay.extra_beds and not rate.extra_bed_allowed:raise ValueError('OCCUPANCY_OR_EXTRA_BED_RESTRICTION_FAILED')
        nights.append({'stay_date':ds,'inventory_day_id':inv.inventory_day_id,'price_minor':rate.price_minor})
    return nights


def create_quote(rid,account,action,start,end):
    with transaction() as s:
        r,stay,guest,a,snap=context(s,rid,account,action)
        policy=hotel_change_policy.terms(r.created_at)
        if action=='CHANGE_DATE':
            policy=hotel_change_policy.require_window(r.created_at,start,now(),
                snap.rules_json['timezone'],snap.rules_json['check_in_hour'])
        from go_hotel.services.hosted_credit_value import allocation,Credit,prepaid
        credited=prepaid(s,rid);allocated=allocation(s,rid)
        if allocated:
            from zoneinfo import ZoneInfo
            try:date.fromisoformat(start)
            except (ValueError,TypeError):raise ValueError('VALID_STAY_DATES_REQUIRED')
            arrival=datetime.fromisoformat(start).replace(hour=snap.rules_json['check_in_hour'],tzinfo=ZoneInfo(snap.rules_json['timezone']))
            if arrival>aware(s.get(Credit,allocated.credit_id).expires_at):raise ValueError('CREDIT_CHECK_IN_MUST_BE_WITHIN_VALIDITY')
        nights=priced(s,r,stay,action,start,end)
        room_total=sum(n['price_minor'] for n in nights)
        # Extension preserves every previous retained amount and adds only new nights.
        quoted=room_total if action=='CHANGE_DATE' else r.amount_minor+sum(n['price_minor'] for n in nights if n['stay_date']>=r.check_out)
        difference=max(0,quoted-r.amount_minor);fee=0;total=r.amount_minor+difference
        q=Quote(quote_id=ident('hfq'),hosted_reservation_id=rid,action=action,
            order_revision=fare.revision(s,r,stay,guest,a,snap),state='QUOTED',result_json={},
            created_at=now(),expires_at=now()+timedelta(minutes=10),quote_json={},quote_hash='')
        payload={'action':action,'reservation_id':rid,'check_in':start,'check_out':end,'old_amount_minor':r.amount_minor,
            'new_room_quote_minor':room_total,'new_amount_minor':total,'fare_difference_minor':difference,
            'change_fee_minor':fee,'additional_amount_minor':difference+fee,'cash_refund_minor':0,'stay_credit_minor':0,
            'lower_price_rule':'NO_REFUND_NO_CASH_NO_BALANCE','currency':r.currency,'nights':nights,
            'authorization_replacement_minor':total-credited if total!=r.amount_minor else 0,
            'old_authorization_release_minor':r.amount_minor-credited if total!=r.amount_minor else 0,
            'prepaid_credit_minor':credited,
            'rule_version_id':snap.rule_version_id,'rule_hash':snap.rule_hash,'expires_at':aware(q.expires_at).isoformat(),
            'data_mode':'SIMULATION','external_live':False,**policy}
        q.quote_json=payload;q.quote_hash=digest(payload);s.add(q);s.flush();return {'quote_id':q.quote_id,**payload}


def replace_authorization(s,r,stay,a,q):
    """Release the known old hold, authorize the new total; keep both immutable roots."""
    payload=q.quote_json
    from go_hotel.services.hosted_credit_value import prepaid
    credited=prepaid(s,r.hosted_reservation_id);total=payload['new_amount_minor']-credited;old_cash=r.amount_minor-credited
    if total==old_cash:return
    payment=funds.root(s,a);auth=next((m for m in funds.active_movements(s,a) if m.movement_type=='AUTHORIZATION' and m.state=='CONFIRMED'),None)
    evidence=['fare-quote://'+q.quote_id,'customer-reauthorization-consent://'+stay.created_by+'/'+q.quote_id]
    if old_cash:
        money.create_in_session(s,payment.payment_intent_id,{'movement_type':'RELEASE','amount_minor':old_cash,
            'parent_movement_id':auth.money_movement_id,'mode':'CONTRACT_SIMULATOR','evidence':evidence},'direct-change-old-release:'+q.quote_id,'hosted-fare')
    offer=s.get(Offer,r.hosted_offer_id);iid=ident('opi');entity=legal_entity(r.currency);timestamp=now();business='HOSTED_HOTEL_FARE_CHANGE'
    facts={'reservation_id':r.hosted_reservation_id,'quote_id':q.quote_id,'hosted_offer_id':r.hosted_offer_id,
        'payer_id':stay.created_by,'payee_id':offer.hosted_hotel_id,'amount_minor':total,'currency':r.currency,
        'check_in':payload['check_in'],'check_out':payload['check_out'],'previous_payment_intent_id':payment.payment_intent_id,
        'rule_hash':payload['rule_hash'],'prepaid_credit_minor':credited,'order_total_minor':payload['new_amount_minor']}
    s.add(Intent(payment_intent_id=iid,business_type=business,business_id=q.quote_id,payer_id=stay.created_by,
        payee_id=offer.hosted_hotel_id,operation='AUTHORIZE',amount_minor=total,currency=r.currency,
        channel_priority_json=['LOCAL_MARKET'],selected_channel='LOCAL_MARKET',state='SUCCEEDED',
        idempotency_key='direct-change-intent:'+q.quote_id,automatic_fallback_allowed=False,
        user_channel_consent_at=timestamp,created_at=timestamp,updated_at=timestamp));s.flush()
    s.add(Root(payment_order_root_id=ident('por'),business_type=business,business_id=q.quote_id,payment_intent_id=iid,
        legal_entity_id=entity,state='ACTIVE',root_hash=digest([business,q.quote_id,iid,entity]),created_at=timestamp))
    source_id=ident('vsd');s.add(Source(vertical_source_decision_id=source_id,vertical='HOTEL',business_id=r.hosted_reservation_id,
        selected_source_id=offer.hosted_hotel_id,selected_source_type='HOSTED_DIRECT_SIMULATION',route='GO_HOSTED_DIRECT',
        authority_reference='hotel-fare-rule://'+payload['rule_version_id'],evidence_reference='fare-quote://'+q.quote_id,
        candidate_snapshot_json=[facts],reason_codes_json=['USER_CONFIRMED_DATED_CHANGE'],decision_hash=digest(facts),created_at=timestamp))
    s.add(Binding(payment_order_fact_binding_id=ident('pofb'),payment_intent_id=iid,business_type=business,business_id=q.quote_id,
        payer_id=stay.created_by,payee_id=offer.hosted_hotel_id,amount_minor=total,currency=r.currency,legal_entity_id=entity,
        source_decision_id=source_id,request_fingerprint=digest(facts),order_fact_hash=digest(facts),evidence_reference='fare-quote://'+q.quote_id,created_at=timestamp))
    previous=s.scalar(select(Funding).where(Funding.hosted_reservation_id==r.hosted_reservation_id).order_by(Funding.generation.desc()))
    s.add(Funding(quote_id=q.quote_id,hosted_reservation_id=r.hosted_reservation_id,generation=previous.generation+1 if previous else 1,payment_intent_id=iid,created_at=timestamp));s.flush()
    money.create_in_session(s,iid,{'movement_type':'AUTHORIZATION','amount_minor':total,'mode':'CONTRACT_SIMULATOR','evidence':evidence},'direct-change-authorization:'+q.quote_id,'hosted-fare')


def execute(rid,account,qid,expected_total,expected_additional,currency):
    with transaction() as s:
        r,stay,guest,a=fare.locked(s,rid,account);probe=s.get(Quote,qid)
        if not probe or probe.action not in {'CHANGE_DATE','EXTEND_STAY'}:raise ValueError('FARE_QUOTE_NOT_FOUND')
        q=fare.checked_quote(s,rid,qid,probe.action);payload=q.quote_json
        if type(expected_total) is not int or type(expected_additional) is not int or (expected_total,expected_additional,currency)!=(payload['new_amount_minor'],payload['additional_amount_minor'],r.currency):raise ValueError('FARE_AMOUNT_CHANGED_RECONFIRM_REQUIRED')
        if q.state=='EXECUTED':return deepcopy(q.result_json)
        r,stay,guest,a,snap=context(s,rid,account,q.action)
        hotel_change_policy.require_zero_fee(payload)
        if q.action=='CHANGE_DATE':
            policy=hotel_change_policy.require_window(r.created_at,payload['check_in'],now(),
                snap.rules_json['timezone'],snap.rules_json['check_in_hour'])
            if any(payload.get(k)!=v for k,v in policy.items()):raise ValueError('HOTEL_CHANGE_POLICY_REQUOTE_REQUIRED')
        if q.order_revision!=fare.revision(s,r,stay,guest,a,snap):raise ValueError('FARE_ORDER_CHANGED_REQUOTE_REQUIRED')
        nights=priced(s,r,stay,q.action,payload['check_in'],payload['check_out'])
        if nights!=payload['nights']:raise ValueError('DATED_RATE_CHANGED_REQUOTE_REQUIRED')
        held={n.stay_date:n for n in s.scalars(select(Night).where(Night.hosted_reservation_id==rid,Night.state=='HELD'))}
        target={n['stay_date']:n for n in nights}
        # Claim all additional nights before releasing old nights; any failure rolls back both.
        for ds,n in target.items():
            if ds in held:held[ds].price_minor=n['price_minor'];continue
            changed=s.execute(update(Inventory).where(Inventory.inventory_day_id==n['inventory_day_id'],Inventory.sale_state=='OPEN',Inventory.capacity_available>0).values(capacity_available=Inventory.capacity_available-1,updated_at=now())).rowcount
            if changed!=1:raise ValueError('NO_DATED_INVENTORY')
            old=s.scalar(select(Night).where(Night.hosted_reservation_id==rid,Night.stay_date==ds))
            if old:old.state='HELD';old.price_minor=n['price_minor'];old.inventory_day_id=n['inventory_day_id']
            else:s.add(Night(reservation_night_id=ident('hrn'),hosted_reservation_id=rid,inventory_day_id=n['inventory_day_id'],stay_date=ds,price_minor=n['price_minor'],state='HELD'))
        for ds,n in held.items():
            if ds in target:continue
            changed=s.execute(update(Inventory).where(Inventory.inventory_day_id==n.inventory_day_id,Inventory.capacity_available<Inventory.capacity_total).values(capacity_available=Inventory.capacity_available+1,updated_at=now())).rowcount
            if changed!=1:raise ValueError('INVENTORY_RELEASE_INVARIANT_FAILED')
            n.state='RELEASED'
        replace_authorization(s,r,stay,a,q)
        r.check_in=payload['check_in'];r.check_out=payload['check_out'];r.amount_minor=expected_total;r.updated_at=stay.updated_at=now()
        if guest:guest.planned_check_out=r.check_out;guest.updated_at=now()
        result={'reservation_id':rid,'quote_id':qid,'action':q.action,'check_in':r.check_in,'check_out':r.check_out,
            'amount_minor':r.amount_minor,'additional_amount_minor':expected_additional,'currency':r.currency,
            'state':'CONFIRMED','cash_refund_minor':0,'data_mode':'SIMULATION','external_live':False}
        if guest:
            from go_hotel.db.models import GuestStayEventRow
            s.add(GuestStayEventRow(stay_event_id=ident('gse'),stay_lifecycle_id=guest.stay_lifecycle_id,
                event_type=q.action+'_CONFIRMED',actor_id=account,payload_json={'quote_id':qid,'check_out':r.check_out},
                evidence_hash=digest(result),occurred_at=now()))
        q.state='EXECUTED';q.result_json=result
        ops._event(s,rid,q.action+'_CONFIRMED',account,{'quote_id':qid,'rule_hash':snap.rule_hash,'additional_amount_minor':expected_additional})
        ops._notify(s,rid,'GUEST',q.action+'_CONFIRMED',result);return result
