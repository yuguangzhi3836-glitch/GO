from __future__ import annotations
from urllib.parse import quote
from go_hotel.services import registration_privacy
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field, field_validator, ConfigDict
from go_hotel.core.config import settings
from go_hotel.services import registration_verification as registration_verification_service
from go_hotel.security.service import identity_service, Principal, uid, now
from go_hotel.security.deps import current_principal, supplier_account_principal, admin_principal
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import AuditEventRow
from typing import Literal
from go_hotel.services.supplier_onboarding import supplier_onboarding_service
from go_hotel.services.supplier_onboarding_state import supplier_onboarding_state_service
from go_hotel.services.legal_entity import legal_entity_service
from go_hotel.services.legal_entity_document import legal_entity_document_service
from go_hotel.services.onboarding_hotel import onboarding_hotel_service
from go_hotel.services import registration_terms as registration_terms_service
from go_hotel.security.login_identity import normalize_login_id, normalize_phone

router=APIRouter(tags=['production-bff'])

class LoginBody(BaseModel):
    # One login box, three identifiers: the field keeps its historical name
    # `username` so the mobile client and any existing caller keep working.
    # `IdentityService.login` normalises the value and matches it against the
    # username, email and phone columns at once, so the human never has to say
    # which of the three they are typing.
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
    """Supplier sign-up payload for three-in-one login.

    ``username`` / ``email`` / ``phone`` are the three login identifiers of the
    account being created, and both verification challenges must be proved before
    the account exists (owner decision, superseding frozen decision D-01).
    ``contact_name`` is deliberately no longer collected here: the applicant
    types a name when they fill in the application, not at the door.
    """
    model_config=ConfigDict(extra="forbid")
    username:str=Field(min_length=3,max_length=32)
    email:str=Field(max_length=128)
    phone:str=Field(min_length=11,max_length=32)
    password:str=Field(min_length=10,max_length=128)
    email_challenge_id:str=Field(default="",max_length=64)
    email_verification_code:str=Field(default="",max_length=6)
    sms_challenge_id:str=Field(default="",max_length=64)
    sms_verification_code:str=Field(default="",max_length=6)
    organization_name:str|None=Field(default=None,max_length=160)
    contact_name:str|None=Field(default=None,max_length=80)
    accepted_terms:bool=Field(default=False,strict=True)
    term_versions:dict[str,str]=Field(default_factory=dict)
    term_hashes:dict[str,str]=Field(default_factory=dict)
    registration_decisions:dict[str,str]=Field(default_factory=dict)
    hotel_name:str|None=Field(default=None,max_length=160)
    province:str=Field(default='',max_length=80)
    city:str=Field(default='',max_length=80)
    street_address:str=Field(default='',max_length=300)

    @field_validator('organization_name','contact_name','hotel_name')
    @classmethod
    def nonblank_identity(cls,value):
        if value is not None and not value.strip():
            raise ValueError('NONBLANK_IDENTITY_REQUIRED')
        return value.strip() if value is not None else value

class SupplierLegalEntityBody(BaseModel):
    """Legal person behind one supplier tenant (frozen decision D-02).

    USCC arrives as free text: lowercase and surrounding whitespace are accepted
    and normalised by the service, never rejected (frozen decision CHANGE 4).
    The client never supplies a legal_entity_id or supplier_id.
    """
    model_config=ConfigDict(extra="forbid")
    legal_name:str=Field(min_length=1,max_length=200)
    unified_social_credit_code:str=Field(min_length=1,max_length=64)
    legal_representative_name:str=Field(min_length=1,max_length=80)
    registered_address:str=Field(min_length=1,max_length=300)
    license_valid_from:str|None=Field(default=None,max_length=32)
    license_valid_until:str|None=Field(default=None,max_length=32)
    license_long_term:bool=Field(default=False)

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

