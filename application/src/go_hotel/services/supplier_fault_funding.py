"""One finite-funding algorithm for independently approved hotel remedies.

Contexts preserve the source order family. They do not create substitute orders
or reuse customer captures as compensation funding.
"""
from dataclasses import dataclass
from sqlalchemy import select
from go_hotel.db.models import (SupplierFinancialAccountRow as Account,SupplierLiabilityRow as Liability,
    CompensationPaymentRow as Compensation,ProtectionFundLedgerRow as Protection,
    OmnichannelPaymentIntentRow as Intent,PaymentOrderRootRow as Root,
    PaymentOrderFactBindingRow as Binding,VerticalSourceDecisionRow as Source)
from go_hotel.services.hosted_direct_booking import ident,now
from go_hotel.services.omnichannel_payment import digest,legal_entity
from go_hotel.services import hosted_money as funds

PROTECTION_ACCOUNT='GO_ISOLATED_CONSUMER_PROTECTION'
MANDATE_SCOPE='CONFIRMED_SUPPLIER_FAULT_CANCELLATION_ONLY'
BUSINESS='HOTEL_COMP'

@dataclass
class FaultFundingContext:
    case_id: str
    supplier_id: str
    order_id: str
    account_id: str
    requester_id: str
    checker_id: str
    decision_json: dict
    decision_hash: str
    compensation_intent_id: str | None
    source_route: str


def locked_accounts(s,supplier_id):
    rows={}
    for aid in sorted([supplier_id,PROTECTION_ACCOUNT]):
        row=s.get(Account,aid,with_for_update=True,populate_existing=True)
        if row and min(row.settlement_available_minor,row.reserve_available_minor,row.bank_available_minor,row.negative_balance_minor)<0:raise ValueError('INVALID_SUPPLIER_FUND_BALANCE')
        rows[aid]=row
    return rows[supplier_id],rows[PROTECTION_ACCOUNT]

def create_compensation_payment(s,c,amount,breakdown):
    """New hotel-to-customer payment; it never refunds the guest capture twice."""
    timestamp=now();iid=ident('opi');entity=legal_entity(c.decision_json['currency'])
    i=Intent(payment_intent_id=iid,business_type=BUSINESS,business_id=c.case_id,payer_id=c.supplier_id,payee_id=c.account_id,
        operation='AUTHORIZE',amount_minor=amount,currency=c.decision_json['currency'],channel_priority_json=['LOCAL_MARKET'],
        selected_channel='LOCAL_MARKET',state='SUCCEEDED',idempotency_key='hotel-comp-intent:'+c.case_id,
        automatic_fallback_allowed=False,user_channel_consent_at=None,created_at=timestamp,updated_at=timestamp)
    s.add(i);s.flush();s.add(Root(payment_order_root_id=ident('por'),business_type=BUSINESS,business_id=c.case_id,
        payment_intent_id=iid,legal_entity_id=entity,state='ACTIVE',root_hash=digest([BUSINESS,c.case_id,iid,entity]),created_at=timestamp))
    facts={'case_id':c.case_id,'reservation_id':c.order_id,'payer_id':c.supplier_id,'payee_id':c.account_id,
        'amount_minor':amount,'currency':i.currency,'decision_hash':c.decision_hash,'funding':breakdown,'data_mode':'SIMULATION'}
    sid=ident('vsd');evidence='approved-hotel-fault://'+c.case_id+'/'+c.decision_hash
    s.add(Source(vertical_source_decision_id=sid,vertical='HOTEL',business_id=c.case_id,selected_source_id=c.supplier_id,
        selected_source_type='SUPPLIER_FAULT_SIMULATION',route=c.source_route,authority_reference=c.decision_json['reference'],
        evidence_reference=evidence,candidate_snapshot_json=[facts],reason_codes_json=['INDEPENDENT_SUPPLIER_FAULT','FINITE_SIMULATED_FUNDING'],
        decision_hash=digest(facts),created_at=timestamp))
    s.add(Binding(payment_order_fact_binding_id=ident('pofb'),payment_intent_id=iid,business_type=BUSINESS,business_id=c.case_id,
        payer_id=c.supplier_id,payee_id=c.account_id,amount_minor=amount,currency=i.currency,legal_entity_id=entity,source_decision_id=sid,
        request_fingerprint=digest(facts),order_fact_hash=digest(facts),evidence_reference=evidence,created_at=timestamp));s.flush()
    auth=funds.money.create_in_session(s,iid,{'movement_type':'AUTHORIZATION','amount_minor':amount,'mode':'CONTRACT_SIMULATOR','evidence':[evidence]},'hotel-comp-auth:'+c.case_id,'hotel-fault')
    capture=funds.money.create_in_session(s,iid,{'movement_type':'CAPTURE','parent_movement_id':auth['money_movement_id'],'amount_minor':amount,
        'mode':'CONTRACT_SIMULATOR','evidence':[evidence,{'funding':breakdown,'beneficiary':c.account_id}]},'hotel-comp-capture:'+c.case_id,'hotel-fault')
    return iid,capture['money_movement_id']


