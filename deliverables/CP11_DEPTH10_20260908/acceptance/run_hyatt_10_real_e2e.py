#!/usr/bin/env python3
"""Hyatt 10-real-hotel three-generation worker drain and evidence gate.

Generation 1 builds all ten hotels; hotel #1 is force-killed by the dedicated
recovery harness before its real build completes. Generations 2 and 3 explicitly
requeue the ACKED business task and execute the production pipeline again. Merely
receiving an old ACK from enqueue is therefore incapable of satisfying idempotency.
"""
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

def now():return datetime.now(timezone.utc).isoformat()
def fetch_page(url):
    req=Request(url,headers={"User-Agent":"GO-Hotel-Official-Capture/DEPTH10"})
    with urlopen(req,timeout=30) as r:final=r.geturl();body=r.read(8*1024*1024+1)
    if len(body)>8*1024*1024:raise ValueError("HYATT_DIRECTORY_RESPONSE_TOO_LARGE")
    return final,body.decode("utf-8",errors="replace")
def require_postgres():
    with SessionLocal() as s:
        if s.get_bind().dialect.name!="postgresql":raise RuntimeError("POSTGRES_REQUIRED")
        return str(s.execute(text("select version()" )).scalar())
def runtime_evidence(hotel_id,property_id):return hyatt_runtime_evidence_service.collect(hotel_id=hotel_id,property_id=property_id,build_state="READY")
def signature(row):
    return {"hotel_id":row.get("hotel_id"),"rooms":sorted(row.get("go_room_type_ids") or []),"page_version":row.get("active_page_version") or row.get("page_version")}
def duplicate_delta(base,current):
    return {"duplicate_hotel_count":0 if base.get("hotel_id")==current.get("hotel_id") else 1,
            "duplicate_room_count":max(0,len(current.get("rooms") or [])-len(set(current.get("rooms") or []))),
            "unintended_page_proliferation_count":0 if base.get("page_version")==current.get("page_version") else 1}
def main():
    ev={"gate":"HYATT_10_REAL_E2E_RUNTIME","started_at":now(),"status":"HOLD","hotels":[],"generations":[]}
    try:
        ev["postgres"]=require_postgres();final,html=fetch_page(HYATT_CHINA_DIRECTORY);ev["directory_url"]=final;ev["directory_snapshot_sha256"]=hashlib.sha256(html.encode()).hexdigest()
        seeds=HyattDirectoryAdapter(directory_url=final,page_size=100).enumerate_all(lambda _:(final,html),max_properties=1000)[:10]
        if len(seeds)!=10:raise RuntimeError("HYATT_OFFICIAL_DIRECTORY_LT_10")
        payloads={s.idempotency_key:{"task_type":"CHAIN_HOTEL","chain":"HYATT","official_property_id":s.official_property_id,"idempotency_key":s.idempotency_key,"directory_url":s.directory_url,"discovery_seed":discovery_seed(s)} for s in seeds}
        baseline={}
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
                if not drained or view.state!="ACKED" or view.generation!=generation or chain_task_lease_service.terminal_event_count(tid,generation=generation)!=1:raise RuntimeError("HYATT_GENERATION_REAL_ACK_REQUIRED")
                result=(drained.get("result") if isinstance(drained,dict) else None) or {};hotel_id=result.get("hotel_id") or drained.get("hotel_id")
                row={"property_id":seed.official_property_id,"hotel_id":hotel_id,"task_id":tid,"generation":generation,"task_attempt":view.attempt,**runtime_evidence(hotel_id,seed.official_property_id)}
                sig=signature(row)
                if generation==1:baseline[tid]=sig
                else:
                    delta=duplicate_delta(baseline[tid],sig);row["db_delta"]=delta
                    if generation==3:
                        hyatt_runtime_evidence_service.record_idempotency(property_id=seed.official_property_id,hotel_id=hotel_id,rerun_count=2,actor="HYATT_10_E2E",**delta)
                        row.update(runtime_evidence(hotel_id,seed.official_property_id))
                generation_rows.append(row)
            ev["generations"].append({"generation":generation,"hotels":generation_rows})
        ev["hotels"]=ev["generations"][-1]["hotels"]
        matrix=evaluate_cohort(ev["hotels"]);ev["matrix"]=matrix;ev["cohort_count"]=10;ev["status"]=matrix["status"];ev["finished_at"]=now();print(json.dumps(ev,ensure_ascii=False,indent=2));return 0 if matrix["status"]=="PASS" else 2
    except Exception as exc:ev["error"]=repr(exc);ev["finished_at"]=now();print(json.dumps(ev,ensure_ascii=False,indent=2));return 1
if __name__=="__main__":raise SystemExit(main())
