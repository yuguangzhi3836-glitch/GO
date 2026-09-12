"""Catalog prepaid value remains allocated to confirmed original cash captures."""
from sqlalchemy import select
from go_hotel.db.models import (StayCreditRow as Credit,CatalogCreditContractRow as Contract,
    CatalogCreditSourceRow as Source,CatalogCreditAllocationRow as Allocation,CatalogCreditValueEventRow as Journal,
    OrderRow,OmnichannelMoneyMovementRow as Movement,OmnichannelPaymentIntentRow as Intent,
    CatalogSupplierRemedyRow as Remedy,SupplierFaultCaseRow as Case)
from go_hotel.services.hosted_direct_booking import ident,now
from go_hotel.services.hosted_reservation_operations import aware
from go_hotel.services.omnichannel_payment import digest

PENDING_CONVERSION={'CANCEL_PENDING','UNKNOWN_CANCEL'}
PENDING_REDEMPTION={'PREBOOK_PENDING','UNKNOWN_PREBOOK','PAYMENT_PENDING','BOOK_PENDING','UNKNOWN_BOOK','CAPTURE_PENDING'}


def journal(s,c,p,kind,delta,order_id,evidence,actor):
    previous=s.scalar(select(Journal).where(Journal.credit_id==c.stay_credit_id).order_by(Journal.generation.desc()))
    number=previous.generation+1 if previous else 1;prior=previous.event_hash if previous else None
    balance=p.available_minor+delta
    if prior!=p.ledger_head_hash or not 0<=balance<=c.credit_value_minor:raise ValueError('CREDIT_VALUE_LEDGER_MISMATCH')
    payload=[c.stay_credit_id,number,kind,delta,balance,order_id,evidence,actor,prior]
    row=Journal(event_id=ident('ccve'),credit_id=c.stay_credit_id,generation=number,event_type=kind,
        delta_minor=delta,balance_after_minor=balance,order_id=order_id,evidence_json=evidence,
        previous_hash=prior,event_hash=digest(payload),actor_id=actor,created_at=now())
    s.add(row);p.available_minor=balance;p.ledger_head_hash=row.event_hash;p.updated_at=now();s.flush()


