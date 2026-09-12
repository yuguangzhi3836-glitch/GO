"""Durable, explicitly accepted catalog credit conversion and redemption."""
from copy import deepcopy
import json
from datetime import date,datetime,timedelta,timezone
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (StayCreditRow as Credit,CatalogCreditContractRow as Contract,
    CatalogCreditSourceRow as Source,CatalogCreditAllocationRow as Allocation,CatalogCreditQuoteRow as Quote,
    OrderRow as Order,OfferRow,PrebookRow,OrderChangeRow,OmnichannelMoneyMovementRow as Movement)
from go_hotel.services.alipay_safeguarded_settlement import transaction
from go_hotel.services.hosted_direct_booking import ident,now
from go_hotel.services.hosted_reservation_operations import aware
from go_hotel.services.omnichannel_payment import digest
from go_hotel.services import catalog_credit_value as value,catalog_supplier_remedy as remedy,hosted_money as funds
from go_hotel.repositories.sql import repo
from go_hotel.domain.models import Event

TERMS={'version':'CATALOG_CREDIT_V1','scope':'PROPERTY_ONLY','validity_basis':'CHECK_IN_BY_EXPIRY',
    'higher_price_rule':'PAY_DIFFERENCE','lower_price_rule':'NO_REFUND_NO_BALANCE',
    'unused_value_on_customer_cancellation':'ORIGINAL_CREDIT_UNDER_ACCEPTED_FEE_TIERS',
    'cash_refund_policy':'INDEPENDENT_DISPUTE_ONLY','expiry_extension_allowed':False}


def quote(s,kind,order_id,credit_id,payload,expires_at=None):
    q=Quote(quote_id=ident('ccq'),kind=kind,order_id=order_id,credit_id=credit_id,payload_json=payload,
        payload_hash=digest(payload),expires_at=expires_at or now()+timedelta(minutes=10),created_at=now())
    s.add(q);s.flush();return {**payload,'quote_id':q.quote_id,'quote_hash':q.payload_hash,'expires_at':aware(q.expires_at).isoformat()}


def checked_quote(s,qid,kind,expected,consent,allow_expired=False):
    q=s.get(Quote,qid)
    if not q or q.kind!=kind:raise ValueError('STAY_CREDIT_QUOTE_NOT_FOUND')
    if digest(q.payload_json)!=q.payload_hash:raise ValueError('STAY_CREDIT_QUOTE_FACT_MISMATCH')
    if q.payload_hash!=expected or consent is not True:raise ValueError('CURRENT_CREDIT_QUOTE_CONSENT_REQUIRED')
    if not allow_expired and aware(q.expires_at)<=now():raise ValueError('STAY_CREDIT_QUOTE_EXPIRED')
    return q


