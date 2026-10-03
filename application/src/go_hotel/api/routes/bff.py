from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from go_hotel.core.config import settings
from go_hotel.security.service import identity_service, Principal, uid, now
from go_hotel.security.deps import current_principal, supplier_account_principal, admin_principal
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import AuditEventRow, IdentityUserRow
from sqlalchemy import select
import uuid
from typing import Literal
from go_hotel.services.supplier_onboarding_state import supplier_onboarding_state_service

router=APIRouter(tags=['production-bff'])

class LoginBody(BaseModel):
    username:str
    password:str
    totp_code:str|None=None
    expected_actor_type:Literal['GO_ADMIN','SUPPLIER_USER']|None=None
class MFAConfirmBody(BaseModel): code:str
SUPPLIER_REGISTRATION_TERMS={
    "supplier_service_terms":"2026-08-25-v1",
    "privacy_policy":"2026-08-25-v1",
    "platform_operating_rules":"2026-08-25-v1",
}
SUPPLIER_DEFERRED_TERMS={
    "data_processing_terms":"2026-08-25-v1",
    "electronic_signature_authorization":"2026-08-25-v1",
}
class SupplierRegisterBody(BaseModel):
    email:str
    password:str=Field(min_length=10)
    organization_name:str|None=Field(default=None,max_length=160)
    contact_name:str|None=Field(default=None,max_length=80)
    phone:str|None=None
    accepted_terms:bool=False
    term_versions:dict[str,str]={}

class SupplierProfileBody(BaseModel):
    organization_name:str|None=None
    hotel_name:str|None=None
    contact_name:str|None=None
    phone:str|None=None
    province:str|None=None
    city:str|None=None
    street_address:str|None=None
    business_license_ref:str|None=None
    legal_representative_name:str|None=None
    identity_document_ref:str|None=None
    storefront_photo_ref:str|None=None
    authorization_ref:str|None=None

class SupplierReviewBody(BaseModel):
    decision:Literal['APPROVE','NEEDS_CHANGES']
    note:str|None=None
    registration_direct_id:str|None=None

class SupplierContractBody(BaseModel):
    contract_ref:str
    contract_version:str|None=None
    note:str|None=None

class SupplierContractReviewBody(BaseModel):
    decision:Literal['APPROVE','NEEDS_CHANGES']
    note:str|None=None

class MFAEnrollStartBody(BaseModel):
    username:str
    password:str
class MFAEnrollConfirmBody(BaseModel):
    enrollment_token:str
    code:str

def _cookie_common():
    return dict(secure=settings.cookie_secure, httponly=True, samesite=settings.session_cookie_samesite, domain=settings.cookie_domain)

def set_session_cookies(response:Response, tokens:dict):
    common=_cookie_common()
    response.set_cookie(settings.access_cookie_name,tokens['access_token'],max_age=tokens['expires_in'],path='/',**common)
    response.set_cookie(settings.refresh_cookie_name,tokens['refresh_token'],max_age=settings.refresh_token_days*86400,path='/bff/auth',**common)
    response.set_cookie(settings.csrf_cookie_name,tokens['csrf_token'],max_age=settings.refresh_token_days*86400,path='/',secure=settings.cookie_secure,httponly=False,samesite=settings.session_cookie_samesite,domain=settings.cookie_domain)

def clear_session_cookies(response:Response):
    for name,path in [(settings.access_cookie_name,'/'),(settings.refresh_cookie_name,'/bff/auth'),(settings.csrf_cookie_name,'/')]:
        response.delete_cookie(name,path=path,domain=settings.cookie_domain)

@router.get('/bff/auth/policy')
def bff_auth_policy():
    return {'data':{'environment':settings.app_env,'admin_mfa_required':bool(settings.mfa_required_for_admin),'oidc_enabled':bool(settings.oidc_enabled)}}


@router.get('/bff/auth/supplier/registration-terms')
def supplier_registration_terms():
    return {'data':{'required':True,'versions':SUPPLIER_REGISTRATION_TERMS,'titles':{
        'supplier_service_terms':'GO 合作伙伴账号与平台服务条款',
        'privacy_policy':'隐私政策',
        'platform_operating_rules':'平台运营规范',
    },'deferred':{
        'versions':SUPPLIER_DEFERRED_TERMS,
        'reason':'DATA_PROCESSING_AND_E_SIGNATURE_ARE_AUTHORIZED_LATER',
    }}}

