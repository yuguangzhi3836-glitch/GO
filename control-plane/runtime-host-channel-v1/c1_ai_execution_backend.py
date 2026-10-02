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
- the prompt is the one the shared contract derives from the task's own payload; no
  caller-supplied prompt, URL, model, C id, shell or deployment reaches this module
- the model endpoint is fixed; the model name is a workflow-side controlled value
- the credential is read from the environment and never written to the result
- the supplied execution_request_id must equal the one derived locally - from the same
  task facts and the same payload - otherwise the run refuses (a dispatch cannot ask for
  an identity it does not belong to, nor smuggle in a payload that is not the one bound)
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
    KIND,
    PROMPT,
    PROVIDER,
    PAYLOAD,
    REAL_TASK_KIND,
    RESULT_KIND,
    SCHEMA_VERSION,
    Refused,
    build_dispatch_request,
    canonical,
    execution_request_id,
    output_sha256,
    prompt_for_spec,
    sha256_hex,
    task_spec,
    validate_result,
)

API_KEY_ENV = "OPENAI_API_KEY"
HTTP_TIMEOUT_S = 45
# The smoke's own budget. It belongs to the smoke contract rather than to the runner's
# configuration: the deployed smoke expects a fixed ten-token literal, and nothing about
# that expectation may move.
SMOKE_MAX_OUTPUT_TOKENS = 32
# Back-compatible name for the smoke budget, and the default of `call_responses_api`.
MAX_OUTPUT_TOKENS = SMOKE_MAX_OUTPUT_TOKENS
# A real task asks an open question, and the model spends tokens on its reasoning before
# it answers - 32 is not enough for that. 1024 is comfortably above a bounded answer while
# still bounded: an unbounded answer is a defect either way.
REAL_TASK_MAX_OUTPUT_TOKENS = 1024
# The range a runner-supplied override may take, so a bad configuration value fails closed
# instead of silently truncating every answer to nothing.
MAX_OUTPUT_TOKENS_MIN = 1
MAX_OUTPUT_TOKENS_MAX = 32768
MAX_RESPONSE_BYTES = 1024 * 1024


def output_token_budget(task_kind: str, override=None) -> int:
    """How many output tokens this execution may spend.

    A property of the task class, not of the caller. The smoke keeps its own budget
    whatever the runner is configured with, so the one path that has already been paid
    for cannot be changed from outside. A real task may be given a bounded override,
    because its right budget depends on the model the repository has configured - the
    same reason the model name itself is a repository-side value.
    """
    if task_kind != REAL_TASK_KIND:
        return SMOKE_MAX_OUTPUT_TOKENS
    if override is None:
        return REAL_TASK_MAX_OUTPUT_TOKENS
    try:
        value = int(override)
    except (TypeError, ValueError):
        raise Refused("MAX_OUTPUT_TOKENS_OUT_OF_RANGE") from None
    if not MAX_OUTPUT_TOKENS_MIN <= value <= MAX_OUTPUT_TOKENS_MAX:
        raise Refused("MAX_OUTPUT_TOKENS_OUT_OF_RANGE")
    return value


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