def conversion_facts(s,order,rule):
    if order.status!='CONFIRMED' or order.currency!='CNY':raise ValueError('CONFIRMED_CNY_ORDER_REQUIRED')
    if s.scalar(select(Credit).where(Credit.original_order_id==order.order_id)):raise ValueError('STAY_CREDIT_ALREADY_EXISTS')
    if s.scalar(select(OrderChangeRow).where(OrderChangeRow.order_id==order.order_id,OrderChangeRow.status=='SUPPLIER_PROCESSING')):raise ValueError('ORDER_CHANGE_RECONCILIATION_REQUIRED')
    if s.scalar(select(remedy.Case).where(remedy.Case.order_id==order.order_id,remedy.Case.status!='COMPLETED')):raise ValueError('SUPPLIER_REMEDY_ORDER_FROZEN')
    from go_hotel.services.catalog_cash_fare import facts as cash_facts
    original_prebook=s.get(PrebookRow,order.prebook_id)
    original_offer=s.get(OfferRow,original_prebook.offer_id)
    cash=cash_facts(s,order,original_offer)
    # Recheck under the order lock at acceptance as well as quotation.
    # Use the latest confirmed stay, not the original offer's pre-change dates.
    if date.fromisoformat(cash['check_in'])<=now().date():raise ValueError('UNUSED_FUTURE_STAY_REQUIRED')
    if not rule.get('stay_credit_allowed') or rule.get('stay_credit_scope')!='PROPERTY_ONLY':raise ValueError('PROPERTY_CREDIT_RULE_REQUIRED')
    days=rule.get('stay_credit_validity_days')
    if type(days) is not int or not 1<=days<=365:raise ValueError('CREDIT_VALIDITY_EXCEEDS_MASTER')
    _,_,lines=remedy.paid_facts(s,order)
    forfeiture=None
    if cash['forfeited_change_value_minor']:
        from go_hotel.services.catalog_credit_source_allocation import split_sources
        lines,forfeiture=split_sources(s,order,cash)
    for line in lines:
        if s.get(Source,line['capture_id']):raise ValueError('CREDIT_SOURCE_ALREADY_ALLOCATED')
        cap=s.get(Movement,line['capture_id']);line['prior_refund_minor']=cap.amount_minor-line['amount_minor']-line.get('excluded_minor',0)
    amount=sum(x['amount_minor'] for x in lines)
    if amount<=0:raise ValueError('FUNDED_POSITIVE_CREDIT_REQUIRED')
    result={'order_id':order.order_id,'order_version':order.version,'account_id':order.account_id,
        'property_id':order.hotel_id,'supplier_id':order.supplier_id,'currency':order.currency,
        'credit_value_minor':amount,'supplier_confirmation_no':order.supplier_confirmation_no,
        'sources':lines,'validity_days':days,'terms':{**TERMS,'cancellation_fee_tiers':deepcopy(rule['tiers'])},
        'rule_snapshot':deepcopy(rule),'data_mode':'SIMULATION'}
    if forfeiture:result['cash_change_forfeiture']=forfeiture
    return result


def conversion_quote(order_id):
    funds.require_isolated()
    from go_hotel.fare.service import fare_service
    order,_,offer,check_in,_=fare_service._context(order_id)
    if date.fromisoformat(check_in)<=now().date():raise ValueError('UNUSED_FUTURE_STAY_REQUIRED')
    rule=fare_service._order_rule(order_id)
    with transaction() as s:
        current=s.get(Order,order_id,with_for_update=True,populate_existing=True)
        payload=conversion_facts(s,current,rule)
        return {**quote(s,'CONVERT',order_id,None,payload),'scope':'PROPERTY_ONLY',
            'higher_price_rule':'PAY_DIFFERENCE','lower_price_rule':'NO_REFUND_NO_BALANCE'}


