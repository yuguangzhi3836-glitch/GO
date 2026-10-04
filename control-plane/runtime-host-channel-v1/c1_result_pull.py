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
    ABANDONED,
    COMPLETED,
    INTENT,
    RUN_FAILED,
    DispatchOutbox,
)
from c1_execution_contract import (
    KIND,
    OWNER_C,
    Refused,
    build_dispatch_request,
    run_identity_name,
    sha256_hex,
    validate_result,
)

ARTIFACT_PREFIX = "c1-ai-execution-result-"

# The one exception type the deployed Runtime kernel raises for every refusal from its
# lease and attempt fence (`renew_task`, `complete`). Matching on the type *name* rather
# than importing the kernel keeps these modules free of any dependency on the installed
# Runtime, while still separating "the Runtime will not accept this identity, ever" -
# which is permanent and must not be retried - from a transport error or a defect of ours,
# which must be raised so it is seen. It lives here, beside the call that provokes it, and
# `c1_execution_loop` imports it instead of keeping a second copy.
FENCED_REFUSAL_TYPES = ("RuntimeErrorInvariant",)


def is_a_fenced_refusal(exc) -> bool:
    return type(exc).__name__ in FENCED_REFUSAL_TYPES


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
                expected_run_id=None, request=None, validator=None,
                artifact=None) -> dict:
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
    if action in (ABANDONED, RUN_FAILED):
        # Settled: there is nothing to look up, and nothing may be sealed.
        return {"action": action, "execution_request_id": request_id}

    snapshot = outbox.snapshot(request_id)
    run_id = snapshot["github_run_id"]
    if run_id is None:
        # The run name carries the execution's own cell, read from the request rather than
        # assumed. C1 is the default because a pre-contract row is a C1 row; for every
        # real execution the cell is right there in the stored request.
        found = client.find_run_by_name(run_identity_name(
            runtime_task_id, attempt, request_id, request.get("owner_c", OWNER_C)))
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

    # WHICH artifact carries this class's answer is a property of the class, not of the
    # task: the C1/C12 classes publish `c1-ai-execution-result-<identity>`, while the
    # review classes publish the Lite workflow's own bundle artifact. `artifact` is an
    # injected loader for exactly that difference; with none the default name is used,
    # so every existing caller is unchanged.
    if artifact is None:
        artifact = client.download_artifact(
            run_id, artifact_name(runtime_task_id, attempt, request=request))
    else:
        # The loader is told WHICH request this is, because which artifact carries a
        # class's answer is a property of the class's payload - a review's artifact is
        # named after the frozen candidate, which only the request knows.
        artifact = artifact(client, run_id, request)
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

    actual_run_id = run_id
    if document.get("github_run_id") != actual_run_id:
        raise Refused("RESULT_BELONGS_TO_ANOTHER_RUN")
    if validator is None:
        validate_result(document, runtime_task_id=runtime_task_id, attempt=attempt,
                        execution_request_id_=request_id, task_kind=task_kind)

    outbox.record_result(request_id, document, runtime_task_id=runtime_task_id,
                         attempt=attempt, validator=validator)
    return {"action": "RESULT_SEALED", "execution_request_id": request_id,
            "result": document,
            "completion": outbox.completion_binding(request_id)}


def complete_after_pull(outbox: DispatchOutbox, runtime, runtime_task_id, attempt, *,
                        client, worker_id, request=None, validator=None,
                        artifact=None, on_result_sealed=None) -> dict:
    """Pull, validate, and complete through the Runtime's own contract.

    `Runtime.complete()` is called with the exact attempt the outbox holds, so the
    Runtime's lease/attempt fencing remains the authority. Nothing here writes to the
    Runtime database directly.

    A run that ended without succeeding has no result to complete with, and is routed to
    `fail_after_pull` - which reports the failure to the Runtime and settles the identity,
    rather than leaving it in flight to be retried forever.
    """
    pulled = pull_result(outbox, runtime_task_id, attempt, client=client, request=request,
                         validator=validator, artifact=artifact)
    if pulled["action"] == "RUN_DID_NOT_SUCCEED":
        return fail_after_pull(outbox, runtime, runtime_task_id, attempt,
                               worker_id=worker_id,
                               request_id=pulled["execution_request_id"],
                               conclusion=pulled.get("conclusion"))
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
    # Between the seal and the completion, and ONLY here. A result that is allowed to
    # have a consequence must have it before the Runtime is told the task is over:
    # completing first would mean a crash in between leaves a finished task whose
    # consequence never happened, and nothing would ever come back for it - the C14 run
    # would be COMPLETED and the C13 half would simply never exist. Enqueueing first uses
    # the Runtime's own idempotency as the transaction coordinator: a crash after the
    # enqueue and before the completion is repaired by the next tick, which re-runs this
    # hook, gets the SAME C13 task back from the same deterministic key, and then
    # completes C14 normally. No coordinator, no second durable journal.
    sealed_effect = None
    if on_result_sealed is not None:
        # A hook is free to have nothing to say - a C13 execution, for instance, has no
        # second half to create - so its return value is recorded when there is one and
        # the absence of one is not an error.
        sealed_effect = on_result_sealed(document, binding, outbox, runtime)
    # The owner cell comes from the stored binding, never from a constant and never from
    # this function's caller. One Builder executor serves twelve cells, so "which cell
    # must be told" is a property of the execution; `completion_binding()` reads it back
    # from the request the identity was registered with, which is what makes it survive a
    # restart, a lost lease and a fresh attempt.
    runtime.complete(
        binding["owner_c"],
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
            "accepted": document["accepted"],
            "sealed_effect": sealed_effect}


