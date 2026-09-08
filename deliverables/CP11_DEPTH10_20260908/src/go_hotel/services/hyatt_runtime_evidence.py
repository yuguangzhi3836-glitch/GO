"""Production evidence producer for the Hyatt 10-hotel gate.

This service stores explicit machine evidence in PostgreSQL. It does not infer
catalog/media/LKG/idempotency/recovery PASS from READY. Producers in the build
pipeline must record each assertion from its owning subsystem; collection remains
fail-closed when any evidence is absent.
"""
from __future__ import annotations
from datetime import datetime, timezone
import os, uuid
from sqlalchemy import select
from go_hotel.db.models import HotelAutoPageEventRow
from go_hotel.db.session import SessionLocal
from .durable_media_index import durable_media_index_service
PREFIX="HYATT_E2E_EVIDENCE_"
def _now(): return datetime.now(timezone.utc)
def _id(): return "hape_"+uuid.uuid4().hex
def _append(s,kind,hotel_id,evidence,actor): s.add(HotelAutoPageEventRow(hotel_auto_page_event_id=_id(),hotel_id=hotel_id,event_type=PREFIX+kind,evidence_json=evidence,actor=actor,created_at=_now()))
def _rows(s,property_id):
    rows=s.scalars(select(HotelAutoPageEventRow).where(HotelAutoPageEventRow.event_type.like(PREFIX+"%")).order_by(HotelAutoPageEventRow.created_at.asc())).all()
    return [r for r in rows if str((r.evidence_json or {}).get("property_id") or "")==property_id]
class HyattRuntimeEvidenceService:
    def record(self,*,kind,property_id,hotel_id,payload,actor="SYSTEM"):
        if not property_id or not isinstance(payload,dict):raise ValueError("HYATT_EVIDENCE_INVALID")
        with SessionLocal() as s:_append(s,kind,hotel_id,{"property_id":property_id,"hotel_id":hotel_id,**payload},actor);s.commit()
    def record_identity(self,*,property_id,hotel_id,canonical_match_count,actor="SYSTEM"):self.record(kind="IDENTITY",property_id=property_id,hotel_id=hotel_id,payload={"canonical_match_count":int(canonical_match_count)},actor=actor)
    def record_catalog(self,*,property_id,hotel_id,official_room_type_ids,go_room_type_ids,actor="SYSTEM"):self.record(kind="CATALOG",property_id=property_id,hotel_id=hotel_id,payload={"official_room_type_ids":list(official_room_type_ids),"go_room_type_ids":list(go_room_type_ids)},actor=actor)
    def record_room_media(self,*,property_id,hotel_id,cross_bind_count,room_bindings_checked,actor="SYSTEM"):self.record(kind="ROOM_MEDIA",property_id=property_id,hotel_id=hotel_id,payload={"room_media_cross_bind_count":int(cross_bind_count),"room_bindings_checked":int(room_bindings_checked)},actor=actor)
    def record_scenes(self,*,property_id,hotel_id,categories,explicit_unborrowed_gap=False,actor="SYSTEM"):self.record(kind="SCENES",property_id=property_id,hotel_id=hotel_id,payload={"hotel_scene_categories":[str(x).upper() for x in categories],"scene_gap_explicit_and_unborrowed":bool(explicit_unborrowed_gap)},actor=actor)
    def record_lkg(self,*,property_id,hotel_id,protected,previous_page_version,failed_candidate_version,active_page_version,actor="SYSTEM"):self.record(kind="LKG",property_id=property_id,hotel_id=hotel_id,payload={"lkg_protected":bool(protected),"previous_page_version":previous_page_version,"failed_candidate_version":failed_candidate_version,"active_page_version":active_page_version},actor=actor)
    def record_idempotency(self,*,property_id,hotel_id,rerun_count,duplicate_hotel_count,duplicate_room_count,unintended_page_proliferation_count,actor="SYSTEM"):self.record(kind="IDEMPOTENCY",property_id=property_id,hotel_id=hotel_id,payload={"rerun_count":int(rerun_count),"duplicate_hotel_count":int(duplicate_hotel_count),"duplicate_room_count":int(duplicate_room_count),"unintended_page_proliferation_count":int(unintended_page_proliferation_count)},actor=actor)
    def record_recovery(self,*,property_id,hotel_id,forced_kill_observed,lease_reclaimed,terminal_ack_count,first_worker,recovery_worker,actor="SYSTEM"):self.record(kind="RECOVERY",property_id=property_id,hotel_id=hotel_id,payload={"forced_kill_observed":bool(forced_kill_observed),"lease_reclaimed":bool(lease_reclaimed),"terminal_ack_count":int(terminal_ack_count),"first_worker":first_worker,"recovery_worker":recovery_worker},actor=actor)
    def collect(self,*,property_id,build_state,hotel_id):
        with SessionLocal() as s:rows=_rows(s,property_id)
        out={"property_id":property_id,"hotel_id":hotel_id,"build_state":build_state}
        for row in rows:
            kind=row.event_type[len(PREFIX):];ev=dict(row.evidence_json or {})
            if kind=="IDENTITY":out["identity_unique"]=int(ev.get("canonical_match_count") or 0)==1
            elif kind=="CATALOG":out["official_room_type_ids"]=list(ev.get("official_room_type_ids") or []);out["go_room_type_ids"]=list(ev.get("go_room_type_ids") or [])
            elif kind=="ROOM_MEDIA":out["room_media_cross_bind_count"]=int(ev.get("room_media_cross_bind_count") or 0);out["room_media_isolation"]=out["room_media_cross_bind_count"]==0 and int(ev.get("room_bindings_checked") or 0)>0
            elif kind=="SCENES":out["hotel_scene_categories"]=list(ev.get("hotel_scene_categories") or []);out["scene_gap_explicit_and_unborrowed"]=ev.get("scene_gap_explicit_and_unborrowed") is True
            elif kind=="LKG":out["lkg_protected"]=ev.get("lkg_protected") is True
            elif kind=="IDEMPOTENCY":out.update({k:int(ev.get(k) or 0) for k in ("rerun_count","duplicate_hotel_count","duplicate_room_count","unintended_page_proliferation_count")})
            elif kind=="RECOVERY":out["forced_kill_observed"]=ev.get("forced_kill_observed") is True;out["lease_reclaimed"]=ev.get("lease_reclaimed") is True;out["terminal_ack_count"]=int(ev.get("terminal_ack_count") or 0)
        assets=durable_media_index_service.list_assets(hotel_id=hotel_id) if hotel_id else []
        out["durable_media_ledger"]=bool(assets);out["published_without_rights_count"]=sum(1 for x in assets if x.get("publication_state")=="PUBLISHED" and not x.get("publishable"))
        media_root=os.getenv("GO_DURABLE_MEDIA_ROOT")
        if media_root:
            from .media_blob_recovery import MediaBlobRecovery
            report=MediaBlobRecovery(media_root).scan(quarantine=False)
            owned={str(x.get("sha256") or "") for x in assets}
            out["missing_blob_count"]=sum(1 for x in report.get("missing",[]) if str(x.get("sha256") or "") in owned)
            out["corrupt_blob_count"]=sum(1 for x in report.get("corrupt",[]) if str(x.get("sha256") or "") in owned)
            out["blob_integrity_evidence_source"]="MEDIA_BLOB_RECOVERY"
        else:
            out["missing_blob_count"]=None;out["corrupt_blob_count"]=None;out["blob_integrity_evidence_source"]="UNAVAILABLE"
        return out
hyatt_runtime_evidence_service=HyattRuntimeEvidenceService()
