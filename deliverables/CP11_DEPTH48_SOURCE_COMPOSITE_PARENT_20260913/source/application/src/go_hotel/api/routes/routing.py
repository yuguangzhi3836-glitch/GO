from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import RoutingDecisionRow
from go_hotel.routing.sla import sla_service
from go_hotel.routing.router import rollout_bucket

router=APIRouter(prefix="/internal/v1/routing",tags=["internal-routing"])

class SlaSnapshotRequest(BaseModel):
    success_rate_bps:int=Field(ge=0,le=10000)
    confirmation_latency_ms_p95:int=Field(ge=0)
    cancel_success_rate_bps:int=Field(ge=0,le=10000)
    inventory_accuracy_bps:int=Field(ge=0,le=10000)
    price_consistency_bps:int=Field(ge=0,le=10000)
    sample_size:int=Field(default=0,ge=0)

@router.put("/sla/{connector_id}")
def put_sla(connector_id:str, body:SlaSnapshotRequest):
    return {"data":sla_service.upsert_snapshot(connector_id,**body.model_dump())}

@router.get("/sla/{connector_id}")
def get_sla(connector_id:str): return {"data":sla_service.get(connector_id).as_dict()}

@router.get("/decisions/{decision_id}")
def get_decision(decision_id:str):
    with SessionLocal() as s:
        r=s.get(RoutingDecisionRow,decision_id)
        if not r: return {"data":None,"error":{"code":"ROUTING_DECISION_NOT_FOUND"}}
        return {"data":{"decision_id":r.decision_id,"operation":r.operation,"hotel_id":r.hotel_id,"request_key":r.request_key,"selected_connector_id":r.selected_connector_id,"candidate_connector_ids":r.candidate_connector_ids,"fallback_connector_ids":r.fallback_connector_ids,"reason_codes":r.reason_codes,"candidate_snapshot":r.candidate_snapshot,"created_at":r.created_at}}

@router.get("/canary-bucket/{connector_id}")
def canary_bucket(connector_id:str,request_key:str): return {"data":{"connector_id":connector_id,"request_key":request_key,"bucket":rollout_bucket(request_key,connector_id)}}