async def convert(order_id,quote_id,expected_hash,consent,actor):
    funds.require_isolated();dispatch=False
    with transaction() as s:
        order=s.get(Order,order_id,with_for_update=True,populate_existing=True)
        q=checked_quote(s,quote_id,'CONVERT',expected_hash,consent,allow_expired=True)
        if q.order_id!=order_id or not order:raise ValueError('STAY_CREDIT_QUOTE_NOT_FOUND')
        existing=s.scalar(select(Credit).where(Credit.original_order_id==order_id))
        if existing:
            c,p=value.checked(s,existing.stay_credit_id)
            if p.quote_id!=quote_id or p.accepted_by!=actor:raise ValueError('CREDIT_CONVERSION_REQUEST_CONFLICT')
            return value.public(c,p)
        if aware(q.expires_at)<=now():raise ValueError('STAY_CREDIT_QUOTE_EXPIRED')
        current=conversion_facts(s,order,q.payload_json['rule_snapshot'])
        if current!=q.payload_json:raise ValueError('CREDIT_QUOTE_STALE_REQUOTE_REQUIRED')
        conn=remedy.connector(s,order);confirmation=order.supplier_confirmation_no
        cid=ident('sc');start=now();expiry=start+timedelta(days=current['validity_days'])
        contract={**deepcopy(current),'valid_from':start.isoformat(),'credit_expires_at':expiry.isoformat()}
        c=Credit(stay_credit_id=cid,original_order_id=order_id,account_id=order.account_id,property_id=order.hotel_id,
            credit_value_minor=current['credit_value_minor'],currency=order.currency,valid_from=start,expires_at=expiry,status='CANCEL_PENDING',created_at=start)
        p=Contract(credit_id=cid,original_order_id=order_id,quote_id=quote_id,contract_json=contract,contract_hash=digest(contract),
            available_minor=0,expired_minor=0,accepted_by=actor,accepted_at=start,updated_at=start)
        s.add_all([c,p]);s.flush()
        for line in current['sources']:s.add(Source(capture_id=line['capture_id'],credit_id=cid,payment_intent_id=line['payment_intent_id'],funded_minor=line['amount_minor'],prior_refund_minor=line['prior_refund_minor'],excluded_minor=line.get('excluded_minor',0)))
        value.journal(s,c,p,'SOURCE_FUNDS_RESERVED',0,order_id,{'quote_hash':q.payload_hash},actor)
        remedy.event(s,order_id,'STAY_CREDIT_CANCEL_PLANNED',actor,{'credit_id':cid,'contract_hash':p.contract_hash})
        dispatch=True
    if dispatch:
        try:result=await conn.cancel(confirmation)
        except BaseException as exc:
            with transaction() as s:
                c,p=value.checked(s,cid);c.status='UNKNOWN_CANCEL'
                value.journal(s,c,p,'SUPPLIER_CANCEL_UNKNOWN',0,order_id,{'quote_id':quote_id},actor)
                response=value.public(c,p)
            if isinstance(exc,Exception):return response
            raise
        with transaction() as s:
            c,p=value.checked(s,cid)
            if result=='CANCELLED':activate(s,c,p,actor)
            else:c.status='UNKNOWN_CANCEL'
            return value.public(c,p)


def activate(s,c,p,actor):
    if c.status not in value.PENDING_CONVERSION:return
    order=s.get(Order,c.original_order_id)
    if order.status!='CONFIRMED' or order.supplier_confirmation_no!=p.contract_json['supplier_confirmation_no']:raise ValueError('CREDIT_SOURCE_ORDER_CHANGED')
    c.status='ACTIVE';order.status='CONVERTED_TO_CREDIT';order.version+=1;order.updated_at=now()
    value.journal(s,c,p,'ISSUED',c.credit_value_minor,c.original_order_id,{'confirmed_supplier_cancel':True},actor)
    value.expire(s,c,p,actor);remedy.event(s,order.order_id,'STAY_CREDIT_ACTIVATED',actor,{'credit_id':c.stay_credit_id})


async def reconcile_conversion(cid,actor):
    funds.require_isolated()
    with transaction() as s:
        c,p=value.checked(s,cid)
        if c.status not in value.PENDING_CONVERSION:return value.public(c,p)
        order=s.get(Order,c.original_order_id);conn=remedy.connector(s,order);confirmation=p.contract_json['supplier_confirmation_no']
    observed=await conn.status(confirmation)
    with transaction() as s:
        c,p=value.checked(s,cid)
        if observed=='CANCELLED':activate(s,c,p,actor)
        elif c.status in value.PENDING_CONVERSION:c.status='UNKNOWN_CANCEL'
        return value.public(c,p)


def get_credit(cid):
    with transaction() as s:
        c=s.get(Credit,cid)
        if not c:raise ValueError('STAY_CREDIT_NOT_FOUND')
        if not s.get(Contract,cid):return value.public(c)
        c,p=value.checked(s,cid);value.expire(s,c,p,'credit-expiry')
        result=value.public(c,p)
        a=s.scalar(select(Allocation).where(Allocation.credit_id==cid).order_by(Allocation.created_at.desc()))
        result['latest_redemption']=allocation_public(a) if a else None
        return result


