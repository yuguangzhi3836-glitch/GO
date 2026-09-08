#!/usr/bin/env python3
"""Hyatt 10-real-hotel exact worker-drain and evidence gate.

Runtime only. Discovers the deterministic cohort from Hyatt official data, enqueues
exact durable tasks, drains those exact task IDs, and refuses PASS until every hotel
has explicit catalog/media/LKG/idempotency/recovery evidence. Hong Kong is not
required to run this during code construction; it belongs to the final one-shot.
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

def now():return datetime.now(timezone.utc).isoformat()
def fetch_page(url):
    req=Request(url,headers={"User-Agent":"GO-Hotel-Official-Capture/DEPTH10"})
    with urlopen(req,timeout=30) as r: final=r.geturl();body=r.read(8*1024*1024+1)
    if len(body)>8*1024*1024:raise ValueError("HYATT_DIRECTORY_RESPONSE_TOO_LARGE")
    return final,body.decode("utf-8",errors="replace")
def require_postgres():
    with SessionLocal() as s:
        if s.get_bind().dialect.name!="postgresql":raise RuntimeError("POSTGRES_REQUIRED")
        return str(s.execute(text("select version()" )).scalar())
def _runtime_evidence(hotel_id,property_id):
    """Read acceptance evidence emitted by production build services.

    Deliberately fail closed: until the catalog/media/LKG producers persist this
    contract, fields remain absent and the cohort stays HOLD rather than inferring
    completeness from READY.
    """
    try:
        from go_hotel.services.hyatt_runtime_evidence import hyatt_runtime_evidence_service
    except Exception:
        return {"property_id":property_id,"hotel_id":hotel_id,"evidence_producer":"MISSING"}
    value=hyatt_runtime_evidence_service.for_hotel(hotel_id=hotel_id,property_id=property_id)
    return value if isinstance(value,dict) else {"property_id":property_id,"hotel_id":hotel_id,"evidence_producer":"INVALID"}
def main():
    evidence={"gate":"HYATT_10_REAL_E2E_RUNTIME","started_at":now(),"status":"HOLD","hotels":[]}
    try:
        evidence["postgres"]=require_postgres();final,html=fetch_page(HYATT_CHINA_DIRECTORY)
        evidence["directory_url"]=final;evidence["directory_snapshot_sha256"]=hashlib.sha256(html.encode()).hexdigest()
        seeds=HyattDirectoryAdapter(directory_url=final,page_size=100).enumerate_all(lambda _:(final,html),max_properties=1000)
        if len(seeds)<10:raise RuntimeError("HYATT_OFFICIAL_DIRECTORY_LT_10")
        cohort=seeds[:10]
        for seed in cohort:
            payload={"task_type":"CHAIN_HOTEL","chain":"HYATT","official_property_id":seed.official_property_id,"idempotency_key":seed.idempotency_key,"directory_url":seed.directory_url,"discovery_seed":discovery_seed(seed)}
            task=chain_task_lease_service.enqueue(task_id=seed.idempotency_key,payload=payload,actor="HYATT_10_E2E")
            drained=chain_autonomous_build_service.process_one(worker_id=f"hyatt-e2e-{seed.official_property_id}",actor="HYATT_10_E2E",lease_seconds=180,task_id=task.task_id)
            view=chain_task_lease_service.get(task.task_id)
            row={"property_id":seed.official_property_id,"name":seed.name,"property_url":seed.property_url,"task_id":task.task_id,"task_state":view.state,"task_attempt":view.attempt}
            if drained and isinstance(drained.get("result"),dict):
                result=drained["result"];row["build_state"]=result.get("build_state");row["hotel_id"]=result.get("hotel_id")
                row.update(_runtime_evidence(row.get("hotel_id"),seed.official_property_id))
            evidence["hotels"].append(row)
        matrix=evaluate_cohort(evidence["hotels"]);evidence["matrix"]=matrix;evidence["cohort_count"]=len(cohort)
        evidence["status"]=matrix["status"];evidence["finished_at"]=now();print(json.dumps(evidence,ensure_ascii=False,indent=2));return 0 if matrix["status"]=="PASS" else 2
    except Exception as exc:
        evidence["error"]=repr(exc);evidence["finished_at"]=now();print(json.dumps(evidence,ensure_ascii=False,indent=2));return 1
if __name__=="__main__":raise SystemExit(main())