@router.post('/bff/auth/supplier/register',status_code=201)
def supplier_register(body:SupplierRegisterBody,request:Request,response:Response):
    email=body.email.strip().lower()
    if not body.accepted_terms:
        raise HTTPException(422,detail='SUPPLIER_TERMS_ACCEPTANCE_REQUIRED')
    if any(body.term_versions.get(k)!=v for k,v in SUPPLIER_REGISTRATION_TERMS.items()):
        raise HTTPException(409,detail='SUPPLIER_TERMS_VERSION_MISMATCH')
    with SessionLocal() as s:
        if s.scalar(select(IdentityUserRow).where(IdentityUserRow.username==email)):
            raise HTTPException(409,detail='EMAIL_ALREADY_REGISTERED')
    supplier_id='sup_'+uuid.uuid4().hex
    user_id=identity_service.create_user(email,body.password,'SUPPLIER_USER',supplier_id,['SUPPLIER_OWNER'])
    t=now()
    with SessionLocal() as s:
        s.add(AuditEventRow(
            audit_id=uid('aud'),actor_id=user_id,actor_type='SUPPLIER_USER',supplier_id=supplier_id,roles=['SUPPLIER_OWNER'],session_id=None,
            action='SUPPLIER_REGISTRATION_TERMS_ACCEPTED',resource_type='SUPPLIER_REGISTRATION',resource_id=supplier_id,request_id=getattr(request.state,'request_id',None),
            client_ip=request.client.host if request.client else None,http_method='POST',path='/bff/auth/supplier/register',before_state=None,
            after_state={'registration_state':'REGISTERED','next_step':'COMPLETE_PROFILE'},decision_id=None,evidence_id=None,approval_id=None,
            metadata_json={'organization_name':body.organization_name,'contact_name':body.contact_name,'phone_provided':bool(body.phone),'term_versions':SUPPLIER_REGISTRATION_TERMS,'deferred_terms':SUPPLIER_DEFERRED_TERMS,'accepted_once':True},created_at=t,
        ));s.commit()
    supplier_onboarding_state_service.create_registered(
        supplier_id,user_id,{'organization_name':body.organization_name,'contact_name':body.contact_name,'phone':body.phone}
    )
    tokens=identity_service.login(email,body.password,request.client.host if request.client else None,request.headers.get('user-agent'))
    set_session_cookies(response,tokens)
    return {'data':{'authenticated':True,'supplier_id':supplier_id,'registration_state':'REGISTERED','next_step':'COMPLETE_PROFILE'}}

@router.post('/bff/auth/login')
def bff_login(body:LoginBody,request:Request,response:Response):
    try:
        tokens=identity_service.login(body.username,body.password,request.client.host if request.client else None,request.headers.get('user-agent'),body.totp_code,expected_actor_type=body.expected_actor_type)
    except ValueError as e:
        raise HTTPException(401,detail=str(e))
    set_session_cookies(response,tokens)
    return {'data':{'authenticated':True,'expires_in':tokens['expires_in']}}

@router.post('/bff/auth/refresh')
def bff_refresh(request:Request,response:Response):
    token=request.cookies.get(settings.refresh_cookie_name)
    if not token: raise HTTPException(401,detail='REFRESH_COOKIE_REQUIRED')
    try: tokens=identity_service.refresh(token,allowed_actor_types={'SUPPLIER_USER','GO_ADMIN'})
    except ValueError as e: raise HTTPException(401,detail=str(e))
    set_session_cookies(response,tokens)
    return {'data':{'refreshed':True,'expires_in':tokens['expires_in']}}

@router.post('/bff/auth/logout')
def bff_logout(response:Response,p:Principal=Depends(current_principal)):
    identity_service.revoke_session(p.session_id)
    clear_session_cookies(response)
    return {'data':{'status':'REVOKED'}}

@router.get('/bff/auth/me')
def bff_me(p:Principal=Depends(current_principal)):
    onboarding=supplier_onboarding_state_service.get(p.supplier_id) if p.actor_type=='SUPPLIER_USER' and p.supplier_id else None
    return {'data':{'user_id':p.user_id,'username':p.username,'actor_type':p.actor_type,'supplier_id':p.supplier_id,'roles':p.roles,'permissions':sorted(p.permissions),'session_id':p.session_id,'onboarding':onboarding}}

