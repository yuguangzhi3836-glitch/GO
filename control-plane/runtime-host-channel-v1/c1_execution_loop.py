"""The C1 loop: Runtime -> GitHub -> Runtime, driven as one bounded, repeatable tick.

`c1_dispatch_outbox` knows how to dispatch exactly once and `c1_result_pull` knows how
to seal and complete. What did not exist is the thing that joins them to the Runtime's
own lease and owns the clock. Two facts about the deployed Runtime kernel fix the shape
of that join (read from `/opt/go/c1-c14-runtime/runtime.py`):

  * `complete()` only lands while the task is `RUNNING`, owned by this worker, with
    `attempts == expected_attempt` and `lease_until` in the future. An execution that
    takes longer than the lease therefore cannot complete at all - unless the lease is
    renewed while we wait for GitHub. `renew_task()` exists for exactly this.
  * an attempt that loses its lease is requeued by `recover_stale()` as a **new**
    attempt, and a new attempt is a new execution identity. That is the concrete way
    one Runtime task turns into two paid model calls.

So this module owns two responsibilities and nothing else:

  1. `advance()` - one bounded tick: push the outbox one step, then, if the execution
     is still in flight, renew the lease so a later tick can still complete it;
  2. before dispatching a **new** attempt, adopt a terminal result that already exists
     for the same Runtime task instead of paying for a second execution.

Everything terminal is reused, never re-derives: `Runtime.complete()` is still the only
way this module touches Runtime state, and it is still called from
`c1_result_pull.complete_after_pull` with the exact attempt the outbox holds.

No I/O of its own, no credential, and no knowledge of the Runtime database.
"""
from __future__ import annotations

import time

from c1_dispatch_outbox import (
    COMPLETED,
    RESULT_SEALED,
    drive_once,
)
from c1_execution_contract import (
    KIND,
    OWNER_C,
    PAYLOAD,
    execution_request_id,
)
from c1_result_pull import complete_after_pull

# The lease the worker asks for, and re-asks for on every unfinished tick.
DEFAULT_LEASE_S = 120


def _not_our_task(claimed) -> dict | None:
    """Refuse anything that is not an AI_WORK_V1 task for C1.

    The claim itself should already be filtered by kind; this is the second, cheap
    gate, and it is the one that makes "the C1 loop never executes RUNTIME_PROBE"
    a property of this file rather than a property of the caller's query.
    """
    owner_c = getattr(claimed, "owner_c", None)
    kind = getattr(claimed, "kind", None)
    payload = getattr(claimed, "payload", None)
    if owner_c != OWNER_C:
        return {"action": "NOT_A_C1_TASK", "reason": "OWNER_C_MISMATCH", "owner_c": owner_c}
    if kind != KIND:
        return {"action": "NOT_A_C1_TASK", "reason": "KIND_MISMATCH", "kind": kind}
    if payload != PAYLOAD:
        return {"action": "NOT_A_C1_TASK", "reason": "PAYLOAD_MISMATCH", "payload": payload}
    return None


def _renew(runtime, claimed, *, worker_id, lease_s) -> bool:
    """Keep the lease alive for the next tick.

    `renew_task()` refuses once the lease has already expired, and losing a lease is a
    normal race rather than a bug, so the failure is reported instead of raised. Only
    this call is guarded: a rejected `complete()` is never swallowed.
    """
    try:
        runtime.renew_task(claimed.task_id, worker_id=worker_id,
                           expected_attempt=claimed.attempts, lease_s=lease_s)
        return True
    except Exception:                                       # noqa: BLE001 - see docstring
        return False


