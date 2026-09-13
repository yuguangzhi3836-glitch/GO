from pydantic import BaseModel, Field, StrictInt
from fastapi import APIRouter, Depends, Header, HTTPException
from go_hotel.compensation.service import compensation_service
from go_hotel.repositories.sql import repo
from go_hotel.api.idempotency import run_idempotent_async
from go_hotel.core.errors import conflict
from go_hotel.security.deps import supplier_principal, consumer_principal, require_permission, assert_supplier_order
from go_hotel.security.service import Principal, audit_service

router=APIRouter()
class SupplierCancelRequest(BaseModel):
    model_config={'extra':'forbid'}
    reason_code: str
    evidence_ids: list[str]=Field(default_factory=list)
class FutureSettlementRequest(BaseModel):
    model_config={'extra':'forbid'}
    amount_minor:StrictInt
    settlement_reference:str
class SupplierFinanceRequest(BaseModel):
    settlement_available_minor:StrictInt=0; reserve_available_minor:StrictInt=0; bank_available_minor:StrictInt=0; debit_mandate_active:bool=False

def idem(operation,key,payload):
    if not key: return None
    rec=repo.get_idempotency(operation,key)
    if rec and rec['request_hash'] != repo.hash_payload(payload): conflict('IDEMPOTENCY_CONFLICT','Same key used with different payload')
    return rec

@router.put('/internal/v1/suppliers/{supplier_id}/financial-account')
def configure_finance(supplier_id:str, body:SupplierFinanceRequest,p:Principal=Depends(require_permission('admin:finance'))):
    result=compensation_service.configure_supplier_finance(supplier_id,body.settlement_available_minor,body.reserve_available_minor,body.bank_available_minor,body.debit_mandate_active)
    audit_service.append(p,'SUPPLIER_FINANCIAL_ACCOUNT_CONFIGURED','SUPPLIER',supplier_id,after=result)
    return {'data':result}
@router.get('/internal/v1/suppliers/{supplier_id}/financial-account')
def get_finance(supplier_id:str,p:Principal=Depends(require_permission('admin:finance'))): return {'data':compensation_service.get_supplier_finance(supplier_id)}
@router.post('/internal/v1/suppliers/{supplier_id}/future-settlement')
def future_settlement(supplier_id:str, body:FutureSettlementRequest,idempotency_key:str=Header(alias='Idempotency-Key'),p:Principal=Depends(require_permission('admin:finance'))):
    return call(compensation_service.apply_future_settlement,supplier_id,body.amount_minor,body.settlement_reference,idempotency_key,p.user_id)

@router.post('/v1/supplier/orders/{order_id}/unable-to-fulfill')
async def unable_to_fulfill(order_id:str, body:SupplierCancelRequest, idempotency_key:str|None=Header(default=None,alias='Idempotency-Key'),p:Principal=Depends(supplier_principal)):
    assert_supplier_order(p,order_id)
    payload=body.model_dump()|{'order_id':order_id,'supplier_id':p.supplier_id,'requester_id':p.user_id}
    async def execute():
        try:result=await compensation_service.supplier_cancel(order_id,p.supplier_id,body.reason_code,body.evidence_ids,p.user_id)
        except ValueError as e:raise HTTPException(409,detail=str(e))
        audit_service.append(p,'SUPPLIER_UNABLE_TO_FULFILL','ORDER',order_id,after=result,evidence_id=(body.evidence_ids[0] if body.evidence_ids else None))
        return {'data':result}
    return await run_idempotent_async('supplier_unable_to_fulfill',idempotency_key,payload,execute,resource_id_fn=lambda response:(response.get('data') or {}).get('case_id'))
@router.get('/internal/v1/supplier-fault-cases/{case_id}')
def get_case(case_id:str,p:Principal=Depends(require_permission('admin:finance'))): return {'data':compensation_service.get_case(case_id)}
@router.get('/internal/v1/supplier-liabilities/{liability_id}')
def get_liability(liability_id:str,p:Principal=Depends(require_permission('admin:finance'))): return {'data':compensation_service.get_liability(liability_id)}
@router.get('/v1/consumer/orders/{order_id}/supplier-cancellation-remedy')
def consumer_remedy(order_id:str,p:Principal=Depends(consumer_principal)): return {'data':compensation_service.remedy_status(order_id,p.user_id)}
@router.get('/internal/v1/supplier-fault/governance')
def fault_governance(p:Principal=Depends(require_permission('admin:finance'))): return {'data':compensation_service.governance_status()}


class EvidenceRequest(BaseModel):
    model_config={'extra':'forbid'}
    reference:str
    sha256:str
    type:str

class IndependentReviewRequest(BaseModel):
    model_config={'extra':'forbid'}
    confirmed_cause:str
    accepted_evidence_ids:list[str]
    decision_reference:str
    expected_evidence_hash:str

class ExecutionRequest(BaseModel):
    model_config={'extra':'forbid'}
    expected_decision_hash:str

class FaultMandateRequest(BaseModel):
    model_config={'extra':'forbid'}
    currency:str
    maximum_per_case_minor:StrictInt
    expires_at:str
    authority_reference:str
    authority_hash:str


def call(fn,*args):
    try:return {'data':fn(*args)}
    except ValueError as e:raise HTTPException(409,detail=str(e))

@router.post('/internal/v1/supplier-fault-cases/{case_id}/evidence')
def add_fault_evidence(case_id:str,b:EvidenceRequest,p:Principal=Depends(require_permission('admin:finance'))):
    from go_hotel.services.catalog_supplier_remedy import add_evidence
    return call(add_evidence,case_id,b.model_dump(),p.user_id)