def checked(s,cid,account=None):
    probe=s.get(Credit,cid)
    if not probe or account is not None and probe.account_id!=account:raise ValueError('STAY_CREDIT_NOT_FOUND')
    s.get(OrderRow,probe.original_order_id,with_for_update=True)
    c=s.get(Credit,cid,with_for_update=True,populate_existing=True)
    p=s.get(Contract,cid,with_for_update=True,populate_existing=True)
    if not p:raise ValueError('HISTORICAL_CREDIT_CONTRACT_RECONCILIATION_REQUIRED')
    b=p.contract_json
    if digest(b)!=p.contract_hash or (c.original_order_id,c.account_id,c.property_id,c.currency,c.credit_value_minor)!=(p.original_order_id,b['account_id'],b['property_id'],b['currency'],b['credit_value_minor']):raise ValueError('CREDIT_CONTRACT_MISMATCH')
    if aware(c.expires_at).isoformat()!=b['credit_expires_at'] or aware(c.valid_from).isoformat()!=b['valid_from']:raise ValueError('CREDIT_ORIGINAL_VALIDITY_CHANGED')
    sources=s.scalars(select(Source).where(Source.credit_id==cid).order_by(Source.capture_id)).all()
    expected={x['capture_id']:x for x in b['sources']}
    facts=[{'capture_id':x.capture_id,'payment_intent_id':x.payment_intent_id,'amount_minor':x.funded_minor,'prior_refund_minor':x.prior_refund_minor,
        **({'excluded_minor':x.excluded_minor} if 'excluded_minor' in expected.get(x.capture_id,{}) else {})} for x in sources]
    if facts!=sorted(b['sources'],key=lambda x:x['capture_id']):raise ValueError('CREDIT_SOURCE_ALLOCATION_MISMATCH')
    if sum(x.funded_minor for x in sources)!=c.credit_value_minor or any(min(x.funded_minor,x.prior_refund_minor,x.excluded_minor)<0 for x in sources):raise ValueError('CREDIT_SOURCE_VALUE_MISMATCH')
    if any(x.excluded_minor and 'excluded_minor' not in expected[x.capture_id] for x in sources):raise ValueError('CREDIT_SOURCE_EXCLUSION_MISMATCH')
    from go_hotel.services.catalog_credit_source_allocation import check_evidence
    check_evidence(s,b)
    if sum(x.excluded_minor for x in sources)!=(b.get('cash_change_forfeiture') or {}).get('excluded_minor',0):raise ValueError('CREDIT_SOURCE_EXCLUSION_MISMATCH')
    current_refunds=0
    for source in sources:
        intent=s.get(Intent,source.payment_intent_id,with_for_update=True)
        cap=s.get(Movement,source.capture_id)
        if not cap or cap.state!='CONFIRMED' or cap.movement_type!='CAPTURE' or cap.root_payment_intent_id!=source.payment_intent_id or cap.currency!=c.currency or cap.amount_minor!=source.funded_minor+source.prior_refund_minor+source.excluded_minor:raise ValueError('CREDIT_CAPTURE_FACT_MISMATCH')
        if not intent or (intent.payer_id,intent.payee_id,intent.currency,intent.state)!=(c.account_id,b['supplier_id'],c.currency,'SUCCEEDED'):raise ValueError('CREDIT_PAYMENT_OWNER_MISMATCH')
        moves=s.scalars(select(Movement).where(Movement.root_payment_intent_id==source.payment_intent_id)).all()
        if any(m.state!='CONFIRMED' for m in moves):raise ValueError('CREDIT_PAYMENT_RECONCILIATION_REQUIRED')
        refunded=sum(m.amount_minor for m in moves if m.parent_movement_id==source.capture_id and m.movement_type in {'REFUND','COMPENSATION'})
        if not source.prior_refund_minor<=refunded<=source.prior_refund_minor+source.funded_minor:raise ValueError('CREDIT_SOURCE_REFUND_MISMATCH')
        current_refunds+=refunded-source.prior_refund_minor
    history=s.scalars(select(Journal).where(Journal.credit_id==cid).order_by(Journal.generation)).all()
    balance=0;previous=None
    for number,e in enumerate(history,1):
        balance+=e.delta_minor
        payload=[cid,number,e.event_type,e.delta_minor,balance,e.order_id,e.evidence_json,e.actor_id,previous]
        if e.generation!=number or e.previous_hash!=previous or e.event_hash!=digest(payload) or e.balance_after_minor!=balance or not 0<=balance<=c.credit_value_minor:raise ValueError('CREDIT_VALUE_LEDGER_MISMATCH')
        previous=e.event_hash
    if p.available_minor!=balance or p.ledger_head_hash!=previous:raise ValueError('CREDIT_VALUE_LEDGER_MISMATCH')
    allocated=forfeited=refunded=0
    for a in s.scalars(select(Allocation).where(Allocation.credit_id==cid)):
        if digest(a.request_json)!=a.request_hash or min(a.applied_minor,a.forfeited_minor,a.restored_minor,a.refunded_minor)<0 or a.restored_minor+a.refunded_minor>a.applied_minor:raise ValueError('CREDIT_REDEMPTION_FACT_MISMATCH')
        if (a.applied_minor,a.cash_due_minor)!=(a.request_json['applied_minor'],a.request_json['amount_due_minor']) or sum(x['amount_minor'] for x in a.request_json['credit_lines'])!=a.applied_minor:raise ValueError('CREDIT_REDEMPTION_AMOUNT_MISMATCH')
        if a.forfeited_minor!=(0 if a.state=='FAILED' else a.request_json['forfeited_difference_minor']):raise ValueError('CREDIT_FORFEITURE_FACT_MISMATCH')
        if a.after_sales_json and digest(a.after_sales_json)!=a.after_sales_hash:raise ValueError('CREDIT_AFTER_SALES_PLAN_MISMATCH')
        allocated+=a.applied_minor-a.restored_minor-a.refunded_minor
        forfeited+=a.forfeited_minor;refunded+=a.refunded_minor
    held=c.credit_value_minor if c.status in PENDING_CONVERSION else 0
    if balance+allocated+forfeited+refunded+p.expired_minor+held!=c.credit_value_minor or current_refunds!=refunded:raise ValueError('CREDIT_SOURCE_VALUE_CONSERVATION_FAILED')
    return c,p


def active(c,p):
    if aware(c.expires_at)<=now():raise ValueError('STAY_CREDIT_EXPIRED')
    if c.status!='ACTIVE' or p.available_minor<=0:raise ValueError('STAY_CREDIT_NOT_ACTIVE')


def expire(s,c,p,actor):
    if aware(c.expires_at)<=now() and c.status=='ACTIVE':
        lost=p.available_minor;p.expired_minor+=lost
        journal(s,c,p,'EXPIRED',-lost,None,{'original_expiry':aware(c.expires_at).isoformat()},actor)
        c.status='EXPIRED'


