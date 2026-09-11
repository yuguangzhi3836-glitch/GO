from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_experimentation import recovery_experimentation_service as svc
router=APIRouter(tags=['sprint3n-recovery-experimentation'])
class CreateExperiment(BaseModel):
    name:str;control_strategy_version_id:str;candidate_strategy_version_id:str;allocation_percent:int=10;min_sample_per_arm:int=30;significance_alpha:float=.05;primary_metric:str='confirmation_rate';stratification:dict|None=None;promotion_gate:dict|None=None
@router.get('/internal/v1/recovery/experimentation/experiments')
def experiments(p:Principal=Depends(admin_principal)):return {'data':{'items':svc.list_experiments()}}
@router.post('/internal/v1/recovery/experimentation/experiments')
def create(b:CreateExperiment,p:Principal=Depends(admin_principal)):
    try:return {'data':{'experiment_id':svc.create(b.name,b.control_strategy_version_id,b.candidate_strategy_version_id,b.allocation_percent,b.min_sample_per_arm,b.significance_alpha,b.primary_metric,b.stratification,b.promotion_gate)}}
    except ValueError as e:raise HTTPException(409,str(e))
@router.post('/internal/v1/recovery/experimentation/experiments/{experiment_id}/approve')
def approve(experiment_id:str,p:Principal=Depends(admin_principal)):
    try:return {'data':{'experiment_id':svc.approve(experiment_id,p.user_id)}}
    except ValueError as e:raise HTTPException(409,str(e))
@router.post('/internal/v1/recovery/experimentation/experiments/{experiment_id}/start')
def start(experiment_id:str,p:Principal=Depends(admin_principal)):
    try:return {'data':{'experiment_id':svc.start(experiment_id,p.user_id)}}
    except ValueError as e:raise HTTPException(409,str(e))
@router.post('/internal/v1/recovery/experimentation/experiments/{experiment_id}/evaluate')
def evaluate(experiment_id:str,p:Principal=Depends(admin_principal)):
    try:return {'data':svc.evaluate(experiment_id)}
    except ValueError as e:raise HTTPException(409,str(e))
@router.post('/internal/v1/recovery/experimentation/experiments/{experiment_id}/calibrate')
def calibrate(experiment_id:str,p:Principal=Depends(admin_principal)):
    try:return {'data':{'items':svc.calibrate(experiment_id)}}
    except ValueError as e:raise HTTPException(409,str(e))
@router.get('/internal/v1/recovery/experimentation/decisions')
def decisions(p:Principal=Depends(admin_principal)):return {'data':{'items':svc.decisions()}}
@router.get('/internal/v1/recovery/experimentation/calibrations')
def calibrations(p:Principal=Depends(admin_principal)):return {'data':{'items':svc.calibrations()}}
