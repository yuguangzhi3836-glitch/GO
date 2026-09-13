from fastapi import APIRouter,Depends,Header,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.production_connector_runtime import production_connector_runtime_service as svc
router=APIRouter(tags=['production-connector-runtime'])
class Payload(BaseModel): model_config={'extra':'allow'}
def call(fn,*args):
 try:return {'data':fn(*args)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
def maker(p):
 if not (p.permissions & {'admin:connector','admin:orders','admin:trust'}):raise HTTPException(403,detail='EXTERNAL_TRUTH_OPERATOR_PERMISSION_REQUIRED')
 return p
def checker(p):
 if 'admin:approve' not in p.permissions:raise HTTPException(403,detail='EXTERNAL_TRUTH_CHECKER_PERMISSION_REQUIRED')
 return p
@router.post('/internal/v1/production-connectors/{connector_id}/runtime/authorize')
def authorize(connector_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.authorize,connector_id,b.model_dump()['operation_type'])
@router.post('/internal/v1/production-connectors/{connector_id}/runtime/operations')
def submit(connector_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.submit,connector_id,b.model_dump(exclude_none=True))
@router.post('/internal/v1/production-connector-runtime/operations/{operation_id}/dispatch')
def dispatch(operation_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.mark_dispatched,operation_id,b.model_dump(exclude_none=True))
@router.post('/internal/v1/production-connector-runtime/operations/{operation_id}/poll-observations')
def poll(operation_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.record_poll,operation_id,b.model_dump(exclude_none=True))
@router.get('/internal/v1/production-connector-runtime/operations/{operation_id}')
def operation(operation_id:str,p:Principal=Depends(admin_principal)):return call(svc.get_operation,operation_id)
@router.get('/internal/v1/production-connector-runtime/reconciliations/due')
def due(limit:int=100,p:Principal=Depends(admin_principal)):maker(p);return call(svc.due_reconciliations,limit)
@router.post('/internal/v1/production-connector-runtime/reconciliations/{reconciliation_id}/claim')
def claim(reconciliation_id:str,b:Payload,p:Principal=Depends(admin_principal)):maker(p);return call(svc.claim,reconciliation_id,p.user_id,int(b.model_dump().get('lease_seconds',900)))
@router.post('/internal/v1/production-connector-runtime/reconciliations/{reconciliation_id}/renew')
def renew(reconciliation_id:str,b:Payload,p:Principal=Depends(admin_principal)):maker(p);return call(svc.renew_claim,reconciliation_id,p.user_id,int(b.model_dump().get('lease_seconds',900)))
@router.post('/internal/v1/production-connector-runtime/reconciliations/{reconciliation_id}/resolution')
def resolution(reconciliation_id:str,b:Payload,p:Principal=Depends(admin_principal)):maker(p);return call(svc.submit_resolution,reconciliation_id,p.user_id,b.model_dump(exclude_none=True))
@router.post('/internal/v1/production-connector-runtime/reconciliations/{reconciliation_id}/review')
def review(reconciliation_id:str,b:Payload,p:Principal=Depends(admin_principal)):
 checker(p);d=b.model_dump(exclude_none=True);return call(svc.review_resolution,reconciliation_id,p.user_id,d.get('decision',''),d.get('evidence_reference',''))
@router.post('/v1/webhooks/production-connectors/{connector_id}')
def webhook(connector_id:str,b:Payload,x_go_delivery_id:str=Header(...),x_go_signature_sha256:str=Header(...)):return call(svc.ingest_webhook,connector_id,x_go_delivery_id,x_go_signature_sha256,b.model_dump(exclude_none=True))