# The contract step is not here any more (Batch 6). `POST /bff/supplier/onboarding/contract`
# took a typed `contract_ref` string as proof of signature, and
# `POST /internal/v1/supplier-onboarding/{id}/contract-decision` was the second human
# review that D-003 abolished. Both are replaced by
# `api/routes/onboarding_contract.py`: serve the template, upload the signed scan as a
# real document, confirm once.


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
        policy=registration_terms_service.account_registration_terms_status('supplier')
    except (ValueError,OSError,KeyError) as exc:
        raise HTTPException(503,detail='REGISTRATION_TERMS_UNAVAILABLE') from exc
    verification_ready=registration_verification_service.ready()
    # Owner decision, superseding frozen decision D-01: an account is created only
    # after BOTH the email and the SMS challenge are proved. Sign-up therefore
    # opens only when the verification runtime is actually configured — the form
    # must not collect two codes and then discover it cannot check them.
    return {'data':{**policy,'required':True,'enabled':bool(policy['acceptance_enabled']) and verification_ready,
        'required_decisions':registration_privacy.required_decisions(policy),
        'registration_scope':'NATIONWIDE','publication_requires_verification':True,
        'login_identifiers':['username','email','phone'],'verification_channels':list(registration_verification_service.required_channels()),
        # Published on purpose so the sign-up form can pre-fill the stand-in code
        # in an environment where delivery is not connected. `None` means real
        # delivery, and the form then asks the human for the code they received.
        'verification_test_code':settings.registration_verification_test_code or None,
        'release_gate':{'registration_verification':{'required':True,'implemented':verification_ready,'status':'READY' if verification_ready else 'NOT_READY','reason':None if verification_ready else 'REGISTRATION_VERIFICATION_NOT_CONFIGURED'},
                        'formal_terms':{'required_for_account':False,'status':'PENDING' if policy.get('formal_approval_pending') else 'READY'}},
        'titles':{d['id']:d['title'] for d in policy['documents']}}}

