#!/usr/bin/env python3
"""Process-level acceptance for durable GO Cell orchestration and restart recovery."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib import request

ROOT = Path(__file__).parent
TOKEN = "process-acceptance-token-at-least-32-characters"
SOURCE_SHA = "a" * 40
EVIDENCE_SHA = "b" * 64


def get(url):
    with request.urlopen(url, timeout=2) as response:
        return json.loads(response.read())


def post(url, path, payload):
    req = request.Request(url + path, data=json.dumps(payload).encode(), method="POST",
                          headers={"Authorization": f"Bearer {TOKEN}",
                                   "Content-Type": "application/json"})
    with request.urlopen(req, timeout=3) as response:
        return json.loads(response.read())


def wait_ready(url, process, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"orchestrator exited early: {process.returncode}")
        try:
            if get(url + "/readyz")["status"] == "ready":
                return
        except OSError:
            pass
        time.sleep(0.1)
    raise RuntimeError("orchestrator did not become ready")


def start(database, port, environment):
    process = subprocess.Popen([
        sys.executable, str(ROOT / "durable_orchestrator.py"),
        "--database", str(database), "--listen", "127.0.0.1", "--port", str(port),
        "--allow-http-loopback", "--reap-interval-seconds", "0.2",
    ], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    url = f"http://127.0.0.1:{port}"
    wait_ready(url, process)
    return process, url


def stop(process):
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-out", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        database, manifest = tmp / "orchestrator.sqlite3", tmp / "ledger-seed.json"
        manifest.write_text(json.dumps({
            "schema": "go.cell-ledger-seed.v1", "canonical_source_sha": SOURCE_SHA,
            "tasks": [
                {"task_id": "accepted-pass", "cell_id": "C01", "state": "PASS"},
                {"task_id": "restart-task", "cell_id": "C03", "state": "UNFINISHED"},
                {"task_id": "worker-task", "cell_id": "C04", "state": "UNFINISHED"},
                {"task_id": "supplier-gate", "cell_id": "C06", "state": "BLOCKED_EXTERNAL",
                 "evidence_sha256": EVIDENCE_SHA, "release_condition": "authorized supplier data"},
            ],
        }), encoding="utf-8")
        seed = subprocess.run([
            sys.executable, str(ROOT / "seed_ledger_tasks.py"), "--database", str(database),
            "--manifest", str(manifest),
        ], check=True, text=True, capture_output=True)
        seed_result = json.loads(seed.stdout)

        sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
        environment = os.environ.copy(); environment["GO_CELL_ORCHESTRATOR_TOKEN"] = TOKEN
        first, url = start(database, port, environment)
        try:
            health = get(url + "/healthz")
            ready_before = get(url + "/readyz")
            original = post(url, "/internal/v1/tasks/claim",
                            {"worker_id": "worker-before-restart", "cell_id": "C03",
                             "lease_seconds": 10})
            heartbeat = post(url, "/internal/v1/tasks/heartbeat", {
                "task_id": original["task_id"], "worker_id": original["worker_id"],
                "attempt_id": original["attempt_id"], "lease_id": original["lease_id"],
                "stage": "RUNNING", "lease_seconds": 10,
            })
        finally:
            stop(first)

        second, url = start(database, port, environment)
        try:
            ready_after = get(url + "/readyz")
            with sqlite3.connect(database) as connection:
                persisted = connection.execute(
                    "SELECT status, attempt_id, lease_id FROM tasks WHERE task_id='restart-task'"
                ).fetchone()
            if persisted != ("RUNNING", original["attempt_id"], original["lease_id"]):
                raise AssertionError(f"lease did not survive restart: {persisted}")

            worker_script = tmp / "worker.py"
            worker_script.write_text(
                "import os, pathlib; pathlib.Path(os.environ['GO_CELL_EVIDENCE_FILE']).write_text('worker evidence\\n')\n",
                encoding="utf-8")
            worker_evidence = tmp / "worker-evidence.txt"
            adapter = subprocess.run([
                sys.executable, str(ROOT / "worker_launch_adapter.py"), "--url", url,
                "--cell", "C04", "--worker-id", "adapter-worker",
                "--evidence-file", str(worker_evidence), "--lease-seconds", "10",
                "--heartbeat-seconds", "1", "--max-attempts", "2", "--",
                sys.executable, str(worker_script),
            ], env=environment, check=True, text=True, capture_output=True)
            adapter_result = json.loads(adapter.stdout)

            deadline = time.monotonic() + 13
            queued = None
            while time.monotonic() < deadline:
                with sqlite3.connect(database) as connection:
                    queued = connection.execute(
                        "SELECT status FROM tasks WHERE task_id='restart-task'"
                    ).fetchone()[0]
                if queued == "QUEUED":
                    break
                time.sleep(0.2)
            if queued != "QUEUED":
                raise AssertionError("background reaper did not return expired lease to queue")
            reclaimed = post(url, "/internal/v1/tasks/claim",
                             {"worker_id": "worker-after-expiry", "cell_id": "C03",
                              "lease_seconds": 10})
            if reclaimed["attempt_id"] == original["attempt_id"]:
                raise AssertionError("expired task reused old attempt")
            snapshot = post(url, "/internal/v1/cell-runtime-snapshot",
                            {"schema": "go.cell-liveness-probe.v1",
                             "challenge": "process-acceptance-challenge"})
        finally:
            stop(second)

        evidence = {
            "schema": "go.cell-orchestrator-process-evidence.v1",
            "seed": seed_result, "health": health,
            "ready_before_restart": ready_before, "ready_after_restart": ready_after,
            "original_attempt_id": original["attempt_id"],
            "heartbeat_status": heartbeat["status"],
            "persisted_restart_state": list(persisted),
            "background_reaper_state": queued,
            "reclaimed_attempt_id": reclaimed["attempt_id"],
            "worker_adapter": adapter_result,
            "snapshot_sequence": snapshot["sequence"],
            "snapshot_live_cells": sorted(item["cell_id"] for item in snapshot["executors"]),
            "accepted_pass_reenqueued": "accepted-pass" in seed_result["enqueued"],
        }
        args.evidence_out.parent.mkdir(parents=True, exist_ok=True)
        encoded = (json.dumps(evidence, sort_keys=True, indent=2) + "\n").encode()
        args.evidence_out.write_bytes(encoded)
        print(json.dumps({"status": "PASS", "evidence": str(args.evidence_out),
                          "sha256": hashlib.sha256(encoded).hexdigest()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
