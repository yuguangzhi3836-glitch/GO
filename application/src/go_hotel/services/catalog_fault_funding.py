"""Legacy hotel supplier bindings for the shared finite compensation ledger."""
from datetime import datetime
import re
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (CatalogFaultDebitMandateRow as Mandate,CatalogFaultRecoveryRow as Recovery,
    SupplierFinancialAccountRow as Account,OrderRow)
from go_hotel.services.hosted_direct_booking import ident,now,out
from go_hotel.services.hosted_reservation_operations import aware
from go_hotel.services.alipay_safeguarded_settlement import transaction
from go_hotel.services import hosted_money as funds
from go_hotel.services.supplier_fault_funding import FaultFundingContext,compensate as fund,recover_in_session,PROTECTION_ACCOUNT,MANDATE_SCOPE


def compensate(s,c):
    context=FaultFundingContext(c.case_id,c.supplier_id,c.order_id,c.account_id,c.requester_id,c.checker_id,
        c.decision_json,c.decision_hash,c.compensation_intent_id,'GO_CATALOG_HOTEL')
    result=fund(s,context,Mandate,Mandate.supplier_id,now)
    c.compensation_intent_id=context.compensation_intent_id
    return result


def register_mandate(supplier_id,currency,maximum,expires,reference,authority_hash,actor):
    funds.require_isolated()
    try:expiry=aware(datetime.fromisoformat(expires))
    except (ValueError,TypeError):raise ValueError('VALID_FAULT_MANDATE_EXPIRY_REQUIRED')
    if currency!='CNY' or type(maximum) is not int or not 1<=maximum<=2**63-1 or expiry<=now() or not isinstance(reference,str) or not 1<=len(reference.strip())<=512 or not isinstance(authority_hash,str) or not re.fullmatch('[a-f0-9]{64}',authority_hash):raise ValueError('VALID_SCOPED_FAULT_MANDATE_REQUIRED')
    with transaction() as s:
        if not s.get(Account,supplier_id,with_for_update=True) or not s.scalar(select(OrderRow.order_id).where(OrderRow.supplier_id==supplier_id).limit(1)):raise ValueError('KNOWN_SUPPLIER_FINANCIAL_ACCOUNT_REQUIRED')
        old=s.scalar(select(Mandate).where(Mandate.supplier_id==supplier_id,Mandate.authority_hash==authority_hash).with_for_update())
        if old:
            if (old.currency,old.maximum_per_case_minor,aware(old.expires_at),old.authority_reference)!=(currency,maximum,expiry,reference):raise ValueError('FAULT_MANDATE_DOCUMENT_CONFLICT')
            if old.state!='ACTIVE':raise ValueError('NEW_SIGNED_FAULT_MANDATE_REQUIRED')
            return out(old)
        for old in s.scalars(select(Mandate).where(Mandate.supplier_id==supplier_id,Mandate.currency==currency,Mandate.state=='ACTIVE').with_for_update()):
            old.state='SUPERSEDED';old.deactivated_by=actor;old.deactivated_at=now()
        row=Mandate(mandate_id=ident('cfm'),supplier_id=supplier_id,currency=currency,scope=MANDATE_SCOPE,maximum_per_case_minor=maximum,
            authority_reference=reference,authority_hash=authority_hash,registered_by=actor,state='ACTIVE',expires_at=expiry,created_at=now())
        s.add(row);s.flush();return out(row)


def revoke_mandate(mandate_id,actor):
    funds.require_isolated()
    with transaction() as s:
        row=s.get(Mandate,mandate_id,with_for_update=True,populate_existing=True)
        if not row:raise ValueError('FAULT_MANDATE_NOT_FOUND')
        if row.state=='ACTIVE':row.state='REVOKED';row.deactivated_by=actor;row.deactivated_at=now()
        return {'mandate_id':mandate_id,'state':row.state,'actor_id':row.deactivated_by,'data_mode':'SIMULATION'}


def recover(supplier_id,amount,reference,key,actor):
    funds.require_isolated()
    with transaction() as s:return recover_in_session(s,supplier_id,amount,reference,key,actor,Recovery,'supplier_id')


def finance_status(supplier_id):
    with SessionLocal() as s:
        acct=s.get(Account,supplier_id);protection=s.get(Account,PROTECTION_ACCOUNT)
        if not s.scalar(select(OrderRow.order_id).where(OrderRow.supplier_id==supplier_id).limit(1)):raise ValueError('KNOWN_SUPPLIER_REQUIRED')
        mandates=s.scalars(select(Mandate).where(Mandate.supplier_id==supplier_id).order_by(Mandate.created_at.desc()).limit(20))
        receipts=s.scalars(select(Recovery).where(Recovery.supplier_id==supplier_id).order_by(Recovery.created_at.desc()).limit(20))
        return {'supplier_id':supplier_id,'hotel_name':'酒店供应商 '+supplier_id,'currency':'CNY','data_mode':'SIMULATION','external_live':False,
            'account':{k:getattr(acct,k) for k in ['settlement_available_minor','reserve_available_minor','bank_available_minor','negative_balance_minor','debit_mandate_active']} if acct else None,
            'protection_available_minor':protection.reserve_available_minor if protection else 0,
            'mandates':[{**out(m),'expires_at':aware(m.expires_at).isoformat(),'effective':m.state=='ACTIVE' and aware(m.expires_at)>now()} for m in mandates],
            'recent_recoveries':[{'settlement_reference':x.request_json['settlement_reference'],**x.result_json} for x in receipts]}