@router.post('/bff/auth/supplier/register',status_code=201)
def supplier_register(body:SupplierRegisterBody,request:Request,response:Response):
    username=normalize_login_id(body.username)
    email=normalize_login_id(body.email)
    phone=normalize_phone(body.phone)
    if not body.accepted_terms:
        raise HTTPException(422,detail='SUPPLIER_TERMS_ACCEPTANCE_REQUIRED')
    try:
        policy=registration_terms_service.require_account_registration_terms_ready('supplier')
    except (ValueError,OSError,KeyError) as exc:
        raise HTTPException(503,detail='REGISTRATION_TERMS_NOT_READY') from exc
    # Fail closed before touching a single code, exactly as the consumer door does.
    # The terms page advertises `enabled=False` in this state, so a caller that
    # ignores the page must not be able to get further than the page says it can.
    if not registration_verification_service.ready():
        raise HTTPException(503,detail='REGISTRATION_VERIFICATION_NOT_READY')
    # Owner decision, superseding frozen decision D-01: sign-up sits *behind* the
    # challenges. Nothing is created and no code is spent until the codes have been
    # proved; `register_account` then consumes them in one transaction with the
    # account and the consent record, so a failure at any point leaves no half-made
    # account and no spent code. Which challenges that means is a property of the
    # environment, not a constant — see `required_channels()` below.
    if body.term_versions != policy['versions']:
        raise HTTPException(409,detail='SUPPLIER_TERMS_VERSION_MISMATCH')
    if body.term_hashes != policy['term_hashes']:
        raise HTTPException(409,detail='SUPPLIER_TERMS_CONTENT_MISMATCH')
    # The channels are checked one at a time and the refusal carries the channel as
    # a prefix, so the form can mark the one code box that is wrong instead of
    # showing a message that fits neither. Only the channels this environment can
    # really deliver on are demanded, so the form never advertises one channel and
    # then hides an unobtainable second one behind it.
    required_channels=registration_verification_service.required_channels()
    proofs=[]
    for channel,identifier,challenge_id,code in (
        ('email',email,body.email_challenge_id,body.email_verification_code),
        ('sms',phone,body.sms_challenge_id,body.sms_verification_code),
    ):
        if channel not in required_channels: continue
        try:
            proofs.append(registration_verification_service.check('supplier',identifier,challenge_id,code,policy,channel))
        except ValueError as exc:
            raise HTTPException(409,detail=f'{channel.upper()}_{exc}') from exc
    def registration_audit(user_id,supplier_id):
        t=now()
        return AuditEventRow(
            audit_id=uid('aud'),actor_id=user_id,actor_type='SUPPLIER_USER',supplier_id=supplier_id,roles=['SUPPLIER_OWNER'],session_id=None,
            action='SUPPLIER_REGISTRATION_TERMS_ACCEPTED',resource_type='SUPPLIER_REGISTRATION',resource_id=supplier_id,request_id=getattr(request.state,'request_id',None),
            client_ip=request.client.host if request.client else None,http_method='POST',path='/bff/auth/supplier/register',before_state=None,
            after_state={'registration_state':'REGISTERED','next_step':'COMPLETE_PROFILE'},decision_id=None,evidence_id=None,approval_id=None,
            metadata_json={'organization_name':body.organization_name,'contact_name':body.contact_name,'phone_provided':True,
                'term_versions':policy['versions'],'term_hashes':policy['term_hashes'],'deferred_terms':policy.get('deferred',[]),
                'accepted_once':True,'email_verified':'email' in required_channels,'sms_verified':'sms' in required_channels,
                'verification_mode':'_AND_'.join(channel.upper() for channel in required_channels),
                'verification_challenge_id':body.email_challenge_id,'sms_verification_challenge_id':body.sms_challenge_id},created_at=t,
        )
    try:
        registration_privacy.validate_decisions(policy,body.registration_decisions)
        # The sign-up phone is a *login identifier*, deliberately not profile data:
        # the contact phone for the application is typed in the application step.
        # Feeding the identifier in here made `_identifier_conflict`-clean
        # accounts look "partly filled in" and moved every fresh sign-up straight
        # to PROFILE_DRAFT, which is a claim about work the applicant has not done.
        initial_profile={
            'organization_name':body.organization_name,'hotel_name':body.hotel_name,'contact_name':body.contact_name,
            'province':body.province.strip() or None,'city':body.city.strip() or None,
            'street_address':body.street_address.strip() or None,
        }
        registration=supplier_onboarding_service.register_account(
            {'username':username,'email':email,'phone':phone,'password':body.password},audit_factory=registration_audit,
            verification_proofs=proofs,
            registration_consent={'audience':'supplier','policy':policy,
                'decisions':body.registration_decisions},
            initial_profile=initial_profile)
    except ValueError as exc:
        raise HTTPException(409,detail=str(exc)) from exc
    supplier_id=registration['supplier_id']
    # The account exists at this point. Minting its first session must not be able
    # to turn a successful sign-up into a 5xx: the applicant would retry and be
    # told the handle or address is taken — by the account they just created.
    # `login` is now deterministic for an ambiguous stored value, so this is
    # defence in depth; when a session still cannot be produced, the honest answer
    # is "created, please log in" rather than an error that hides the account.
    try:
        tokens=identity_service.login(username,body.password,request.client.host if request.client else None,request.headers.get('user-agent'))
    except ValueError:
        return {'data':{'authenticated':False,'supplier_id':supplier_id,'registration_state':registration['onboarding_state'],
            'next_step':'LOGIN','registration_scope':'NATIONWIDE'}}
    set_session_cookies(response,tokens)
    return {'data':{'authenticated':True,'supplier_id':supplier_id,'registration_state':registration['onboarding_state'],
        'next_step':'COMPLETE_PROFILE','registration_scope':'NATIONWIDE'}}


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

@router.get('/bff/supplier/legal-entity')
def supplier_legal_entity_get(p:Principal=Depends(supplier_account_principal)):
    return {'data':legal_entity_service.get_for_supplier(p.supplier_id)}

@router.put('/bff/supplier/legal-entity')
def supplier_legal_entity_put(body:SupplierLegalEntityBody,p:Principal=Depends(supplier_account_principal)):
    try:return {'data':legal_entity_service.save(p.supplier_id,body.model_dump(exclude_none=True))}
    except ValueError as e:raise HTTPException(409,detail=str(e))

# --- applicant private evidence (frozen decisions CHANGE 2 / CHANGE 10 / D-03) ---
# Transport is multipart/form-data, never base64: a 10 MB licence must not be
# inflated into a JSON string. The bytes are stored on a private volume and the
# response body never carries the internal storage key.
def _document_response(raw:bytes,mime:str,filename:str,disposition:str)->Response:
    """Serve private evidence with the headers a private file needs."""
    ascii_fallback=''.join(c if 32<=ord(c)<127 and c not in '"\\' else '_' for c in filename) or 'document'
    return Response(content=raw,media_type=mime,headers={
        'Cache-Control':'private, no-store',
        'X-Content-Type-Options':'nosniff',
        # Preview and download are two different intents: inline must never
        # become a stored download, and an attachment must never render.
        'Content-Disposition':f"{disposition}; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}",
    })