def compensate(s,c,mandate_model,supplier_column,clock):
    timestamp=clock()
    funds.require_isolated();d=c.decision_json;amount=d['compensation_due_minor']
    if not amount:return {'state':'NOT_REQUIRED'}
    if d['fault_party']!='SUPPLIER' or not c.checker_id or c.checker_id==c.requester_id or digest(d)!=c.decision_hash:raise ValueError('INDEPENDENT_SUPPLIER_FAULT_REQUIRED')
    old=s.scalar(select(Compensation).join(Liability,Liability.liability_id==Compensation.liability_id).where(Liability.case_id==c.case_id))
    if old:
        if old.status!='COMPLETED' or old.amount_minor!=amount or not c.compensation_intent_id:raise ValueError('COMPENSATION_FACT_MISMATCH')
        return {'state':'COMPLETED','amount_minor':amount,'compensation_id':old.compensation_id}
    if d['currency']!='CNY':raise ValueError('SCOPED_CNY_FAULT_FUNDING_REQUIRED')
    acct,protection=locked_accounts(s,c.supplier_id)
    if not acct:return {'state':'AWAITING_FUNDS','shortfall_minor':amount}
    remaining=amount;settlement=min(remaining,acct.settlement_available_minor);remaining-=settlement
    reserve=min(remaining,acct.reserve_available_minor);remaining-=reserve
    mandate=s.scalar(select(mandate_model).where(supplier_column==c.supplier_id,mandate_model.state=='ACTIVE',
        mandate_model.scope==MANDATE_SCOPE,mandate_model.currency==d['currency'],mandate_model.expires_at>timestamp,mandate_model.maximum_per_case_minor>0)
        .order_by(mandate_model.created_at.desc()).with_for_update()) if remaining and acct.debit_mandate_active else None
    bank=min(remaining,acct.bank_available_minor,mandate.maximum_per_case_minor) if mandate else 0;remaining-=bank
    advance=min(remaining,protection.reserve_available_minor) if protection else 0;remaining-=advance
    if remaining:return {'state':'AWAITING_FUNDS','shortfall_minor':remaining}
    breakdown={'settlement':settlement,'reserve':reserve,'bank_debit':bank,'protection_fund':advance,
        'mandate_id':mandate.mandate_id if mandate and bank else None,'data_mode':'SIMULATION'}
    acct.settlement_available_minor-=settlement;acct.reserve_available_minor-=reserve;acct.bank_available_minor-=bank
    acct.negative_balance_minor+=advance;acct.updated_at=now()
    if advance:protection.reserve_available_minor-=advance;protection.updated_at=now()
    iid,movement=create_compensation_payment(s,c,amount,breakdown)
    li=Liability(liability_id=ident('liab'),case_id=c.case_id,supplier_id=c.supplier_id,order_id=c.order_id,
        actual_paid_minor=d['actual_paid_minor'],refund_minor=d['actual_paid_minor'],compensation_minor=amount,total_return_minor=d['actual_paid_minor']+amount,
        settlement_offset_minor=settlement,reserve_offset_minor=reserve,bank_debit_minor=bank,protection_fund_minor=advance,
        negative_balance_minor=advance,status='NEGATIVE_BALANCE' if advance else 'CLEARED',decision_id=d['decision_id'],created_at=now(),cleared_at=None if advance else now());s.add(li);s.flush()
    if advance:s.add(Protection(entry_id=ident('pf'),liability_id=li.liability_id,order_id=c.order_id,supplier_id=c.supplier_id,
        entry_type='ADVANCE',amount_minor=advance,status='POSTED',created_at=now()))
    payment=Compensation(compensation_id=ident('comp'),liability_id=li.liability_id,order_id=c.order_id,
        amount_minor=amount,currency=d['currency'],source_breakdown={**breakdown,'payment_intent_id':iid,'money_movement_id':movement},
        status='COMPLETED',created_at=now(),completed_at=now());s.add(payment);c.compensation_intent_id=iid
    return {'state':'COMPLETED','amount_minor':amount,'compensation_id':payment.compensation_id}


