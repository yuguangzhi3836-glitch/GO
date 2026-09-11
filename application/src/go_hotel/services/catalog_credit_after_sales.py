"""Customer cancellation of a credit redemption preserves original value and expiry."""
from copy import deepcopy
from datetime import datetime,timezone
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (CatalogCreditAllocationRow as Allocation,OrderRow as Order,
    CatalogCreditQuoteRow as Quote,OmnichannelMoneyMovementRow as Movement,SupplierFaultCaseRow as Case)
from go_hotel.services.alipay_safeguarded_settlement import transaction
from go_hotel.services.hosted_direct_booking import now
from go_hotel.services.omnichannel_payment import digest
from go_hotel.services.hosted_reservation_operations import aware
from go_hotel.services import catalog_credit_value as value,catalog_stay_credit as credit,catalog_supplier_remedy as remedy,hosted_money as funds


def facts(s,a,c,p):
    order=s.get(Order,a.order_id,with_for_update=True)
    if a.state!='ACTIVE' or not order or order.status!='CONFIRMED':raise ValueError('ACTIVE_CREDIT_BOOKING_REQUIRED')
    if s.scalar(select(Case).where(Case.order_id==a.order_id)):raise ValueError('SUPPLIER_REMEDY_ORDER_FROZEN')
    roots=remedy.roots(s,order)
    moves=s.scalars(select(Movement).where(Movement.root_payment_intent_id.in_([r.payment_intent_id for r in roots]))).all()
    if any(m.state!='CONFIRMED' for m in moves) or any(m.movement_type in {'REFUND','COMPENSATION'} for m in moves):raise ValueError('CREDIT_CANCELLATION_MONEY_RECONCILIATION_REQUIRED')
    caps=[m for m in moves if m.movement_type=='CAPTURE']
    if sum(m.amount_minor for m in caps)!=a.cash_due_minor:raise ValueError('CREDIT_DIFFERENCE_CAPTURE_REQUIRED')
    return order,caps


def accepted_fee_terms(order,a,p,at):
    from go_hotel.services.catalog_fare_snapshot import cancellation_terms
    rules=p.contract_json['rule_snapshot'].get('rules')
    if not rules:
        tiers=p.contract_json['terms']['cancellation_fee_tiers']
        if not isinstance(tiers,list) or not tiers or any(type(x.get('min_hours')) is not int or type(x.get('fee_percent')) is not int or not 0<=x['fee_percent']<=100 for x in tiers):raise ValueError('VALID_ACCEPTED_CANCELLATION_TIERS_REQUIRED')
        rules={'timezone':'UTC','check_in_hour':0,'cooling_off_minutes':0,'no_show_grace_hours':0,
            'cancellation_tiers':[{'min_hours':x['min_hours'],'fee_basis_points':x['fee_percent']*100} for x in tiers]}
    return cancellation_terms(order,a.request_json['check_in'],{'rules':rules,'order_created_at':aware(order.created_at).isoformat()},at)


def cancellation_quote(oid):
    funds.require_isolated()
    with transaction() as s:
        a,c,p=credit.lock_allocation(s,oid);order,caps=facts(s,a,c,p)
        terms=accepted_fee_terms(order,a,p,now());bps=terms['fee_basis_points'];pct=bps/100
        paid=a.applied_minor+a.cash_due_minor;fee=paid*bps//10000;credit_fee=min(fee,a.applied_minor)
        restore=a.applied_minor-credit_fee;cash_refund=a.cash_due_minor-(fee-credit_fee);remaining=cash_refund;lines=[]
        for cap in sorted(caps,key=lambda x:x.money_movement_id):
            amount=min(remaining,cap.amount_minor);remaining-=amount
            if amount:lines.append({'capture_id':cap.money_movement_id,'payment_intent_id':cap.root_payment_intent_id,'amount_minor':amount})
        b={'order_id':oid,'credit_id':c.stay_credit_id,'order_version':order.version,'supplier_confirmation_no':order.supplier_confirmation_no,
            'credit_contract_hash':p.contract_hash,'credit_request_hash':a.request_hash,'paid_amount_minor':paid,'fee_minor':fee,'fee_percent':pct,'fee_basis_points':bps,
            'currency':c.currency,'restore_credit_minor':restore,'cash_refund_minor':cash_refund,'cash_refund_lines':lines,
            'original_credit_expires_at':aware(c.expires_at).isoformat(),'forfeited_difference_minor':a.forfeited_minor,
            'check_in_reference':terms['check_in_at'],'hotel_timezone':terms['hotel_timezone'],
            'cooling_off_applied':terms['cooling_off_applied'],'rule_snapshot':deepcopy(p.contract_json['terms'])}
        return credit.quote(s,'CANCEL_REDEMPTION',oid,c.stay_credit_id,b,expires_at=terms['expires_at'])


def public(a,c,p):
    b=a.after_sales_json
    return {'order_id':a.order_id,'stay_credit_id':a.credit_id,'state':a.state,'status':a.state,
        'cancellation_fee_minor':b['fee_minor'] if b else None,'cash_refund_minor':b['cash_refund_minor'] if b else None,
        'restored_credit_minor':a.restored_minor,'available_credit_minor':p.available_minor if c.status=='ACTIVE' and aware(c.expires_at)>now() else 0,
        'original_credit_expires_at':aware(c.expires_at).isoformat(),'quote_hash':b['quote_hash'] if b else None,
        'refund_state':'COMPLETED' if a.state=='CANCELLED' else 'PENDING','data_mode':'SIMULATION','external_live':False}


