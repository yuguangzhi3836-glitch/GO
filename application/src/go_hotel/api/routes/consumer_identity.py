from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Header
from pydantic import BaseModel, Field, ConfigDict, field_validator
import re
from sqlalchemy import select
from go_hotel.core.config import settings
from go_hotel.services import registration_verification as registration_verification_service
from go_hotel.security.service import identity_service, Principal
from go_hotel.security.deps import consumer_principal, assert_consumer_order
from go_hotel.consumer.service import consumer_service
from go_hotel.services import registration_terms as registration_terms_service
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OrderRow, AuditEventRow
from go_hotel.services.booking import booking_service
from go_hotel.services.booking_data_release import release_booking_data
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence
from go_hotel.domain.models import new_id
from go_hotel.api.idempotency import run_idempotent_async
from datetime import datetime, timezone

router=APIRouter(tags=["sprint1y-consumer-identity"])
CONSUMER_REGISTRATION_TERMS={"consumer_service_terms":"2026-08-25-v1","privacy_policy":"2026-08-25-v1","personal_vault_terms":"2026-08-25-v1"}
class RegisterBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=128)
    display_name: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=32)
    accepted_terms: bool = Field(strict=True)
    term_versions: dict[str, str]
    term_hashes: dict[str, str] = Field(default_factory=dict)
    challenge_id: str = Field(default="", max_length=64)
    verification_code: str = Field(default="", max_length=6)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+", value):
            raise ValueError("INVALID_EMAIL")
        return value

class LoginBody(BaseModel): email:str; password:str
class TravelerBody(BaseModel):
    full_name:str; date_of_birth:str|None=None; nationality:str|None=None; document_type:str|None=None; document_number:str|None=None; is_primary:bool=False
class TokenizeBody(BaseModel):
    pan:str; expiry_month:int; expiry_year:int; cvc:str|None=None; make_default:bool=False
class ConsumerOrderBody(BaseModel):
    prebook_id:str
    traveler_id:str|None=None
    expected_fare_rule_hash:str|None=Field(default=None,pattern=r'^[a-f0-9]{64}$')
    fare_confirmed:bool=Field(default=False,strict=True)
class ConsumerCheckoutBody(BaseModel): payment_method_id:str

def _cookie_kwargs(http_only=True): return dict(secure=settings.cookie_secure,httponly=http_only,samesite=settings.session_cookie_samesite,domain=settings.cookie_domain,path="/")
def _set(response,t):
    response.set_cookie(settings.consumer_access_cookie_name,t["access_token"],max_age=t["expires_in"],**_cookie_kwargs(True))
    response.set_cookie(settings.consumer_refresh_cookie_name,t["refresh_token"],max_age=settings.refresh_token_days*86400,**_cookie_kwargs(True))
    response.set_cookie(settings.consumer_csrf_cookie_name,t["csrf_token"],max_age=settings.refresh_token_days*86400,**_cookie_kwargs(False))
def _clear(response):
    for n in [settings.consumer_access_cookie_name,settings.consumer_refresh_cookie_name,settings.consumer_csrf_cookie_name]: response.delete_cookie(n,path="/",domain=settings.cookie_domain)

@router.get("/v1/consumer/auth/registration")
def registration_options():
    try:
        policy = registration_terms_service.registration_terms_status("consumer")
    except (ValueError, OSError, KeyError) as exc:
        raise HTTPException(503, detail="REGISTRATION_TERMS_UNAVAILABLE") from exc
    verification_ready = registration_verification_service.ready()
    return {"data": {**policy, "enabled": bool(policy["acceptance_enabled"] and verification_ready), "coverage": "CN_NATIONWIDE", "method": "EMAIL_PASSWORD", "terms": policy["versions"], "phone_verified": False, "release_gate": {"registration_verification": {"required": True, "implemented": verification_ready, "status": "READY" if verification_ready else "BLOCKED", "reason": None if verification_ready else "LIVE_EMAIL_OR_PHONE_VERIFICATION_EVIDENCE_REQUIRED"}, "candidate_runtime": {"required": True, "status": "BLOCKED", "reason": "SIGNED_HK_STAGING_TEST_PR_EVIDENCE_REQUIRED"}, "page_acceptance": {"required": True, "status": "BLOCKED", "reason": "EXACT_CANDIDATE_C_B_MOBILE_ACCEPTANCE_REQUIRED"}}}}

