from __future__ import annotations
import uuid
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from go_hotel.core.config import settings
from go_hotel.security.deps import admin_principal
from go_hotel.security.service import Principal
from go_hotel.travel_intelligence.service import travel_intelligence_service as svc
from go_hotel.repositories.sql import repo

router=APIRouter(tags=["travel-intelligence"])

def _enabled():
    if not settings.travel_intelligence_enabled: raise HTTPException(503,detail="TRAVEL_INTELLIGENCE_DISABLED")
def _corr(x_correlation_id:str|None): return x_correlation_id or f"corr_{uuid.uuid4().hex}"
def _call(fn,*args,**kwargs):
    try:return fn(*args,**kwargs)
    except ValueError as e:
        code=str(e); status=404 if code.endswith("NOT_FOUND") else 409 if "CONFLICT" in code or "AMBIGUOUS" in code or "MISMATCH" in code else 422
        if code.startswith("MODEL_GATEWAY_") and ("DENIED" in code or "UNAVAILABLE" in code or "NOT_IMPLEMENTED" in code or "CIRCUIT" in code or "BUDGET" in code or "QUALITY_FLOOR" in code): status=503
        if code=="IDEMPOTENCY_IN_PROGRESS": status=409
        if code=="C07_JUDGMENT_AUTHORITY_FORBIDDEN": status=409
        raise HTTPException(status,detail=code) from e

def _idem(operation:str,key:str,payload:dict,fn,status_code:int=200):
    if not key or len(key)>128: raise HTTPException(422,detail="IDEMPOTENCY_KEY_INVALID")
    try:
        state,rec=repo.claim_idempotency(operation,key,payload)
    except ValueError as e:
        raise HTTPException(409,detail=str(e)) from e
    if state=="REPLAY": return rec["response"]
    if state=="IN_PROGRESS": raise HTTPException(409,detail="IDEMPOTENCY_IN_PROGRESS")
    try:
        response=fn()
        repo.complete_idempotency(operation,key,payload,response,response_code=status_code)
        return response
    except Exception:
        repo.release_idempotency_claim(operation,key,payload)
        raise

class IntentCreateRequest(BaseModel):
    traveler_id:str; session_id:str; raw_input:str=Field(min_length=1,max_length=20000); consent_scope:list[str]=Field(default_factory=list)
class EntityResolveRequest(BaseModel): source_type:str; source_entity_id:str
class EntityCreateRequest(BaseModel): entity_type:str; canonical_name:str=Field(min_length=1,max_length=500); source_type:str|None=None; source_entity_id:str|None=None
class JudgmentRequest(BaseModel): intent_id:str; candidate_entity_ids:list[str]=Field(min_length=1,max_length=200); context:dict=Field(default_factory=dict)
class ModelInvokeRequest(BaseModel):
    capability:str; input:dict; privacy_class:str; session_id:str=Field(min_length=1,max_length=64); complexity:float=Field(default=0.2,ge=0,le=1); latency_budget_ms:int|None=None; cost_budget_usd:float|None=None
    cost_scope:str="JUDGMENT"; business_reference_id:str|None=None; attributed_revenue_usd:float=Field(default=0.0,ge=0); estimated_quality:float=Field(default=1.0,ge=0,le=1); estimated_call_cost_usd:float=Field(default=0.0,ge=0); input_tokens:int=Field(default=0,ge=0); output_tokens:int=Field(default=0,ge=0); price_snapshot_id:str="LOCAL_ZERO_COST_V1"; circuit_open:bool=False
class TravelEventRequest(BaseModel):
    event_id:str|None=None; event_type:str; occurred_at:str|None=None; actor_type:str; actor_id:str|None=None; tenant_id:str|None=None; organization_id:str|None=None; traveler_id:str|None=None; session_id:str|None=None; intent_id:str|None=None; entity_id:str|None=None; decision_id:str|None=None; trip_id:str|None=None; order_id:str|None=None; transaction_root_id:str|None=None; source:str; schema_version:str="1.0"; correlation_id:str; causation_id:str|None=None; idempotency_key:str; privacy_class:str; retention_class:str; payload_schema:str|None=None; payload:dict=Field(default_factory=dict)

