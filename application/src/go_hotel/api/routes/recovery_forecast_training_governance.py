from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.journey.recovery_forecast_training_governance import recovery_forecast_training_governance_service as svc
router=APIRouter(tags=['sprint4o-forecast-training-governance'])
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))
class PolicyB(BaseModel):
    environment:str='PROD';minimum_training_rows:int=20;max_missing_rate:float=.05;max_duplicate_rate:float=.02;max_invalid_rate:float=.01;reproducibility_required:bool=True
class FeatureB(BaseModel): environment:str='PROD';feature_key:str;data_type:str;definition:dict={}
class DatasetB(BaseModel): environment:str='PROD';dataset_key:str;records:list[dict];feature_version_ids:list[str];source_refs:list[str]=[]
class QualityB(BaseModel): snapshot_id:str;missing_rate:float;duplicate_rate:float;invalid_rate:float;evidence:dict
class LineageB(BaseModel): environment:str='PROD';challenger_model_version_id:str;snapshot_id:str;source_retraining_request_id:str|None=None
class ManifestB(BaseModel): lineage_id:str;code_ref:str;code_hash:str;hyperparameters:dict|None=None;random_seed:int=42
class ReproB(BaseModel): manifest_id:str;reproduced_code_hash:str;reproduced_hyperparameters:dict;reproduced_seed:int;evidence_reference:str
class EligibilityB(BaseModel): challenger_model_version_id:str
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-training/policies')
def create_policy(b:PolicyB,p:Principal=Depends(admin_principal)):return call(svc.create_policy,b.environment,b.minimum_training_rows,b.max_missing_rate,b.max_duplicate_rate,b.max_invalid_rate,b.reproducibility_required,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-training/policies/{policy_id}/approve')
def approve(policy_id:str,p:Principal=Depends(admin_principal)):return call(svc.approve_policy,policy_id,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-training/features')
def feature(b:FeatureB,p:Principal=Depends(admin_principal)):return call(svc.register_feature,b.environment,b.feature_key,b.data_type,b.definition,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-training/datasets')
def dataset(b:DatasetB,p:Principal=Depends(admin_principal)):return call(svc.snapshot_dataset,b.environment,b.dataset_key,b.records,b.feature_version_ids,b.source_refs)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-training/data-quality')
def quality(b:QualityB,p:Principal=Depends(admin_principal)):return call(svc.assess_data_quality,b.snapshot_id,b.missing_rate,b.duplicate_rate,b.invalid_rate,b.evidence,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-training/lineage')
def lineage(b:LineageB,p:Principal=Depends(admin_principal)):return call(svc.create_lineage,b.environment,b.challenger_model_version_id,b.snapshot_id,b.source_retraining_request_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-training/manifests')
def manifest(b:ManifestB,p:Principal=Depends(admin_principal)):return call(svc.create_manifest,b.lineage_id,b.code_ref,b.code_hash,b.hyperparameters,b.random_seed,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-training/reproducibility')
def repro(b:ReproB,p:Principal=Depends(admin_principal)):return call(svc.check_reproducibility,b.manifest_id,b.reproduced_code_hash,b.reproduced_hyperparameters,b.reproduced_seed,b.evidence_reference,p.user_id)
@router.post('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-training/eligibility')
def eligibility(b:EligibilityB,p:Principal=Depends(admin_principal)):return call(svc.evaluate_build,b.challenger_model_version_id,p.user_id)
@router.get('/internal/v1/recovery/runtime/trust-plane/readiness/enterprise-risk/forecast-training/status')
def status(environment:str='PROD',p:Principal=Depends(admin_principal)):return {'data':svc.status(environment)}
