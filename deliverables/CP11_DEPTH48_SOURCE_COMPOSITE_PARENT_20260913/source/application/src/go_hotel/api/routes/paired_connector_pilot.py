from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.paired_connector_pilot import paired_connector_pilot_service as svc
router=APIRouter(prefix='/internal/v1/paired-connector-pilot',tags=['first-paired-connector-pilot'])
class Payload(BaseModel):model_config={'extra':'allow'}
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
@router.get('/dashboard')
def dashboard(p:Principal=Depends(admin_principal)):return {'data':svc.dashboard()}
@router.post('/pairs')
def pair(b:Payload,p:Principal=Depends(admin_principal)):return call(svc.create_pair,b.model_dump(exclude_none=True),p.user_id)
@router.post('/pairs/{pair_id}/scenarios')
def scenario(pair_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.create_scenario,pair_id,b.model_dump(exclude_none=True),p.user_id)
@router.put('/pairs/{pair_id}/drill-gate')
def drills(pair_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.set_drill_gate,pair_id,b.model_dump(exclude_none=True),p.user_id)
@router.put('/pairs/{pair_id}/kill-switch')
def kill(pair_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.kill_switch,pair_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/scenarios/{scenario_id}/execute')
def execute(scenario_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.execute,scenario_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/executions/{execution_id}/callbacks')
def callback(execution_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.callback,execution_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/executions/{execution_id}/reconcile')
def reconcile(execution_id:str,p:Principal=Depends(admin_principal)):return call(svc.reconcile,execution_id,p.user_id)
@router.get('/executions/{execution_id}')
def status(execution_id:str,p:Principal=Depends(admin_principal)):return call(svc.status,execution_id)