@router.post("/v1/consumer/auth/register")
def register(body:RegisterBody,request:Request,response:Response):
    try:
        if body.accepted_terms is not True:
            raise HTTPException(422, detail="CONSUMER_TERMS_ACCEPTANCE_REQUIRED")
        try:
            policy = registration_terms_service.require_registration_terms_ready("consumer")
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(503, detail="REGISTRATION_TERMS_NOT_READY") from exc
        if not registration_verification_service.ready():
            raise HTTPException(503, detail="REGISTRATION_VERIFICATION_NOT_READY")
        if body.term_versions != policy["versions"]:
            raise HTTPException(409,detail="CONSUMER_TERMS_VERSION_MISMATCH")
        if body.term_hashes != policy["term_hashes"]:
            raise HTTPException(409,detail="CONSUMER_TERMS_CONTENT_MISMATCH")
        proof = registration_verification_service.check("consumer", body.email, body.challenge_id, body.verification_code, policy)
        profile=consumer_service.register(body.email,body.password,body.display_name,body.phone,verification_proof=proof,registration_audit={"request_id":getattr(request.state,"request_id",None),"client_ip":request.client.host if request.client else None,"term_versions":policy["versions"],"term_hashes":policy["term_hashes"]})
        t=consumer_service.login(body.email,body.password,request.client.host if request.client else None,request.headers.get("user-agent")); _set(response,t)
        return {"data":{"authenticated":True,"profile":profile,"terms":policy["versions"],"term_hashes":policy["term_hashes"]}}
    except ValueError as e: raise HTTPException(409,detail=str(e))

@router.post("/v1/consumer/auth/login")
def login(body:LoginBody,request:Request,response:Response):
    try: t=consumer_service.login(body.email,body.password,request.client.host if request.client else None,request.headers.get("user-agent")); _set(response,t); return {"data":{"authenticated":True}}
    except ValueError as e: raise HTTPException(401,detail=str(e))

@router.post("/v1/consumer/auth/refresh")
def refresh(request:Request,response:Response):
    token=request.cookies.get(settings.consumer_refresh_cookie_name)
    if not token: raise HTTPException(401,detail="REFRESH_COOKIE_REQUIRED")
    try:
        t=identity_service.refresh(token,allowed_actor_types={'CONSUMER'})
        _set(response,t); return {"data":{"refreshed":True}}
    except ValueError as e: raise HTTPException(401,detail=str(e))

@router.post("/v1/consumer/auth/logout")
def logout(response:Response,p:Principal=Depends(consumer_principal)):
    identity_service.revoke_session(p.session_id); _clear(response); return {"data":{"status":"REVOKED"}}

@router.get("/v1/consumer/me")
def me(p:Principal=Depends(consumer_principal)): return {"data":consumer_service.profile_by_user(p.user_id)}

@router.get("/v1/consumer/travelers")
def travelers(p:Principal=Depends(consumer_principal)): return {"data":{"items":consumer_service.list_travelers(p)}}
@router.post("/v1/consumer/travelers")
def add_traveler(body:TravelerBody,p:Principal=Depends(consumer_principal)):
    try: return {"data":consumer_service.add_traveler(p,**body.model_dump())}
    except ValueError as e: raise HTTPException(422,detail=str(e))
@router.delete("/v1/consumer/travelers/{traveler_id}")
def del_traveler(traveler_id:str,p:Principal=Depends(consumer_principal)):
    try: consumer_service.delete_traveler(p,traveler_id); return {"data":{"status":"DELETED"}}
    except ValueError as e: raise HTTPException(404,detail=str(e))

@router.post("/v1/consumer/wallet/payment-methods/tokenize")
def tokenize(body:TokenizeBody,p:Principal=Depends(consumer_principal)):
    try: return {"data":consumer_service.tokenize_payment_method(p,**body.model_dump())}
    except ValueError as e: raise HTTPException(422,detail=str(e))
