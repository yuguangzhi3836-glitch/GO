from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from typing import Literal
from go_hotel.security.deps import consumer_principal,admin_principal,supplier_principal
from go_hotel.security.service import Principal
from go_hotel.services.go_identity_entitlements import go_identity_entitlement_service as svc
router=APIRouter(tags=['mother-plan-go-identity-entitlements'])
class P(BaseModel):model_config={'extra':'allow'}
def call(fn,*a):
 try:return {'data':fn(*a)}
 except ValueError as e:raise HTTPException(409,detail=str(e))
@router.get('/v1/consumer/go-identity/credentials')
def credentials(p:Principal=Depends(consumer_principal)):return call(svc.list,p.user_id)
@router.post('/v1/consumer/go-identity/credentials',status_code=201)
def apply(b:P,p:Principal=Depends(consumer_principal)):return call(svc.apply,p.user_id,b.model_dump()['credential_type'],b.model_dump().get('supplier_id'))
@router.post('/v1/consumer/go-identity/credentials/{credential_id}/owner-privilege')
def owner_privilege(credential_id:str,b:P,p:Principal=Depends(consumer_principal)):return call(svc.select_owner_privilege,p.user_id,credential_id,b.model_dump()['privilege'])
@router.post('/v1/consumer/go-identity/credentials/{credential_id}/friends-family-invitations',status_code=201)
def invite(credential_id:str,b:P,p:Principal=Depends(consumer_principal)):
 x=b.model_dump();return call(svc.invite,p.user_id,credential_id,x['invitee_account_id'],x['invitee_legal_name'],x['expires_at'],x.get('annual_usage_limit',2))
@router.get('/v1/consumer/go-identity/entitlement')
def entitlement(supplier_id:str,room_id:str,stay_date:str,bar_minor:int,p:Principal=Depends(consumer_principal)):return call(svc.entitlement,p.user_id,supplier_id,room_id,stay_date,bar_minor)
@router.put('/v1/supplier/go-identity/programs/{program_type}')
def program(program_type:str,b:P,p:Principal=Depends(supplier_principal)):
 if 'supplier:fare-rules' not in p.permissions:raise HTTPException(403,detail='PERMISSION_DENIED')
 x=b.model_dump(exclude_none=True);x['program_type']=program_type;return call(svc.program,p.supplier_id,x,p.user_id)
@router.get('/v1/supplier/go-identity/programs')
def programs(p:Principal=Depends(supplier_principal)):return call(svc.programs,p.supplier_id)

class ProgramSelection(BaseModel):
 model_config=ConfigDict(extra='forbid')
 program_type:Literal['STAFF_RATE','OWNER_RATE','OWNER_BENEFITS','FRIENDS_FAMILY']
 enabled:bool=Field(strict=True)
 eligible_room_ids:list[str]=Field(max_length=1000)
 benefits:list[str]|None=Field(default=None,max_length=50)
class ProgramConfiguration(BaseModel):
 model_config=ConfigDict(extra='forbid')
 programs:list[ProgramSelection]=Field(min_length=1,max_length=4)
 revision:str=Field(pattern=r'^[a-f0-9]{64}$')
@router.get('/v1/supplier/go-identity/configuration')
def configuration(p:Principal=Depends(supplier_principal)):return call(svc.configuration,p.supplier_id)
@router.put('/v1/supplier/go-identity/configuration')
def configure(b:ProgramConfiguration,p:Principal=Depends(supplier_principal)):
 if 'supplier:fare-rules' not in p.permissions:raise HTTPException(403,detail='PERMISSION_DENIED')
 return call(svc.configure_programs,p.supplier_id,[x.model_dump() for x in b.programs],b.revision,p.user_id)
@router.post('/v1/consumer/go-identity/friends-family-invitations/{invitation_id}/consume')
def consume(invitation_id:str,p:Principal=Depends(consumer_principal)):return call(svc.consume_invitation,p.user_id,invitation_id)
@router.post('/internal/v1/go-identity/credentials/{credential_id}/evidence')
def evidence(credential_id:str,b:P,p:Principal=Depends(admin_principal)):return call(svc.evidence,credential_id,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/go-identity/credentials/{credential_id}/transition')
def transition(credential_id:str,b:P,p:Principal=Depends(admin_principal)):
 x=b.model_dump();return call(svc.transition,credential_id,x['state'],x.get('reason'),p.user_id)
@router.get('/internal/v1/go-identity/credentials')
def admin_credentials(state:str|None=None,p:Principal=Depends(admin_principal)):return call(svc.all_credentials,state)
@router.post('/internal/v1/go-identity/revalidation/tick')
def revalidate(p:Principal=Depends(admin_principal)):return call(svc.revalidate_due,p.user_id)
@router.post('/internal/v1/go-identity/credentials/{credential_id}/risk-signals')
def risk(credential_id:str,b:P,p:Principal=Depends(admin_principal)):return call(svc.risk_signal,credential_id,b.model_dump(exclude_none=True),p.user_id)
