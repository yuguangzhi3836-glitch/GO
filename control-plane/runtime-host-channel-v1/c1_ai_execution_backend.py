"""C1 real AI execution backend (V1) - runs INSIDE a GitHub-hosted ephemeral job.

Architecture (Owner current Runtime design):

  Runtime Host  = durable coordination kernel only
                  (queue / task identity / attempts+lease / completion / Evidence)
                  -> holds NO model credential and NO outbound model access
  GitHub Actions = ephemeral AI execution backend
  OPENAI_API_KEY = stays a repository secret; it exists only inside a disposable
                   runner process, never on a persistent host

This module is the execution half. It is deliberately NOT a worker service and NOT
a scheduler: it executes exactly one already-bound C1 task and writes exactly one
sealed result document.

Boundaries enforced here:
- fixed smoke payload only (``{"schema_version":1,"smoke_id":"C1_REAL_AI_WORKER_V1"}``)
- fixed model endpoint (the Responses API URL is NOT configurable)
- no arbitrary prompt, no arbitrary URL, no arbitrary C id, no shell, no deployment
- the API credential is read from the environment and is never written to the
  result document, to stdout, or to any file this module creates

Exactly-once (V1 model): one Runtime task + one attempt maps to one deterministic
``execution_request_id``. Re-running with a terminal result for the same id REUSES
it instead of paying for a second model call.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

OWNER_C = "C1"
AI_KIND = "AI_WORK_V1"
SMOKE_ID = "C1_REAL_AI_WORKER_V1"
SMOKE_PAYLOAD = {"schema_version": 1, "smoke_id": SMOKE_ID}
SMOKE_IDEMPOTENCY_KEY = "c1-real-ai-worker-v1:smoke:1"
EXPECTED_OUTPUT = "GO_C1_REAL_AI_WORKER_V1_OK"
FIXED_PROMPT = (
    "This is a bounded infrastructure smoke test. "
    "Reply with exactly GO_C1_REAL_AI_WORKER_V1_OK and nothing else."
)

AI_PROVIDER = "OPENAI_RESPONSES_API"
API_URL = "https://api.openai.com/v1/responses"  # fixed in V1, never a parameter
API_KEY_ENV = "OPENAI_API_KEY"
HTTP_TIMEOUT_S = 45
MAX_OUTPUT_TOKENS = 32
MAX_RESPONSE_BYTES = 1024 * 1024

RESULT_KIND = "c1-ai-execution-result"
REQUEST_KIND = "c1-ai-execution-request"
SCHEMA_VERSION = 1


class Refused(Exception):
    """Fail-closed refusal. Carries a stable machine-readable reason code."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def canonical(document) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


def require_smoke_payload(payload) -> dict:
    if type(payload) is not dict or payload != SMOKE_PAYLOAD:
        raise Refused("PAYLOAD_NOT_FIXED_SMOKE")
    return payload


def request_binding(*, runtime_task_id: str, attempt: int, model: str) -> dict:
    """The exact identity a model execution is allowed to be performed under.

    Runtime task id + attempt are the Runtime's own state; the rest is frozen by
    this module. Nothing here is caller-invented except the two Runtime facts.
    """
    if not isinstance(runtime_task_id, str) or not runtime_task_id:
        raise Refused("RUNTIME_TASK_ID_MISSING")
    if type(attempt) is not int or attempt < 1:
        raise Refused("ATTEMPT_NOT_POSITIVE_INT")
    if not isinstance(model, str) or not model:
        raise Refused("MODEL_NOT_EXPLICIT")
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": REQUEST_KIND,
        "owner_c": OWNER_C,
        "task_kind": AI_KIND,
        "smoke_id": SMOKE_ID,
        "payload": SMOKE_PAYLOAD,
        "idempotency_key": SMOKE_IDEMPOTENCY_KEY,
        "runtime_task_id": runtime_task_id,
        "attempt": attempt,
        "ai_provider": AI_PROVIDER,
        "ai_model": model,
        "prompt_sha256": hashlib.sha256(FIXED_PROMPT.encode("utf-8")).hexdigest(),
    }


def execution_request_id(binding: dict) -> str:
    return hashlib.sha256(canonical(binding).encode("utf-8")).hexdigest()


def build_execution_request(*, runtime_task_id: str, attempt: int, model: str) -> dict:
    """The document the Runtime-side caller would hand to the execution backend."""
    binding = request_binding(runtime_task_id=runtime_task_id, attempt=attempt, model=model)
    return dict(binding, execution_request_id=execution_request_id(binding))


def extract_output_text(document) -> str:
    if type(document) is not dict:
        raise Refused("MODEL_RESPONSE_NOT_AN_OBJECT")
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
        raise Refused("MODEL_RESPONSE_HAD_NO_OUTPUT_TEXT")
    return output


def call_responses_api(*, api_key: str, model: str, opener=urllib.request.urlopen):
    """One real model call. The key is used and then goes out of scope."""
    if not api_key:
        raise Refused("MISSING_OPENAI_API_KEY")
    body = canonical({
        "model": model,
        "input": FIXED_PROMPT,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "store": False,
    }).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with opener(request, timeout=HTTP_TIMEOUT_S) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:  # never echo the response body verbatim
        raise Refused("MODEL_HTTP_%s" % exc.code) from None
    except (urllib.error.URLError, OSError):
        raise Refused("MODEL_ENDPOINT_UNREACHABLE") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise Refused("MODEL_RESPONSE_TOO_LARGE")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Refused("MODEL_RESPONSE_NOT_JSON") from None
    if document.get("status") != "completed":
        raise Refused("MODEL_RESPONSE_NOT_COMPLETED")
    return {
        "response_id": document.get("id"),
        "model": document.get("model") or model,
        "output": extract_output_text(document),
    }