@router.get("/v1/consumer/wallet")
def wallet(p:Principal=Depends(consumer_principal)): return {"data":consumer_service.wallet(p)}
@router.delete("/v1/consumer/wallet/payment-methods/{payment_method_id}")
def delete_payment(payment_method_id:str,p:Principal=Depends(consumer_principal)):
    try: consumer_service.delete_payment_method(p,payment_method_id); return {"data":{"status":"DELETED"}}
    except ValueError as e: raise HTTPException(404,detail=str(e))

@router.post("/v1/consumer/orders")
async def create_consumer_order(body:ConsumerOrderBody,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    async def execute():
        from go_hotel.services.catalog_fare_snapshot import consent_preflight
        try:consent_preflight(body.prebook_id,body.expected_fare_rule_hash,body.fare_confirmed)
        except ValueError as exc:raise HTTPException(409,detail=str(exc))
        released=release_booking_data(p.user_id,'HOTEL',[body.traveler_id] if body.traveler_id else [],[],requester_id=p.user_id)
        o=await booking_service.create_order(body.prebook_id,p.user_id,body.expected_fare_rule_hash,body.fare_confirmed)
        if released['release_ids']:
            with SessionLocal.begin() as s:
                append_vertical_evidence(s,'HOTEL',o.order_id,'VAULT_BOOKING_DATA_RELEASED',o.status,{'release_ids':released['release_ids'],'minimum_necessary':True,'fields':['LEGAL_NAME','MOBILE']})
        return {"data":{"order_id":o.order_id,"status":o.status,"total_amount_minor":o.total_amount_minor,"currency":o.currency,"vault_release_ids":released['release_ids']}}
    return await run_idempotent_async('CONSUMER_HOTEL_CREATE',idempotency_key,{'account_id':p.user_id,**body.model_dump()},execute)

@router.post("/v1/consumer/orders/{order_id}/secure-checkout")
async def secure_checkout(order_id:str,body:ConsumerCheckoutBody,p:Principal=Depends(consumer_principal)):
    o=assert_consumer_order(p,order_id)
    try: token=consumer_service.payment_token(p,body.payment_method_id)
    except ValueError as e: raise HTTPException(404,detail=str(e))
    payment=await booking_service.pay(order_id,o.total_amount_minor,o.currency,token)
    confirmed=await booking_service.confirm(order_id)
    return {"data":{"order_id":confirmed.order_id,"status":confirmed.status,"payment_id":payment.payment_id,"supplier_confirmation_no":confirmed.supplier_confirmation_no}}

from go_hotel.truth.service import truth_service
from go_hotel.db.models import ReviewSessionRow
class StarBody(BaseModel): star:int
class TagsBody(BaseModel): tags:list[str]

def _assert_review(p:Principal,review_id:str):
    with SessionLocal() as s:
        r=s.get(ReviewSessionRow,review_id)
        if not r or r.account_id!=p.user_id: raise HTTPException(404,detail="REVIEW_NOT_FOUND")
    return r

@router.get("/v1/consumer/reviews/pending")
def consumer_pending_reviews(p:Principal=Depends(consumer_principal)): return {"data":truth_service.pending(p.user_id)}
@router.post("/v1/consumer/reviews/{review_id}/second-trigger")
def consumer_second_trigger(review_id:str,p:Principal=Depends(consumer_principal)):
    _assert_review(p,review_id); return {"data":truth_service.trigger_second(review_id)}
@router.post("/v1/consumer/reviews/{review_id}/star")
def consumer_review_star(review_id:str,body:StarBody,p:Principal=Depends(consumer_principal)):
    _assert_review(p,review_id); return {"data":truth_service.submit_star(review_id,body.star)}
@router.post("/v1/consumer/reviews/{review_id}/tags")
def consumer_review_tags(review_id:str,body:TagsBody,p:Principal=Depends(consumer_principal)):
    _assert_review(p,review_id); return {"data":truth_service.add_tags(review_id,body.tags)}
@router.post("/v1/consumer/reviews/{review_id}/complete")
def consumer_review_complete(review_id:str,p:Principal=Depends(consumer_principal)):
    _assert_review(p,review_id); return {"data":truth_service.complete(review_id)}
