#!/usr/bin/env python3
"""Forced-kill probe bound to one exact Hyatt cohort task.

Parent process enqueues/targets the exact cohort task. Child claims that exact task
and is SIGKILLed before ACK. Parent proves no early reclaim, waits for lease expiry,
then reclaims the same task with a second worker and records recovery evidence.
No other queued hotel can satisfy this probe.
"""
from __future__ import annotations
import os, signal, sys, time

from go_hotel.services.chain_task_lease import chain_task_lease_service
from go_hotel.services.hyatt_runtime_evidence import hyatt_runtime_evidence_service

LEASE_SECONDS = int(os.getenv("GO_HYATT_KILL_LEASE_SECONDS", "15"))


def child(task_id: str):
    task = chain_task_lease_service.claim(worker_id="HYATT_KILL_CHILD", lease_seconds=LEASE_SECONDS,
                                          task_type="CHAIN_HOTEL", task_id=task_id, actor="HYATT_10_E2E")
    if task is None or task.task_id != task_id:
        raise RuntimeError("HYATT_KILL_EXACT_CLAIM_FAILED")
    print("LEASED", flush=True)
    time.sleep(LEASE_SECONDS * 3)


def run(*, task_id: str, property_id: str, hotel_id: str | None = None) -> dict:
    pid = os.fork()
    if pid == 0:
        try: child(task_id)
        finally: os._exit(0)
    time.sleep(1)
    os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0)
    early = chain_task_lease_service.claim(worker_id="HYATT_EARLY_RECLAIM", lease_seconds=LEASE_SECONDS,
                                           task_type="CHAIN_HOTEL", task_id=task_id, actor="HYATT_10_E2E")
    if early is not None:
        raise RuntimeError("HYATT_LEASE_RECLAIMED_BEFORE_EXPIRY")
    time.sleep(LEASE_SECONDS + 1)
    reclaimed = chain_task_lease_service.claim(worker_id="HYATT_RECOVERY_WORKER", lease_seconds=LEASE_SECONDS,
                                               task_type="CHAIN_HOTEL", task_id=task_id, actor="HYATT_10_E2E")
    if reclaimed is None or reclaimed.task_id != task_id or reclaimed.attempt < 2:
        raise RuntimeError("HYATT_EXPIRED_LEASE_NOT_RECLAIMED")
    chain_task_lease_service.ack(task_id=task_id, worker_id="HYATT_RECOVERY_WORKER",
                                 result={"forced_kill_probe": True}, actor="HYATT_10_E2E")
    final = chain_task_lease_service.get(task_id)
    if final.state != "ACKED": raise RuntimeError("HYATT_RECOVERY_ACK_FAILED")
    hyatt_runtime_evidence_service.record_recovery(property_id=property_id, hotel_id=hotel_id,
        forced_kill_observed=True, lease_reclaimed=True, terminal_ack_count=1,
        first_worker="HYATT_KILL_CHILD", recovery_worker="HYATT_RECOVERY_WORKER", actor="HYATT_10_E2E")
    return {"task_id": task_id, "property_id": property_id, "attempt": final.attempt, "state": final.state}


if __name__ == "__main__":
    if len(sys.argv) not in (3,4): raise SystemExit("usage: hyatt_cohort_forced_kill.py TASK_ID PROPERTY_ID [HOTEL_ID]")
    print(run(task_id=sys.argv[1], property_id=sys.argv[2], hotel_id=sys.argv[3] if len(sys.argv)==4 else None))
