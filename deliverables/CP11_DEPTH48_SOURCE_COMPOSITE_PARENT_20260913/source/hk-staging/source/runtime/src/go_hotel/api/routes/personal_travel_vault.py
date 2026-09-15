from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from go_hotel.security.deps import consumer_principal,admin_principal
from go_hotel.security.service import Principal
from go_hotel.services.personal_travel_vault import personal_travel_vault_service as svc

router=APIRouter(tags=['go-personal-travel-vault'])
class P(BaseModel): model_config={'extra':'allow'}
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:
        code=404 if str(e) in {'PROFILE_IMPORT_NOT_FOUND','PROFILE_IMPORT_ITEM_NOT_FOUND','TRAVELER_NOT_FOUND','PROFILE_FACT_NOT_FOUND','CONSENT_NOT_FOUND'} else 409
        raise HTTPException(code,detail=str(e))

@router.post('/v1/consumer/profile/vault/bootstrap',status_code=201)
def bootstrap_vault(b:P,p:Principal=Depends(consumer_principal)):return call(svc.bootstrap_vault,p.user_id,b.model_dump(exclude_none=True))

@router.post('/v1/consumer/profile/imports',status_code=201)
def create_import(b:P,p:Principal=Depends(consumer_principal)):return call(svc.create_import,p.user_id,b.model_dump(exclude_none=True))
@router.get('/v1/consumer/profile/imports/{import_job_id}')
def get_import(import_job_id:str,p:Principal=Depends(consumer_principal)):return call(svc.get_import,p.user_id,import_job_id)
@router.post('/v1/consumer/profile/imports/{import_job_id}/items/{item_id}/review')
def review(import_job_id:str,item_id:str,b:P,p:Principal=Depends(consumer_principal)):return call(svc.review_item,p.user_id,import_job_id,item_id,b.model_dump()['action'])
@router.post('/v1/consumer/profile/imports/{import_job_id}/commit')
def commit(import_job_id:str,p:Principal=Depends(consumer_principal)):return call(svc.commit_import,p.user_id,import_job_id)
@router.get('/v1/consumer/profile/vault')
def vault(p:Principal=Depends(consumer_principal)):return call(svc.vault,p.user_id,p.user_id,p.actor_type)
@router.get('/v1/consumer/profile/completeness')
def completeness(p:Principal=Depends(consumer_principal)):return call(svc.completeness,p.user_id)
@router.post('/v1/consumer/profile/consents',status_code=201)
def consent(b:P,p:Principal=Depends(consumer_principal)):return call(svc.grant_consent,p.user_id,b.model_dump(exclude_none=True))
@router.delete('/v1/consumer/profile/consents/{consent_id}')
def revoke(consent_id:str,p:Principal=Depends(consumer_principal)):return call(svc.revoke_consent,p.user_id,consent_id)
@router.post('/v1/consumer/profile/data-release')
def data_release(b:P,p:Principal=Depends(consumer_principal)):return call(svc.release,p.user_id,b.model_dump(exclude_none=True),p.user_id,p.actor_type)
@router.put('/v1/consumer/profile/travelers/{traveler_id}/permissions/{permission_type}')
def permission(traveler_id:str,permission_type:str,b:P,p:Principal=Depends(consumer_principal)):return call(svc.set_permission,p.user_id,traveler_id,permission_type,bool(b.model_dump().get('allowed')))
@router.delete('/v1/consumer/profile/facts/{fact_id}')
def delete_fact(fact_id:str,p:Principal=Depends(consumer_principal)):return call(svc.delete_fact,p.user_id,fact_id)
@router.delete('/v1/consumer/profile/sources/{source_fingerprint}')
def delete_source(source_fingerprint:str,p:Principal=Depends(consumer_principal)):return call(svc.delete_source,p.user_id,source_fingerprint)
@router.get('/internal/v1/admin/profile/imports')
def admin_imports(limit:int=100,status:str|None=None,p:Principal=Depends(admin_principal)):return {'data':{'items':svc.admin_imports(min(limit,500),status)}}
@router.get('/internal/v1/admin/profile/data-releases')
def admin_releases(limit:int=100,decision:str|None=None,p:Principal=Depends(admin_principal)):return {'data':{'items':svc.admin_releases(min(limit,500),decision)}}