@router.post('/bff/supplier/legal-entity/documents',status_code=201)
def supplier_document_upload(file:UploadFile=File(...),document_type:str=Form(...),
        expected_revision:str|None=Form(default=None),scope:str|None=Form(default=None),
        p:Principal=Depends(supplier_account_principal)):
    try:
        revision=int(expected_revision) if expected_revision not in (None,'') else None
    except ValueError:
        raise HTTPException(409,detail='DOCUMENT_REVISION_STALE') from None
    data=file.file.read()
    try:
        saved=legal_entity_document_service.upload(
            supplier_id=p.supplier_id,uploaded_by=p.user_id,document_type=document_type,
            data=data,filename=file.filename,declared_mime=file.content_type,
            scope=scope or None,expected_revision=revision)
    except ValueError as e:raise HTTPException(409,detail=str(e)) from e
    return {'data':saved}

@router.get('/bff/supplier/legal-entity/documents')
def supplier_document_list(scope:str|None=None,p:Principal=Depends(supplier_account_principal)):
    # No scope = every document the applicant owns (both scopes). The step screens
    # need one honest answer to "what have I uploaded", without holding a case id.
    try:return {'data':legal_entity_document_service.list_for_supplier(p.supplier_id,scope=scope or None)}
    except ValueError as e:raise HTTPException(409,detail=str(e)) from e

@router.get('/bff/supplier/legal-entity/document-history')
def supplier_document_history(document_type:str,scope:str|None=None,
        p:Principal=Depends(supplier_account_principal)):
    try:rows=legal_entity_document_service.history(p.supplier_id,document_type,scope=scope or None)
    except ValueError as e:raise HTTPException(409,detail=str(e)) from e
    return {'data':rows}

@router.get('/bff/supplier/legal-entity/documents/{document_id}')
def supplier_document_meta(document_id:str,p:Principal=Depends(supplier_account_principal)):
    try:return {'data':legal_entity_document_service.meta_for_owner(p.supplier_id,document_id)}
    except ValueError as e:raise HTTPException(404,detail=str(e)) from e

@router.get('/bff/supplier/legal-entity/documents/{document_id}/content')
def supplier_document_content(document_id:str,disposition:Literal['inline','attachment']='attachment',
        p:Principal=Depends(supplier_account_principal)):
    try:raw,mime,filename,resolved=legal_entity_document_service.read_for_owner(
        p.supplier_id,document_id,inline=disposition=='inline')
    except ValueError as e:raise HTTPException(404,detail=str(e)) from e
    return _document_response(raw,mime,filename,resolved)

class SupplierHotelClaimBody(BaseModel):
    """The hotel this applicant claims to run.

    ``mode``/``relationship_type`` are plain strings rather than ``Literal``: a
    rejected literal produces a FastAPI validation payload the UI cannot
    translate, while the service returns one stable code the UI already maps to a
    sentence. ``hotel_id`` is an opaque option value returned by search — the
    human picks a result row and never sees or types it.
    """
    model_config=ConfigDict(extra="forbid")
    mode:str=Field(max_length=16)
    relationship_type:str=Field(max_length=32)
    hotel_id:str|None=Field(default=None,max_length=64)
    proposed_hotel:dict|None=None


@router.get('/bff/supplier/hotel/search')
def supplier_hotel_search(q:str|None=None,city:str|None=None,limit:int=10,
        p:Principal=Depends(supplier_account_principal)):
    try:return {'data':onboarding_hotel_service.search(query=q,city=city,limit=limit)}
    except ValueError as e:raise HTTPException(422,detail=str(e)) from e

@router.get('/bff/supplier/hotel/claim')
def supplier_hotel_claim_get(p:Principal=Depends(supplier_account_principal)):
    return {'data':onboarding_hotel_service.get_claim(p.supplier_id)}

@router.put('/bff/supplier/hotel/claim')
def supplier_hotel_claim_save(body:SupplierHotelClaimBody,p:Principal=Depends(supplier_account_principal)):
    try:return {'data':onboarding_hotel_service.save_claim(p.supplier_id,p.user_id,body.model_dump(exclude_none=True))}
    except ValueError as e:raise HTTPException(409,detail=str(e)) from e


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
