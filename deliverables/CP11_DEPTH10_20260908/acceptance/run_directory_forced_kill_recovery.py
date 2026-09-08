#!/usr/bin/env python3
"""Real PostgreSQL forced-kill acceptance for directory emission/enqueue boundaries.

Runs three independent Marriott synthetic frozen-directory cohorts against the real
production durable snapshot/outbox/task-ledger code, without network access:

1. SIGKILL after PREPARED and before any enqueue.
2. SIGKILL after a strict subset of deterministic tasks has been enqueued.
3. SIGKILL after all deterministic tasks are enqueued but before emission commit.

After each kill the parent restarts the production enumerate_and_enqueue path from the
same durable cursor. PASS requires frozen inventory count == unique logical task count,
exactly one QUEUED ledger event per deterministic task, a committed emission batch,
and the snapshot emitted offset equal to the frozen inventory count. Any lost or
logically duplicated hotel is HOLD/FAIL.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import sys
import time
import uuid

from sqlalchemy import select, text

from go_hotel.db.models import HotelAutoPageEventRow
from go_hotel.db.session import SessionLocal
from go_hotel.services.chain_autonomous_build import chain_autonomous_build_service, discovery_seed
from go_hotel.services.chain_directory_emission_outbox import chain_directory_emission_outbox
from go_hotel.services.chain_directory_snapshot_store import postgres_directory_snapshot_store
from go_hotel.services.chain_hotel_registry import ChainCode, OfficialPropertySeed
from go_hotel.services.chain_task_lease import chain_task_lease_service, EVENT_PREFIX
from go_hotel.services.durable_hierarchical_chain_directory import DurableHierarchicalDirectoryAdapter, _encode_cursor
from go_hotel.services.standard_chain_directory_adapters import MarriottDirectoryAdapter

SCENARIOS=("PREPARED_ONLY","PARTIAL_ENQUEUE","ALL_ENQUEUED_NO_COMMIT")
PROPERTY_COUNT=int(os.getenv("GO_DIRECTORY_KILL_PROPERTY_COUNT","7"))


def _require_postgres():
    with SessionLocal() as s:
        if s.get_bind().dialect.name!="postgresql":raise RuntimeError("POSTGRES_REQUIRED")
        return str(s.execute(text("select version()" )).scalar())


def _inventory(run_id:str,scenario:str):
    rows=[]
    for i in range(PROPERTY_COUNT):
        pid=(run_id.replace("-","")[:10]+scenario[:3]+f"{i:03d}").upper()
        rows.append({"property_id":pid,"name":f"DEPTH10 Marriott Recovery {scenario} {i}","url":f"https://www.marriott.com/en-us/hotels/{pid.lower()}-depth10-recovery/overview/"})
    return rows


def _state(inventory:list[dict]):
    digest=hashlib.sha256(json.dumps(inventory,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
    return {"phase":"EMIT","frontier":[],"visited":["https://www.marriott.com/en-us/hotel-search.mi"],"aliases":{},"properties":{x["property_id"]:{"name":x["name"],"url":x["url"]} for x in inventory},"page_digests":{},"frozen_inventory":inventory,"inventory_sha256":digest,"emitted":0}


def _seeds(inventory:list[dict]):
    return [OfficialPropertySeed(chain=ChainCode.MARRIOTT,official_property_id=x["property_id"],name=x["name"],property_url=x["url"],directory_url="https://www.marriott.com/en-us/hotel-search.mi") for x in inventory]


def _enqueue(seed):
    payload={"task_type":"CHAIN_HOTEL","chain":seed.chain.value,"official_property_id":seed.official_property_id,"idempotency_key":seed.idempotency_key,"directory_url":seed.directory_url,"discovery_seed":discovery_seed(seed)}
    return chain_task_lease_service.enqueue(task_id=seed.idempotency_key,payload=payload,actor="DIRECTORY_FORCED_KILL")


def _queued_event_counts(task_ids:set[str]):
    with SessionLocal() as s:
        rows=s.scalars(select(HotelAutoPageEventRow).where(HotelAutoPageEventRow.event_type==EVENT_PREFIX+"QUEUED")).all()
    counts={tid:0 for tid in task_ids}
    for row in rows:
        tid=str((row.evidence_json or {}).get("task_id") or "")
        if tid in counts:counts[tid]+=1
    return counts


def _child(snapshot_id:str,revision:int,scenario:str,write_fd:int):
    adapter=DurableHierarchicalDirectoryAdapter(MarriottDirectoryAdapter())
    cursor=_encode_cursor(chain=ChainCode.MARRIOTT.value,snapshot_id=snapshot_id,revision=revision)
    seeds,prepared_cursor,evidence=adapter.enumerate_page(lambda _: (_ for _ in ()).throw(RuntimeError("NETWORK_NOT_ALLOWED")),cursor,actor="DIRECTORY_FORCED_KILL")
    if not evidence.get("emission_prepared") or len(seeds)!=PROPERTY_COUNT:raise RuntimeError("DIRECTORY_PREPARE_FAILED")
    if scenario=="PARTIAL_ENQUEUE":
        for seed in seeds[:max(1,len(seeds)//2)]:_enqueue(seed)
    elif scenario=="ALL_ENQUEUED_NO_COMMIT":
        for seed in seeds:_enqueue(seed)
    os.write(write_fd,b"KILL_NOW\n");os.close(write_fd);time.sleep(120)


def _kill_at_boundary(snapshot_id,revision,scenario):
    read_fd,write_fd=os.pipe();pid=os.fork()
    if pid==0:
        os.close(read_fd)
        try:_child(snapshot_id,revision,scenario,write_fd)
        finally:os._exit(0)
    os.close(write_fd);signal_bytes=os.read(read_fd,32);os.close(read_fd)
    if signal_bytes!=b"KILL_NOW\n":
        os.waitpid(pid,0);raise RuntimeError(f"DIRECTORY_CHILD_BOUNDARY_NOT_REACHED:{scenario}")
    os.kill(pid,signal.SIGKILL);_,status=os.waitpid(pid,0)
    if not os.WIFSIGNALED(status) or os.WTERMSIG(status)!=signal.SIGKILL:raise RuntimeError("DIRECTORY_CHILD_NOT_SIGKILL")


def _recover(snapshot_id,revision):
    cursor=_encode_cursor(chain=ChainCode.MARRIOTT.value,snapshot_id=snapshot_id,revision=revision)
    return chain_autonomous_build_service.enumerate_and_enqueue(chain=ChainCode.MARRIOTT,fetch_page=lambda _: (_ for _ in ()).throw(RuntimeError("NETWORK_NOT_ALLOWED_DURING_EMIT")),cursor=cursor,actor="DIRECTORY_FORCED_KILL_RECOVERY")


def _run_scenario(run_id,scenario):
    inventory=_inventory(run_id,scenario);seed_list=_seeds(inventory);task_ids={x.idempotency_key for x in seed_list}
    view=postgres_directory_snapshot_store.create(chain=ChainCode.MARRIOTT.value,initial_state=_state(inventory),actor="DIRECTORY_FORCED_KILL")
    _kill_at_boundary(view.snapshot_id,view.revision,scenario)
    prepared_before=chain_directory_emission_outbox.load_prepared(snapshot_id=view.snapshot_id,base_revision=view.revision)
    if not prepared_before or prepared_before.get("committed"):raise RuntimeError("DIRECTORY_PREPARED_BATCH_NOT_RECOVERABLE")
    recovery=_recover(view.snapshot_id,view.revision)
    final=postgres_directory_snapshot_store.load(snapshot_id=view.snapshot_id,expected_chain=ChainCode.MARRIOTT.value)
    prepared_after=chain_directory_emission_outbox.load_prepared(snapshot_id=view.snapshot_id,base_revision=view.revision)
    logical={x.task_id for x in chain_task_lease_service.list() if x.task_id in task_ids}
    queue_counts=_queued_event_counts(task_ids)
    checks={
        "sigkill_boundary_observed":True,
        "prepared_replayed":prepared_after is not None,
        "emission_committed":bool(prepared_after and prepared_after.get("committed")),
        "directory_complete":recovery.get("directory_complete") is True,
        "frozen_inventory_equals_unique_tasks":len(inventory)==len(logical)==len(task_ids),
        "zero_lost":logical==task_ids,
        "zero_duplicate_queue_events":all(v==1 for v in queue_counts.values()),
        "offset_equals_inventory":int(final.state.get("emitted") or -1)==len(inventory),
        "snapshot_revision_advanced_once":final.revision==view.revision+1,
    }
    return {"scenario":scenario,"snapshot_id":view.snapshot_id,"inventory_count":len(inventory),"unique_task_count":len(logical),"queued_event_counts":queue_counts,"final_revision":final.revision,"checks":checks,"status":"PASS" if all(checks.values()) else "HOLD"}


def main():
    evidence={"gate":"DIRECTORY_FORCED_KILL_RECOVERY","status":"HOLD","postgres":None,"scenarios":[]}
    try:
        evidence["postgres"]=_require_postgres();run_id=uuid.uuid4().hex
        evidence["scenarios"]=[_run_scenario(run_id,s) for s in SCENARIOS]
        evidence["status"]="PASS" if all(x["status"]=="PASS" for x in evidence["scenarios"]) else "HOLD"
        print(json.dumps(evidence,ensure_ascii=False,indent=2));return 0 if evidence["status"]=="PASS" else 2
    except Exception as exc:
        evidence["error"]=repr(exc);print(json.dumps(evidence,ensure_ascii=False,indent=2));return 1

if __name__=="__main__":raise SystemExit(main())
