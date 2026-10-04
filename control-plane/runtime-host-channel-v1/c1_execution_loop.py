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

A third fact fixes the *entry* into the loop, and it is the one that broke the first
deployment: `claim()` hands out `QUEUED` tasks and nothing else. A task this worker has
already taken is `RUNNING` and owned by this worker, so `claim()` will never return it
again - which means that if a tick only ever advances what it has just claimed, the
dispatch leg of a task can never be followed by its result leg. The outbox, not the task
queue, is what remembers work in progress, and that is why `resume()` exists.

`resume()` is the other half of that entry: given a task id and an attempt that this
outbox already holds, it drives exactly the same three steps as `advance()` - dispatch,
pull, complete - with no claim involved. Nothing about the execution identity is
re-derived: it is the same `execution_request_id` the first tick registered, so the
exactly-once counter and every "have we already sent something" question keep their
meaning across ticks, restarts and crashes.

One state is genuinely unrecoverable, and the loop has to say so rather than retry it
forever. `complete()` is fenced on `status='RUNNING' AND lease_owner=this worker AND
attempts==expected_attempt AND lease_until>now`; `renew_task()` carries the identical
fence. If the Runtime refuses a completion, then `lease_until` is in the past and can
never be extended again (renewal checks the same condition), and the attempt can never
come back either - a requeued task is handed out as the *next* attempt. So a refusal
from `complete()` is permanent for that (task, attempt), and the identity is abandoned
rather than retried: see `DispatchOutbox.abandon`. A refusal is told apart from a
transport failure or a bug by the kernel's own exception type, `RuntimeErrorInvariant`,
which the kernel raises from nowhere else this module can reach with a well-formed
attempt.

Everything terminal is reused, never re-derives: `Runtime.complete()` is still the only
way this module touches Runtime state, and it is still called from
`c1_result_pull.complete_after_pull` with the exact attempt the outbox holds.

