#!/usr/bin/env python3
"""Real PostgreSQL worker-death recovery gate using SIGKILL.

A child process claims a durable task and remains alive without ACK. The parent
proves the lease exists, sends SIGKILL, proves the child died, proves no early
reclaim, then waits for lease expiry and requires a second worker to reclaim the
same task at attempt 2 and ACK it. PostgreSQL is mandatory.
"""
from __future__ import annotations
import json, multiprocessing as mp, os, signal, sys, time, uuid
from datetime import datetime, timezone
from sqlalchemy import text
from go_hotel.db.session import SessionLocal
from go_hotel.services.chain_task_lease import chain_task_lease_service

def now(): return datetime.now(timezone.utc).isoformat()
def db_info():
    with SessionLocal() as s:
        if s.get_bind().dialect.name!="postgresql": raise RuntimeError("POSTGRES_REQUIRED")
        return {"dialect":"postgresql","version":s.execute(text("select version()" )).scalar()}

def doomed_worker(task_id, ready):
    task=chain_task_lease_service.claim(worker_id="sigkill-worker-A",lease_seconds=15,task_type="CHAIN_HOTEL")
    if not task or task.task_id!=task_id:
        ready.put({"error":"SIGKILL_WORKER_FAILED_TO_CLAIM"}); return
    ready.put({"pid":os.getpid(),"task_id":task.task_id,"attempt":task.attempt,"lease_until":task.lease_until.isoformat() if task.lease_until else None})
    while True: time.sleep(60)

def main():
    ev={"gate":"POSTGRES_CRASH_RECOVERY_GATE","started_at":now(),"checks":[]}
    try:
        ev["database"]=db_info(); task_id="depth10-sigkill-"+uuid.uuid4().hex
        chain_task_lease_service.enqueue(task_id=task_id,payload={"task":"CHAIN_HOTEL","probe":True})
        q=mp.Queue(); p=mp.Process(target=doomed_worker,args=(task_id,q)); p.start(); claimed=q.get(timeout=10)
        if claimed.get("error"): raise RuntimeError(claimed["error"])
        if claimed["pid"]!=p.pid or claimed["attempt"]!=1: raise RuntimeError("SIGKILL_CLAIM_EVIDENCE_INVALID")
        ev["checks"].append({"name":"child_claimed_attempt_1","pass":True,**claimed})
        early=chain_task_lease_service.claim(worker_id="worker-B-early",lease_seconds=15,task_type="CHAIN_HOTEL")
        if early is not None: raise RuntimeError("EARLY_RECLAIM_OCCURRED")
        os.kill(p.pid,signal.SIGKILL); killed_at=now(); p.join(10)
        if p.is_alive(): raise RuntimeError("SIGKILL_CHILD_STILL_ALIVE")
        if p.exitcode != -signal.SIGKILL: raise RuntimeError(f"SIGKILL_EXIT_CODE_INVALID:{p.exitcode}")
        ev["checks"].append({"name":"worker_forced_killed","pass":True,"pid":p.pid,"signal":"SIGKILL","exitcode":p.exitcode,"killed_at":killed_at})
        early2=chain_task_lease_service.claim(worker_id="worker-B-before-expiry",lease_seconds=15,task_type="CHAIN_HOTEL")
        if early2 is not None: raise RuntimeError("POST_KILL_EARLY_RECLAIM_OCCURRED")
        lease_until=datetime.fromisoformat(claimed["lease_until"].replace("Z","+00:00"))
        wait=max(0,(lease_until-datetime.now(timezone.utc)).total_seconds())+1.0; time.sleep(wait)
        b=chain_task_lease_service.claim(worker_id="worker-B",lease_seconds=30,task_type="CHAIN_HOTEL")
        if not b or b.task_id!=task_id or b.attempt!=2: raise RuntimeError("EXPIRED_LEASE_NOT_RECLAIMED_AS_ATTEMPT_2")
        ack=chain_task_lease_service.ack(task_id=task_id,worker_id="worker-B",result={"recovered_after_sigkill":True})
        if ack.state!="ACKED": raise RuntimeError("RECOVERED_TASK_NOT_ACKED")
        ev["checks"].append({"name":"same_task_reclaimed_and_acked","pass":True,"task_id":task_id,"attempt":b.attempt,"reclaimed_at":now()})
        after=chain_task_lease_service.claim(worker_id="worker-C",lease_seconds=15,task_type="CHAIN_HOTEL")
        if after is not None: raise RuntimeError("ACKED_TASK_RECLAIMED")
        ev["checks"].append({"name":"acked_terminal","pass":True})
        ev["status"]="PASS"; ev["finished_at"]=now(); print(json.dumps(ev,ensure_ascii=False,indent=2)); return 0
    except Exception as exc:
        ev["status"]="HOLD"; ev["error"]=repr(exc); ev["finished_at"]=now(); print(json.dumps(ev,ensure_ascii=False,indent=2)); return 1
if __name__=="__main__": sys.exit(main())