async def redemption_quote(cid,check_in,check_out):
    funds.require_isolated();ci=date.fromisoformat(check_in);co=date.fromisoformat(check_out)
    with transaction() as s:
        c,p=value.checked(s,cid);value.active(c,p)
        if not now().date()<ci<co or ci>aware(c.expires_at).date():raise ValueError('CREDIT_STAY_DATES_OUTSIDE_VALIDITY')
        order=s.get(Order,c.original_order_id);conn=remedy.connector(s,order);currency=c.currency;property_id=c.property_id
    offers=await conn.search('TYO',check_in,check_out,currency)
    candidates=[o for o in offers if o.hotel_id==property_id and o.currency==currency and o.check_in==check_in and o.check_out==check_out and o.total_amount_minor>0]
    if not candidates:raise ValueError('STAY_CREDIT_NO_INVENTORY')
    offer=candidates[0]
    repo.save_offer_with_event(offer,Event(ident('evt'),'STAY_CREDIT_REDEMPTION_OFFER_CREATED','HOTEL_OFFER',offer.offer_id,{'credit_id':cid}))
    with transaction() as s:
        c,p=value.checked(s,cid);value.active(c,p)
        if offer.supplier_id!=p.contract_json['supplier_id']:raise ValueError('ORIGINAL_PROPERTY_SUPPLIER_REQUIRED')
        amount=offer.total_amount_minor;applied=min(p.available_minor,amount);remaining=applied;lines=[];forfeiture_lines=[]
        # Previous restored allocations release the same prepaid source budgets.
        for source in sorted(p.contract_json['sources'],key=lambda x:x['capture_id']):
            used=0
            for a in s.scalars(select(Allocation).where(Allocation.credit_id==cid)):
                for x in value.source_usage(a):
                    if x['capture_id']==source['capture_id']:used+=x['amount_minor']
            free=source['amount_minor']-used;take=min(remaining,free)
            if take>0:lines.append({'capture_id':source['capture_id'],'payment_intent_id':source['payment_intent_id'],'amount_minor':take});remaining-=take
            if free-take>0:forfeiture_lines.append({'capture_id':source['capture_id'],'payment_intent_id':source['payment_intent_id'],'amount_minor':free-take})
        if remaining:raise ValueError('CREDIT_SOURCE_ALLOCATION_RECONCILIATION_REQUIRED')
        payload={'credit_id':cid,'contract_hash':p.contract_hash,'ledger_head_hash':p.ledger_head_hash,
            'offer_id':offer.offer_id,'property_id':c.property_id,'supplier_id':offer.supplier_id,'currency':c.currency,
            'check_in':check_in,'check_out':check_out,'new_value_minor':amount,'credit_value_minor':p.available_minor,
            'applied_minor':applied,'amount_due_minor':amount-applied,'forfeited_difference_minor':p.available_minor-applied,
            'credit_lines':lines,'forfeiture_lines':forfeiture_lines,'lower_price_no_refund_no_balance':True,'terms':deepcopy(p.contract_json['terms'])}
        return quote(s,'REDEEM',c.original_order_id,cid,payload)


def allocation_public(a):
    return {'stay_credit_id':a.credit_id,'order_id':a.order_id,'status':'REDEEMED' if a.state=='ACTIVE' else a.state,
        'supplier_confirmation_no':a.supplier_confirmation_no,'amount_due_minor':a.cash_due_minor,
        'applied_minor':a.applied_minor,'forfeited_difference_minor':a.forfeited_minor,
        'quote_hash':a.request_json['quote_hash'],'data_mode':'SIMULATION','external_live':False,
        'customer_cancellation':{'cash_refund_minor':a.after_sales_json['cash_refund_minor'],'restored_credit_minor':a.restored_minor,
            'fee_minor':a.after_sales_json['fee_minor'],'quote_hash':a.after_sales_json['quote_hash'],'state':a.state} if a.after_sales_json else None}


