from __future__ import annotations

import os, re, uuid
from datetime import datetime, timezone
from sqlalchemy import select

from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    HotelCanonicalProfileRow, HotelContentSourceSnapshotRow, HotelContactPointRow,
    HotelAutoPageVersionRow, HotelRegistrationDirectRow, HotelAutoPageEventRow,
    TravelEntityRow, TravelEntityAliasRow, TravelEntityFactRow, TravelEntityRelationRow,
)
from go_hotel.services.media_harvester import media_harvester_service
from go_hotel.travel_intelligence.service import travel_intelligence_service

UTC=timezone.utc
HARBIN_NAMES=("哈尔滨", "harbin")
RESET_CONFIRMATION="DELETE_HARBIN_HOTEL_INFRASTRUCTURE"
TIER5_MARKERS=("五星","5星","五星级","5-star","five star","五钻","5钻")
TIER4_MARKERS=("四星","4星","四星级","4-star","four star","四钻","4钻")


def now(): return datetime.now(UTC)

def _text(v)->str:
    if isinstance(v,(dict,list,tuple,set)):
        return str(v).lower()
    return str(v or "").strip().lower()

def _is_harbin_payload(v)->bool:
    t=_text(v)
    return any(x in t for x in HARBIN_NAMES)

def admission(candidate:dict)->dict:
    """Tier admission is evidence based. Source classification controls build tier only.
    It never turns OTA/platform 'diamond' classification into official government star truth.
    """
    raw=[]
    for k in ("stars","star_rating","rating_class","diamond","diamond_rating","hotel_class","category","segment","source_classification"):
        val=candidate.get(k)
        if val not in (None,""): raw.append((k,str(val)))
    blob=" ".join(v.lower() for _,v in raw)
    tier=0; matched=None
    if any(m.lower() in blob for m in TIER5_MARKERS): tier=5
    elif any(m.lower() in blob for m in TIER4_MARKERS): tier=4
    else:
        # Numeric values are admitted only when the source explicitly names the field as star/diamond.
        for k,v in raw:
            try: n=int(float(v))
            except Exception: continue
            if k in {"stars","star_rating","diamond","diamond_rating"} and n in {4,5}:
                tier=n; matched=(k,v); break
    if tier and matched is None:
        matched=next(((k,v) for k,v in raw if any(m.lower() in v.lower() for m in (TIER5_MARKERS if tier==5 else TIER4_MARKERS))),None)
    return {
        "admitted": tier in {4,5}, "build_tier": tier,
        "source_classification": matched[1] if matched else None,
        "classification_field": matched[0] if matched else None,
        "official_star_truth": False,
        "rule_version":"TIER_ADMISSION_V1",
    }

