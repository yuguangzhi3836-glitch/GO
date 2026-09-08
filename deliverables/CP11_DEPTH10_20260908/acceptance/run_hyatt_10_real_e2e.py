#!/usr/bin/env python3
"""Hyatt 10-real-hotel three-generation authoritative acceptance runner."""
from __future__ import annotations
import hashlib,json
from datetime import datetime,timezone
from urllib.request import Request,urlopen
from sqlalchemy import text
from go_hotel.db.session import SessionLocal
from go_hotel.services.hyatt_directory_adapter import HyattDirectoryAdapter,HYATT_CHINA_DIRECTORY
from go_hotel.services.chain_autonomous_build import discovery_seed,chain_autonomous_build_service
from go_hotel.services.chain_task_lease import chain_task_lease_service
from go_hotel.services.hyatt_e2e_evidence import evaluate_cohort
from go_hotel.services.hyatt_runtime_evidence import hyatt_runtime_evidence_service
from go_hotel.services.hyatt_db_authority_snapshot import snapshot as db_snapshot,diff as db_diff

def now():return datetime.now(timezone.utc).isoformat()
def fetch_page(url):
    req=Request(url,headers={"User-Agent":"GO-Hotel-Official-Capture/DEPTH10"})
    with urlopen(req,timeout=30) as r:final=r.geturl();body=r.read(8*1024*1024+1)
    if len(body)>8*1024*1024:raise ValueError("HYATT_DIRECTORY_RESPONSE_TOO_LARGE")
    return final,body.decode("utf-8",errors="replace")
def require_postgres():
    with SessionLocal() as s:
        if s.get_bind().dialect.name!="postgresql":raise RuntimeError("POSTGRES_REQUIRED")
        return str(s.execute(text("select version()")).scalar())
