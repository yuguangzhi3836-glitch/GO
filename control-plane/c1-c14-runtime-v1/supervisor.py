"""Supervisor loop for C1-C14 Runtime V1.

The supervisor coordinates only. Worker execution is injected through a narrow
adapter and remains subject to Runtime authorization.
"""
from __future__ import annotations
import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from runtime import C_IDS, ClaimedTask, Runtime, RuntimeErrorInvariant

class WorkerAdapter(Protocol):
    def execute(self, c_id: str, task: ClaimedTask) -> dict: ...

@dataclass
class NoopWorker:
    """Safe adapter used for runtime validation; never performs external I/O."""
    def execute(self, c_id: str, task: ClaimedTask) -> dict:
        return {"adapter": "noop", "c_id": c_id, "task_id": task.task_id, "accepted": True}

class Supervisor:
    def __init__(self, runtime: Runtime, worker: WorkerAdapter, *, worker_prefix: str = "supervisor", task_kinds: tuple[str, ...] | None = None):
        self.runtime = runtime
        self.worker = worker
        self.worker_prefix = worker_prefix
        self.task_kinds = task_kinds

    def tick(self) -> dict:
        recovery = self.runtime.recover_stale()
        runnable = self.runtime.wake_candidates()
        executed = []
        for c_id in runnable:
            worker_id = f"{self.worker_prefix}:{c_id}"
            self.runtime.heartbeat(c_id, status="READY")
            task = self.runtime.claim(c_id, worker_id=worker_id, kinds=self.task_kinds)
            if task is None:
                continue
            error = None
            result = None
            try:
                result = self.worker.execute(c_id, task)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            try:
                self.runtime.complete(c_id, task.task_id, worker_id=worker_id,
                                      expected_attempt=task.attempts,
                                      success=error is None, result=result, error=error)
            except RuntimeErrorInvariant:
                # A stale worker must not retry completion or escalate the new owner's task.
                executed.append({"c_id": c_id, "task_id": task.task_id, "status": "LEASE_LOST"})
                continue
            if error is not None:
                self.runtime.escalate(c_id, "WORKER_EXECUTION_FAILED", task_id=task.task_id,
                                      severity="HIGH", details={"error": error})
            executed.append({"c_id": c_id, "task_id": task.task_id,
                             "status": "SUCCEEDED" if error is None else "ESCALATED"})
        return {"recovery": recovery, "runnable": runnable, "executed": executed}

    def run_forever(self, *, interval_s: float = 5.0) -> None:
        while True:
            self.tick()
            time.sleep(interval_s)

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="c1-c14-runtime.db")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()
    supervisor = Supervisor(Runtime(Path(args.db)), NoopWorker())
    if args.once:
        print(json.dumps(supervisor.tick(), sort_keys=True))
    else:
        supervisor.run_forever(interval_s=args.interval)

if __name__ == "__main__":
    main()