def public(c,p=None):
    state='EXPIRED' if c.status=='ACTIVE' and aware(c.expires_at)<=now() else c.status
    return {'stay_credit_id':c.stay_credit_id,'original_order_id':c.original_order_id,
        'property_id':c.property_id,'credit_value_minor':c.credit_value_minor,'currency':c.currency,
        'scope':'PROPERTY_ONLY','status':state,'available_minor':p.available_minor if p and state=='ACTIVE' else 0,
        'valid_from':aware(c.valid_from).isoformat(),'expires_at':aware(c.expires_at).isoformat(),
        'redemption_order_id':c.redemption_order_id,'contract_hash':p.contract_hash if p else None,
        'reconciliation_required':p is None,'terms':p.contract_json['terms'] if p else None,
        'cash_change_forfeiture':{k:v for k,v in p.contract_json['cash_change_forfeiture'].items() if k not in {'accepted_changes','evidence_hash'}} if p and p.contract_json.get('cash_change_forfeiture') else None,
        'data_mode':'SIMULATION','external_live':False}


def allowed_supplier_refund(s,intent,parent,amount,key):
    if not key.startswith('catalog-fault-refund:'):return False
    parts=key.split(':')
    if len(parts)!=3:return False
    case=s.get(Case,parts[1]);plan=s.get(Remedy,parts[1])
    if not case or not plan or case.status!='CANCELLED_REFUND_PENDING' or digest(plan.refund_lines_json)!=plan.refund_lines_hash:return False
    a=s.get(Allocation,plan.order_id)
    if not a or a.state!='REFUND_RESERVED':return False
    return any((x['capture_id'],x['payment_intent_id'],x['amount_minor'])==(parent,intent.payment_intent_id,amount) for x in plan.refund_lines_json)


def assert_money_action(s,intent,typ,amount,parent,key):
    source=s.scalar(select(Source).where(Source.payment_intent_id==intent.payment_intent_id))
    if source:
        if typ=='RELEASE':return
        if typ=='REFUND' and allowed_supplier_refund(s,intent,parent,amount,key):return
        raise ValueError('CREDIT_SOURCE_FUNDS_RESERVED')
    if intent.business_type=='CREDIT_DIFF':
        a=s.get(Allocation,intent.business_id)
        if not a:raise ValueError('CREDIT_DIFFERENCE_ALLOCATION_REQUIRED')
        prefix='credit-diff:'+a.order_id
        if typ=='AUTHORIZATION' and a.state=='PAYMENT_PENDING' and key==prefix+':auth' and amount==a.cash_due_minor:return
        if typ=='CAPTURE' and a.state=='CAPTURE_PENDING' and key==prefix+':cap' and amount==a.cash_due_minor:return
        if typ=='RELEASE' and a.state in {'FAILED','PAYMENT_CANCEL_PENDING','REFUND_RESERVED'} and key==prefix+':release':return
        if typ=='REFUND' and allowed_supplier_refund(s,intent,parent,amount,key):return
        if typ=='REFUND' and a.state=='CANCEL_REFUND_PENDING' and a.after_sales_json and digest(a.after_sales_json)==a.after_sales_hash:
            plan=a.after_sales_json
            if any((line['payment_intent_id'],line['capture_id'],line['amount_minor'],key)==(intent.payment_intent_id,parent,amount,'credit-cancel:'+a.order_id+':'+line['capture_id']) for line in plan['cash_refund_lines']):return
        raise ValueError('CREDIT_DIFFERENCE_FUNDS_RESERVED')


def source_usage(a):
    if a.state=='FAILED':return []
    retained=a.applied_minor-a.restored_minor if a.state=='CANCELLED' else a.applied_minor
    lines=[]
    for line in a.request_json['credit_lines']:
        amount=min(retained,line['amount_minor']);retained-=amount
        if amount:lines.append({**line,'amount_minor':amount})
    return lines+a.request_json.get('forfeiture_lines',[])


def allocation_lines(s,a):
    """Only the value applied to this reservation can be refunded; forfeiture is separate."""
    return a.request_json['credit_lines']


def reserve_supplier(s,order_id):
    a=s.get(Allocation,order_id)
    if not a:return
    c,p=checked(s,a.credit_id)
    if a.state!='ACTIVE':raise ValueError('CREDIT_ALLOCATION_NOT_ACTIVE')
    a.state='REFUND_RESERVED';a.updated_at=now()
    journal(s,c,p,'SUPPLIER_REFUND_RESERVED',0,order_id,{'applied_minor':a.applied_minor},'catalog-fault')


def complete_supplier(s,order_id):
    a=s.get(Allocation,order_id)
    if not a:return
    c=s.get(Credit,a.credit_id);p=s.get(Contract,a.credit_id)
    if a.state=='REFUNDED':return
    if a.state!='REFUND_RESERVED':raise ValueError('CREDIT_REFUND_RESERVATION_REQUIRED')
    a.refunded_minor=a.applied_minor-a.restored_minor;a.state='REFUNDED';a.updated_at=now()
    journal(s,c,p,'SUPPLIER_ORIGINAL_CASH_REFUNDED',0,order_id,{'refunded_minor':a.refunded_minor},'catalog-fault')
    checked(s,a.credit_id)