@router.post("/internal/v1/travel-intelligence/intents",status_code=201)
def create_intent(body:IntentCreateRequest,x_correlation_id:str|None=Header(default=None,alias="X-Correlation-ID"),idempotency_key:str=Header(alias="Idempotency-Key"),p:Principal=Depends(admin_principal)):
    _enabled(); corr=_corr(x_correlation_id); payload=body.model_dump()|{"actor_id":p.user_id,"correlation_id":x_correlation_id or "AUTO"}
    return _idem("ti.create_intent",idempotency_key,payload,lambda:{"data":_call(svc.create_intent,traveler_id=body.traveler_id,session_id=body.session_id,raw_input=body.raw_input,consent_scope=body.consent_scope,correlation_id=corr)},201)

@router.post("/internal/v1/travel-intelligence/intents/{intent_id}/refine")
def refine_intent(intent_id:str,body:IntentCreateRequest,x_correlation_id:str|None=Header(default=None,alias="X-Correlation-ID"),idempotency_key:str=Header(alias="Idempotency-Key"),p:Principal=Depends(admin_principal)):
    _enabled(); corr=_corr(x_correlation_id); payload=body.model_dump()|{"intent_id":intent_id,"actor_id":p.user_id,"correlation_id":x_correlation_id or "AUTO"}
    return _idem("ti.refine_intent",idempotency_key,payload,lambda:{"data":_call(svc.refine_intent,intent_id,traveler_id=body.traveler_id,session_id=body.session_id,raw_input=body.raw_input,consent_scope=body.consent_scope,correlation_id=corr)})

@router.get("/internal/v1/travel-entities/{entity_id}")
def get_entity(entity_id:str,p:Principal=Depends(admin_principal)):
    _enabled(); return {"data":_call(svc.get_entity,entity_id)}

@router.post("/internal/v1/travel-entities/resolve")
def resolve_entity(body:EntityResolveRequest,idempotency_key:str=Header(alias="Idempotency-Key"),p:Principal=Depends(admin_principal)):
    _enabled(); payload=body.model_dump()|{"actor_id":p.user_id}
    return _idem("ti.resolve_entity",idempotency_key,payload,lambda:{"data":_call(svc.resolve_entity,source_type=body.source_type,source_entity_id=body.source_entity_id)})

@router.post("/internal/v1/travel-entities",status_code=201)
def create_entity(body:EntityCreateRequest,idempotency_key:str=Header(alias="Idempotency-Key"),p:Principal=Depends(admin_principal)):
    _enabled(); payload=body.model_dump()|{"actor_id":p.user_id}
    return _idem("ti.create_entity",idempotency_key,payload,lambda:{"data":_call(svc.create_entity,entity_type=body.entity_type,canonical_name=body.canonical_name,source_type=body.source_type,source_entity_id=body.source_entity_id)},201)

@router.post("/internal/v1/judgment/evaluate")
def evaluate(body:JudgmentRequest,x_correlation_id:str|None=Header(default=None,alias="X-Correlation-ID"),idempotency_key:str=Header(alias="Idempotency-Key"),p:Principal=Depends(admin_principal)):
    _enabled(); corr=_corr(x_correlation_id); payload=body.model_dump()|{"actor_id":p.user_id,"correlation_id":x_correlation_id or "AUTO"}
    return _idem("ti.evaluate_judgment",idempotency_key,payload,lambda:{"data":_call(svc.evaluate_judgment,intent_id=body.intent_id,candidate_entity_ids=body.candidate_entity_ids,context=body.context,correlation_id=corr)})

@router.get("/internal/v1/judgment/decisions/{decision_id}")
def decision(decision_id:str,p:Principal=Depends(admin_principal)):
    _enabled(); return {"data":_call(svc.get_decision,decision_id)}