def recover_in_session(s,supplier_id,amount,reference,key,actor,recovery_model,supplier_field):
    """Serialize declared receipts and restore only verified, scoped advances."""
    from sqlalchemy import union
    from go_hotel.db.models import (HostedFaultRecoveryRow,CatalogFaultRecoveryRow,
        HostedSupplierDisruptionRow,CatalogSupplierRemedyRow)
    if type(amount) is not int or not 1<=amount<=2**63-1 or not isinstance(reference,str) or not 1<=len(reference.strip())<=512 or not isinstance(key,str) or not 1<=len(key)<=128:raise ValueError('VALID_SCOPED_RECOVERY_RECEIPT_REQUIRED')
    acct,protection=locked_accounts(s,supplier_id)
    if not acct:raise ValueError('SUPPLIER_FINANCIAL_ACCOUNT_REQUIRED')
    payload={supplier_field:supplier_id,'amount_minor':amount,'currency':'CNY','settlement_reference':reference,'data_mode':'SIMULATION'}
    source_hash=digest([supplier_id,reference,'CNY']);rid=('hfr_' if supplier_field=='hosted_hotel_id' else 'cfr_')+digest([supplier_id,key])[:32]
    # Preserve the DEPTH10 hosted receipt identity and request payload.
    if supplier_field=='hosted_hotel_id':payload['hotel_id']=payload.pop('hosted_hotel_id')
    old=s.get(recovery_model,rid)
    if not old:
        for model in [HostedFaultRecoveryRow,CatalogFaultRecoveryRow]:
            old=s.scalar(select(model).where(model.source_reference_hash==source_hash))
            if old:break
    if old:
        if digest(old.request_json)!=old.request_hash:raise ValueError('RECOVERY_RECEIPT_INTEGRITY_MISMATCH')
        before=old.request_json
        same=(before.get('hotel_id',before.get('supplier_id')),before['amount_minor'],before['currency'],before['settlement_reference'])==(supplier_id,amount,'CNY',reference)
        if not same:raise ValueError('RECOVERY_RECEIPT_IDEMPOTENCY_CONFLICT')
        return old.result_json.copy()
    known=union(select(HostedSupplierDisruptionRow.case_id),select(CatalogSupplierRemedyRow.case_id))
    liabilities=s.scalars(select(Liability).where(Liability.case_id.in_(known),Liability.supplier_id==supplier_id,Liability.negative_balance_minor>0)
        .order_by(Liability.created_at,Liability.liability_id).with_for_update()).all()
    if not protection and liabilities:raise ValueError('PROTECTION_FUND_ACCOUNT_REQUIRED')
    if acct.negative_balance_minor!=sum(x.negative_balance_minor for x in liabilities):raise ValueError('SCOPED_SUPPLIER_LIABILITY_BALANCE_MISMATCH')
    remaining=amount;allocations=[]
    for li in liabilities:
        take=min(remaining,li.negative_balance_minor)
        if not take:break
        li.negative_balance_minor-=take;li.settlement_offset_minor+=take;acct.negative_balance_minor-=take
        protection.reserve_available_minor+=take;protection.updated_at=now();remaining-=take
        if not li.negative_balance_minor:li.status='CLEARED';li.cleared_at=now()
        s.add(Protection(entry_id=ident('pf'),liability_id=li.liability_id,order_id=li.order_id,supplier_id=supplier_id,entry_type='RECOVERY',amount_minor=take,status='POSTED',created_at=now()))
        allocations.append({'liability_id':li.liability_id,'amount_minor':take})
    acct.settlement_available_minor+=remaining;acct.updated_at=now()
    result={'recovery_id':rid,'incoming_settlement_minor':amount,'recovered_minor':amount-remaining,'new_available_minor':remaining,
        'negative_balance_minor':acct.negative_balance_minor,'allocations':allocations,'data_mode':'SIMULATION','external_live':False}
    s.add(recovery_model(recovery_id=rid,**{supplier_field:supplier_id},source_reference_hash=source_hash,request_hash=digest(payload),
        request_json=payload,result_json=result,actor_id=actor,created_at=now()))
    return result
