#!/usr/bin/env python3
"""Forced-kill probe bound to one exact Hyatt cohort business task.

Parent kills only after the child has successfully exact-claimed the task and signaled
LEASED through a pipe. Recovery evidence uses the durable task ledger's generation-1
terminal ACK count rather than a hard-coded value.
"""
from __future__ import annotations
import os,signal,sys,time
from go_hotel.services.chain_task_lease import chain_task_lease_service
from go_hotel.services.chain_autonomous_build import chain_autonomous_build_service
from go_hotel.services.hyatt_runtime_evidence import hyatt_runtime_evidence_service
LEASE_SECONDS=int(os.getenv("GO_HYATT_KILL_LEASE_SECONDS","15"))

def child(task_id:str,write_fd:int):
    task=chain_task_lease_service.claim(worker_id="HYATT_KILL_CHILD",lease_seconds=LEASE_SECONDS,task_type="CHAIN_HOTEL",task_id=task_id,actor="HYATT_10_E2E")
    if task is None or task.task_id!=task_id:raise RuntimeError("HYATT_KILL_EXACT_CLAIM_FAILED")
    os.write(write_fd,b"LEASED\n");os.close(write_fd);time.sleep(LEASE_SECONDS*3)

def run(*,task_id:str,property_id:str)->dict:
    read_fd,write_fd=os.pipe();pid=os.fork()
    if pid==0:
        os.close(read_fd)
        try:child(task_id,write_fd)
        finally:os._exit(0)
    os.close(write_fd)
    leased=os.read(read_fd,32);os.close(read_fd)
    if leased!=b"LEASED\n":
        os.waitpid(pid,0);raise RuntimeError("HYATT_KILL_CHILD_DID_NOT_CONFIRM_LEASE")
    os.kill(pid,signal.SIGKILL);os.waitpid(pid,0)
    early=chain_task_lease_service.claim(worker_id="HYATT_EARLY_RECLAIM",lease_seconds=LEASE_SECONDS,task_type="CHAIN_HOTEL",task_id=task_id,actor="HYATT_10_E2E")
    if early is not None:raise RuntimeError("HYATT_LEASE_RECLAIMED_BEFORE_EXPIRY")
    time.sleep(LEASE_SECONDS+1)
    result=chain_autonomous_build_service.process_one(worker_id="HYATT_RECOVERY_WORKER",actor="HYATT_10_E2E",lease_seconds=180,task_id=task_id)
    final=chain_task_lease_service.get(task_id)
    terminal_ack_count=chain_task_lease_service.terminal_event_count(task_id,generation=1,state="ACKED")
    if not result or result.get("state")!="ACKED" or final.state!="ACKED" or final.attempt<2 or terminal_ack_count!=1:raise RuntimeError("HYATT_REAL_BUILD_RECOVERY_FAILED")
    hotel_id=(result.get("result") or {}).get("hotel_id")
    if not hotel_id:raise RuntimeError("HYATT_RECOVERY_HOTEL_ID_REQUIRED")
    hyatt_runtime_evidence_service.record_recovery(property_id=property_id,hotel_id=hotel_id,forced_kill_observed=True,lease_reclaimed=True,terminal_ack_count=terminal_ack_count,first_worker="HYATT_KILL_CHILD",recovery_worker="HYATT_RECOVERY_WORKER",actor="HYATT_10_E2E")
    return {"task_id":task_id,"property_id":property_id,"hotel_id":hotel_id,"attempt":final.attempt,"state":final.state,"result":result.get("result"),"terminal_ack_count":terminal_ack_count}

if __name__=="__main__":
    if len(sys.argv)!=3:raise SystemExit("usage: hyatt_cohort_forced_kill.py TASK_ID PROPERTY_ID")
    print(run(task_id=sys.argv[1],property_id=sys.argv[2]))