class HotelInfrastructureP0Service:
    def _harbin_ids(self,s)->set[str]:
        ids=set()
        for r in s.scalars(select(HotelCanonicalProfileRow)).all():
            if _is_harbin_payload(r.canonical_json): ids.add(r.hotel_id)
        for r in s.scalars(select(HotelContentSourceSnapshotRow)).all():
            if _is_harbin_payload(r.payload_json) or _is_harbin_payload(r.source_url):
                if r.canonical_hotel_id: ids.add(r.canonical_hotel_id)
        return ids

    def reset_preview(self)->dict:
        with SessionLocal() as s:
            ids=self._harbin_ids(s)
            snaps=[r for r in s.scalars(select(HotelContentSourceSnapshotRow)).all() if (r.canonical_hotel_id in ids) or _is_harbin_payload(r.payload_json)]
            events=[r for r in s.scalars(select(HotelAutoPageEventRow)).all() if (r.hotel_id in ids) or _is_harbin_payload(r.evidence_json)]
            aliases=s.scalars(select(TravelEntityAliasRow).where(TravelEntityAliasRow.source_type=="GO_HOTEL_CANONICAL")).all()
            ti_ids={a.go_entity_id for a in aliases if a.source_entity_id in ids}
            return {
                "scope":"哈尔滨市","hotel_ids":sorted(ids),"hotel_count":len(ids),
                "source_snapshots":len(snaps),
                "contacts":sum(1 for r in s.scalars(select(HotelContactPointRow)).all() if r.hotel_id in ids),
                "page_versions":sum(1 for r in s.scalars(select(HotelAutoPageVersionRow)).all() if r.hotel_id in ids),
                "registrations":sum(1 for r in s.scalars(select(HotelRegistrationDirectRow)).all() if r.hotel_id in ids),
                "events":len(events),"travel_graph_entities":len(ti_ids),
                "media_assets":sum(len(media_harvester_service.list_assets(hotel_id=x)) for x in ids),
                "destructive":True,"rds_schema_change":False,"alembic_action":False,
                "required_confirmation":RESET_CONFIRMATION,
            }

    def reset_execute(self,*,confirmation:str,actor:str)->dict:
        env=(os.getenv("APP_ENV") or os.getenv("GO_ENV") or "").lower()
        if env not in {"staging","test","testing","development","dev"}:
            raise ValueError("CLEAN_SLATE_RESET_NON_PRODUCTION_ONLY")
        if confirmation!=RESET_CONFIRMATION: raise ValueError("CLEAN_SLATE_RESET_CONFIRMATION_REQUIRED")
        preview=self.reset_preview(); ids=set(preview["hotel_ids"])
        with SessionLocal.begin() as s:
            # Travel Graph projections derived from these hotel canonical IDs.
            aliases=s.scalars(select(TravelEntityAliasRow).where(TravelEntityAliasRow.source_type=="GO_HOTEL_CANONICAL")).all()
            ti_ids={a.go_entity_id for a in aliases if a.source_entity_id in ids}
            for r in s.scalars(select(TravelEntityRelationRow)).all():
                if r.from_entity_id in ti_ids or r.to_entity_id in ti_ids: s.delete(r)
            for r in s.scalars(select(TravelEntityFactRow)).all():
                if r.go_entity_id in ti_ids: s.delete(r)
            for r in aliases:
                if r.go_entity_id in ti_ids: s.delete(r)
            for eid in ti_ids:
                row=s.get(TravelEntityRow,eid)
                if row: s.delete(row)
            for r in s.scalars(select(HotelRegistrationDirectRow)).all():
                if r.hotel_id in ids: s.delete(r)
            for r in s.scalars(select(HotelContactPointRow)).all():
                if r.hotel_id in ids: s.delete(r)
            for r in s.scalars(select(HotelAutoPageVersionRow)).all():
                if r.hotel_id in ids: s.delete(r)
            for r in s.scalars(select(HotelContentSourceSnapshotRow)).all():
                if r.canonical_hotel_id in ids or _is_harbin_payload(r.payload_json): s.delete(r)
            for r in s.scalars(select(HotelAutoPageEventRow)).all():
                if r.hotel_id in ids or _is_harbin_payload(r.evidence_json): s.delete(r)
            for hid in ids:
                row=s.get(HotelCanonicalProfileRow,hid)
                if row: s.delete(row)
        for hid in ids: media_harvester_service.purge_hotel(hid)
        after=self.reset_preview()
        if any(after[k] for k in ("hotel_count","source_snapshots","contacts","page_versions","registrations","events","travel_graph_entities","media_assets")):
            raise ValueError("CLEAN_SLATE_RESET_NOT_EMPTY")
        return {"status":"PASS","scope":"哈尔滨市","before":preview,"after":after,"actor":actor,"completed_at":now().isoformat(),"migration_unchanged":True}

    def completeness_gate(self,hotel_id:str,*,tier:int)->dict:
        with SessionLocal() as s:
            p=s.get(HotelCanonicalProfileRow,hotel_id)
            if not p: raise ValueError("HOTEL_CANONICAL_NOT_FOUND")
            c=p.canonical_json or {}
            sources=s.scalars(select(HotelContentSourceSnapshotRow).where(HotelContentSourceSnapshotRow.canonical_hotel_id==hotel_id)).all()
        independent={(x.source_type,x.source_key) for x in sources}
        rooms=c.get("rooms") if isinstance(c.get("rooms"),list) else []
        publishable=media_harvester_service.list_assets(hotel_id=hotel_id,publishable_only=True)
        identity=bool((c.get("name") or c.get("name_zh")) and c.get("address") and c.get("latitude") is not None and c.get("longitude") is not None)
        hotel_name=_text(c.get("name") or c.get("name_zh"))
        is_golden=("敖麓谷雅" in hotel_name or "aoluguya" in hotel_name)

        # Golden-media diversity: exact SHA duplicates and perceptual near-duplicates do not count twice.
        unique=[]
        for rec in publishable:
            ph=str(rec.get("perceptual_hash") or "").strip().lower()
            sha=str(rec.get("sha256") or "").strip().lower()
            duplicate=False
            for prev in unique:
                if sha and sha==str(prev.get("sha256") or "").strip().lower():
                    duplicate=True; break
                pph=str(prev.get("perceptual_hash") or "").strip().lower()
                if ph and pph and len(ph)==16 and len(pph)==16:
                    if (int(ph,16)^int(pph,16)).bit_count() <= 6:
                        duplicate=True; break
            if not duplicate: unique.append(rec)
        roles={str(x.get("role") or "").upper() for x in unique}
        scene_map={
            "EXTERIOR":"外观", "LOBBY":"大堂", "ROOM":"客房", "DINING":"餐饮",
            "WELLNESS":"康体", "SIGNATURE_SPACE":"特色空间",
        }
        scene_coverage={cn:(role in roles) for role,cn in scene_map.items()}

        min_completeness=9500 if is_golden else 8500
        min_media=30 if is_golden else 3
        requirements={
            "identity_complete":identity,
            "independent_sources_ge_2":len(independent)>=2,
            "rooms_ge_1":len(rooms)>=1,
            f"publishable_unique_media_ge_{min_media}":len(unique)>=min_media,
            f"completeness_ge_{min_completeness//100}":int(p.completeness_bps or 0)>=min_completeness,
        }
        if is_golden:
            requirements["golden_six_scene_media_coverage"]=all(scene_coverage.values())
            requirements["rights_unknown_effective_count_zero"]=all(str(x.get("rights_state") or "")!="RIGHTS_UNKNOWN" for x in unique)
        passed=all(requirements.values())
        return {
            "hotel_id":hotel_id,"tier":tier,"passed":passed,"golden_build":is_golden,
            "requirements":requirements,"completeness_bps":p.completeness_bps,
            "source_count":len(independent),"room_count":len(rooms),
            "publishable_media_raw_count":len(publishable),"publishable_media_count":len(unique),
            "media_scene_coverage":scene_coverage if is_golden else None,
            "media_near_duplicate_removed":max(0,len(publishable)-len(unique)),
            "page_eligible":passed,
            "rule_version":"AOLUGUYA_GOLDEN_95_30_SIX_SCENE_V1" if is_golden else "HOTEL_COMPLETENESS_GATE_P0_1.0",
        }

    def project_to_travel_graph(self,hotel_id:str)->dict:
        with SessionLocal() as s:
            p=s.get(HotelCanonicalProfileRow,hotel_id)
            if not p: raise ValueError("HOTEL_CANONICAL_NOT_FOUND")
            c=p.canonical_json or {}
            snaps=s.scalars(select(HotelContentSourceSnapshotRow).where(HotelContentSourceSnapshotRow.canonical_hotel_id==hotel_id)).all()
        entity=travel_intelligence_service.upsert_entity_alias(entity_type="HOTEL",canonical_name=c.get("name") or c.get("name_zh") or hotel_id,source_type="GO_HOTEL_CANONICAL",source_entity_id=hotel_id)
        eid=entity["go_entity_id"]
        for snap in snaps:
            travel_intelligence_service.append_entity_fact(entity_id=eid,fact_type="HOTEL_SOURCE_SNAPSHOT",fact_value=snap.payload_json or {},provenance=snap.source_type,source_id=snap.source_key,confidence=min(1.0,max(0.0,float(snap.confidence_bps or 0)/10000)),verification_state="SOURCE_OBSERVED",evidence_ref=snap.content_source_snapshot_id)
        travel_intelligence_service.append_entity_fact(entity_id=eid,fact_type="HOTEL_CANONICAL_PROFILE",fact_value={"hotel_id":hotel_id,"canonical":c,"completeness_bps":p.completeness_bps},provenance="GO_CANONICAL",source_id=hotel_id,confidence=1.0,verification_state="GO_CANONICAL",evidence_ref=f"hotel:{hotel_id}")
        return {"hotel_id":hotel_id,"go_entity_id":eid,"fact_sources":len(snaps)+1}

hotel_infrastructure_p0_service=HotelInfrastructureP0Service()
