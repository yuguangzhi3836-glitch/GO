#!/usr/bin/env python3
"""Claim one Cell task, launch an allowlisted command, and maintain its lease."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
from urllib import error, request


class AdapterError(RuntimeError):
    pass


def post(base_url: str, token: str, path: str, payload: dict, timeout: float = 10) -> dict:
    data = json.dumps(payload).encode()
    req = request.Request(base_url.rstrip("/") + path, data=data, method="POST",
                          headers={"Authorization": f"Bearer {token}",
                                   "Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=timeout) as response:
            value = json.loads(response.read())
    except error.HTTPError as exc:
        raise AdapterError(f"orchestrator HTTP {exc.code}: {exc.read().decode(errors='replace')}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterError(f"orchestrator request failed: {exc}") from exc
    if not isinstance(value, dict):
        raise AdapterError("orchestrator response must be an object")
    return value


class Heartbeat(threading.Thread):
    def __init__(self, base_url: str, token: str, binding: dict, interval: float,
                 lease_seconds: int):
        super().__init__(name="go-cell-worker-heartbeat", daemon=True)
        self.base_url, self.token, self.binding = base_url, token, binding
        self.interval, self.lease_seconds = interval, lease_seconds
        self.stopped = threading.Event()
        self.failure = None

    def run(self):
        while not self.stopped.wait(self.interval):
            try:
                post(self.base_url, self.token, "/internal/v1/tasks/heartbeat", {
                    **self.binding, "stage": "RUNNING", "lease_seconds": self.lease_seconds,
                })
            except AdapterError as exc:
                self.failure = str(exc)
                return

    def stop(self):
        self.stopped.set()


def binding(task: dict, worker_id: str) -> dict:
    return {"task_id": task["task_id"], "worker_id": worker_id,
            "attempt_id": task["attempt_id"], "lease_id": task["lease_id"]}


def run_task(base_url: str, token: str, cell_id: str, worker_id: str,
             command: list[str], evidence_file: Path, *, lease_seconds: int = 30,
             heartbeat_seconds: float = 5, max_attempts: int = 3) -> dict:
    if not command:
        raise AdapterError("fixed worker command is required")
    task = post(base_url, token, "/internal/v1/tasks/claim",
                {"worker_id": worker_id, "cell_id": cell_id,
                 "lease_seconds": lease_seconds})
    if not task:
        return {"status": "NO_TASK"}
    lease = binding(task, worker_id)
    environment = os.environ.copy()
    environment.update({"GO_CELL_ID": cell_id, "GO_CELL_TASK_ID": task["task_id"],
                        "GO_CELL_SOURCE_SHA": task["source_sha"],
                        "GO_CELL_ATTEMPT_ID": task["attempt_id"],
                        "GO_CELL_LEASE_ID": task["lease_id"],
                        "GO_CELL_EVIDENCE_FILE": str(evidence_file)})
    for attempt in range(1, max_attempts + 1):
        post(base_url, token, "/internal/v1/tasks/heartbeat",
             {**lease, "stage": "RUNNING", "lease_seconds": lease_seconds})
        heartbeat = Heartbeat(base_url, token, lease, heartbeat_seconds, lease_seconds)
        heartbeat.start()
        process = subprocess.run(command, env=environment, check=False)
        heartbeat.stop()
        heartbeat.join(timeout=max(1, heartbeat_seconds * 2))
        if heartbeat.failure:
            raise AdapterError(f"heartbeat failed: {heartbeat.failure}")
        if process.returncode == 0:
            if not evidence_file.is_file():
                raise AdapterError("worker succeeded without evidence file")
            digest = hashlib.sha256(evidence_file.read_bytes()).hexdigest()
            result = post(base_url, token, "/internal/v1/tasks/complete",
                          {**lease, "evidence_sha256": digest})
            return {"status": "DONE_SCOPED", "task_id": task["task_id"],
                    "evidence_sha256": digest, "orchestrator": result}
        post(base_url, token, "/internal/v1/tasks/fail",
             {**lease, "error": f"worker exit {process.returncode}"})
        if attempt == max_attempts:
            return {"status": "DIAGNOSE", "task_id": task["task_id"],
                    "exit_code": process.returncode}
        post(base_url, token, "/internal/v1/tasks/recovery/advance", lease)
        post(base_url, token, "/internal/v1/tasks/recovery/advance", lease)
    raise AssertionError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("GO_CELL_ORCHESTRATOR_URL"), required=False)
    parser.add_argument("--token-env", default="GO_CELL_ORCHESTRATOR_TOKEN")
    parser.add_argument("--cell", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--evidence-file", type=Path, required=True)
    parser.add_argument("--lease-seconds", type=int, default=30)
    parser.add_argument("--heartbeat-seconds", type=float, default=5)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.url:
        raise SystemExit("GO_CELL_ORCHESTRATOR_URL or --url is required")
    token = os.environ.get(args.token_env)
    if not token:
        raise SystemExit(f"{args.token_env} is required")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    result = run_task(args.url, token, args.cell, args.worker_id, command,
                      args.evidence_file, lease_seconds=args.lease_seconds,
                      heartbeat_seconds=args.heartbeat_seconds,
                      max_attempts=args.max_attempts)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {"DONE_SCOPED", "NO_TASK"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