def advance(outbox, runtime, claimed, *, worker_id: str, client,
            lease_s: int = DEFAULT_LEASE_S, clock=time.time) -> dict:
    """One bounded tick of the loop. Safe to call repeatedly; never dispatches twice.

    `claimed` is what `Runtime.claim()` returned (task_id, owner_c, kind, payload,
    attempts, lease_until). `client` is the GitHub transport: a `GitHubActionsClient`
    in production, a stub offline - it must expose `send`, `find_run`, `find_run_by_name`,
    `get_run` and `download_artifact`.
    """
    refusal = _not_our_task(claimed)
    if refusal is not None:
        return refusal

    task_id = claimed.task_id
    attempt = claimed.attempts
    request_id = execution_request_id(task_id, attempt)
    registration = outbox.register(task_id, attempt)
    action = registration["action"]

    # ---- already answered for this exact execution identity -------------------
    if action == "REUSE_TERMINAL":
        return _finish(outbox, runtime, claimed, worker_id=worker_id, clock=clock,
                       reused=False)

    # ---- never pay twice for one Runtime task ---------------------------------
    # A task that lost its lease mid-flight comes back as a new attempt, and a new
    # attempt is a new execution identity - which would dispatch a second, paid model
    # call for a task that already has an answer. Adopt the existing result instead.
    if action == "DISPATCH":
        earlier = outbox.terminal_for_task(task_id, exclude_request_id=request_id)
        if earlier is not None:
            outbox.adopt_terminal_result(request_id, earlier)
            return _finish(outbox, runtime, claimed, worker_id=worker_id, clock=clock,
                           reused=True, source_request_id=earlier["execution_request_id"],
                           source_attempt=earlier["attempt"])

    # ---- dispatch leg: at most one POST per execution identity ----------------
    if action in ("DISPATCH", "LOOKUP_RUN"):
        step = drive_once(outbox, task_id, attempt, send=client.send, find_run=client.find_run)
        if outbox.next_action(request_id) != "AWAIT_RESULT":
            # Still unresolved (ambiguous POST with no run found yet). Renew, come back.
            return _pending(outbox, runtime, claimed, worker_id=worker_id,
                            lease_s=lease_s, leg="DISPATCH", step=step)

    # ---- result leg: pull, validate, seal, then complete ----------------------
    outcome = complete_after_pull(outbox, runtime, task_id, attempt,
                                  client=client, worker_id=worker_id)
    if outcome["action"] in ("COMPLETED", "ALREADY_COMPLETED"):
        return {"action": outcome["action"], "execution_request_id": request_id,
                "runtime_task_id": task_id, "attempt": attempt,
                "state": outbox.dispatch_status(request_id),
                "accepted": outcome.get("accepted"),
                "reused": False, "renewed": False}

    return _pending(outbox, runtime, claimed, worker_id=worker_id,
                    lease_s=lease_s, leg="RESULT", step=outcome)


def _finish(outbox, runtime, claimed, *, worker_id, clock, reused,
            source_request_id=None, source_attempt=None) -> dict:
    """Complete an execution whose result is already sealed (own or adopted)."""
    task_id = claimed.task_id
    attempt = claimed.attempts
    request_id = execution_request_id(task_id, attempt)
    outcome = complete_after_pull(outbox, runtime, task_id, attempt,
                                  client=_NoPull(), worker_id=worker_id)
    result = {"action": outcome["action"], "execution_request_id": request_id,
              "runtime_task_id": task_id, "attempt": attempt,
              "state": outbox.dispatch_status(request_id),
              "accepted": outcome.get("accepted"), "reused": reused, "renewed": False}
    if reused:
        result["reused_from_request_id"] = source_request_id
        result["reused_from_attempt"] = source_attempt
    return result


class _NoPull:
    """A client that refuses to reach the network.

    `_finish` is only reached when a sealed result already exists, so no pull can be
    needed; if one ever is, that is a bug and it must fail loudly rather than silently
    dispatch or fetch.
    """

    def _refuse(self, *_args, **_kwargs):
        raise AssertionError("no pull may be needed once a result is sealed")

    send = find_run = find_run_by_name = get_run = download_artifact = _refuse


def _pending(outbox, runtime, claimed, *, worker_id, lease_s, leg, step) -> dict:
    request_id = execution_request_id(claimed.task_id, claimed.attempts)
    return {"action": step["action"], "execution_request_id": request_id,
            "runtime_task_id": claimed.task_id, "attempt": claimed.attempts,
            "state": outbox.dispatch_status(request_id), "leg": leg,
            "renewed": _renew(runtime, claimed, worker_id=worker_id, lease_s=lease_s)}


def loop_state(outbox, runtime_task_id, attempt) -> dict:
    """Read-only view of where this execution is, for a status line or a test."""
    request_id = execution_request_id(runtime_task_id, attempt)
    snapshot = outbox.snapshot(request_id)
    return {"execution_request_id": request_id, "state": snapshot["state"],
            "dispatch_status": outbox.dispatch_status(request_id),
            "dispatches_sent": snapshot["dispatches_sent"],
            "github_run_id": snapshot["github_run_id"],
            "reused_from": snapshot.get("reused_from"),
            "terminal": snapshot["state"] in (RESULT_SEALED, COMPLETED)}
