"""C1 real AI execution backend (V1) - runs INSIDE a GitHub-hosted ephemeral job.

Architecture (Owner current Runtime design):

  Runtime Host   = durable coordination kernel only
                   (queue / task identity / attempts + lease / completion / Evidence)
                   -> holds NO model credential and NO outbound model access
  GitHub Actions = ephemeral AI execution backend (this module is its body)
  OPENAI_API_KEY = repository secret; it exists only inside a disposable runner

This module executes exactly one already-bound task and seals exactly one result.
The identity it executes under is defined in `c1_execution_contract.py`, shared with
the Runtime-side requester, so the two can never disagree about what an execution is.

Boundaries:
- fixed smoke payload; no arbitrary prompt, URL, model, C id, shell or deployment
- the model endpoint is fixed; the model name is a workflow-side controlled value
- the credential is read from the environment and never written to the result
- the supplied execution_request_id must equal the one derived locally, otherwise
  the run refuses (a dispatch cannot ask for an identity it does not belong to)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from c1_execution_contract import (  # noqa: E402
    API_URL,
    EXPECTED_OUTPUT,
    PROMPT,
    PROVIDER,
    RESULT_KIND,
    SCHEMA_VERSION,
    Refused,
    build_dispatch_request,
    canonical,
    execution_request_id,
    output_sha256,
    validate_result,
)

API_KEY_ENV = "OPENAI_API_KEY"
HTTP_TIMEOUT_S = 45
MAX_OUTPUT_TOKENS = 32
MAX_RESPONSE_BYTES = 1024 * 1024


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
        "input": PROMPT,
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
    """Deterministic stand-in for offline tests and CI. No network, no key."""
    return {"response_id": "stub:no-model-call", "model": model, "output": EXPECTED_OUTPUT}


def sealed_result(*, runtime_task_id, attempt, request_id, reply, github_run_id,
                  github_run_attempt, reused: bool) -> dict:
    accepted = reply["output"] == EXPECTED_OUTPUT
    document = {
        "version": SCHEMA_VERSION,
        "kind": RESULT_KIND,
        "runtime_task_id": runtime_task_id,
        "attempt": attempt,
        "execution_request_id": request_id,
        "github_run_id": github_run_id,
        "github_run_attempt": github_run_attempt,
        "provider": PROVIDER,
        "model": reply.get("model"),
        "response_id": reply.get("response_id"),
        "status": "SUCCEEDED" if accepted else "FAILED",
        "output_sha256": output_sha256(reply["output"]),
        "output": reply["output"],
        "accepted": accepted,
        "reused_terminal_result": reused,
        "authorizes_any_action": False,
    }
    if not accepted:
        document["failure_reason"] = "MODEL_OUTPUT_DID_NOT_MATCH_SMOKE_STRING"
    return document


def reuse_terminal_result(path, request_id):
    """Return a previously sealed result for the SAME identity, else None.

    Anti-double-pay guard: a repeated trigger for a task+attempt that already has a
    terminal result must never reach the model again.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError):
        return None
    if type(document) is not dict or document.get("kind") != RESULT_KIND:
        return None
    if document.get("execution_request_id") != request_id or "accepted" not in document:
        return None
    return document


def run_execution(*, runtime_task_id, attempt, model, github_run_id, github_run_attempt,
                  execution_request_id_given=None, existing_result=None, stub=False,
                  api_key="", opener=urllib.request.urlopen) -> dict:
    derived = execution_request_id(runtime_task_id, attempt)
    if execution_request_id_given is not None and execution_request_id_given != derived:
        # The dispatch asked for an identity that does not belong to these Runtime facts.
        raise Refused("EXECUTION_REQUEST_ID_DOES_NOT_MATCH_RUNTIME_FACTS")

    if existing_result:
        reused = reuse_terminal_result(existing_result, derived)
        if reused is not None:
            return dict(reused, reused_terminal_result=True)

    reply = stub_response(model=model) if stub else call_responses_api(
        api_key=api_key, model=model, opener=opener)
    document = sealed_result(
        runtime_task_id=runtime_task_id, attempt=attempt, request_id=derived, reply=reply,
        github_run_id=github_run_id, github_run_attempt=github_run_attempt, reused=False)
    validate_result(document, runtime_task_id=runtime_task_id, attempt=attempt,
                    execution_request_id_=derived)
    return document


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
    """Stdout summary. Lists its fields explicitly - it never prints the whole doc."""
    return canonical({
        "status": document["status"],
        "runtime_task_id": document["runtime_task_id"],
        "attempt": document["attempt"],
        "execution_request_id": document["execution_request_id"],
        "github_run_id": document["github_run_id"],
        "model": document["model"],
        "response_id": document["response_id"],
        "accepted": document["accepted"],
        "reused_terminal_result": document["reused_terminal_result"],
    })


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="C1 real AI execution backend (V1)")
    sub = parser.add_subparsers(dest="command", required=True)

    emit = sub.add_parser("emit-request", help="print the canonical dispatch request")
    emit.add_argument("--runtime-task-id", required=True)
    emit.add_argument("--attempt", type=int, required=True)

    run = sub.add_parser("run", help="execute the fixed smoke and seal one result")
    run.add_argument("--runtime-task-id", required=True)
    run.add_argument("--attempt", type=int, required=True)
    run.add_argument("--execution-request-id", required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--github-run-id", type=int, required=True)
    run.add_argument("--github-run-attempt", type=int, required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--existing-result", default=None)
    run.add_argument("--stub", action="store_true",
                     help="no network, no credential - offline/CI path")

    args = parser.parse_args(argv)

    try:
        if args.command == "emit-request":
            print(canonical(build_dispatch_request(args.runtime_task_id, args.attempt)))
            return 0

        api_key = os.environ.get(API_KEY_ENV, "")
        document = run_execution(
            runtime_task_id=args.runtime_task_id,
            attempt=args.attempt,
            model=args.model,
            github_run_id=args.github_run_id,
            github_run_attempt=args.github_run_attempt,
            execution_request_id_given=args.execution_request_id,
            existing_result=args.existing_result,
            stub=args.stub,
            api_key=api_key,
        )
        assert_no_credential_material(document, api_key)
        write_result(document, args.out)
        print(_status_line(document))
        return 0 if document["accepted"] else 2
    except Refused as refusal:
        print(canonical({"status": "REFUSED", "reason": refusal.reason}))
        return 3


if __name__ == "__main__":
    sys.exit(main())
