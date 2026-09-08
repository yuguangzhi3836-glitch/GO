"""Strict machine-readable evidence matrix for the Hyatt 10-hotel gate.

READY never implies PASS. Every hotel must pass truth, media, LKG and idempotency
checks. Exactly one cohort hotel is the forced-kill recovery probe; requiring all ten
to be killed would be both unnecessary and inconsistent with the acceptance runner.
"""
from __future__ import annotations

REQUIRED_SCENES={"EXTERIOR","LOBBY","DINING","WELLNESS","MEETING"}

def _bool(value): return value is True
def _zero(value): return isinstance(value,int) and not isinstance(value,bool) and value==0

def evaluate_hotel_evidence(record:dict)->dict:
    checks={}
    checks["ready"]=record.get("build_state")=="READY"
    checks["identity_unique"]=_bool(record.get("identity_unique"))
    checks["catalog_parity"]=(
        isinstance(record.get("official_room_type_ids"),list)
        and isinstance(record.get("go_room_type_ids"),list)
        and len(record["official_room_type_ids"])>0
        and set(record["official_room_type_ids"])==set(record["go_room_type_ids"])
        and len(record["go_room_type_ids"])==len(set(record["go_room_type_ids"]))
    )
    checks["room_media_isolation"]=_bool(record.get("room_media_isolation")) and _zero(record.get("room_media_cross_bind_count"))
    scenes={str(x).upper() for x in (record.get("hotel_scene_categories") or [])}
    checks["hotel_scene_media"]=REQUIRED_SCENES.issubset(scenes) or _bool(record.get("scene_gap_explicit_and_unborrowed"))
    checks["blob_integrity_available"]=(
        record.get("blob_integrity_evidence_source")=="MEDIA_BLOB_RECOVERY"
        and isinstance(record.get("missing_blob_count"),int)
        and isinstance(record.get("corrupt_blob_count"),int)
    )
    checks["durable_media"]=(
        checks["blob_integrity_available"]
        and _bool(record.get("durable_media_ledger"))
        and _zero(record.get("missing_blob_count"))
        and _zero(record.get("corrupt_blob_count"))
        and _zero(record.get("published_without_rights_count"))
    )
    checks["lkg_event_evidence"]=(
        record.get("lkg_evidence_source")=="POSTGRES_PUBLICATION_EVENT_LEDGER"
        and isinstance(record.get("failed_candidate_count"),int)
        and record.get("failed_candidate_count")>0
        and record.get("failed_candidate_count")==record.get("protected_failure_count")
    )
    checks["lkg_protected"]=checks["lkg_event_evidence"] and _bool(record.get("lkg_protected"))
    db_diffs=record.get("authoritative_db_diffs")
    checks["authoritative_db_idempotency"]=(
        isinstance(db_diffs,list)
        and len(db_diffs)==2
        and all(isinstance(x,dict) and _bool(x.get("zero_proliferation")) for x in db_diffs)
    )
    checks["idempotent_reruns"]=(
        isinstance(record.get("rerun_count"),int)
        and record.get("rerun_count")>=2
        and _zero(record.get("duplicate_hotel_count"))
        and _zero(record.get("duplicate_room_count"))
        and _zero(record.get("unintended_page_proliferation_count"))
        and checks["authoritative_db_idempotency"]
    )
    if _bool(record.get("recovery_probe_required")):
        checks["forced_kill_recovery"]=(
            _bool(record.get("forced_kill_observed"))
            and _bool(record.get("lease_reclaimed"))
            and record.get("terminal_ack_count")==1
        )
    else:
        checks["forced_kill_recovery"]=True
    return {"status":"PASS" if all(checks.values()) else "HOLD","checks":checks}

def evaluate_cohort(records:list[dict])->dict:
    if len(records)!=10:
        return {"status":"HOLD","reason":"HYATT_COHORT_MUST_BE_EXACTLY_10","count":len(records),"hotels":[]}
    probes=[x for x in records if _bool(x.get("recovery_probe_required"))]
    if len(probes)!=1:
        return {"status":"HOLD","reason":"HYATT_COHORT_REQUIRES_EXACTLY_ONE_FORCED_KILL_PROBE","probe_count":len(probes),"hotels":[]}
    hotels=[];seen=set()
    for record in records:
        pid=str(record.get("property_id") or "")
        if not pid or pid in seen:
            return {"status":"HOLD","reason":"HYATT_COHORT_PROPERTY_ID_INVALID_OR_DUPLICATE","property_id":pid,"hotels":hotels}
        seen.add(pid)
        result=evaluate_hotel_evidence(record)
        hotels.append({"property_id":pid,**result})
    passed=all(x["status"]=="PASS" for x in hotels)
    return {
        "status":"PASS" if passed else "HOLD",
        "count":len(records),
        "recovery_probe_property_id":str(probes[0].get("property_id") or ""),
        "pass_count":sum(1 for x in hotels if x["status"]=="PASS"),
        "hold_count":sum(1 for x in hotels if x["status"]!="PASS"),
        "hotels":hotels,
    }