def failure_record(*, runtime_task_id, attempt, execution_request_id_, github_run_id,
                   conclusion) -> dict:
    """What the Runtime is told when the execution itself failed.

    Deliberately NOT a sealed result: it is not produced by a run, it carries no model
    output, and it must never be adoptable as an answer for a later attempt - the outbox
    stores it nowhere near `result_json`. It exists so the Runtime's own Evidence says why
    the task failed, in the same vocabulary as everything else this channel records.
    """
    return {
        "outcome": "RUN_FAILED",
        "runtime_task_id": runtime_task_id,
        "attempt": attempt,
        "execution_request_id": execution_request_id_,
        "github_run_id": github_run_id,
        "conclusion": conclusion,
        "authorizes_any_action": False,
    }


def fail_after_pull(outbox: DispatchOutbox, runtime, runtime_task_id, attempt, *,
                    worker_id, request_id, conclusion, run_id=None) -> dict:
    """Report a run that ended without succeeding, and settle its identity.

    Two things have to happen, in this order:

      1. the Runtime is told the execution failed (`complete(success=False)`). That is the
         Runtime's own way to record a failed execution, and it is what stops the task from
         being requeued as a new attempt - a new attempt is a new execution identity, and
         nothing would stop it from dispatching a second paid model call for a task that
         has already been tried;
      2. the outbox identity is settled as RUN_FAILED, so it stops holding work and the
         worker can claim again.

    The order matters. Settling locally first would leave a window in which a crash leaves
    a live Runtime task that `recover_stale()` would requeue. If the Runtime refuses the
    completion - its lease already expired, say - the identity is settled anyway, because
    the run really did fail, and `runtime_told` records that it was not told.
    """
    snapshot = outbox.snapshot(request_id)
    if run_id is None:
        run_id = snapshot["github_run_id"]
    reason = "RUN_DID_NOT_SUCCEED:%s" % (conclusion or "unknown")
    record = failure_record(runtime_task_id=runtime_task_id, attempt=attempt,
                            execution_request_id_=request_id, github_run_id=run_id,
                            conclusion=conclusion)
    # The owner comes from the same durable place the success path reads it from - the
    # identity's own stored request - and is resolved BEFORE the try, because a missing
    # owner is a defect of ours rather than a refusal by the Runtime's fence, and must
    # not be mistaken for one. A failing C7 run has to tell C7.
    owner_c = outbox.owner_c_for(request_id)
    runtime_told = True
    try:
        runtime.complete(owner_c, runtime_task_id, worker_id=worker_id,
                         expected_attempt=attempt, success=False, error=reason,
                         result=record)
    except Exception as exc:                        # noqa: BLE001 - re-raised below
        if not is_a_fenced_refusal(exc):
            # Not a refusal by the Runtime's fence: a transport failure, or a defect of
            # ours. Leave the row exactly as it is - settling it here would hide it.
            raise
        runtime_told = False
    outbox.record_run_failed(request_id, reason=reason, github_run_id=run_id)
    return {"action": RUN_FAILED, "execution_request_id": request_id,
            "runtime_task_id": runtime_task_id, "attempt": attempt,
            "conclusion": conclusion, "github_run_id": run_id,
            "runtime_told": runtime_told}


def is_pending(outbox: DispatchOutbox, runtime_task_id, attempt) -> bool:
    request = outbox.stored_request(runtime_task_id, attempt) or \
        build_dispatch_request(runtime_task_id, attempt)
    try:
        return outbox.snapshot(request["execution_request_id"])["state"] == INTENT
    except Refused:
        return False
