"""Runtime-side puller for a sealed C1 execution result.

Completes the return leg of the loop without giving the Runtime Host any privileged
channel: the Agent asks GitHub for the run by its deterministic name, downloads the
artifact whose name is the execution identity, validates the bytes against the exact
task it belongs to, and only then hands them to the outbox for completion.

Hard boundaries, all structural:

- no listener is opened on the Runtime Host, and nothing public is exposed;
- the Runtime database is never touched by this module - completion is a separate,
  explicit call the Agent makes with the attempt the outbox returns;
- the GitHub client is injected, so every failure path (timeout, missing run, missing
  artifact, malformed body, wrong run identity) is reproducible offline;
- a result whose `github_run_id` is not the run it was pulled from is refused.

This module holds no credential itself: the client owns the transport and the
credential, which is exactly the boundary the design wants.
"""
from __future__ import annotations

import json

from c1_dispatch_outbox import (
    COMPLETED,
    INTENT,
    DispatchOutbox,
)
from c1_execution_contract import (
    KIND,
    Refused,
    build_dispatch_request,
    run_identity_name,
    sha256_hex,
    validate_result,
)

ARTIFACT_PREFIX = "c1-ai-execution-result-"


def artifact_name(runtime_task_id: int | str, attempt: int, request=None) -> str:
    """The artifact name IS the execution identity, so it is derived from the request.

    For a smoke task the request is the fixed one and this is unchanged. For a real task
    the caller passes the request the outbox holds, because the identity of a real task is
    derived from its payload and cannot be recovered from (task, attempt) alone.
    """
    if request is None:
        request = build_dispatch_request(runtime_task_id, attempt)
    return ARTIFACT_PREFIX + request["execution_request_id"]


def pull_result(outbox: DispatchOutbox, runtime_task_id, attempt, *, client,
                expected_run_id=None, request=None) -> dict:
    """One bounded attempt to obtain and seal the terminal result for this execution.

    `client` must provide:
        find_run_by_name(name) -> {"id": int, "run_attempt": int, "status": str,
                                   "conclusion": str|None, "head_sha": str} | None
        download_artifact(run_id, name) -> {"bytes": bytes, "digest": str|None} | None

    `request` identifies which execution this is. When it is omitted the outbox is asked
    first and only a pre-contract row falls back to the smoke binding, so the smoke path
    is unchanged and a real task never has to be re-derived from (task, attempt).
    """
    if request is None:
        request = outbox.stored_request(runtime_task_id, attempt) or \
            build_dispatch_request(runtime_task_id, attempt)
    request_id = request["execution_request_id"]
    task_kind = request.get("task_kind", KIND)
    registered = outbox.register(runtime_task_id, attempt, request=request)
    action = registered["action"]

    if action == "REUSE_TERMINAL":
        return {"action": "REUSE_TERMINAL", "execution_request_id": request_id,
                "result": outbox.terminal_result(request_id)}
    if action == "DISPATCH":
        return {"action": "DISPATCH_REQUIRED", "execution_request_id": request_id}

    snapshot = outbox.snapshot(request_id)
    run_id = snapshot["github_run_id"]
    if run_id is None:
        found = client.find_run_by_name(run_identity_name(runtime_task_id, attempt, request_id))
        if found is None:
            return {"action": "RUN_NOT_FOUND", "execution_request_id": request_id}
        outbox.record_run_lookup(request_id, found["id"])
        run_id = found["id"]

    if expected_run_id is not None and run_id != expected_run_id:
        raise Refused("RUN_ID_DOES_NOT_MATCH_THE_BOUND_RUN")

    run = client.get_run(run_id)
    if run is None:
        return {"action": "RUN_NOT_FOUND", "execution_request_id": request_id}
    if run.get("status") != "completed":
        return {"action": "AWAIT_RESULT", "execution_request_id": request_id,
                "run_status": run.get("status")}
    if run.get("conclusion") != "success":
        # No artifact can be trusted from a run that did not finish successfully; this
        # is a refusal to complete, not an invitation to dispatch again.
        return {"action": "RUN_DID_NOT_SUCCEED", "execution_request_id": request_id,
                "conclusion": run.get("conclusion")}

    artifact = client.download_artifact(run_id, artifact_name(runtime_task_id, attempt,
                                                             request=request))
    if artifact is None:
        return {"action": "ARTIFACT_MISSING", "execution_request_id": request_id}

    raw = artifact["bytes"]
    digest = artifact.get("digest")
    if digest is not None and digest != "sha256:" + sha256_hex(raw.decode("utf-8")):
        raise Refused("ARTIFACT_DIGEST_MISMATCH")

    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Refused("ARTIFACT_NOT_VALID_JSON") from None

    validate_result(document, runtime_task_id=runtime_task_id, attempt=attempt,
                    execution_request_id_=request_id, task_kind=task_kind)
    if document["github_run_id"] != run_id:
        raise Refused("RESULT_BELONGS_TO_ANOTHER_RUN")

    outbox.record_result(request_id, document, runtime_task_id=runtime_task_id,
                         attempt=attempt)
    return {"action": "RESULT_SEALED", "execution_request_id": request_id,
            "result": document,
            "completion": outbox.completion_binding(request_id)}


def complete_after_pull(outbox: DispatchOutbox, runtime, runtime_task_id, attempt, *,
                        client, worker_id, request=None) -> dict:
    """Pull, validate, and complete through the Runtime's own contract.

    `Runtime.complete()` is called with the exact attempt the outbox holds, so the
    Runtime's lease/attempt fencing remains the authority. Nothing here writes to the
    Runtime database directly.
    """
    pulled = pull_result(outbox, runtime_task_id, attempt, client=client, request=request)
    if pulled["action"] != "RESULT_SEALED":
        if pulled["action"] == "REUSE_TERMINAL":
            pass
        else:
            return pulled

    request_id = pulled["execution_request_id"]
    snapshot = outbox.snapshot(request_id)
    if snapshot["state"] == COMPLETED:
        return {"action": "ALREADY_COMPLETED", "execution_request_id": request_id}

    binding = outbox.completion_binding(request_id)
    document = outbox.terminal_result(request_id)
    runtime.complete(
        "C1",
        binding["runtime_task_id"],
        worker_id=worker_id,
        expected_attempt=binding["expected_attempt"],
        success=bool(document["accepted"]),
        result=document,
    )
    outbox.mark_completed(request_id)
    return {"action": "COMPLETED", "execution_request_id": request_id,
            "runtime_task_id": binding["runtime_task_id"],
            "expected_attempt": binding["expected_attempt"],
            "accepted": document["accepted"]}


def is_pending(outbox: DispatchOutbox, runtime_task_id, attempt) -> bool:
    request = outbox.stored_request(runtime_task_id, attempt) or \
        build_dispatch_request(runtime_task_id, attempt)
    try:
        return outbox.snapshot(request["execution_request_id"])["state"] == INTENT
    except Refused:
        return False