async def cancel(oid,qid,expected_hash,consent,actor):
    funds.require_isolated();dispatch=False
    with transaction() as s:
        a,c,p=credit.lock_allocation(s,oid)
        q=credit.checked_quote(s,qid,'CANCEL_REDEMPTION',expected_hash,consent,allow_expired=True)
        if q.order_id!=oid or q.credit_id!=a.credit_id:raise ValueError('CREDIT_CANCELLATION_QUOTE_NOT_FOUND')
        if a.after_sales_json:
            if a.after_sales_json['quote_id']!=qid or a.after_sales_json['actor_id']!=actor:raise ValueError('CREDIT_CANCELLATION_REQUEST_CONFLICT')
            if a.state in {'CANCEL_PENDING','UNKNOWN_CANCEL','CANCELLED'}:return public(a,c,p)
        else:
            if aware(q.expires_at)<=now():raise ValueError('STAY_CREDIT_QUOTE_EXPIRED')
            order,_=facts(s,a,c,p);b=q.payload_json
            if (order.version,order.supplier_confirmation_no,p.contract_hash,a.request_hash)!=(b['order_version'],b['supplier_confirmation_no'],b['credit_contract_hash'],b['credit_request_hash']):raise ValueError('CREDIT_CANCELLATION_QUOTE_STALE')
            # A quote expiring across a fee boundary cannot silently retain a cheaper fee.
            applicable=accepted_fee_terms(order,a,p,now())
            if applicable['fee_basis_points']!=b.get('fee_basis_points',b['fee_percent']*100):raise ValueError('CREDIT_CANCELLATION_FEE_CHANGED_REQUOTE_REQUIRED')
            a.after_sales_json={**deepcopy(b),'quote_id':qid,'quote_hash':expected_hash,'actor_id':actor};a.after_sales_hash=digest(a.after_sales_json)
            a.state='CANCEL_PENDING';a.updated_at=now();dispatch=True;conn=remedy.connector(s,order);confirmation=order.supplier_confirmation_no
            remedy.event(s,oid,'CREDIT_CUSTOMER_CANCEL_PLANNED',actor,{'quote_id':qid,'quote_hash':expected_hash})
    if dispatch:
        try:result=await conn.cancel(confirmation)
        except BaseException as exc:
            with transaction() as s:
                a,c,p=credit.lock_allocation(s,oid);a.state='UNKNOWN_CANCEL';a.updated_at=now();response=public(a,c,p)
            if isinstance(exc,Exception):return response
            raise
        with transaction() as s:
            a,c,p=credit.lock_allocation(s,oid)
            if result=='CANCELLED':cancel_commit(s,a,actor)
            else:a.state='UNKNOWN_CANCEL';return public(a,c,p)
    return complete(oid,actor)


def cancel_commit(s,a,actor):
    if a.state not in {'CANCEL_PENDING','UNKNOWN_CANCEL'}:return
    order=s.get(Order,a.order_id)
    order.status='CANCELLED';order.version+=1;order.updated_at=now();a.state='CANCEL_REFUND_PENDING';a.updated_at=now()
    remedy.event(s,a.order_id,'CREDIT_CUSTOMER_CANCEL_CONFIRMED',actor,{'quote_id':a.after_sales_json['quote_id']})


def complete(oid,actor):
    with transaction() as s:
        a,c,p=credit.lock_allocation(s,oid)
        if a.state=='CANCELLED':return public(a,c,p)
        if a.state!='CANCEL_REFUND_PENDING':raise ValueError('CONFIRMED_CUSTOMER_CREDIT_CANCEL_REQUIRED')
        b=a.after_sales_json
        for line in b['cash_refund_lines']:
            funds.money.create_in_session(s,line['payment_intent_id'],{'movement_type':'REFUND','parent_movement_id':line['capture_id'],
                'amount_minor':line['amount_minor'],'mode':'CONTRACT_SIMULATOR','evidence':['credit-customer-cancel://'+oid+'/'+b['quote_hash']]},
                'credit-cancel:'+oid+':'+line['capture_id'],'catalog-credit')
        restore=b['restore_credit_minor'];a.restored_minor=restore;a.state='CANCELLED';a.updated_at=now();c.status='ACTIVE' if restore else 'REDEEMED'
        value.journal(s,c,p,'CUSTOMER_UNUSED_CREDIT_RESTORED',restore,oid,{'fee_minor':b['fee_minor'],'cash_refund_minor':b['cash_refund_minor'],'original_expiry':b['original_credit_expires_at']},actor)
        value.expire(s,c,p,actor);value.checked(s,c.stay_credit_id)
        remedy.event(s,oid,'CREDIT_CUSTOMER_REFUND_COMPLETED',actor,{'quote_hash':b['quote_hash'],'cash_refund_minor':b['cash_refund_minor'],'restored_credit_minor':restore})
        return public(a,c,p)


async def reconcile(oid,actor):
    funds.require_isolated()
    with transaction() as s:
        a,c,p=credit.lock_allocation(s,oid)
        if a.state=='CANCELLED':return public(a,c,p)
        phase=a.state
        if phase not in {'CANCEL_PENDING','UNKNOWN_CANCEL','CANCEL_REFUND_PENDING'}:raise ValueError('CREDIT_CANCELLATION_RECONCILIATION_NOT_REQUIRED')
        order=s.get(Order,oid);conn=remedy.connector(s,order);confirmation=order.supplier_confirmation_no
    if phase in {'CANCEL_PENDING','UNKNOWN_CANCEL'}:
        observed=await conn.status(confirmation)
        with transaction() as s:
            a,c,p=credit.lock_allocation(s,oid)
            if observed=='CANCELLED':cancel_commit(s,a,actor)
            else:return public(a,c,p)
    return complete(oid,actor)