def call_responses_api(*, api_key: str, model: str, prompt: str = PROMPT,
                       max_output_tokens: int = MAX_OUTPUT_TOKENS,
                       opener=urllib.request.urlopen):
    """One real model call. The key is used and then goes out of scope.

    `prompt` and `max_output_tokens` are supplied by the caller, which obtained both from
    the task it holds. Their defaults are the fixed smoke prompt and the smoke's own
    budget, matching `prompt_sha256()`'s convention, so a direct call with no task in hand
    behaves exactly as it did before the real-task contract existed.
    """
    if not api_key:
        raise Refused("MISSING_OPENAI_API_KEY")
    body = canonical({
        "model": model,
        "input": prompt,
        "max_output_tokens": max_output_tokens,
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


def stub_response(*, model: str, task_kind: str = KIND, prompt: str = "") -> dict:
    """Deterministic stand-in for offline tests and CI. No network, no key.

    For the smoke this is the fixed smoke literal, exactly as before. For a real task the
    stand-in is derived from the prompt, so the offline path produces a well-formed
    non-empty answer that is deliberately NOT the smoke string - which is what makes it
    exercise the real acceptance rule ("any non-empty output") instead of the smoke one.
    """
    output = EXPECTED_OUTPUT if task_kind == KIND else "STUB_TASK_RESULT " + sha256_hex(prompt)
    return {"response_id": "stub:no-model-call", "model": model, "output": output}


def sealed_result(*, runtime_task_id, attempt, request_id, reply, github_run_id,
                  github_run_attempt, reused: bool, task_kind: str = KIND) -> dict:
    if task_kind == KIND:
        accepted = reply["output"] == EXPECTED_OUTPUT
        failure_reason = "MODEL_OUTPUT_DID_NOT_MATCH_SMOKE_STRING"
    else:
        # A real task's result is bound to its task by the identity triple, not by its
        # text. Any non-empty answer carrying a response id is a completed execution;
        # judging the answer's quality is not this contract's job, and reintroducing a
        # fixed literal here would make the identity check redundant.
        accepted = bool(reply["output"].strip()) and bool(reply.get("response_id"))
        failure_reason = "MODEL_RETURNED_NO_USABLE_OUTPUT"
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
        document["failure_reason"] = failure_reason
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
                  api_key="", opener=urllib.request.urlopen, task_kind: str = KIND,
                  payload=None, max_output_tokens=None) -> dict:
    """Execute exactly one already-bound task and seal exactly one result.

    The task's kind and payload decide the identity, the prompt AND the output budget, and
    all three are re-derived here rather than taken from the caller. A dispatch that
    carries a payload other than the one its `execution_request_id` was built from is
    therefore refused rather than executed - which is what stops a valid-looking dispatch
    from substituting one task's content for another's.
    """
    spec = task_spec(task_kind, PAYLOAD if payload is None else payload)
    derived = execution_request_id(runtime_task_id, attempt, spec)
    if execution_request_id_given is not None and execution_request_id_given != derived:
        # The dispatch asked for an identity that does not belong to these task facts.
        raise Refused("EXECUTION_REQUEST_ID_DOES_NOT_MATCH_RUNTIME_FACTS")

    if existing_result:
        reused = reuse_terminal_result(existing_result, derived)
        if reused is not None:
            return dict(reused, reused_terminal_result=True)

    # Resolved for every path - including the offline stub - so a bad runner-supplied
    # budget fails the run instead of being silently ignored until a live call.
    budget = output_token_budget(task_kind, max_output_tokens)
    prompt = prompt_for_spec(spec)
    reply = (stub_response(model=model, task_kind=task_kind, prompt=prompt) if stub
             else call_responses_api(api_key=api_key, model=model, prompt=prompt,
                                     max_output_tokens=budget, opener=opener))
    document = sealed_result(
        runtime_task_id=runtime_task_id, attempt=attempt, request_id=derived, reply=reply,
        github_run_id=github_run_id, github_run_attempt=github_run_attempt, reused=False,
        task_kind=task_kind)
    validate_result(document, runtime_task_id=runtime_task_id, attempt=attempt,
                    execution_request_id_=derived, task_kind=task_kind)
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

    def add_task_arguments(command):
        """The task identity a dispatch carries.

        A smoke dispatch supplies neither (the defaults reproduce the fixed smoke exactly,
        which is why existing invocations are unaffected). A real dispatch supplies both,
        and the payload is what its `execution_request_id` must have been derived from.
        """
        command.add_argument("--runtime-task-id", required=True)
        command.add_argument("--attempt", type=int, required=True)
        command.add_argument("--task-kind", default=KIND,
                             help="AI_WORK_V1 (fixed smoke) or AI_TASK_V1 (real task)")
        command.add_argument("--task-payload", default=None,
                             help="canonical JSON payload; required for a real task")

    emit = sub.add_parser("emit-request", help="print the canonical dispatch request")
    add_task_arguments(emit)

    run = sub.add_parser("run", help="execute one bound task and seal one result")
    add_task_arguments(run)
    run.add_argument("--execution-request-id", required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--github-run-id", type=int, required=True)
    run.add_argument("--github-run-attempt", type=int, required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--existing-result", default=None)
    run.add_argument("--max-output-tokens", type=int, default=None,
                     help="runner-side override for a REAL task's output budget; the "
                          "fixed smoke always keeps its own")
    run.add_argument("--stub", action="store_true",
                     help="no network, no credential - offline/CI path")

    args = parser.parse_args(argv)

    try:
        payload = None
        if args.task_payload is not None:
            try:
                payload = json.loads(args.task_payload)
            except ValueError:
                raise Refused("TASK_PAYLOAD_NOT_JSON") from None
        spec = task_spec(args.task_kind, PAYLOAD if payload is None else payload)

        if args.command == "emit-request":
            print(canonical(build_dispatch_request(args.runtime_task_id, args.attempt, spec)))
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
            task_kind=args.task_kind,
            payload=payload,
            max_output_tokens=args.max_output_tokens,
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