@router.get('/bff/supplier/onboarding')
def supplier_onboarding_status(p:Principal=Depends(supplier_account_principal)):
    onboarding=supplier_onboarding_state_service.get(p.supplier_id)
    if not onboarding: raise HTTPException(404,detail='SUPPLIER_ONBOARDING_NOT_FOUND')
    return {'data':onboarding}

@router.put('/bff/supplier/onboarding/profile')
def supplier_onboarding_profile(body:SupplierProfileBody,p:Principal=Depends(supplier_account_principal)):
    try:return {'data':supplier_onboarding_state_service.save_profile(p.supplier_id,body.model_dump(exclude_none=True))}
    except ValueError as e:raise HTTPException(409,detail=str(e))

@router.post('/bff/supplier/onboarding/profile/submit')
def supplier_onboarding_submit(p:Principal=Depends(supplier_account_principal)):
    try:return {'data':supplier_onboarding_state_service.submit_profile(p.supplier_id)}
    except ValueError as e:raise HTTPException(409,detail=str(e))

@router.post('/internal/v1/supplier-onboarding/{supplier_id}/profile-decision')
def supplier_onboarding_profile_decision(supplier_id:str,body:SupplierReviewBody,p:Principal=Depends(admin_principal)):
    try:return {'data':supplier_onboarding_state_service.decide_profile(supplier_id,p.user_id,body.decision,body.note,body.registration_direct_id)}
    except ValueError as e:raise HTTPException(409,detail=str(e))

@router.post('/bff/supplier/onboarding/contract')
def supplier_onboarding_contract(body:SupplierContractBody,p:Principal=Depends(supplier_account_principal)):
    try:return {'data':supplier_onboarding_state_service.submit_contract(p.supplier_id,body.model_dump(exclude_none=True))}
    except ValueError as e:raise HTTPException(409,detail=str(e))

@router.post('/internal/v1/supplier-onboarding/{supplier_id}/contract-decision')
def supplier_onboarding_contract_decision(supplier_id:str,body:SupplierContractReviewBody,p:Principal=Depends(admin_principal)):
    try:return {'data':supplier_onboarding_state_service.decide_contract(supplier_id,p.user_id,body.decision,body.note)}
    except ValueError as e:raise HTTPException(409,detail=str(e))

@router.post('/bff/auth/mfa/enroll/start')
def mfa_enroll_start(body:MFAEnrollStartBody):
    try: return {'data':identity_service.begin_admin_mfa_enrollment(body.username,body.password)}
    except ValueError as e: raise HTTPException(401 if str(e)=='INVALID_CREDENTIALS' else 422,detail=str(e))

@router.post('/bff/auth/mfa/enroll/confirm')
def mfa_enroll_confirm(body:MFAEnrollConfirmBody,request:Request,response:Response):
    try:
        tokens=identity_service.confirm_admin_mfa_enrollment(body.enrollment_token,body.code,request.client.host if request.client else None,request.headers.get('user-agent'))
    except ValueError as e:
        raise HTTPException(422,detail=str(e))
    set_session_cookies(response,tokens)
    return {'data':{'authenticated':True,'mfa_enrolled':True,'expires_in':tokens['expires_in']}}

@router.post('/bff/auth/mfa/setup')
def mfa_setup(p:Principal=Depends(current_principal)):
    try: return {'data':identity_service.begin_mfa_enrollment(p)}
    except ValueError as e: raise HTTPException(422,detail=str(e))

@router.post('/bff/auth/mfa/confirm')
def mfa_confirm(body:MFAConfirmBody,p:Principal=Depends(current_principal)):
    try: return {'data':identity_service.confirm_mfa_enrollment(p,body.code)}
    except ValueError as e: raise HTTPException(422,detail=str(e))

from fastapi.responses import RedirectResponse
from go_hotel.security.oidc import oidc_service

@router.get('/bff/auth/sso/start')
def sso_start():
    try: return RedirectResponse(oidc_service.start(),status_code=302)
    except Exception as e: raise HTTPException(503,detail=str(e))

@router.get('/bff/auth/sso/callback')
def sso_callback(code:str,state:str,request:Request):
    try:
        claims=oidc_service.callback(code,state)
        username=claims.get('preferred_username') or claims.get('email') or claims.get('sub')
        tokens=identity_service.login_sso(settings.oidc_provider_name,claims['sub'],username,request.client.host if request.client else None,request.headers.get('user-agent'))
    except Exception as e:
        raise HTTPException(401,detail=str(e))
    response=RedirectResponse('/go-admin/',status_code=302)
    set_session_cookies(response,tokens)
    return response