def runtime_evidence(hotel_id,property_id):return hyatt_runtime_evidence_service.collect(hotel_id=hotel_id,property_id=property_id,build_state="READY")
def main():
    ev={"gate":"HYATT_10_REAL_E2E_RUNTIME","started_at":now(),"status":"HOLD","hotels":[],"generations":[]}
    try:
        ev["postgres"]=require_postgres();final,html=fetch_page(HYATT_CHINA_DIRECTORY);ev["directory_url"]=final;ev["directory_snapshot_sha256"]=hashlib.sha256(html.encode()).hexdigest()
        seeds=HyattDirectoryAdapter(directory_url=final,page_size=100).enumerate_all(lambda _:(final,html),max_properties=1000)[:10]
        if len(seeds)!=10:raise RuntimeError("HYATT_OFFICIAL_DIRECTORY_LT_10")
        payloads={s.idempotency_key:{"task_type":"CHAIN_HOTEL","chain":"HYATT","official_property_id":s.official_property_id,"idempotency_key":s.idempotency_key,"directory_url":s.directory_url,"discovery_seed":discovery_seed(s)} for s in seeds}
        baseline_db={};diffs_by_task={s.idempotency_key:[] for s in seeds};hotel_ids={}
        for generation in (1,2,3):
            generation_rows=[]
            for index,seed in enumerate(seeds):
                tid=seed.idempotency_key;payload=payloads[tid]
                if generation==1:
                    task=chain_task_lease_service.enqueue(task_id=tid,payload=payload,actor="HYATT_10_E2E")
                    if task.state=="ACKED":raise RuntimeError("HYATT_GENERATION1_PREEXISTING_ACK_REQUIRES_CLEAN_COHORT")
                    if index==0:
                        from hyatt_cohort_forced_kill import run as forced_kill
                        drained=forced_kill(task_id=tid,property_id=seed.official_property_id)
                    else:drained=chain_autonomous_build_service.process_one(worker_id=f"hyatt-g1-{index}",actor="HYATT_10_E2E",lease_seconds=180,task_id=tid)
                else:
                    task=chain_task_lease_service.rerun(task_id=tid,payload=payload,actor="HYATT_10_E2E",reason=f"IDEMPOTENCY_GENERATION_{generation}")
                    if task.generation!=generation or task.state!="QUEUED":raise RuntimeError("HYATT_RERUN_NOT_NEW_GENERATION")
                    drained=chain_autonomous_build_service.process_one(worker_id=f"hyatt-g{generation}-{index}",actor="HYATT_10_E2E",lease_seconds=180,task_id=tid)
                view=chain_task_lease_service.get(tid)
                ack_count=chain_task_lease_service.terminal_event_count(tid,generation=generation,state="ACKED")
                if not drained or view.state!="ACKED" or view.generation!=generation or ack_count!=1:raise RuntimeError("HYATT_GENERATION_REAL_ACK_REQUIRED")
                result=(drained.get("result") if isinstance(drained,dict) else None) or {};hotel_id=result.get("hotel_id") or drained.get("hotel_id")
                if not hotel_id:raise RuntimeError("HYATT_GENERATION_HOTEL_ID_REQUIRED")
                if tid in hotel_ids and hotel_ids[tid]!=hotel_id:raise RuntimeError("HYATT_CANONICAL_HOTEL_ID_DRIFT")
                hotel_ids[tid]=hotel_id;snap=db_snapshot(hotel_id=hotel_id)
                row={"property_id":seed.official_property_id,"hotel_id":hotel_id,"task_id":tid,"generation":generation,"task_attempt":view.attempt,"terminal_ack_count_generation":ack_count,"db_snapshot":snap,**runtime_evidence(hotel_id,seed.official_property_id)}
                if generation==1:baseline_db[tid]=snap
                else:
                    authoritative=db_diff(baseline_db[tid],snap);diffs_by_task[tid].append(authoritative);row["authoritative_db_diff"]=authoritative
                generation_rows.append(row)
            ev["generations"].append({"generation":generation,"hotels":generation_rows})
        final_rows=[]
        for index,row in enumerate(ev["generations"][2]["hotels"]):
            tid=row["task_id"];diffs=diffs_by_task[tid]
            if len(diffs)!=2:raise RuntimeError("HYATT_REQUIRES_TWO_AUTHORITATIVE_DB_DIFFS")
            row["authoritative_db_diffs"]=diffs;row["authoritative_db_idempotency"]=all(x.get("zero_proliferation") is True for x in diffs);row["recovery_probe_required"]=index==0
            duplicate_hotel_count=sum(len(x.get("hotel_entity_added") or [])+len(x.get("hotel_entity_removed") or []) for x in diffs)
            duplicate_room_count=sum(len(x.get("room_entity_added") or [])+len(x.get("room_entity_removed") or []) for x in diffs)
            unintended_page_proliferation_count=sum(len(x.get("page_version_added") or [])+len(x.get("active_page_version_added") or []) for x in diffs)
            hyatt_runtime_evidence_service.record_idempotency(property_id=row["property_id"],hotel_id=row["hotel_id"],rerun_count=2,duplicate_hotel_count=duplicate_hotel_count,duplicate_room_count=duplicate_room_count,unintended_page_proliferation_count=unintended_page_proliferation_count,actor="HYATT_10_E2E")
            refreshed=runtime_evidence(row["hotel_id"],row["property_id"]);row.update(refreshed);row["authoritative_db_diffs"]=diffs;row["authoritative_db_idempotency"]=all(x.get("zero_proliferation") is True for x in diffs);row["recovery_probe_required"]=index==0
            final_rows.append(row)
        ev["hotels"]=final_rows;matrix=evaluate_cohort(final_rows);ev["matrix"]=matrix;ev["cohort_count"]=10;ev["status"]=matrix["status"];ev["finished_at"]=now();print(json.dumps(ev,ensure_ascii=False,indent=2));return 0 if matrix["status"]=="PASS" else 2
    except Exception as exc:ev["error"]=repr(exc);ev["finished_at"]=now();print(json.dumps(ev,ensure_ascii=False,indent=2));return 1
if __name__=="__main__":raise SystemExit(main())
