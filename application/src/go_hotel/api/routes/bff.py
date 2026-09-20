from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator, ConfigDict
from go_hotel.core.config import settings
from go_hotel.security.service import identity_service, Principal, uid, now
from go_hotel.security.deps import current_principal
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import AuditEventRow
from typing import Literal
from go_hotel.services.supplier_onboarding import supplier_onboarding_service
from go_hotel.services import registration_terms as registration_terms_service

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
    "data_processing_terms":"2026-08-25-v1",
    "electronic_signature_authorization":"2026-08-25-v1",
    "platform_operating_rules":"2026-08-25-v1",
}
class SupplierRegisterBody(BaseModel):
    model_config=ConfigDict(extra="forbid")
    email:str=Field(max_length=128)
    password:str=Field(min_length=10,max_length=128)
    organization_name:str=Field(min_length=2,max_length=160)
    contact_name:str=Field(min_length=1,max_length=80)
    phone:str|None=None
    accepted_terms:bool=False
    term_versions:dict[str,str]=Field(default_factory=dict)
    term_hashes:dict[str,str]=Field(default_factory=dict)
    hotel_name:str|None=Field(default=None,min_length=2,max_length=160)
    province:str=Field(default='',max_length=80)
    city:str=Field(default='',max_length=80)
    street_address:str=Field(default='',max_length=300)

    @field_validator('organization_name','contact_name','hotel_name')
    @classmethod
    def nonblank_identity(cls,value):
        if value is not None and not value.strip():
            raise ValueError('NONBLANK_IDENTITY_REQUIRED')
        return value.strip() if value is not None else value


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
    try:
        policy=registration_terms_service.registration_terms_status('supplier')
    except (ValueError, OSError, KeyError) as exc:
        raise HTTPException(503,detail='REGISTRATION_TERMS_UNAVAILABLE') from exc
    return {'data':{**policy,'required':True,'enabled':policy['acceptance_enabled'],
        'registration_scope':'NATIONWIDE','publication_requires_verification':True,
        'release_gate':{'registration_verification':{'required':True,'implemented':False,'status':'BLOCKED','reason':'LIVE_EMAIL_OR_PHONE_VERIFICATION_EVIDENCE_REQUIRED'},
                        'candidate_runtime':{'required':True,'status':'BLOCKED','reason':'SIGNED_HK_STAGING_TEST_PR_EVIDENCE_REQUIRED'},
                        'page_acceptance':{'required':True,'status':'BLOCKED','reason':'EXACT_CANDIDATE_C_B_MOBILE_ACCEPTANCE_REQUIRED'}},
        'titles':{d['id']:d['title'] for d in policy['documents']}}}

@router.post('/bff/auth/supplier/register',status_code=201)
def supplier_register(body:SupplierRegisterBody,request:Request,response:Response):
    email=body.email.strip().lower()
    if not body.accepted_terms:
        raise HTTPException(422,detail='SUPPLIER_TERMS_ACCEPTANCE_REQUIRED')
    try:
        policy=registration_terms_service.require_registration_terms_ready('supplier')
    except (ValueError, OSError, KeyError) as exc:
        raise HTTPException(503,detail='REGISTRATION_TERMS_NOT_READY') from exc
    if not settings.registration_verification_enabled:
        raise HTTPException(503,detail='REGISTRATION_VERIFICATION_NOT_READY')
    if body.term_versions != policy['versions']:
        raise HTTPException(409,detail='SUPPLIER_TERMS_VERSION_MISMATCH')
    if body.term_hashes != policy['term_hashes']:
        raise HTTPException(409,detail='SUPPLIER_TERMS_CONTENT_MISMATCH')
    def registration_audit(user_id,supplier_id,property_id):
        t=now()
        return AuditEventRow(
            audit_id=uid('aud'),actor_id=user_id,actor_type='SUPPLIER_USER',supplier_id=supplier_id,roles=['SUPPLIER_OWNER'],session_id=None,
            action='SUPPLIER_REGISTRATION_TERMS_ACCEPTED',resource_type='SUPPLIER_REGISTRATION',resource_id=supplier_id,request_id=getattr(request.state,'request_id',None),
            client_ip=request.client.host if request.client else None,http_method='POST',path='/bff/auth/supplier/register',before_state=None,
            after_state={'registration_state':'ACCOUNT_CREATED_TERMS_ACCEPTED'},decision_id=None,evidence_id=None,approval_id=None,
            metadata_json={'organization_name':body.organization_name,'contact_name':body.contact_name,'phone_provided':bool(body.phone),'term_versions':policy['versions'],'term_hashes':policy['term_hashes'],'accepted_once':True},created_at=t,
        )
    try:
        registration=supplier_onboarding_service.register({'username':email,'password':body.password,'hotel':{
            'name_zh':body.hotel_name or body.organization_name,'property_type':'HOTEL',
            'address':{'country_code':'CN','province':body.province.strip(),'city':body.city.strip(),'street':body.street_address.strip()},
            'legal':{'declared_organization_name':body.organization_name},
            'contacts':{'contact_name':body.contact_name,'phone':body.phone,'email':email},
        }}, audit_factory=registration_audit)
    except ValueError as exc:
        raise HTTPException(409,detail=str(exc)) from exc
    supplier_id=registration['supplier_id'];user_id=registration['user_id'];property_id=registration['property_id']
    tokens=identity_service.login(email,body.password,request.client.host if request.client else None,request.headers.get('user-agent'))
    set_session_cookies(response,tokens)
    return {'data':{'authenticated':True,'supplier_id':supplier_id,'property_id':property_id,'registration_state':'ACCOUNT_CREATED_TERMS_ACCEPTED','next_step':'BUILD_HOTEL_LIBRARY','registration_scope':'NATIONWIDE','ownership_status':'DECLARED','publication_state':'DRAFT'}}

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
    return {'data':{'user_id':p.user_id,'username':p.username,'actor_type':p.actor_type,'supplier_id':p.supplier_id,'roles':p.roles,'permissions':sorted(p.permissions),'session_id':p.session_id}}

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