def failed(s,a,c,p,actor,reason):
    a.state='FAILED';a.updated_at=now();restored=a.applied_minor+a.forfeited_minor
    a.restored_minor=a.applied_minor;a.forfeited_minor=0;c.status='ACTIVE'
    order=s.get(Order,a.order_id)
    if order:order.status='FAILED';order.version+=1;order.updated_at=now()
    value.journal(s,c,p,'FAILED_REDEMPTION_RESTORED',restored,a.order_id,{'reason':reason},actor)
    value.expire(s,c,p,actor)


def lock_allocation(s,oid):
    probe=s.get(Allocation,oid)
    if not probe:raise ValueError('CREDIT_REDEMPTION_NOT_FOUND')
    c,p=value.checked(s,probe.credit_id)
    a=s.get(Allocation,oid,with_for_update=True,populate_existing=True)
    return a,c,p


def payment_outcome(token):
    if token not in {'pm_success','pm_decline','pm_capture_fail'}:raise ValueError('ISOLATED_PAYMENT_TEST_TOKEN_REQUIRED')
    return {'pm_success':'SUCCESS','pm_decline':'DECLINED','pm_capture_fail':'CAPTURE_FAILED'}[token]


def release_traveler(account,traveler_id,consent_id):
    from go_hotel.services.personal_travel_vault import personal_travel_vault_service
    from go_hotel.security.crypto import encrypt_secret
    if not traveler_id:raise ValueError('EXPLICIT_HOTEL_TRAVELER_REQUIRED')
    if not consent_id:raise ValueError('CURRENT_TRAVELER_HOTEL_CONSENT_REQUIRED')
    from go_hotel.services.hosted_stay_credit import booking_consent
    with SessionLocal() as s:booking_consent(s,account,traveler_id,consent_id)
    r=personal_travel_vault_service.release(account,{'traveler_id':traveler_id,'requested_fields':['LEGAL_NAME','MOBILE'],
        'vertical':'HOTEL','purpose':'HOTEL_BOOKING','destination':'HOTEL_BOOKING_ADAPTER'},requester_id=account)
    fields=r['released_fields']
    if not fields.get('LEGAL_NAME') or not fields.get('MOBILE'):raise ValueError('HOTEL_GUEST_NAME_AND_CONTACT_REQUIRED')
    return {'traveler_id':traveler_id,'release_id':r['release_id'],'consent_id':consent_id,
        'guest_ciphertext':encrypt_secret(json.dumps({'full_name':fields['LEGAL_NAME'],'mobile':fields['MOBILE']},ensure_ascii=False))}


def verify_traveler(s,account,profile):
    if not profile:return
    from go_hotel.db.models import TravelerProfileRow,ProfileTravelerPermissionRow,ProfileConsentRow,ProfileDataReleaseAuditRow
    t=s.get(TravelerProfileRow,profile['traveler_id']);r=s.get(ProfileDataReleaseAuditRow,profile['release_id'])
    perms={x.permission_type:x.allowed for x in s.scalars(select(ProfileTravelerPermissionRow).where(ProfileTravelerPermissionRow.user_id==account,ProfileTravelerPermissionRow.traveler_id==profile['traveler_id']))}
    if not t or t.user_id!=account or t.status!='ACTIVE' or not t.booking_permission or not perms.get('USE_FOR_BOOKING',t.relationship_type=='SELF'):raise ValueError('CURRENT_HOTEL_TRAVELER_PERMISSION_REQUIRED')
    if not r or (r.user_id,r.traveler_id,r.decision,r.purpose,r.destination)!=(account,t.traveler_id,'ALLOW','HOTEL_BOOKING','HOTEL_BOOKING_ADAPTER'):raise ValueError('CURRENT_HOTEL_TRAVELER_RELEASE_REQUIRED')
    if not {'LEGAL_NAME','MOBILE'}.issubset(r.released_fields_json):raise ValueError('HOTEL_GUEST_NAME_AND_CONTACT_REQUIRED')
    if profile.get('consent_id'):
        from go_hotel.services.hosted_stay_credit import booking_consent
        booking_consent(s,account,t.traveler_id,profile['consent_id'])
        if not perms.get('SENSITIVE_DATA',t.relationship_type=='SELF') or t.relationship_type=='CHILD' and t.guardian_consent_status not in {'GRANTED','ACTIVE'}:raise ValueError('CURRENT_HOTEL_TRAVELER_SENSITIVE_PERMISSION_REQUIRED')
        consent=s.get(ProfileConsentRow,profile['consent_id'])
        if not consent or consent.user_id!=account or consent.traveler_id!=t.traveler_id or consent.status!='ACTIVE' or consent.revoked_at or not consent.expires_at or aware(consent.expires_at)<=now():raise ValueError('CURRENT_HOTEL_TRAVELER_CONSENT_REQUIRED')


