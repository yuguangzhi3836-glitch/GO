from pydantic import BaseModel, Field
from fastapi import APIRouter, Header, Query, Depends, HTTPException
from go_hotel.truth.service import truth_service
from go_hotel.repositories.sql import repo
from go_hotel.core.errors import conflict
from go_hotel.security.deps import supplier_principal, require_permission, assert_supplier_risk
from go_hotel.security.service import Principal, approval_service, audit_service

router=APIRouter()

class EligibilityRequest(BaseModel):
    verified_stay: bool = True
    trigger_source: str = "FIRST_INVITE"

class StarRequest(BaseModel):
    star: int = Field(ge=1,le=5)

class TagsRequest(BaseModel):
    tags: list[str] = Field(min_length=1,max_length=5)

class ContentRequest(BaseModel):
    text: str|None=None
    voice_ref: str|None=None
    photo_refs: list[str]=Field(default_factory=list,max_length=10)

class EvidenceRequest(BaseModel):
    evidence_type: str
    payload: dict=Field(default_factory=dict)
    content_ref: str|None=None

class RiskDecisionRequest(BaseModel):
    decision: str
    confidence_bps: int=Field(default=8000,ge=0,le=10000)

class RemediationRequest(BaseModel):
    action: str
    evidence_ids: list[str]=Field(default_factory=list)

def idem(operation,key,payload):
    if not key: return None
    rec=repo.get_idempotency(operation,key)
    if rec and rec['request_hash'] != repo.hash_payload(payload): conflict('IDEMPOTENCY_CONFLICT','Same key used with different payload')
    return rec

@router.post('/internal/v1/orders/{order_id}/reviews/eligibility')
def review_eligibility(order_id:str,body:EligibilityRequest):
    return {'data':truth_service.create_eligibility(order_id,body.verified_stay,body.trigger_source)}

@router.post('/internal/v1/reviews/{review_id}/first-invite')
def first_invite(review_id:str): return {'data':truth_service.send_first_invite(review_id)}

@router.post('/internal/v1/reviews/{review_id}/mark-not-reviewed')
def mark_not_reviewed(review_id:str): return {'data':truth_service.mark_not_reviewed(review_id)}

@router.get('/v1/reviews/pending')
def pending(account_id:str=Query(default='acct_demo')): return {'data':truth_service.pending(account_id)}

@router.post('/v1/reviews/{review_id}/second-trigger')
def second_trigger(review_id:str): return {'data':truth_service.trigger_second(review_id)}

@router.post('/v1/reviews/{review_id}/star')
def star(review_id:str,body:StarRequest,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload=body.model_dump()|{'review_id':review_id}; rec=idem('review_star',idempotency_key,payload)
    if rec: return rec['response']
    result=truth_service.submit_star(review_id,body.star); response={'data':result}
    if idempotency_key: repo.save_idempotency('review_star',idempotency_key,payload,response,review_id)
    return response

@router.post('/v1/reviews/{review_id}/tags')
def tags(review_id:str,body:TagsRequest): return {'data':truth_service.add_tags(review_id,body.tags)}

@router.post('/v1/reviews/{review_id}/content')
def content(review_id:str,body:ContentRequest): return {'data':truth_service.add_content(review_id,body.text,body.voice_ref,body.photo_refs)}

@router.post('/v1/reviews/{review_id}/complete')
def complete(review_id:str,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload={'review_id':review_id}; rec=idem('review_complete',idempotency_key,payload)
    if rec: return rec['response']
    result=truth_service.complete(review_id); response={'data':result}
    if idempotency_key: repo.save_idempotency('review_complete',idempotency_key,payload,response,review_id)
    return response

@router.get('/v1/reviews/{review_id}')
def get_review(review_id:str): return {'data':truth_service.get_review(review_id)}

@router.get('/internal/v1/risk-events/{risk_event_id}')
def get_risk(risk_event_id:str): return {'data':truth_service.get_risk(risk_event_id)}

@router.post('/v1/supplier/risk-cases/{risk_event_id}/evidence')
def supplier_evidence(risk_event_id:str,body:EvidenceRequest,p:Principal=Depends(supplier_principal)):
    assert_supplier_risk(p,risk_event_id); result=truth_service.supplier_evidence(risk_event_id,body.evidence_type,body.payload,body.content_ref); audit_service.append(p,'SUPPLIER_RISK_EVIDENCE_SUBMITTED','RISK_EVENT',risk_event_id,after=result); return {'data':result}

@router.post('/internal/v1/risk-events/{risk_event_id}/decision')
def risk_decision(risk_event_id:str,body:RiskDecisionRequest,x_approval_id:str|None=Header(default=None,alias='X-Approval-ID'),p:Principal=Depends(require_permission('admin:trust'))):
    if not x_approval_id: raise HTTPException(403,detail='SECOND_APPROVAL_REQUIRED')
    try: approval_service.consume(p,x_approval_id,'RISK_FINALIZATION',risk_event_id)
    except PermissionError as e: raise HTTPException(403,detail=str(e))
    result=truth_service.decide_risk(risk_event_id,body.decision,body.confidence_bps); audit_service.append(p,'RISK_FINALIZED','RISK_EVENT',risk_event_id,after=result,approval_id=x_approval_id); return {'data':result}

@router.post('/v1/supplier/risk-cases/{risk_event_id}/remediation')
def remediation(risk_event_id:str,body:RemediationRequest,p:Principal=Depends(supplier_principal)):
    assert_supplier_risk(p,risk_event_id); result=truth_service.submit_remediation(risk_event_id,body.action,body.evidence_ids); audit_service.append(p,'SUPPLIER_REMEDIATION_SUBMITTED','RISK_EVENT',risk_event_id,after=result); return {'data':result}

@router.post('/internal/v1/risk-events/{risk_event_id}/verify-remediation')
def verify_remediation(risk_event_id:str,p:Principal=Depends(require_permission('admin:trust'))): return {'data':truth_service.verify_remediation(risk_event_id)}
