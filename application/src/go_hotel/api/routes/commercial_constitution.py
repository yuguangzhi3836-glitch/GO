from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal,supplier_principal
from go_hotel.security.service import Principal
from go_hotel.services.commercial_constitution import commercial_constitution_service as svc
router=APIRouter(prefix='/internal/v1/commercial',tags=['commercial-constitution-admin-os'])
class P(BaseModel):model_config={'extra':'allow'}
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
@router.post('/policies')
def policy(b:P,p:Principal=Depends(admin_principal)):x=b.model_dump(exclude_none=True);return call(svc.create_policy,x['policy_key'],x.get('scope','GLOBAL'),x['rule'],p.user_id)
@router.post('/policies/{policy_id}/approve')
def approve(policy_id:str,p:Principal=Depends(admin_principal)):return call(svc.approve_policy,policy_id,p.user_id)
@router.post('/pool-decisions')
def pools(b:P,p:Principal=Depends(admin_principal)):
 x=b.model_dump(exclude_none=True)
 if 'recommendation_eligible' in x:raise HTTPException(409,detail='ADMIN_RECOMMENDATION_ASSIGNMENT_FORBIDDEN')
 return call(svc.evaluate_pools,x['property_id'],x.get('judgment_decision_id'),x.get('value_eligible',False),x.get('basis',{}),p.user_id)
@router.put('/distribution-authorities/{property_id}')
def distribution(property_id:str,b:P,p:Principal=Depends(admin_principal)):x=b.model_dump(exclude_none=True);return call(svc.set_distribution,x['supplier_id'],property_id,x,p.user_id)
@router.post('/subscriptions/{supplier_id}/qualifying-orders')
def order(supplier_id:str,b:P,p:Principal=Depends(admin_principal)):x=b.model_dump(exclude_none=True);return call(svc.record_order_evidence,supplier_id,x['property_id'],x,p.user_id)
@router.post('/subscriptions/{supplier_id}/invoices/{period}')
def invoice(supplier_id:str,period:str,p:Principal=Depends(admin_principal)):return call(svc.issue_invoice,supplier_id,period,p.user_id)
@router.post('/waivers/{waiver_id}/approve')
def waiver_approve(waiver_id:str,p:Principal=Depends(admin_principal)):return call(svc.approve_waiver,waiver_id,p.user_id)
@router.get('/finance-status')
def finance_status(p:Principal=Depends(admin_principal)):return {'data':svc.finance_status()}
@router.post('/hotel-net-guard/assess')
def net_guard(b:P,p:Principal=Depends(admin_principal)):x=b.model_dump(exclude_none=True);return call(svc.assess_net_guard,x['property_id'],x['supplier_net_minor'],x['authorized_floor_minor'],x['currency'],x.get('evidence',[]))
@router.post('/cases')
def case(b:P,p:Principal=Depends(admin_principal)):return call(svc.open_case,b.model_dump(exclude_none=True),p.user_id)
@router.get('/dashboard')
def dashboard(p:Principal=Depends(admin_principal)):return {'data':svc.dashboard()}

supplier_router=APIRouter(prefix='/v1/supplier/commercial',tags=['supplier-t20-commercial'])
@supplier_router.get('/t20')
def supplier_t20(p:Principal=Depends(supplier_principal)):return {'data':svc.finance_status(p.supplier_id)}
@supplier_router.get('/cohort/{property_id}')
def supplier_cohort(property_id:str,p:Principal=Depends(supplier_principal)):return call(svc.cohort,p.supplier_id,property_id)
@supplier_router.post('/waivers')
def supplier_waiver(b:P,p:Principal=Depends(supplier_principal)):x=b.model_dump(exclude_none=True);return call(svc.request_waiver,p.supplier_id,x['billing_period'],x['reason'],x['evidence_reference'],p.user_id)