async def redeem(cid,qid,expected_hash,consent,token,actor,profile_release=None):
    funds.require_isolated();outcome=payment_outcome(token)
    with transaction() as s:
        c,p=value.checked(s,cid)
        q=checked_quote(s,qid,'REDEEM',expected_hash,consent,allow_expired=True)
        if q.credit_id!=cid:raise ValueError('STAY_CREDIT_QUOTE_NOT_FOUND')
        old=s.scalar(select(Allocation).where(Allocation.quote_id==qid))
        if old:
            if old.request_json['actor_id']!=actor or old.request_json['payment_outcome']!=outcome or (old.request_json.get('profile_release') or {}).get('traveler_id')!=(profile_release or {}).get('traveler_id'):raise ValueError('CREDIT_REDEMPTION_REQUEST_CONFLICT')
            return allocation_public(old)
        verify_traveler(s,c.account_id,profile_release)
        value.active(c,p)
        if aware(q.expires_at)<=now():raise ValueError('STAY_CREDIT_QUOTE_EXPIRED')
        b=q.payload_json
        if b['contract_hash']!=p.contract_hash or b['ledger_head_hash']!=p.ledger_head_hash or b['credit_value_minor']!=p.available_minor:raise ValueError('CREDIT_QUOTE_STALE_REQUOTE_REQUIRED')
        if date.fromisoformat(b['check_in'])<=now().date() or date.fromisoformat(b['check_in'])>aware(c.expires_at).date():raise ValueError('CREDIT_STAY_DATES_OUTSIDE_VALIDITY')
        offer=s.get(OfferRow,b['offer_id'])
        if not offer or (offer.hotel_id,offer.supplier_id,offer.total_amount_minor,offer.currency,offer.check_in,offer.check_out)!=(c.property_id,b['supplier_id'],b['new_value_minor'],c.currency,b['check_in'],b['check_out']):raise ValueError('CREDIT_REDEMPTION_OFFER_CHANGED')
        conn=remedy.connector(s,s.get(Order,c.original_order_id));domain_offer=repo._offer(offer)
        oid=ident('ord');request={**deepcopy(b),'quote_hash':expected_hash,'actor_id':actor,'payment_outcome':outcome,'booking_key':'credit-book:'+oid,'prebook_key':'credit-prebook:'+oid}
        if profile_release:request['profile_release']=profile_release
        a=Allocation(order_id=oid,credit_id=cid,quote_id=qid,state='PREBOOK_PENDING',request_json=request,request_hash=digest(request),
            applied_minor=b['applied_minor'],forfeited_minor=b['forfeited_difference_minor'],restored_minor=0,refunded_minor=0,
            cash_due_minor=b['amount_due_minor'],created_at=now(),updated_at=now())
        s.add(a);c.status='REDEMPTION_PENDING';s.flush()
        value.journal(s,c,p,'REDEMPTION_VALUE_RESERVED',-p.available_minor,oid,{'quote_hash':expected_hash,'applied_minor':a.applied_minor,'forfeited_minor':a.forfeited_minor},actor)
        if outcome=='DECLINED' and a.cash_due_minor:
            failed(s,a,c,p,actor,'PAYMENT_AUTHORIZATION_DECLINED');return allocation_public(a)
    try:pb=await conn.prebook_with_key(domain_offer,'credit-prebook:'+oid)
    except BaseException as exc:
        with transaction() as s:
            a,c,p=lock_allocation(s,oid);a.state='UNKNOWN_PREBOOK';response=allocation_public(a)
        if isinstance(exc,Exception):return response
        raise
    with transaction() as s:
        a,c,p=lock_allocation(s,oid);commit_prebook(s,a,c,p,pb,actor)
    return await resume_redemption(oid,actor)


