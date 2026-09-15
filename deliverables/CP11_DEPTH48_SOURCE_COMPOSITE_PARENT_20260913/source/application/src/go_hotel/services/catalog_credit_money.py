"""Isolated cash difference has its own root; prepaid credit is never recaptured."""
from sqlalchemy import select
from go_hotel.db.models import (OmnichannelPaymentIntentRow as Intent,PaymentOrderRootRow as Root,
    PaymentOrderFactBindingRow as Binding,OmnichannelMoneyMovementRow as Movement)
from go_hotel.services.hosted_direct_booking import ident,now
from go_hotel.services.omnichannel_payment import digest
from go_hotel.services.hosted_money import money


def prepare(s,a,c,p):
    if not a.cash_due_minor:return None
    source=p.contract_json['sources'][0]
    old=s.scalar(select(Root).where(Root.business_type=='CREDIT_DIFF',Root.business_id==a.order_id))
    if old:raise ValueError('CREDIT_DIFFERENCE_ROOT_RECONCILIATION_REQUIRED')
    binding=s.scalar(select(Binding).where(Binding.payment_intent_id==source['payment_intent_id']))
    root=s.scalar(select(Root).where(Root.payment_intent_id==source['payment_intent_id']))
    if not binding or not root:raise ValueError('CREDIT_ORIGINAL_SOURCE_BINDING_REQUIRED')
    iid=ident('opi');t=now();key='credit-diff:'+a.order_id
    fact={'business_type':'CREDIT_DIFF','business_id':a.order_id,'payer_id':c.account_id,'payee_id':p.contract_json['supplier_id'],
        'amount_minor':a.cash_due_minor,'currency':c.currency,'credit_quote_hash':a.request_json['quote_hash'],'source_decision_id':binding.source_decision_id,'data_mode':'SIMULATION'}
    s.add(Intent(payment_intent_id=iid,business_type='CREDIT_DIFF',business_id=a.order_id,payer_id=c.account_id,payee_id=fact['payee_id'],
        operation='PAY',amount_minor=a.cash_due_minor,currency=c.currency,channel_priority_json=['LOCAL_MARKET'],selected_channel='LOCAL_MARKET',
        state='SUCCEEDED',idempotency_key=key+':intent',automatic_fallback_allowed=False,user_channel_consent_at=t,created_at=t,updated_at=t))
    s.flush()
    s.add(Root(payment_order_root_id=ident('por'),business_type='CREDIT_DIFF',business_id=a.order_id,payment_intent_id=iid,legal_entity_id=root.legal_entity_id,
        state='ACTIVE',root_hash=digest({'business_type':'CREDIT_DIFF','business_id':a.order_id,'payment_intent_id':iid,'legal_entity_id':root.legal_entity_id}),created_at=t))
    s.add(Binding(payment_order_fact_binding_id=ident('pofb'),payment_intent_id=iid,business_type='CREDIT_DIFF',business_id=a.order_id,
        payer_id=c.account_id,payee_id=fact['payee_id'],amount_minor=a.cash_due_minor,currency=c.currency,legal_entity_id=root.legal_entity_id,
        source_decision_id=binding.source_decision_id,request_fingerprint=digest(fact),order_fact_hash=digest(fact),evidence_reference='credit-quote://'+a.quote_id,created_at=t))
    s.flush()
    auth=money.create_in_session(s,iid,{'movement_type':'AUTHORIZATION','amount_minor':a.cash_due_minor,'mode':'CONTRACT_SIMULATOR',
        'evidence':['credit-quote://'+a.quote_id]},key+':auth','catalog-credit')
    return {'payment_intent_id':iid,'authorization_id':auth['money_movement_id'],'outcome':a.request_json['payment_outcome']}


def capture(s,a):
    if not a.cash_due_minor:return
    p=a.payment_json
    if not p:raise ValueError('CREDIT_DIFFERENCE_AUTHORIZATION_REQUIRED')
    i=s.get(Intent,p['payment_intent_id'])
    if not i or (i.business_type,i.business_id,i.amount_minor)!=('CREDIT_DIFF',a.order_id,a.cash_due_minor):raise ValueError('CREDIT_DIFFERENCE_FACT_MISMATCH')
    return money.create_in_session(s,i.payment_intent_id,{'movement_type':'CAPTURE','parent_movement_id':p['authorization_id'],
        'amount_minor':a.cash_due_minor,'mode':'CONTRACT_SIMULATOR','evidence':['credit-booking://'+a.order_id+'/'+a.supplier_confirmation_no]},
        'credit-diff:'+a.order_id+':cap','catalog-credit')


def release(s,a):
    if not a.cash_due_minor or not a.payment_json:return
    p=a.payment_json
    return money.create_in_session(s,p['payment_intent_id'],{'movement_type':'RELEASE','parent_movement_id':p['authorization_id'],
        'amount_minor':a.cash_due_minor,'mode':'CONTRACT_SIMULATOR','evidence':['credit-booking-rejected://'+a.order_id]},
        'credit-diff:'+a.order_id+':release','catalog-credit')