@router.post('/internal/v1/supplier-fault-cases/{case_id}/review')
def review_fault(case_id:str,b:IndependentReviewRequest,p:Principal=Depends(require_permission('admin:finance'))):
    from go_hotel.services.catalog_supplier_remedy import review
    return call(review,case_id,b.confirmed_cause,b.accepted_evidence_ids,b.decision_reference,p.user_id,b.expected_evidence_hash)

@router.post('/internal/v1/supplier-fault-cases/{case_id}/execute')
async def execute_fault(case_id:str,b:ExecutionRequest,p:Principal=Depends(require_permission('admin:finance'))):
    from go_hotel.services.catalog_supplier_remedy import execute
    try:return {'data':await execute(case_id,b.expected_decision_hash)}
    except ValueError as e:raise HTTPException(409,detail=str(e))

@router.post('/internal/v1/supplier-fault-cases/{case_id}/reconcile')
async def reconcile_fault(case_id:str,p:Principal=Depends(require_permission('admin:finance'))):
    from go_hotel.services.catalog_supplier_remedy import reconcile
    try:return {'data':await reconcile(case_id,p.user_id)}
    except ValueError as e:raise HTTPException(409,detail=str(e))

@router.get('/internal/v1/suppliers/{supplier_id}/fault-finance')
def catalog_fault_finance(supplier_id:str,p:Principal=Depends(require_permission('admin:finance'))):
    from go_hotel.services.catalog_fault_funding import finance_status
    return call(finance_status,supplier_id)

@router.post('/internal/v1/suppliers/{supplier_id}/fault-mandates')
def catalog_fault_mandate(supplier_id:str,b:FaultMandateRequest,p:Principal=Depends(require_permission('admin:finance'))):
    from go_hotel.services.catalog_fault_funding import register_mandate
    return call(register_mandate,supplier_id,b.currency,b.maximum_per_case_minor,b.expires_at,b.authority_reference,b.authority_hash,p.user_id)

@router.post('/internal/v1/supplier-fault-mandates/{mandate_id}/revoke')
def revoke_catalog_fault_mandate(mandate_id:str,p:Principal=Depends(require_permission('admin:finance'))):
    from go_hotel.services.catalog_fault_funding import revoke_mandate
    return call(revoke_mandate,mandate_id,p.user_id)

@router.post('/v1/consumer/orders/{order_id}/supplier-cancellation-remedy/retry')
async def retry_customer_remedy(order_id:str,p:Principal=Depends(consumer_principal)):
    from go_hotel.db.session import SessionLocal
    from go_hotel.db.models import CatalogSupplierRemedyRow
    from sqlalchemy import select
    from go_hotel.services.catalog_supplier_remedy import execute
    with SessionLocal() as s:
        c=s.scalar(select(CatalogSupplierRemedyRow).where(CatalogSupplierRemedyRow.order_id==order_id,CatalogSupplierRemedyRow.account_id==p.user_id))
        if not c:raise HTTPException(404,detail='SUPPLIER_REMEDY_NOT_FOUND')
        case_id=c.case_id
    try:
        await execute(case_id)
        from go_hotel.services.catalog_supplier_remedy import status
        return {'data':status(case_id,p.user_id)}
    except ValueError as e:raise HTTPException(409,detail=str(e))

@router.get('/internal/v1/supplier-fault/cases')
def list_catalog_faults(offset:int=0,p:Principal=Depends(require_permission('admin:finance'))):
    if offset<0:raise HTTPException(422,detail='NONNEGATIVE_OFFSET_REQUIRED')
    from go_hotel.services.catalog_supplier_remedy import admin_cases
    return call(admin_cases,offset)

@router.get('/v1/supplier/orders/{order_id}/supplier-cancellation')
def supplier_cancellation_status(order_id:str,p:Principal=Depends(supplier_principal)):
    assert_supplier_order(p,order_id)
    from go_hotel.db.session import SessionLocal
    from go_hotel.db.models import SupplierFaultCaseRow,CatalogSupplierRemedyRow
    from sqlalchemy import select
    from go_hotel.services.catalog_supplier_remedy import status
    with SessionLocal() as s:
        case=s.scalar(select(SupplierFaultCaseRow).where(SupplierFaultCaseRow.order_id==order_id))
        if not case:return {'data':None}
        if not s.get(CatalogSupplierRemedyRow,case.case_id):return {'data':{'case_id':case.case_id,'state':'HISTORICAL_REVIEW_REQUIRED'}}
        case_id=case.case_id
    return call(status,case_id)

@router.post('/v1/supplier/orders/{order_id}/supplier-cancellation/evidence')
def supplier_cancellation_evidence(order_id:str,b:EvidenceRequest,p:Principal=Depends(supplier_principal)):
    assert_supplier_order(p,order_id)
    from go_hotel.db.session import SessionLocal
    from go_hotel.db.models import SupplierFaultCaseRow
    from sqlalchemy import select
    from go_hotel.services.catalog_supplier_remedy import add_evidence
    with SessionLocal() as s:
        case=s.scalar(select(SupplierFaultCaseRow).where(SupplierFaultCaseRow.order_id==order_id))
        if not case:raise HTTPException(404,detail='SUPPLIER_CANCELLATION_NOT_FOUND')
        case_id=case.case_id
    return call(add_evidence,case_id,b.model_dump(),p.user_id)