def commit_prebook(s,a,c,p,pb,actor):
    if a.state not in {'PREBOOK_PENDING','UNKNOWN_PREBOOK'}:return
    b=a.request_json
    if pb.status.value!='PREBOOKED' or (pb.offer_id,pb.total_amount_minor,pb.currency)!=(b['offer_id'],b['new_value_minor'],c.currency) or aware(pb.expires_at)<=now():
        failed(s,a,c,p,actor,'PREBOOK_INVENTORY_PRICE_OR_EXPIRY_CHANGED');return
    s.add(PrebookRow(prebook_id=pb.prebook_id,offer_id=pb.offer_id,total_amount_minor=pb.total_amount_minor,currency=pb.currency,status=pb.status.value,
        expires_at=pb.expires_at,created_at=now(),hold_type=pb.hold_type,inventory_held=pb.inventory_held,price_locked=pb.price_locked,fare_rule_id=pb.fare_rule_id))
    s.add(Order(order_id=a.order_id,prebook_id=pb.prebook_id,hotel_id=c.property_id,account_id=c.account_id,total_amount_minor=b['new_value_minor'],
        currency=c.currency,status='BOOKING_PENDING',supplier_id=p.contract_json['supplier_id'],version=1,created_at=now(),updated_at=now()))
    a.state='PAYMENT_PENDING';a.updated_at=now();s.flush()
    remedy.event(s,a.order_id,'STAY_CREDIT_REDEMPTION_PREBOOKED',actor,{'credit_id':c.stay_credit_id,'quote_hash':b['quote_hash']})


async def resume_redemption(oid,actor):
    funds.require_isolated();dispatch=False
    with transaction() as s:
        a,c,p=lock_allocation(s,oid)
        if a.state not in {'PAYMENT_PENDING','CAPTURE_PENDING'}:return allocation_public(a)
        if a.state=='PAYMENT_PENDING':
            try:verify_traveler(s,c.account_id,a.request_json.get('profile_release'))
            except ValueError:
                failed(s,a,c,p,actor,'TRAVELER_PERMISSION_CHANGED_BEFORE_BOOKING');return allocation_public(a)
            order=s.get(Order,oid);pb=s.get(PrebookRow,order.prebook_id)
            if aware(pb.expires_at)<=now():
                failed(s,a,c,p,actor,'PREBOOK_EXPIRED');return allocation_public(a)
            from go_hotel.services.catalog_credit_money import prepare
            a.payment_json=prepare(s,a,c,p)
            conn=remedy.connector(s,order);prebook=repo._prebook(pb);key=a.request_json['booking_key']
            a.state='BOOK_PENDING';a.updated_at=now();dispatch=True
            remedy.event(s,oid,'STAY_CREDIT_SUPPLIER_BOOK_PLANNED',actor,{'credit_id':c.stay_credit_id,'booking_key':key})
    if dispatch:
        try:
            if a.request_json.get('profile_release'):
                from go_hotel.security.crypto import decrypt_secret
                guest=json.loads(decrypt_secret(a.request_json['profile_release']['guest_ciphertext']))
                confirmation=await conn.book_credit(oid,prebook,guest,idempotency_key=key)
            else:confirmation=await conn.book(oid,prebook,idempotency_key=key)
        except BaseException as exc:
            with transaction() as s:
                a,c,p=lock_allocation(s,oid);a.state='UNKNOWN_BOOK';a.updated_at=now();response=allocation_public(a)
            if isinstance(exc,Exception):return response
            raise
        with transaction() as s:
            a,c,p=lock_allocation(s,oid)
            if a.state in {'BOOK_PENDING','UNKNOWN_BOOK'}:
                a.supplier_confirmation_no=confirmation;a.state='CAPTURE_PENDING';a.updated_at=now()
    return finish_redemption(oid,actor)


