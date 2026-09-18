from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from go_hotel.security.service import identity_service, approval_service, audit_service, Principal
from go_hotel.security.deps import current_principal, require_permission
from go_hotel.services.supplier_onboarding import supplier_onboarding_service

router=APIRouter(tags=['identity-security'])
class LoginBody(BaseModel): username:str; password:str
class RefreshBody(BaseModel): refresh_token:str
class UserCreateBody(BaseModel): username:str; password:str=Field(min_length=10); actor_type:str; supplier_id:str|None=None; roles:list[str]
class ApprovalBody(BaseModel): operation_type:str; subject_type:str; subject_id:str; payload:dict={}
class ApprovalDecisionBody(BaseModel): note:str|None=None
class SupplierRegistrationBody(BaseModel):
    username:str
    password:str=Field(min_length=10)
    hotel:dict

@router.post('/v1/auth/login')
def login(body:LoginBody,request:Request):
    try: return {'data':identity_service.login(body.username,body.password,request.client.host if request.client else None,request.headers.get('user-agent'))}
    except ValueError as e: raise HTTPException(401,detail=str(e))
@router.post('/v1/supplier/self-registration',status_code=201)
def supplier_self_registration(body:SupplierRegistrationBody):
    try:return {'data':supplier_onboarding_service.register(body.model_dump())}
    except ValueError as e:raise HTTPException(409,detail=str(e))
@router.post('/v1/auth/refresh')
def refresh(body:RefreshBody):
    try: return {'data':identity_service.refresh(body.refresh_token)}
    except ValueError as e: raise HTTPException(401,detail=str(e))
@router.post('/v1/auth/logout')
def logout(p:Principal=Depends(current_principal)):
    identity_service.revoke_session(p.session_id); return {'data':{'status':'REVOKED'}}
@router.get('/v1/auth/me')
def me(p:Principal=Depends(current_principal)): return {'data':{'user_id':p.user_id,'username':p.username,'actor_type':p.actor_type,'supplier_id':p.supplier_id,'roles':p.roles,'permissions':sorted(p.permissions),'session_id':p.session_id}}
@router.post('/internal/v1/identity/users')
def create_user(body:UserCreateBody,p:Principal=Depends(require_permission('admin:approve'))):
    uid=identity_service.create_user(body.username,body.password,body.actor_type,body.supplier_id,body.roles); audit_service.append(p,'IDENTITY_USER_CREATED','IDENTITY_USER',uid,after={'username':body.username,'actor_type':body.actor_type,'supplier_id':body.supplier_id,'roles':body.roles}); return {'data':{'user_id':uid}}
@router.post('/internal/v1/approvals')
def request_approval(body:ApprovalBody,p:Principal=Depends(current_principal)):
    try: r=approval_service.request(p,body.operation_type,body.subject_type,body.subject_id,body.payload); audit_service.append(p,'HIGH_RISK_APPROVAL_REQUESTED','APPROVAL',r['approval_id'],after=r); return {'data':r}
    except ValueError as e: raise HTTPException(422,detail=str(e))
@router.post('/internal/v1/approvals/{approval_id}/approve')
def approve(approval_id:str,body:ApprovalDecisionBody,p:Principal=Depends(require_permission('admin:approve'))):
    try: r=approval_service.approve(p,approval_id,body.note); audit_service.append(p,'HIGH_RISK_APPROVAL_GRANTED','APPROVAL',approval_id,after=r); return {'data':r}
    except PermissionError as e: raise HTTPException(403,detail=str(e))
    except ValueError as e: raise HTTPException(409,detail=str(e))
@router.get('/internal/v1/audit-events')
def audits(limit:int=100,actor_id:str|None=None,resource_id:str|None=None,p:Principal=Depends(require_permission('admin:read'))): return {'data':audit_service.list(limit,actor_id,resource_id)}
