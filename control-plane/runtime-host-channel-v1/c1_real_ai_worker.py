"""C1 Real AI Worker V1.

Narrow first real-worker path for the dedicated Runtime Host.

This worker:
- claims only C1 / AI_WORK_V1 tasks
- accepts one fixed smoke payload schema
- calls OpenAI's Responses API over HTTPS
- completes through the frozen Runtime.complete() contract
- never handles shell, deployment, arbitrary prompts, arbitrary URLs or arbitrary C domains

The existing RUNTIME_PROBE -> NoopWorker path is not replaced.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

RUNTIME_SOURCE_DIR = "/opt/go/c1-c14-runtime"
DEFAULT_DB = "/var/lib/go-c-runtime/runtime.db"

OWNER_C = "C1"
AI_KIND = "AI_WORK_V1"
SMOKE_PAYLOAD = {"schema_version": 1, "smoke_id": "C1_REAL_AI_WORKER_V1"}
SMOKE_IDEMPOTENCY_KEY = "c1-real-ai-worker-v1:smoke:1"
EXPECTED_TEXT = "GO_C1_REAL_AI_WORKER_V1_OK"
FIXED_PROMPT = (
    "This is a bounded infrastructure smoke test. "
    "Reply with exactly GO_C1_REAL_AI_WORKER_V1_OK and nothing else."
)

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.6-luna"
HTTP_TIMEOUT_S = 45
LEASE_S = 90
MAX_RESPONSE_BYTES = 1024 * 1024


def load_runtime(source_dir: str = RUNTIME_SOURCE_DIR):
    if source_dir not in sys.path:
        sys.path.insert(0, source_dir)
    import runtime  # noqa: E402
    return runtime


def require_smoke_payload(payload):
    if type(payload) is not dict or payload != SMOKE_PAYLOAD:
        raise ValueError("AI_WORK_V1 payload is not the fixed smoke schema")
    return payload


def extract_output_text(document):
    if type(document) is not dict:
        raise ValueError("response object must be an object")
    chunks = []
    for item in document.get("output", []):
        if type(item) is not dict or item.get("type") != "message":
            continue
        for part in item.get("content", []):
            if type(part) is dict and part.get("type") == "output_text":
                text = part.get("text")
                if type(text) is str:
                    chunks.append(text)
    output = "".join(chunks).strip()
    if not output:
        raise ValueError("response contained no output_text")
    return output


class OpenAIResponsesClient:
    def __init__(self, api_key=None, model=None, url=OPENAI_RESPONSES_URL,
                 timeout_s=HTTP_TIMEOUT_S):
        self.api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
        self.model = model if model is not None else os.environ.get("GO_C1_OPENAI_MODEL", DEFAULT_MODEL)
        self.url = url
        self.timeout_s = timeout_s
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required")
        if not self.model or not isinstance(self.model, str):
            raise ValueError("GO_C1_OPENAI_MODEL must be a non-empty string")
        if self.url != OPENAI_RESPONSES_URL:
            raise ValueError("Responses endpoint is fixed in V1")

    def invoke_smoke(self):
        body = json.dumps({
            "model": self.model,
            "input": FIXED_PROMPT,
            "max_output_tokens": 32,
            "store": False,
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=body,
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("response too large")
        document = json.loads(raw.decode("utf-8"))
        if document.get("status") != "completed":
            raise ValueError("response did not complete")
        output = extract_output_text(document)
        return {
            "response_id": document.get("id"),
            "model": document.get("model") or self.model,
            "output": output,
        }


class C1RealAIWorker:
    def __init__(self, runtime, client, *, worker_id=None):
        self.runtime = runtime
        self.client = client
        self.worker_id = worker_id or ("c1-real-ai:" + uuid.uuid4().hex)

    def tick(self):
        self.runtime.recover_stale()
        task = self.runtime.claim(
            OWNER_C,
            worker_id=self.worker_id,
            lease_s=LEASE_S,
            kinds=(AI_KIND,),
        )
        if task is None:
            return {"status": "IDLE"}

        try:
            require_smoke_payload(task.payload)
            reply = self.client.invoke_smoke()
            if reply["output"] != EXPECTED_TEXT:
                raise ValueError("smoke response mismatch")
            result = {
                "adapter": "openai-responses",
                "schema_version": 1,
                "model": reply["model"],
                "response_id": reply["response_id"],
                "output": reply["output"],
                "accepted": True,
            }
            self.runtime.complete(
                OWNER_C,
                task.task_id,
                worker_id=self.worker_id,
                expected_attempt=task.attempts,
                success=True,
                result=result,
            )
            return {"status": "SUCCEEDED", "task_id": task.task_id, "model": reply["model"]}
        except Exception as exc:
            runtime_mod = load_runtime()
            try:
                self.runtime.complete(
                    OWNER_C,
                    task.task_id,
                    worker_id=self.worker_id,
                    expected_attempt=task.attempts,
                    success=False,
                    error=type(exc).__name__,
                )
            except runtime_mod.RuntimeErrorInvariant:
                return {"status": "LEASE_LOST", "task_id": task.task_id}
            self.runtime.escalate(
                OWNER_C,
                "REAL_AI_WORKER_FAILED",
                task_id=task.task_id,
                severity="HIGH",
                details={"error_type": type(exc).__name__},
                requires_human=True,
            )
            return {"status": "ESCALATED", "task_id": task.task_id,
                    "error_type": type(exc).__name__}

    def run_forever(self, stop, *, interval_s=2.0):
        while not stop.is_set():
            result = self.tick()
            if result["status"] != "IDLE":
                print(json.dumps(result, sort_keys=True), flush=True)
            stop.wait(interval_s)


def enqueue_smoke(runtime):
    return runtime.enqueue(
        OWNER_C,
        AI_KIND,
        dict(SMOKE_PAYLOAD),
        max_attempts=1,
        idempotency_key=SMOKE_IDEMPOTENCY_KEY,
    )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--runtime-source", default=RUNTIME_SOURCE_DIR)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--enqueue-smoke", action="store_true")
    args = parser.parse_args(argv)

    if args.interval <= 0:
        raise SystemExit("interval must be positive")

    runtime_mod = load_runtime(args.runtime_source)
    runtime = runtime_mod.Runtime(Path(args.db))

    if args.enqueue_smoke:
        print(json.dumps({"task_id": enqueue_smoke(runtime), "kind": AI_KIND,
                          "owner_c": OWNER_C}, sort_keys=True))
        return 0

    client = OpenAIResponsesClient()
    worker = C1RealAIWorker(runtime, client)
    if args.once:
        print(json.dumps(worker.tick(), sort_keys=True))
        return 0

    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    worker.run_forever(stop, interval_s=args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