def finish_redemption(oid,actor):
    from go_hotel.services.catalog_credit_money import capture
    with transaction() as s:
        a,c,p=lock_allocation(s,oid)
        if a.state!='CAPTURE_PENDING':return allocation_public(a)
        if not a.supplier_confirmation_no:raise ValueError('CONFIRMED_CREDIT_BOOKING_REQUIRED')
        if a.cash_due_minor and (a.payment_json or {}).get('outcome',a.request_json['payment_outcome'])!='SUCCESS':return allocation_public(a)
        capture(s,a);order=s.get(Order,oid)
        order.status='CONFIRMED';order.supplier_confirmation_no=a.supplier_confirmation_no;order.version+=1;order.updated_at=now()
        a.state='ACTIVE';a.updated_at=now();c.status='REDEEMED';c.redemption_order_id=oid;c.redeemed_at=now()
        value.journal(s,c,p,'REDEMPTION_CONFIRMED',0,oid,{'supplier_confirmation_no':a.supplier_confirmation_no,'cash_minor':a.cash_due_minor},actor)
        remedy.event(s,oid,'STAY_CREDIT_REDEEMED',actor,{'credit_id':c.stay_credit_id,'applied_minor':a.applied_minor,'cash_minor':a.cash_due_minor})
        return allocation_public(a)


async def reconcile_redemption(oid,actor):
    funds.require_isolated()
    with transaction() as s:
        a,c,p=lock_allocation(s,oid);phase=a.state
        conn=remedy.connector(s,s.get(Order,c.original_order_id));b=deepcopy(a.request_json)
    if phase in {'PREBOOK_PENDING','UNKNOWN_PREBOOK'}:
        pb=await conn.lookup_prebook(b['prebook_key'])
        if pb:
            with transaction() as s:
                a,c,p=lock_allocation(s,oid);commit_prebook(s,a,c,p,pb,actor)
    elif phase in {'BOOK_PENDING','UNKNOWN_BOOK'}:
        observed=await conn.lookup_booking(b['booking_key'])
        with transaction() as s:
            a,c,p=lock_allocation(s,oid)
            if a.state in {'BOOK_PENDING','UNKNOWN_BOOK'}:
                if observed['status']=='CONFIRMED':a.supplier_confirmation_no=observed['confirmation'];a.state='CAPTURE_PENDING'
                elif observed['status']=='REJECTED':
                    from go_hotel.services.catalog_credit_money import release
                    a.state='FAILED';release(s,a);failed(s,a,c,p,actor,'CONFIRMED_SUPPLIER_BOOKING_REJECTION')
    return await resume_redemption(oid,actor)


def retry_payment(oid,expected_hash,consent,token,actor):
    funds.require_isolated();outcome=payment_outcome(token)
    with transaction() as s:
        a,c,p=lock_allocation(s,oid)
        if a.state!='CAPTURE_PENDING' or consent is not True or expected_hash!=a.request_json['quote_hash']:raise ValueError('CURRENT_CREDIT_DIFFERENCE_CONSENT_REQUIRED')
        a.payment_json={**(a.payment_json or {}),'outcome':outcome}
        remedy.event(s,oid,'STAY_CREDIT_DIFFERENCE_RETRY_CONSENT',actor,{'amount_minor':a.cash_due_minor,'quote_hash':expected_hash,'simulation_outcome':outcome})
    if outcome!='SUCCESS':
        with SessionLocal() as s:return allocation_public(s.get(Allocation,oid))
    return finish_redemption(oid,actor)