No I/O of its own other than through the injected client, no credential, and no
knowledge of the Runtime database.
"""
from __future__ import annotations

import time

from c1_dispatch_outbox import (
    ABANDONED,
    COMPLETED,
    RESULT_SEALED,
    RUN_FAILED,
    drive_once,
)
from c1_execution_contract import (
    CLAIMABLE_KINDS,
    GHAW_BUILDER_KIND,
    KIND,
    PAYLOAD,
    REAL_TASK_KIND,
    REVIEW_KINDS,
    Refused,
    allowed_owner_cs_for_kind,
    build_dispatch_request,
    require_runtime_facts,
    task_spec,
    validate_review_task_payload,
    validate_task_payload,
)
from c1_result_pull import complete_after_pull, fail_after_pull, is_a_fenced_refusal

# The lease the worker asks for, and re-asks for on every unfinished tick.
DEFAULT_LEASE_S = 120

# The non-smoke kinds: a payload of one of these must validate through the shared
# contract before this module will touch it. Kept as data so a new real class cannot be
# added to the contract and silently skip the payload gate.
PAYLOAD_VALIDATED_KINDS = (REAL_TASK_KIND, GHAW_BUILDER_KIND)
# The review classes are validated by their own payload rule, for the same reason:
# a review task a caller composed by hand must never reach an outbox.
REVIEW_VALIDATED_KINDS = REVIEW_KINDS

# Exactly the four facts an execution identity is built from, and the only attributes
# `claimed_identity()` will read off a claim.
CLAIMED_IDENTITY_FIELDS = ("task_id", "attempts", "kind", "payload")


def claimed_identity(claimed) -> dict:
    """The identity of what `Runtime.claim()` actually handed out. U10, formalised.

    The deployed Runtime is a scheduler, and `claim(kinds=...)` returns the oldest QUEUED
    task matching the filter - not necessarily the one some caller enqueued most
    recently, and not something a caller can steer. There is no `claim(task_id=...)` and
    this channel must not grow one: the only way to run a particular task is to run what
    `claim` returned.

    So the identity is read here and nowhere else, in one place, as a unit. That is the
    whole point: an `enqueue()` return value is a task id with no attempt, no kind and no
    payload, so a caller that wanted "the task I just enqueued" had to borrow an attempt
    from somewhere - and Round 3 measured what happens when those come from different
    tasks (`A.task_id` + `B.attempt`). The Runtime's own fence rejected the completion,
    which was correct but late and only after a paid dispatch. Returning all four facts
    from one function makes the mixed pair unrepresentable rather than merely forbidden:
    `attempts` cannot be taken from a claim other than the one `task_id` came from,
    because there is no other claim in scope.

    Fail-closed: a claim missing any of the four, or carrying a task id / attempt the
    contract would refuse, raises rather than being repaired. The caller dispatches
    nothing.
    """
    missing = [name for name in CLAIMED_IDENTITY_FIELDS if not hasattr(claimed, name)]
    if missing:
        raise Refused("CLAIMED_OBJECT_INCOMPLETE:" + ",".join(missing))
    try:
        task_id, attempt = require_runtime_facts(claimed.task_id, claimed.attempts)
    except Refused as refusal:
        raise Refused("CLAIMED_IDENTITY_INVALID:" + refusal.reason) from None
    kind = claimed.kind
    if not isinstance(kind, str) or not kind:
        raise Refused("CLAIMED_IDENTITY_KIND_INVALID")
    if type(claimed.payload) is not dict:
        raise Refused("CLAIMED_IDENTITY_PAYLOAD_NOT_AN_OBJECT")
    return {"task_id": task_id, "attempt": attempt, "kind": kind, "payload": claimed.payload}


def _not_our_task(claimed, claimable_kinds) -> dict | None:
    """Refuse anything that is not a task this executor owns.

    `claimable_kinds` is the executor's own set - the smoke and real kinds for
    `c1_worker`, the gh-aw Builder kind for `c1_ghaw_builder_worker`. It is a parameter
    rather than a module constant because a kind belongs to exactly one executor: the
    executor states which kinds it owns and this function holds it to that, so a worker
    cannot silently execute work another executor is responsible for.

    Two sorts of kind are ours: the fixed smoke (`AI_WORK_V1`, whose payload must be the
    literal) and a real task (`AI_TASK_V1`, `GHAW_BUILDER_V1`, whose payload must
    validate). Everything else - including both probe kinds - is refused.

    The owner cell is checked against the OWNER BOUNDARY OF THE KIND, not against a
    constant. `allowed_owner_cs_for_kind()` is the single definition of that boundary, so
    the kind a task carries also decides which cells it may belong to: `AI_TASK_V1`
    admits only C1, `GHAW_BUILDER_V1` admits C1..C12, and the two control-only cells are
    in neither. The kind gate runs first because the owner set is a function of the kind -
    refusing an unknown kind before asking which cells it allows is what keeps this total.

    The claim itself should already be filtered by kind; this is the second, cheap gate,
    and it is the one that makes "this loop never executes RUNTIME_PROBE, and never
    executes a C13 Builder task" a property of this file rather than a property of the
    caller's query.

    It is also, structurally, the reason an outbox can never contain a probe identity:
    it runs *before* `outbox.register()`, so a task that fails it is never recorded.
    That is what makes the resume leg safe without re-checking the payload against the
    Runtime - which is not possible anyway, since the kernel exposes no way to read a
    task back.
    """
    owner_c = getattr(claimed, "owner_c", None)
    kind = getattr(claimed, "kind", None)
    payload = getattr(claimed, "payload", None)
    if kind not in claimable_kinds:
        return {"action": "NOT_A_C1_TASK", "reason": "KIND_MISMATCH", "kind": kind}
    try:
        allowed_owner_cs = allowed_owner_cs_for_kind(kind)
    except Refused:
        # A kind this contract cannot describe has no owner boundary, so no boundary this
        # executor could be inside. Refused for the same reason the kind check refuses.
        return {"action": "NOT_A_C1_TASK", "reason": "KIND_MISMATCH", "kind": kind}
    if owner_c not in allowed_owner_cs:
        return {"action": "NOT_A_C1_TASK", "reason": "OWNER_C_MISMATCH",
                "owner_c": owner_c, "kind": kind}
    if kind == KIND and payload != PAYLOAD:
        return {"action": "NOT_A_C1_TASK", "reason": "PAYLOAD_MISMATCH", "payload": payload}
    if kind in PAYLOAD_VALIDATED_KINDS:
        try:
            validate_task_payload(payload, allowed_owner_cs=allowed_owner_cs)
        except Refused as refusal:
            # A real task whose payload is not a valid task is not ours to execute, and
            # must never be registered - the same guarantee the smoke payload check gives.
            return {"action": "NOT_A_C1_TASK", "reason": "TASK_PAYLOAD_REFUSED",
                    "detail": refusal.reason}
    if kind in REVIEW_VALIDATED_KINDS:
        try:
            validate_review_task_payload(payload, allowed_owner_cs=allowed_owner_cs)
        except Refused as refusal:
            return {"action": "NOT_A_C1_TASK", "reason": "TASK_PAYLOAD_REFUSED",
                    "detail": refusal.reason}
    return None


def _renew(runtime, task_id, attempt, *, worker_id, lease_s) -> bool:
    """Keep the lease alive for the next tick.

    `renew_task()` refuses once the lease has already expired, and losing a lease is a
    normal race rather than a bug, so the failure is reported instead of raised. Only
    this call is guarded: a rejected `complete()` is never swallowed.
    """
    try:
        runtime.renew_task(task_id, worker_id=worker_id,
                           expected_attempt=attempt, lease_s=lease_s)
        return True
    except Exception:                                       # noqa: BLE001 - see docstring
        return False


def advance(outbox, runtime, claimed, *, worker_id: str, client,
            lease_s: int = DEFAULT_LEASE_S, clock=time.time,
            claimable_kinds=CLAIMABLE_KINDS, result_validator=None,
            artifact_loader=None, on_result_sealed=None,
            confirm_lease=False) -> dict:
    """One bounded tick for a task that was just claimed. Never dispatches twice.

    `claimed` is what `Runtime.claim()` returned (task_id, owner_c, kind, payload,
    attempts, lease_until), and it is the ONLY source of the execution identity here: the
    four facts `claimed_identity()` returns are what every downstream derivation uses.
    No `enqueue()` return value is read, and `priority` is never consulted - it orders
    the Runtime's queue and has no meaning as an identity.

    `claimable_kinds` is the executor's own kind set. It defaults to the Responses-API
    executor's, so every existing caller keeps the behaviour it was proven with; the
    gh-aw Builder executor passes its own set instead.
    """
    refusal = _not_our_task(claimed, claimable_kinds)
    if refusal is not None:
        return refusal
    identity = claimed_identity(claimed)
    # The request is built from what was actually claimed - for a real task that is the
    # payload the Runtime handed out - and then travels with the identity everywhere.
    return _drive(outbox, runtime, identity["task_id"], identity["attempt"],
                  request=build_dispatch_request(
                      identity["task_id"], identity["attempt"],
                      task_spec(identity["kind"], identity["payload"])),
                  worker_id=worker_id, client=client, lease_s=lease_s, clock=clock,
                  result_validator=result_validator, artifact_loader=artifact_loader,
                  on_result_sealed=on_result_sealed, confirm_lease=confirm_lease)


def resume(outbox, runtime, runtime_task_id, attempt, *, worker_id: str, client,
           lease_s: int = DEFAULT_LEASE_S, clock=time.time,
           claimable_kinds=CLAIMABLE_KINDS, result_validator=None,
           artifact_loader=None, on_result_sealed=None,
           confirm_lease=False) -> dict:
    """One bounded tick for an execution identity this outbox already owns.

    This is the half the first deployment was missing. A task the worker has claimed is
    `RUNNING` and will never be handed out by `claim()` again, so without this entry
    point the dispatch leg of a task could never be followed by its result leg: the
    workload sat in the outbox, GitHub finished, the artifact existed, and nothing
    looked at it again.

    Nothing is re-derived. The identity is `execution_request_id(task, attempt)`, the
    same one the claiming tick registered, so the stored dispatch counter still decides
    that an ambiguous POST is resolved by lookup and never by a second POST - across
    ticks, across a restart, and across a crash between the POST and the pull.

    `claimable_kinds` is the executor's own kind set, and it is checked here as well as
    at claim time. The outbox is per-executor, so this normally cannot bite - but
    "normally" is the whole problem this formalises: the isolation used to be a
    convention about paths, and a convention is not a contract. An identity belonging to
    a kind this executor does not own is refused outright rather than executed (the
    wrong executor running a task) or settled (destroying another executor's in-flight
    state). A row predating the real-task contract has no stored request, is a smoke row
    by construction, and is unaffected.

    `client` is the GitHub transport: a `GitHubActionsClient` in production, a stub
    offline - it must expose `send`, `find_run`, `find_run_by_name`, `get_run` and
    `download_artifact`.
    """
    request = outbox.stored_request(runtime_task_id, attempt)
    if request is None:
        if KIND not in claimable_kinds:
            # A missing stored request means "a row that predates the real-task contract",
            # and the fallback below reproduces a pre-contract SMOKE identity - which is
            # only ever the right answer for an executor that owns the smoke kind. For any
            # other executor it means this identity is not in this outbox at all, and
            # reproducing a smoke binding would register and dispatch an execution nobody
            # asked for. Refuse instead.
            raise Refused("RESUME_IDENTITY_NOT_IN_THIS_OUTBOX")
    else:
        kind = request.get("task_kind", KIND)
        if kind not in claimable_kinds:
            raise Refused("RESUME_KIND_NOT_OWNED_BY_THIS_EXECUTOR:" + str(kind))
    return _drive(outbox, runtime, runtime_task_id, attempt, worker_id=worker_id,
                  client=client, lease_s=lease_s, clock=clock, request=request,
                  result_validator=result_validator, artifact_loader=artifact_loader,
                  on_result_sealed=on_result_sealed, confirm_lease=confirm_lease)


def _drive(outbox, runtime, task_id, attempt, *, worker_id, client, lease_s, clock,
           request=None, result_validator=None, artifact_loader=None,
           on_result_sealed=None, confirm_lease=False) -> dict:
    """The three legs, once, for one execution identity. Shared by claim and resume.

    It starts by registering the identity, which commits the intent durably before
    anything can be sent - the property the whole exactly-once model rests on, and the
    reason a crash here can never lose the fact that this identity exists.

    `request` is that identity's already-formed dispatch request. `advance()` builds it
    from the task it just claimed; `resume()` omits it, and the outbox - which already
    remembers work in progress - is asked what this identity was registered with. Only a
    row written before the real-task contract falls back to the smoke binding, which is
    exactly the identity such a row was created from. Either way the identity is never
    re-derived from a guess, which is what keeps the exactly-once counter meaningful
    across ticks, restarts and crashes.

    `clock` is threaded through from the public entry points and is deliberately never
    read: every lease decision belongs to the Runtime, which samples the wall clock
    itself. Judging the lease here would let a wrong local clock turn into a wrong
    completion, which is exactly what the fence exists to prevent.
    """
    if request is None:
        request = outbox.stored_request(task_id, attempt) or \
            build_dispatch_request(task_id, attempt)
    request_id = request["execution_request_id"]
    action = outbox.register(task_id, attempt, request=request)["action"]

    if action == ABANDONED:
        # Already settled as uncompletable. Reachable if a caller keeps a stale list of
        # in-flight identities; harmless, and never a dispatch.
        return {"action": ABANDONED, "execution_request_id": request_id,
                "runtime_task_id": task_id, "attempt": attempt,
                "state": outbox.dispatch_status(request_id),
                "reused": False, "renewed": False}

    if action == RUN_FAILED:
        # Settled by an earlier tick: the run finished without succeeding. Terminal, and
        # never a dispatch. Renewing here is what used to hold the worker forever.
        return {"action": RUN_FAILED, "execution_request_id": request_id,
                "runtime_task_id": task_id, "attempt": attempt,
                "state": outbox.dispatch_status(request_id),
                "reused": False, "renewed": False}

    # ---- already answered for this exact execution identity -------------------
    # Reachable from a fresh claim, a resume, or an adoption, so it is routed through
    # _complete() like everything else - which is what makes "the Runtime refused this
    # identity" behave the same on all three paths.
    if action == "REUSE_TERMINAL":
        return _finish(outbox, runtime, task_id, attempt, request=request, client=client,
                       worker_id=worker_id, lease_s=lease_s, reused=False,
                       result_validator=result_validator,
                       artifact_loader=artifact_loader,
                       on_result_sealed=on_result_sealed)

    # ---- never pay twice for one Runtime task ---------------------------------
    # A task that lost its lease mid-flight comes back as a new attempt, and a new
    # attempt is a new execution identity - which would dispatch a second, paid model
    # call for a task that already has an answer. Adopt the existing result instead.
    if action == "DISPATCH":
        earlier = outbox.terminal_for_task(task_id, exclude_request_id=request_id)
        if earlier is not None:
            outbox.adopt_terminal_result(request_id, earlier)
            return _finish(outbox, runtime, task_id, attempt, request=request,
                           client=client,
                           worker_id=worker_id, lease_s=lease_s, reused=True,
                           source_request_id=earlier["execution_request_id"],
                           source_attempt=earlier["attempt"],
                           result_validator=result_validator,
                           artifact_loader=artifact_loader,
                           on_result_sealed=on_result_sealed)
        already_failed = outbox.failed_for_task(task_id, exclude_request_id=request_id)
        if already_failed is not None:
            # A run for this Runtime task already ended without succeeding, so there is
            # nothing to adopt - no answer exists. Dispatching is the only thing this
            # branch could do, and it would be a second paid model call for a task that
            # has already been tried. Settle this identity the same way instead.
            return _fail(outbox, runtime, task_id, attempt, request=request,
                         worker_id=worker_id,
                         conclusion="PRIOR_ATTEMPT_RUN_FAILED")

    # ---- the lease, before the one leg that can spend anything ----------------
    # Optional, and OFF by default, so every existing caller keeps the behaviour it has
    # always had - including the settlement tests that deliberately drive a dispatch with
    # a lease that has already gone (the run really did happen, `runtime_told` is False,
    # and the identity is settled locally). An executor that opts in gets the stricter
    # rule, and the review executor does, for a reason of its own: see its `main`.
    #
    # `renew_task()` refuses once the lease has expired, or once the task is no longer
    # RUNNING under this worker - recovered, escalated, or taken by someone else. Every one
    # of those is permanent for THIS identity, and the Runtime would refuse the completion
    # for the same reason, so a dispatch sent now would be a real, PAID execution whose
    # result could never be recorded.
    #
    # Checked only in the DISPATCH branch, which is the only branch that calls `send`: a
    # lookup that finds an already-paid run costs nothing and must still happen, so that a
    # sealed result stays available to be adopted.
    if confirm_lease and action == "DISPATCH" and \
            not _renew(runtime, task_id, attempt, worker_id=worker_id, lease_s=lease_s):
        return _abandon(outbox, task_id, attempt, request=request, reason="LEASE_LOST")

    # ---- dispatch leg: at most one POST per execution identity ----------------
    if action in ("DISPATCH", "LOOKUP_RUN"):
        step = drive_once(outbox, task_id, attempt, send=client.send, find_run=client.find_run,
                          request=request)
        if outbox.next_action(request_id) != "AWAIT_RESULT":
            # Still unresolved (ambiguous POST with no run found yet). Renew, come back.
            return _pending(outbox, runtime, task_id, attempt, request=request,
                            worker_id=worker_id, lease_s=lease_s, leg="DISPATCH", step=step)

    # ---- result leg: pull, validate, seal, then complete ----------------------
    return _complete(outbox, runtime, task_id, attempt, request=request, client=client,
                     worker_id=worker_id, lease_s=lease_s,
                     result_validator=result_validator, artifact_loader=artifact_loader,
                     on_result_sealed=on_result_sealed)


def _complete(outbox, runtime, task_id, attempt, *, client, worker_id, lease_s,
              request, result_validator=None, artifact_loader=None,
              on_result_sealed=None) -> dict:
    """Pull if one is still needed, then complete - and settle a refused identity.

    Every completion in this module goes through here, so the one unrecoverable outcome
    is handled identically however this point was reached: from a fresh pull, from a
    result this identity already sealed, or from one adopted from an earlier attempt.
    """
    request_id = request["execution_request_id"]
    try:
        outcome = complete_after_pull(outbox, runtime, task_id, attempt,
                                      client=client, worker_id=worker_id, request=request,
                                      validator=result_validator, artifact=artifact_loader,
                                      on_result_sealed=on_result_sealed)
    except Exception as exc:                                # noqa: BLE001 - re-raised below
        if not is_a_fenced_refusal(exc):
            # A transport failure, a defect of ours, anything else - NOT permanent.
            # Raise it, leave the row in flight, and let the next tick try again.
            raise
        return _abandon(outbox, task_id, attempt, request=request,
                        reason=type(exc).__name__)

    if outcome["action"] in ("COMPLETED", "ALREADY_COMPLETED"):
        return {"action": outcome["action"], "execution_request_id": request_id,
                "runtime_task_id": task_id, "attempt": attempt,
                "state": outbox.dispatch_status(request_id),
                "accepted": outcome.get("accepted"),
                "reused": False, "renewed": False}

    if outcome["action"] == RUN_FAILED:
        # The run finished without succeeding, so `complete_after_pull` has already
        # settled this identity and told the Runtime. There is nothing left to renew -
        # and renewing was exactly the loop that used to hold the worker forever.
        return _settled(request_id, task_id, attempt, outbox, outcome)

    return _pending(outbox, runtime, task_id, attempt, request=request,
                    worker_id=worker_id, lease_s=lease_s, leg="RESULT", step=outcome)


def _fail(outbox, runtime, task_id, attempt, *, request, worker_id, conclusion,
          run_id=None) -> dict:
    """Settle an execution whose run failed, through the same path the pull leg uses.

    Reached from the dispatch branch when this Runtime task already had a run that failed:
    the Runtime hands a requeued task out as a NEW attempt, and a new attempt is a new
    execution identity - so without this the task would be dispatched, and paid for, a
    second time.
    """
    outcome = fail_after_pull(outbox, runtime, task_id, attempt, worker_id=worker_id,
                              request_id=request["execution_request_id"],
                              conclusion=conclusion, run_id=run_id)
    return _settled(request["execution_request_id"], task_id, attempt, outbox, outcome)


def _settled(request_id, task_id, attempt, outbox, outcome) -> dict:
    """The terminal report for an identity that was settled rather than completed."""
    return {"action": outcome["action"], "execution_request_id": request_id,
            "runtime_task_id": task_id, "attempt": attempt,
            "state": outbox.dispatch_status(request_id),
            "reason": outcome.get("conclusion") or outcome.get("reason"),
            "runtime_told": outcome.get("runtime_told"),
            "reused": False, "renewed": False}


def _abandon(outbox, task_id, attempt, *, request, reason) -> dict:
    """Settle an identity the Runtime will not accept a completion for, so it stops being retried.

    Reachable two ways, and both are permanent for this (task, attempt): the Runtime
    refused a completion (its fence), or the lease could not be renewed before the
    dispatch leg - so the completion would be refused for exactly the same reason, and
    the identity is settled WITHOUT spending anything. Retrying would be pointless, and
    leaving the row unfinished would keep the worker from ever claiming anything again.
    Nothing is dispatched here, and nothing can be dispatched for this identity later.
    """
    request_id = request["execution_request_id"]
    outbox.abandon(request_id, reason)
    return {"action": ABANDONED, "execution_request_id": request_id,
            "runtime_task_id": task_id, "attempt": attempt,
            "state": outbox.dispatch_status(request_id), "reason": reason,
            "reused": False, "renewed": False}


def _finish(outbox, runtime, task_id, attempt, *, request, client, worker_id, lease_s,
            reused, source_request_id=None, source_attempt=None, result_validator=None,
            artifact_loader=None, on_result_sealed=None) -> dict:
    """Complete an execution whose result is already sealed (own or adopted)."""
    result = _complete(outbox, runtime, task_id, attempt, request=request,
                       client=_NoPull(client), worker_id=worker_id, lease_s=lease_s,
                       result_validator=result_validator,
                       artifact_loader=artifact_loader,
                       on_result_sealed=on_result_sealed)
    result["reused"] = reused
    if reused:
        result["reused_from_request_id"] = source_request_id
        result["reused_from_attempt"] = source_attempt
    return result


class _NoPull:
    """A client that refuses to reach the network FOR A PULL.

    `_finish` is only reached when a sealed result already exists, so no pull can be
    needed; if one ever is, that is a bug and it must fail loudly rather than silently
    dispatch or fetch.

    What it does NOT refuse is everything else, and that distinction is not cosmetic: the
    sealed-result HOOK may legitimately need the transport. A Builder's completion resolves
    the pull request its own run created - that is what admits the review round - and on the
    adoption path it runs from right here. Delegating the rest keeps the pull guarantee
    (which is about re-dispatching) without starving the hook of the only client there is.
    """

    def __init__(self, client):
        self._client = client

    def _refuse(self, *_args, **_kwargs):
        raise AssertionError("no pull may be needed once a result is sealed")

    send = find_run = find_run_by_name = get_run = download_artifact = _refuse

    def __getattr__(self, name):
        return getattr(self._client, name)


def _pending(outbox, runtime, task_id, attempt, *, request, worker_id, lease_s, leg,
             step) -> dict:
    request_id = request["execution_request_id"]
    return {"action": step["action"], "execution_request_id": request_id,
            "runtime_task_id": task_id, "attempt": attempt,
            "state": outbox.dispatch_status(request_id), "leg": leg,
            "renewed": _renew(runtime, task_id, attempt, worker_id=worker_id,
                              lease_s=lease_s)}


def loop_state(outbox, runtime_task_id, attempt) -> dict:
    """Read-only view of where this execution is, for a status line or a test.

    The identity comes from the outbox, so this reports correctly for a real task too -
    including one this process has not seen before, such as after a restart.
    """
    request = outbox.stored_request(runtime_task_id, attempt) or \
        build_dispatch_request(runtime_task_id, attempt)
    request_id = request["execution_request_id"]
    snapshot = outbox.snapshot(request_id)
    return {"execution_request_id": request_id, "state": snapshot["state"],
            "dispatch_status": outbox.dispatch_status(request_id),
            "dispatches_sent": snapshot["dispatches_sent"],
            "github_run_id": snapshot["github_run_id"],
            "reused_from": snapshot.get("reused_from"),
            "abandon_reason": snapshot.get("abandon_reason"),
            "terminal": snapshot["state"] in (RESULT_SEALED, COMPLETED, ABANDONED)}