def stub_response(*, model: str) -> dict:
    """Deterministic stand-in used by offline tests and CI. No network, no key."""
    return {"response_id": "stub:no-model-call", "model": model, "output": EXPECTED_OUTPUT}


def sealed_result(*, binding: dict, request_id: str, reply: dict, reused: bool) -> dict:
    accepted = reply["output"] == EXPECTED_OUTPUT
    document = {
        "schema_version": SCHEMA_VERSION,
        "kind": RESULT_KIND,
        "runtime_task_id": binding["runtime_task_id"],
        "attempt": binding["attempt"],
        "execution_request_id": request_id,
        "owner_c": OWNER_C,
        "task_kind": AI_KIND,
        "smoke_id": SMOKE_ID,
        "idempotency_key": SMOKE_IDEMPOTENCY_KEY,
        "ai_provider": AI_PROVIDER,
        "ai_model": reply.get("model") or binding["ai_model"],
        "response_id": reply.get("response_id"),
        "expected_output": EXPECTED_OUTPUT,
        "output": reply["output"],
        "accepted": accepted,
        "reused_terminal_result": reused,
        "authorizes_any_action": False,
    }
    if not accepted:
        document["failure_reason"] = "MODEL_OUTPUT_DID_NOT_MATCH_SMOKE_STRING"
    return document


def reuse_terminal_result(path: str, request_id: str):
    """Return a previously sealed result for the SAME execution identity, else None.

    This is the anti-double-pay guard: a repeated trigger for a task+attempt that
    already has a terminal result must not reach the model again.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError):
        return None
    if type(document) is not dict or document.get("kind") != RESULT_KIND:
        return None
    if document.get("execution_request_id") != request_id:
        return None
    if document.get("reused_terminal_result") is not None and "accepted" in document:
        return document
    return None


def run_execution(*, runtime_task_id, attempt, payload, model, api_key, existing_result=None,
                  stub=False, opener=urllib.request.urlopen) -> dict:
    require_smoke_payload(payload)
    binding = request_binding(runtime_task_id=runtime_task_id, attempt=attempt, model=model)
    request_id = execution_request_id(binding)

    if existing_result:
        reused = reuse_terminal_result(existing_result, request_id)
        if reused is not None:
            return dict(reused, reused_terminal_result=True)

    reply = stub_response(model=model) if stub else call_responses_api(
        api_key=api_key, model=model, opener=opener)
    return sealed_result(binding=binding, request_id=request_id, reply=reply, reused=False)


def assert_no_credential_material(document: dict, api_key) -> None:
    """Hard guard: a result document must never contain the API credential."""
    if not api_key:
        return
    if api_key in canonical(document):
        raise Refused("CREDENTIAL_MATERIAL_IN_RESULT")


def write_result(document: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(canonical(document) + "\n")


def _status_line(document: dict) -> str:
    """Stdout summary. Explicitly lists the fields it prints - never the whole doc."""
    return canonical({
        "status": "ACCEPTED" if document["accepted"] else "REFUSED_OUTPUT_MISMATCH",
        "runtime_task_id": document["runtime_task_id"],
        "attempt": document["attempt"],
        "execution_request_id": document["execution_request_id"],
        "ai_model": document["ai_model"],
        "response_id": document["response_id"],
        "accepted": document["accepted"],
        "reused_terminal_result": document["reused_terminal_result"],
    })


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="C1 real AI execution backend (V1)")
    sub = parser.add_subparsers(dest="command", required=True)

    emit = sub.add_parser("emit-request", help="print the canonical execution request")
    emit.add_argument("--runtime-task-id", required=True)
    emit.add_argument("--attempt", type=int, required=True)
    emit.add_argument("--model", required=True)

    run = sub.add_parser("run", help="execute the fixed smoke and seal one result")
    run.add_argument("--runtime-task-id", required=True)
    run.add_argument("--attempt", type=int, required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--payload-json", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--existing-result", default=None)
    run.add_argument("--stub", action="store_true",
                     help="no network, no credential - offline/CI path")

    args = parser.parse_args(argv)

    try:
        if args.command == "emit-request":
            print(canonical(build_execution_request(
                runtime_task_id=args.runtime_task_id, attempt=args.attempt, model=args.model)))
            return 0

        payload = json.loads(args.payload_json)
        api_key = os.environ.get(API_KEY_ENV, "")
        document = run_execution(
            runtime_task_id=args.runtime_task_id,
            attempt=args.attempt,
            payload=payload,
            model=args.model,
            api_key=api_key,
            existing_result=args.existing_result,
            stub=args.stub,
        )
        assert_no_credential_material(document, api_key)
        write_result(document, args.out)
        print(_status_line(document))
        return 0 if document["accepted"] else 2
    except Refused as refusal:
        print(canonical({"status": "REFUSED", "reason": refusal.reason}))
        return 3
    except ValueError as exc:
        print(canonical({"status": "REFUSED", "reason": "PAYLOAD_NOT_JSON",
                         "detail": type(exc).__name__}))
        return 3


if __name__ == "__main__":
    sys.exit(main())
