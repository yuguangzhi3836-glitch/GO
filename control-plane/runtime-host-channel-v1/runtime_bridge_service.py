"""Runtime-side local bridge worker for the C1-C14 probe channel.

Proposed candidate path: control-plane/runtime-host-channel-v1/runtime_bridge_service.py
Installed on the Runtime Host at:

    /opt/go/runtime-host-agent/runtime_bridge_service.py

and run by `go-runtime-host-runtime-bridge.service` as User=go-runtime / Group=go-runtime
(the source file itself stays root-owned and read-only).

Responsibilities, and nothing else:

  * scan the fixed inbox directory every second
  * validate each fixed bridge request against the closed schema
  * call the installed `Runtime.enqueue()` once per external task, under a derived
    idempotency key, so the same external task always maps to the same Runtime task
  * observe the Runtime task status and its TASK_COMPLETED evidence
  * write the fixed result file into the outbox directory when the task is terminal

It is NOT a worker. It never claims, executes or completes a Runtime task, never
replaces the Supervisor, never calls a model or an API, and has no GitHub access, no
Evidence key, no CC signer and no network. Actual completion stays with the frozen
Runtime Supervisor and its injected worker adapter.

Runtime logic is imported from the installed path and never copied or forked.
"""
import json
import os
import sqlite3
import sys
import time

# Fixed installed locations. Constants, never caller inputs.
RUNTIME_SOURCE_DIR = "/opt/go/c1-c14-runtime"
RUNTIME_DB = "/var/lib/go-c-runtime/runtime.db"
INBOX_DIR = "/var/lib/go-runtime-bridge/inbox"
OUTBOX_DIR = "/var/lib/go-runtime-bridge/outbox"

SCAN_SECONDS = 1.0
IDEMPOTENCY_PREFIX = "runtime-host:"

TERMINAL_STATUSES = ("SUCCEEDED", "FAILED", "CANCELLED", "ESCALATED")
SUCCEEDED = "SUCCEEDED"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from runtime_bridge import (INBOX_MODE, OUTBOX_MODE, Reject, atomic_write, bridge_path,
                            encode_result, parse_request, parse_result, read_bounded,
                            read_optional, runtime_result_sha256)


def emit(obj):
    sys.stdout.write(json.dumps(obj, sort_keys=True) + "\n")
    sys.stdout.flush()


def load_runtime(source_dir=RUNTIME_SOURCE_DIR):
    """Import the installed Runtime module from its fixed path. Never a fork, never a copy."""
    if source_dir not in sys.path:
        sys.path.insert(0, source_dir)
    import runtime  # noqa: E402 -- resolved from the installed Runtime directory
    return runtime


def open_runtime(source_dir=RUNTIME_SOURCE_DIR, db_path=RUNTIME_DB):
    return load_runtime(source_dir).Runtime(db_path)


def idempotency_key(external_task_id):
    """Deterministic: one external task identity maps to one Runtime task, forever."""
    return IDEMPOTENCY_PREFIX + external_task_id


def enqueue(rt, request):
    """Fixed enqueue contract: C1 / RUNTIME_PROBE / a three-field payload. Nothing else."""
    return rt.enqueue(
        "C1",
        "RUNTIME_PROBE",
        {"external_task_id": request["external_task_id"],
         "external_task_sha256": request["external_task_sha256"],
         "registration_sha256": request["registration_sha256"]},
        idempotency_key=idempotency_key(request["external_task_id"]),
    )


def observe(db_path, runtime_task_id):
    """Read-only observation of the Runtime task and its completion evidence."""
    connection = sqlite3.connect(db_path, timeout=10.0)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            "SELECT task_id,owner_c,kind,status,attempts FROM tasks WHERE task_id=?",
            (runtime_task_id,)).fetchone()
        if row is None:
            return None
        if row["status"] not in TERMINAL_STATUSES:
            return {"terminal": False, "status": row["status"]}
        event = connection.execute(
            "SELECT event_hash,body_json FROM evidence WHERE task_id=? AND event_type='TASK_COMPLETED' "
            "ORDER BY rowid DESC LIMIT 1", (runtime_task_id,)).fetchone()
        if event is None:
            return None
        body = json.loads(event["body_json"])
        return {"terminal": True, "status": row["status"], "event_hash": event["event_hash"],
                "worker_status": body.get("status"), "result": body.get("result")}
    finally:
        connection.close()


