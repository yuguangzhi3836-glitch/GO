from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_strategy_governance import recovery_strategy_governance_service as svc
router=APIRouter(tags=['sprint3m-recovery-strategy-governance'])
class CreateStrategy(BaseModel):name:str;min_sample_count:int=20;min_confidence:float=.8;rollout_percent:int=0
class ActivateStrategy(BaseModel):mode:str
class RollbackStrategy(BaseModel):reason:str
@router.get('/internal/v1/recovery/strategy-governance/strategies')
def strategies(p:Principal=Depends(admin_principal)):return {'data':{'items':svc.list_strategies()}}
@router.post('/internal/v1/recovery/strategy-governance/strategies')
def create(b:CreateStrategy,p:Principal=Depends(admin_principal)):return {'data':{'strategy_version_id':svc.create(b.name,b.min_sample_count,b.min_confidence,b.rollout_percent)}}
@router.post('/internal/v1/recovery/strategy-governance/strategies/{strategy_id}/approve')
def approve(strategy_id:str,p:Principal=Depends(admin_principal)):
    try:return {'data':{'strategy_version_id':svc.approve(strategy_id,p.user_id)}}
    except ValueError as e:raise HTTPException(409,str(e))
@router.post('/internal/v1/recovery/strategy-governance/strategies/{strategy_id}/activate')
def activate(strategy_id:str,b:ActivateStrategy,p:Principal=Depends(admin_principal)):
    try:return {'data':{'strategy_version_id':svc.activate(strategy_id,b.mode,p.user_id)}}
    except ValueError as e:raise HTTPException(409,str(e))
@router.post('/internal/v1/recovery/strategy-governance/strategies/{strategy_id}/rollback')
def rollback(strategy_id:str,b:RollbackStrategy,p:Principal=Depends(admin_principal)):
    try:return {'data':{'strategy_version_id':svc.rollback(strategy_id,p.user_id,b.reason)}}
    except ValueError as e:raise HTTPException(409,str(e))
@router.post('/internal/v1/recovery/strategy-governance/guardrail/tick')
def tick(p:Principal=Depends(admin_principal)):return {'data':svc.auto_guardrail()}
@router.get('/internal/v1/recovery/strategy-governance/evaluations')
def evaluations(p:Principal=Depends(admin_principal)):return {'data':{'items':svc.evaluations()}}