@router.post("/internal/v1/model-gateway/invoke")
def model_invoke(body:ModelInvokeRequest,x_correlation_id:str|None=Header(default=None,alias="X-Correlation-ID"),idempotency_key:str=Header(alias="Idempotency-Key"),p:Principal=Depends(admin_principal)):
    _enabled(); corr=_corr(x_correlation_id); payload=body.model_dump()|{"actor_id":p.user_id,"correlation_id":x_correlation_id or "AUTO"}
    return _idem("ti.model_invoke",idempotency_key,payload,lambda:{"data":_call(svc.model_invoke,capability=body.capability,input_data=body.input,privacy_class=body.privacy_class,latency_budget_ms=body.latency_budget_ms,cost_budget_usd=body.cost_budget_usd,complexity=body.complexity,correlation_id=corr,session_id=body.session_id,cost_scope=body.cost_scope,business_reference_id=body.business_reference_id,attributed_revenue_usd=body.attributed_revenue_usd,estimated_quality=body.estimated_quality,estimated_call_cost_usd=body.estimated_call_cost_usd,input_tokens=body.input_tokens,output_tokens=body.output_tokens,price_snapshot_id=body.price_snapshot_id,circuit_open=body.circuit_open)})

@router.post("/internal/v1/travel-events",status_code=202)
def append_event(body:TravelEventRequest,p:Principal=Depends(admin_principal)):
    _enabled(); return {"data":_call(svc.append_event,body.model_dump())}

@router.get("/internal/v1/travelers/{traveler_id}/preferences")
def preferences(traveler_id:str,purpose:str=Query(min_length=1),p:Principal=Depends(admin_principal)):
    _enabled(); return {"data":{"traveler_id":traveler_id,"purpose":purpose,"preferences":[],"projection":"P0_EMPTY_PURPOSE_BOUND"}}

@router.get("/internal/v1/intelligence/entities/{entity_id}/evidence")
def entity_evidence(entity_id:str,limit:int=Query(50,ge=1,le=100),p:Principal=Depends(admin_principal)):
    _enabled(); return {"data":svc.entity_evidence(entity_id,limit=limit)}

@router.get("/internal/v1/intelligence/decisions/{decision_id}/explain")
def explain(decision_id:str,p:Principal=Depends(admin_principal)):
    _enabled(); return {"data":_call(svc.explain_decision,decision_id)}


class EntityFactRequest(BaseModel):
    fact_type:str; fact_value:dict; provenance:str; source_id:str|None=None; confidence:float=Field(ge=0,le=1); verification_state:str; evidence_ref:str|None=None
class EntityLinkRequest(BaseModel):
    from_entity_id:str; relation_type:str; to_entity_id:str

@router.post('/internal/v1/travel-entities/{entity_id}/facts')
def entity_fact(entity_id:str,body:EntityFactRequest,idempotency_key:str=Header(alias='Idempotency-Key'),p:Principal=Depends(admin_principal)):
    _enabled(); payload=body.model_dump()|{'entity_id':entity_id,'actor_id':p.user_id}
    return _idem('ti.append_entity_fact',idempotency_key,payload,lambda:{'data':_call(svc.append_entity_fact,entity_id=entity_id,**body.model_dump())})

@router.post('/internal/v1/travel-entities/relations')
def entity_relation(body:EntityLinkRequest,idempotency_key:str=Header(alias='Idempotency-Key'),p:Principal=Depends(admin_principal)):
    _enabled(); payload=body.model_dump()|{'actor_id':p.user_id}
    return _idem('ti.link_entities',idempotency_key,payload,lambda:{'data':_call(svc.link_entities,**body.model_dump())})

@router.get('/internal/v1/travelers/{traveler_id}/graph')
def traveler_graph(traveler_id:str,purpose:str=Query(min_length=1),p:Principal=Depends(admin_principal)):
    _enabled(); return {'data':_call(svc.traveler_graph,traveler_id,purpose=purpose)}

@router.post('/internal/v1/judgment/evaluate-independent')
def evaluate_independent(body:JudgmentRequest,x_correlation_id:str|None=Header(default=None,alias='X-Correlation-ID'),idempotency_key:str=Header(alias='Idempotency-Key'),p:Principal=Depends(admin_principal)):
    _enabled(); corr=_corr(x_correlation_id); payload=body.model_dump()|{'actor_id':p.user_id,'correlation_id':x_correlation_id or 'AUTO'}
    return _idem('ti.independent_judgment',idempotency_key,payload,lambda:{'data':_call(svc.independent_judgment,intent_id=body.intent_id,candidate_entity_ids=body.candidate_entity_ids,context=body.context,correlation_id=corr)})
