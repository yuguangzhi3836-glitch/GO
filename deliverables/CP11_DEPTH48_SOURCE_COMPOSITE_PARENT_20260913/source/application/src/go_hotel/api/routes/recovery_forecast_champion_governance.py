from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_forecast_champion_governance import recovery_forecast_champion_governance_service as svc
router=APIRouter(tags=['recovery-forecast-champion-governance'])
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
class RegisterB(BaseModel):portfolio_id:str;champion_model_version_id:str|None=None;previous_stable_champion_model_version_id:str|None=None
class ContinuityB(BaseModel):champion_state_id:str;portfolio_objective_score:float;target_health_state:str='PASS';protected_segment_state:str='PASS';serving_health_state:str='PASS';holdout_state:str='PASS';evidence:dict|None=None
class ChallengeB(BaseModel):champion_state_id:str;portfolio_candidate_id:str
class CompareB(BaseModel):challenge_id:str;champion_portfolio_score:float;candidate_portfolio_score:float;protected_segment_safe:bool=True;generalization_pass:bool=True;serving_health_pass:bool=True;statistical_confidence_pass:bool=True;evidence:dict|None=None
class DecisionB(BaseModel):challenge_id:str;evidence:dict
class TransitionB(BaseModel):replacement_decision_id:str;action:str='SYNC';evidence:dict|None=None
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-portfolio-champions')
def register(b:RegisterB,p:Principal=Depends(admin_principal)):return call(svc.register_champion,b.portfolio_id,b.champion_model_version_id,b.previous_stable_champion_model_version_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-portfolio-champions/continuity')
def continuity(b:ContinuityB,p:Principal=Depends(admin_principal)):return call(svc.assess_continuity,b.champion_state_id,b.portfolio_objective_score,b.target_health_state,b.protected_segment_state,b.serving_health_state,b.holdout_state,b.evidence,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-portfolio-champions/challenges')
def challenge(b:ChallengeB,p:Principal=Depends(admin_principal)):return call(svc.open_challenge,b.champion_state_id,b.portfolio_candidate_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-portfolio-champions/compare')
def compare(b:CompareB,p:Principal=Depends(admin_principal)):return call(svc.compare_candidate,b.challenge_id,b.champion_portfolio_score,b.candidate_portfolio_score,b.protected_segment_safe,b.generalization_pass,b.serving_health_pass,b.statistical_confidence_pass,b.evidence,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-portfolio-champions/replacement-decision')
def decision(b:DecisionB,p:Principal=Depends(admin_principal)):return call(svc.decide_replacement,b.challenge_id,b.evidence,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-portfolio-champions/transition')
def transition(b:TransitionB,p:Principal=Depends(admin_principal)):return call(svc.sync_transition,b.replacement_decision_id,b.action,b.evidence,p.user_id)
@router.get('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-portfolio-champions/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
