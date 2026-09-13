from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import RoomExternalIdentityRow, OfferMergeDecisionRow, OfferDriftEventRow
from go_hotel.merge.identity import room_identity_service

router=APIRouter(prefix="/internal/v1/merge",tags=["internal-merge"])

class RoomMapRequest(BaseModel):
    connector_id:str
    external_room_id:str
    canonical_room_id:str
    confidence_bps:int=Field(default=10000,ge=0,le=10000)
    match_method:str="CONTRACTED_MAPPING"

@router.put("/room-mappings")
def put_room_mapping(body:RoomMapRequest):
    room_identity_service.map(body.connector_id,body.external_room_id,body.canonical_room_id,body.confidence_bps,body.match_method)
    return {"data":body.model_dump()|{"status":"ACTIVE"}}

@router.get("/decisions/{decision_id}")
def get_merge_decision(decision_id:str):
    with SessionLocal() as s:
        r=s.get(OfferMergeDecisionRow,decision_id)
        if not r:return {"data":None,"error":{"code":"MERGE_DECISION_NOT_FOUND"}}
        return {"data":{"decision_id":r.decision_id,"hotel_id":r.hotel_id,"canonical_room_id":r.canonical_room_id,"selected_offer_id":r.selected_offer_id,"selected_connector_id":r.selected_connector_id,"alternate_offer_ids":r.alternate_offer_ids,"reason_codes":r.reason_codes,"conflicts":r.conflicts,"candidate_snapshot":r.candidate_snapshot,"created_at":r.created_at}}

@router.get("/drift")
def list_drift(hotel_id:str|None=None,status:str="OPEN",limit:int=100):
    with SessionLocal() as s:
        q=select(OfferDriftEventRow).where(OfferDriftEventRow.status==status).order_by(OfferDriftEventRow.detected_at.desc()).limit(limit)
        if hotel_id:q=q.where(OfferDriftEventRow.hotel_id==hotel_id)
        rows=s.scalars(q).all()
        return {"data":[{"drift_id":r.drift_id,"connector_id":r.connector_id,"hotel_id":r.hotel_id,"canonical_room_id":r.canonical_room_id,"changed_fields":r.changed_fields,"before_snapshot":r.before_snapshot,"after_snapshot":r.after_snapshot,"detected_at":r.detected_at,"status":r.status} for r in rows]}
