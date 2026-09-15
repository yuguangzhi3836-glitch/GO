from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, Header, HTTPException
from go_hotel.compensation.service import compensation_service
from go_hotel.repositories.sql import repo
from go_hotel.api.idempotency import run_idempotent_async
from go_hotel.core.errors import conflict
from go_hotel.security.deps import supplier_principal, consumer_principal, require_permission, assert_supplier_order
from go_hotel.security.service import Principal, audit_service

router=APIRouter()
class SupplierCancelRequest(BaseModel):
    reason_code: str
    evidence_ids: list[str]=Field(default_factory=list)
class FutureSettlementRequest(BaseModel): amount_minor:int
class SupplierFinanceRequest(BaseModel):
    settlement_available_minor:int=0; reserve_available_minor:int=0; bank_available_minor:int=0; debit_mandate_active:bool=False

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
def future_settlement(supplier_id:str, body:FutureSettlementRequest,p:Principal=Depends(require_permission('admin:finance'))): return {'data':compensation_service.apply_future_settlement(supplier_id,body.amount_minor)}

@router.post('/v1/supplier/orders/{order_id}/unable-to-fulfill')
async def unable_to_fulfill(order_id:str, body:SupplierCancelRequest, idempotency_key:str|None=Header(default=None,alias='Idempotency-Key'),p:Principal=Depends(supplier_principal)):
    assert_supplier_order(p,order_id)
    payload=body.model_dump()|{'order_id':order_id,'supplier_id':p.supplier_id}
    async def execute():
        result=await compensation_service.supplier_cancel(order_id,p.supplier_id,body.reason_code,body.evidence_ids)
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