def write_result(outbox_dir, result):
    """Immutable result: reuse identical bytes, never overwrite different bytes."""
    path = bridge_path(outbox_dir, result["external_task_id"])
    raw = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    existing = read_optional(path)
    if existing is not None:
        if existing == raw:
            return "REUSED"
        raise Reject("bridge_result_conflict")
    os.makedirs(outbox_dir, mode=0o750, exist_ok=True)
    atomic_write(path, raw, os.getuid(), -1, OUTBOX_MODE)
    if read_optional(path) != raw:
        raise Reject("bridge_result_readback")
    return "WRITTEN"


def process_once(inbox_dir, outbox_dir, rt=None, db_path=RUNTIME_DB):
    """One scan. Returns a bounded summary. Never raises for a single bad request."""
    summary = {"scanned": 0, "enqueued": 0, "completed": 0, "pending": 0, "refused": 0,
               "results": []}
    try:
        names = sorted(os.listdir(inbox_dir))
    except FileNotFoundError:
        return summary
    for name in names:
        if not name.endswith(".json"):
            continue
        summary["scanned"] += 1
        try:
            request = parse_request(read_bounded(os.path.join(inbox_dir, name)))
            if name != request["external_task_id"] + ".json":
                raise Reject("bridge_name_binding")
        except (Reject, OSError):
            summary["refused"] += 1
            continue
        external_task_id = request["external_task_id"]
        if rt is None:
            rt = open_runtime(db_path=db_path)
        try:
            # A terminal result already on disk is reused; nothing is re-enqueued.
            existing = read_optional(bridge_path(outbox_dir, external_task_id))
            if existing is not None:
                parse_result(existing)
                summary["completed"] += 1
                summary["results"].append([external_task_id, "ALREADY_RESULT"])
                continue
            runtime_task_id = enqueue(rt, request)
            summary["enqueued"] += 1
            observation = observe(db_path, runtime_task_id)
            if observation is None or not observation["terminal"]:
                summary["pending"] += 1
                summary["results"].append([external_task_id, "PENDING", runtime_task_id])
                continue
            if observation["status"] != SUCCEEDED or observation["worker_status"] != SUCCEEDED:
                summary["refused"] += 1
                summary["results"].append([external_task_id, "NOT_SUCCEEDED", runtime_task_id])
                continue
            result = json.loads(encode_result(
                external_task_id, request["external_task_sha256"], runtime_task_id,
                observation["status"], observation["event_hash"],
                runtime_result_sha256(observation["result"])).decode("utf-8"))
            write_result(outbox_dir, result)
            summary["completed"] += 1
            summary["results"].append([external_task_id, "RESULT", runtime_task_id])
        except Reject as exc:
            summary["refused"] += 1
            summary["results"].append([external_task_id, "REFUSED", str(exc)[:60]])
        except Exception as exc:  # noqa: BLE001 -- one bad request must not stall the rest
            summary["refused"] += 1
            summary["results"].append([external_task_id, "ERROR", type(exc).__name__])
    return summary


def main(argv):
    if len(argv) > 1 and argv[1] not in ("--once",):
        emit({"status": "REFUSED", "reason": "bad_argument"})
        return 1
    once = len(argv) > 1
    rt = None
    while True:
        try:
            if rt is None:
                # Opened once and reused: the Runtime handle is not re-initialised per scan.
                rt = open_runtime(db_path=RUNTIME_DB)
            summary = process_once(INBOX_DIR, OUTBOX_DIR, rt, RUNTIME_DB)
            if summary["scanned"] or once:
                emit(dict(summary, status="PASS", verb="runtime-bridge-scan",
                          runtime_db=RUNTIME_DB))
        except Exception as exc:  # noqa: BLE001 -- fail closed but stay observable
            emit({"status": "REFUSED", "reason": "scan", "detail": type(exc).__name__})
            if once:
                return 1
        if once:
            return 0
        time.sleep(SCAN_SECONDS)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
