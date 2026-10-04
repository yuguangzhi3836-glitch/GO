"""Bounded C1 AI worker: the component that actually runs the Runtime -> GitHub -> Runtime loop.

Installed at `/opt/go/runtime-host-c1-worker/c1_worker.py` and run by
`go-runtime-host-c1-worker.service` as User=go-runtime / Group=go-runtime.

It is deliberately NOT installed inside `/opt/go/runtime-host-agent`: the Management
Agent's `executor_sha256` is computed over every `*.py` in that directory and is bound by
the registration, so adding files there would change the Agent's identity and make it
refuse to start with `local_executor_mismatch` until a new registration was issued. It
would also make the Agent's manifest cover code the Agent never runs.

Why this is a third component rather than a step inside the resident root Agent
------------------------------------------------------------------------------
Both existing components state their own limits, and the AI loop falls outside both:

  * `agent_service.py`: "The Agent never opens the Runtime database and never calls
    Runtime.enqueue()". It reaches the C1 Runtime only through the fixed local bridge
    directory pair. It also runs as **root**.
  * `runtime_bridge_service.py`: "It is NOT a worker. It never claims, executes or
    completes a Runtime task", and it runs with `PrivateNetwork=true` - no network.

The AI loop is exactly a worker: it *claims* a task, *executes* it through GitHub, and
*completes* it. So it needs two things no existing component has together - Runtime
access (owned by `go-runtime`) and outbound network. Hence a third component, running
as the same unprivileged account that already owns the Runtime database.

The Agent's root process, its closed `channel.ACTIONS` set, the bridge handoff and the
whole `RUNTIME_PROBE` path are untouched by this file. It never imports `channel`,
`flow` or `adapter`, never reads or writes the channel registry, and never names a model
credential - the model credential stays a GitHub repository secret and never reaches
this host.

Responsibilities, and nothing else
----------------------------------
  * finish what is already in flight: for an execution identity our own outbox still
    holds, drive it one bounded step (lookup / pull / complete). `Runtime.claim()`
    hands out `QUEUED` tasks only, so a task this worker has already taken is
    `RUNNING` and can never be claimed again - the outbox is what remembers it
  * only when nothing is in flight, claim ONE task, `owner_c=C1`, kind restricted to
    `CLAIM_KINDS` - the fixed smoke and the real task kind. The kind filter is passed to
    `Runtime.claim()` itself, so the probe kinds are never even looked at
  * refuse to claim at all when it could not execute the task: claiming a task it cannot
    run would burn one of that task's attempts, so the GitHub credential is checked
    before anything is claimed
  * emit one bounded JSON status line per tick

Usage:
    c1_worker.py                 # resident: tick, sleep, repeat
    c1_worker.py --once          # one tick, then exit
    c1_worker.py --check         # report readiness only; claims nothing
    c1_worker.py --interval 10   # resident with an explicit bounded interval
"""
import json
import os
import sys
import time

from c1_dispatch_outbox import DispatchOutbox
from c1_execution_contract import WORKFLOW_FILE
from c1_execution_loop import DEFAULT_LEASE_S, advance, resume

# Fixed installed locations. Constants, never caller inputs - the same pattern the
# bridge service uses, so the two components cannot disagree about where the Runtime is.
#
# These four constants ARE the executor boundary. One executor / one execution loop owns
# one durable outbox, one worker identity and one set of task kinds, and this file is the
# Responses-API executor's statement of its own:
#
#     kinds       AI_WORK_V1 (fixed smoke), AI_TASK_V1 (real, prompt derived)
#     outbox      /var/lib/go-runtime-c1/outbox.db
#     worker id   go-runtime-host-c1-worker
#     executes    one OpenAI Responses call per execution
#
# The gh-aw Builder executor is `c1_ghaw_builder_worker.py`, with its own kind, its own
# outbox path and its own worker id. The two sets are disjoint on purpose: `claim(kinds=)`
# is how the Runtime decides which executor a task goes to, so a kind claimed by two
# executors is not a shared duty but a race, and the loser is whichever executor was
# restarted last. `test_c1_executor_boundary` asserts the disjointness rather than leaving
# it to whoever edits this file next. The Runtime database is deliberately the SAME one:
# the two executors are two workers of one Runtime, not two Runtimes.
RUNTIME_SOURCE_DIR = "/opt/go/c1-c14-runtime"
RUNTIME_DB = "/var/lib/go-c-runtime/runtime.db"
OUTBOX_DB = "/var/lib/go-runtime-c1/outbox.db"

WORKER_ID = "go-runtime-host-c1-worker"
OWNER_C = "C1"
# The cells this worker claims for. The Responses-API executor serves C1 and only C1, and
# that does not change in this round: the gh-aw Builder is what generalised, not this one.
# It is a tuple rather than a scalar so that both executors run the SAME claim loop - a
# claim loop per executor is how the exactly-once model would fork.
CLAIM_OWNER_CS = (OWNER_C,)
# The two kinds this worker owns, and nothing else. RUNTIME_PROBE / RUNTIME_C1_PROBE_V1
# are not in this set and never will be: those belong to the probe path and its own
# worker. `AI_TASK_V1` is a real task - its payload carries the task's own objective and
# scope, and its prompt is derived from that payload by the shared contract rather than
# from a fixed literal. `GHAW_BUILDER_V1` is deliberately absent: it is a real task too,
# but it is a different execution, and it belongs to the gh-aw Builder executor.
CLAIM_KINDS = ("AI_WORK_V1", "AI_TASK_V1")

DEFAULT_INTERVAL_S = 5.0
INTERVAL_MIN_S = 1.0
INTERVAL_MAX_S = 3600.0

# How many unfinished execution identities one tick will look at. Only the oldest is
# driven, so this is a read bound rather than a work bound: it keeps a long-neglected
# outbox from being loaded wholesale.
DEFAULT_RESUME_LIMIT = 10

# Everything the status line may contain. An allowlist, so a future field cannot leak by
# accident - the same rule the GitHub-side executor follows when it prints.
STATUS_FIELDS = (
    "status", "verb", "claimed", "resumed", "unfinished", "kind", "runtime_task_id",
    "attempt", "action", "dispatch_status", "reused", "renewed", "reason", "detail",
    "conclusion", "runtime_told", "failure_reason",
    "claimed_kinds", "claimed_owners", "owner_c", "next_owner_cursor",
    "runtime_db", "outbox_db", "dispatch_target", "credential",
    "runtime_source", "lite_package", "lite_modules",
)


def emit(obj) -> None:
    """One bounded JSON line on stdout. Keys outside the allowlist are dropped."""
    safe = {k: obj[k] for k in STATUS_FIELDS if k in obj}
    sys.stdout.write(json.dumps(safe, sort_keys=True) + "\n")
    sys.stdout.flush()


def load_runtime(source_dir=RUNTIME_SOURCE_DIR):
    """Import the installed Runtime module from its fixed path. Never a fork, never a copy."""
    if source_dir not in sys.path:
        sys.path.insert(0, source_dir)
    import runtime  # noqa: E402 -- resolved from the installed Runtime directory
    return runtime


def open_runtime(source_dir=RUNTIME_SOURCE_DIR, db_path=RUNTIME_DB):
    return load_runtime(source_dir).Runtime(db_path)


def open_outbox(path=OUTBOX_DB):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    return DispatchOutbox(path)


def build_client(*, workflow_file=None, workflow_files=None):
    """The GitHub transport, bound to the workflow file THIS executor dispatches.

    With no argument this is the channel's original target, so the deployed Responses
    worker behaves exactly as it did. A second executor passes its own workflow file,
    and from then on the client refuses any request whose recorded target is not that
    file - which is what stops two executors that share this class from sharing a
    transport target.
    """
    from c1_github_actions_client import GitHubActionsClient, configured_token_loader
    return GitHubActionsClient(token_loader=configured_token_loader(),
                               workflow_file=workflow_file,
                               workflow_files=workflow_files)


def credential_refusal(loader=None):
    """Every reason a task must not be claimed, checked before any claim happens.

    Returns a refusal dict, or None when the worker is able to execute. The credential
    value is never stored, returned or printed - only its presence is tested.
    """
    try:
        if loader is None:
            from c1_github_actions_client import configured_token_loader
            loader = configured_token_loader()
        # Presence, not content: the value is never stored, returned or printed. The strip
        # makes this strictly stronger than the loader's own emptiness rule, so a
        # whitespace-only file is treated as absent rather than as a credential.
        present = bool(str(loader() or "").strip())
    except Exception as exc:  # noqa: BLE001 -- a missing credential must not raise here
        return {"status": "REFUSED", "reason": "no_github_credential",
                "detail": type(exc).__name__}
    if not present:
        return {"status": "REFUSED", "reason": "empty_github_credential"}
    return None


def claim_across_owners(runtime, *, worker_id, lease_s, claim_kinds, claim_owner_cs,
                        cursor) -> tuple:
    """Ask each owned cell in turn for ONE queued task. Returns (claimed, next_cursor).

    This is the whole of "one worker serves several cells". It asks the Runtime one cell
    at a time with the same kind filter and stops at the first task it is handed, so a
    tick still claims AT MOST ONE task - exactly as it did with a single cell - and the
    concurrency this channel has always had (one execution in flight, globally) does not
    change. Where a scan begins cannot change what a task is: identity, idempotency and
    the execution request are all derived from the task itself, never from the order it
    was found in. That is why this needs no table, no database and no durable service,
    and it is why a restart is allowed to begin again at the first cell.

    The cursor is scheduling convenience and nothing else: a plain integer living in the
    caller's loop. It exists so that a permanently busy C1 cannot starve C12.
    """
    count = len(claim_owner_cs)
    if count == 0:
        return None, cursor
    for step in range(count):
        index = (cursor + step) % count
        claimed = runtime.claim(claim_owner_cs[index], worker_id=worker_id,
                                lease_s=lease_s, kinds=claim_kinds)
        if claimed is not None:
            return claimed, (index + 1) % count
    return None, (cursor + 1) % count


def tick(runtime, outbox, client, *, worker_id=WORKER_ID, lease_s=DEFAULT_LEASE_S,
         clock=time.time, claim_kinds=CLAIM_KINDS, claim_owner_cs=CLAIM_OWNER_CS,
         owner_cursor=0, resume_limit=DEFAULT_RESUME_LIMIT, result_validator=None,
         artifact_loader=None, on_result_sealed=None,
         confirm_lease=False) -> dict:
    """One bounded tick: resume what is in flight, and only then claim new work.

    Phase 1 is not an optimisation, it is the fix for the defect that stopped the first
    deployment. `Runtime.claim()` selects `status='QUEUED'` only, and a task this worker
    has already taken is `RUNNING` and owned by this worker - so `claim()` will never
    return it again. A tick that only advances what it has just claimed therefore
    advances each task exactly once, forever: the dispatch leg succeeds, GitHub runs,
    the artifact exists, and the result leg never happens because the next tick asks the
    Runtime for work and is handed nothing.

    So the outbox is asked first. Its unfinished identities are the tasks this worker is
    in the middle of, and each one is driven by `resume()` using the identity it already
    has - no new claim, no new dispatch, the stored counter still in charge. The outbox is
    the whole set of cells: an unfinished identity names its own owner, so resuming is
    never a per-cell decision and the `claim_owner_cs` list plays no part in this phase.

    Phase 2 runs only when nothing is unfinished, which is also why a task is never
    claimed while an execution of ours is still in flight. It walks `claim_owner_cs` - the
    cells this executor serves - and takes at most one task in total, so adding cells
    widens who can be served without widening how much runs at once.

    A resume that could not be driven and was not settled by the Runtime (a transport
    failure, say) reports `BLOCKED` and claims nothing this tick: continuing past it
    would start new paid work while an existing one is unresolved. The identity stays in
    the outbox and the next tick tries again, so a transient fault costs time, not money.
    """
    unfinished = outbox.unfinished(limit=resume_limit)
    if unfinished:
        row = unfinished[0]
        try:
            outcome = resume(outbox, runtime, row["runtime_task_id"], row["attempt"],
                             worker_id=worker_id, client=client, lease_s=lease_s,
                             clock=clock, claimable_kinds=claim_kinds,
                             result_validator=result_validator,
                             artifact_loader=artifact_loader,
                             on_result_sealed=on_result_sealed,
                             confirm_lease=confirm_lease)
        except Exception as exc:  # noqa: BLE001 -- one bad task must not stop the worker
            return {"status": "BLOCKED", "claimed": False, "resumed": True,
                    "unfinished": len(unfinished),
                    "runtime_task_id": row["runtime_task_id"], "attempt": row["attempt"],
                    "next_owner_cursor": owner_cursor,
                    "reason": type(exc).__name__}
        return {"status": "RESUMED", "claimed": False, "resumed": True,
                "unfinished": len(unfinished),
                "runtime_task_id": row["runtime_task_id"], "attempt": row["attempt"],
                "action": outcome.get("action"),
                "dispatch_status": outcome.get("state"),
                "reason": outcome.get("reason"),
                "reused": bool(outcome.get("reused")),
                "next_owner_cursor": owner_cursor,
                "renewed": bool(outcome.get("renewed"))}

    claimed, next_cursor = claim_across_owners(
        runtime, worker_id=worker_id, lease_s=lease_s, claim_kinds=claim_kinds,
        claim_owner_cs=claim_owner_cs, cursor=owner_cursor)
    if claimed is None:
        return {"status": "IDLE", "claimed": False, "resumed": False, "unfinished": 0,
                "next_owner_cursor": next_cursor}
    try:
        outcome = advance(outbox, runtime, claimed, worker_id=worker_id, client=client,
                          lease_s=lease_s, clock=clock, claimable_kinds=claim_kinds,
                          result_validator=result_validator,
                          artifact_loader=artifact_loader,
                          on_result_sealed=on_result_sealed,
                          confirm_lease=confirm_lease)
    except Exception as exc:  # noqa: BLE001 -- one bad task must not stop the worker
        # Nothing is completed here. The outbox keeps its durable state, so the next
        # tick resumes from it - and because the dispatch counter survives, a failure
        # after a POST can only lead to a lookup, never to a second POST.
        return {"status": "FAILED", "claimed": True, "resumed": False, "unfinished": 0,
                "kind": claimed.kind, "runtime_task_id": claimed.task_id,
                "attempt": claimed.attempts, "owner_c": claimed.owner_c,
                "next_owner_cursor": next_cursor, "reason": type(exc).__name__}
    return {"status": "ADVANCED", "claimed": True, "resumed": False, "unfinished": 0,
            "kind": claimed.kind, "runtime_task_id": claimed.task_id,
            "attempt": claimed.attempts, "owner_c": claimed.owner_c,
            "next_owner_cursor": next_cursor,
            "action": outcome.get("action"),
            "dispatch_status": outcome.get("state"),
            "reused": bool(outcome.get("reused")),
            "renewed": bool(outcome.get("renewed"))}


def main(argv, *, runtime=None, client=None, outbox=None, clock=time.time,
         token_loader=None, worker_id=WORKER_ID, claim_kinds=CLAIM_KINDS,
         claim_owner_cs=CLAIM_OWNER_CS,
         runtime_db=RUNTIME_DB, outbox_db=OUTBOX_DB,
         workflow_file=WORKFLOW_FILE, workflow_files=None, result_validator=None,
         artifact_loader=None, on_result_sealed=None, hooks_factory=None,
         confirm_lease=False, readiness=None) -> int:
    """The resident loop, parameterised by the executor's OWN boundary.

    `worker_id`, `claim_kinds`, `claim_owner_cs`, `runtime_db`, `outbox_db` and
    `workflow_file` default to this file's own values, so running `c1_worker.py` directly
    is unchanged. They are parameters so that a second executor can reuse this loop - and
    only this loop - while stating its own kinds, its own cells, its own outbox and its
    own dispatch target. Those values are what makes an executor an executor, and nothing
    else about the loop changes: copying the loop for the second executor would be a
    second implementation of the exactly-once model, which is precisely the thing that
    must never fork.

    `claim_owner_cs` is a tuple, and for this executor it has one element. A cell is not a
    second execution mechanism - it is who a task belongs to - so serving more cells must
    cost one more entry here and nothing else, which is the property the gh-aw Builder
    relies on.
    """
    once = False
    check = False
    interval = DEFAULT_INTERVAL_S
    args = list(argv)
    # Accept both `main(sys.argv)` and `main(["--once"])`: a leading element that does not
    # look like an option is the program name. Without this, a caller that omits it would
    # silently get the RESIDENT loop instead of the bounded one it asked for - which is a
    # bad way to find out.
    if args and not args[0].startswith("-"):
        args.pop(0)
    while args:
        arg = args.pop(0)
        if arg == "--once":
            once = True
        elif arg == "--check":
            check = True
        elif arg == "--interval":
            if not args:
                emit({"status": "REFUSED", "reason": "bad_argument", "detail": "--interval"})
                return 1
            try:
                interval = float(args.pop(0))
            except ValueError:
                emit({"status": "REFUSED", "reason": "bad_argument", "detail": "--interval"})
                return 1
            if not INTERVAL_MIN_S <= interval <= INTERVAL_MAX_S:
                emit({"status": "REFUSED", "reason": "interval_out_of_range"})
                return 1
        else:
            emit({"status": "REFUSED", "reason": "bad_argument", "detail": arg[:60]})
            return 1

    refusal = credential_refusal(token_loader)
    if refusal is not None:
        # Claiming a task this worker cannot execute would burn one of its attempts.
        # Nothing is claimed, nothing is opened, and the message is bounded.
        emit(dict(refusal, verb="credential"))
        return 1

    if check:
        # Readiness only: no claim, no outbox, no POST, no model. An executor that can
        # be claimed for work it cannot finish would burn a paid execution before
        # anyone noticed, so whatever this executor needs in order to COMPLETE a task
        # is checked here, before the first claim - and a missing piece is a refusal
        # with a non-zero exit, not a warning.
        report = {"status": "READY", "verb": "check", "credential": "present",
                  "claimed_kinds": list(claim_kinds),
                  "claimed_owners": list(claim_owner_cs), "runtime_db": runtime_db,
                  "outbox_db": outbox_db, "dispatch_target": workflow_file}
        if readiness is not None:
            extra = readiness()
            if isinstance(extra, dict):
                report.update(extra)
        emit(report)
        return 0 if report["status"] == "READY" else 1

    if runtime is None:
        runtime = open_runtime(db_path=runtime_db)
    if outbox is None:
        outbox = open_outbox(outbox_db)
    if client is None:
        client = build_client(workflow_file=workflow_file,
                              workflow_files=workflow_files)

    # The transport hooks, gathered once and applied to every tick. `hooks_factory`
    # exists because an executor whose validator needs the outbox cannot supply it until
    # the outbox has been opened - and a loop that silently ran without its own result
    # validator would be an executor accepting results it cannot check.
    transport_hooks = {"result_validator": result_validator,
                       "artifact_loader": artifact_loader,
                       "on_result_sealed": on_result_sealed,
                       "confirm_lease": confirm_lease}
    if hooks_factory is not None:
        transport_hooks.update(hooks_factory(outbox))

    # Where the next scan begins. Deliberately a local: it is scheduling convenience, not
    # state. A restart begins at the first cell, which is allowed, and no task's identity
    # depends on where it was found.
    owner_cursor = 0
    while True:
        try:
            outcome = tick(runtime, outbox, client, worker_id=worker_id,
                           claim_kinds=claim_kinds, claim_owner_cs=claim_owner_cs,
                           owner_cursor=owner_cursor, clock=clock,
                           **transport_hooks)
            owner_cursor = outcome.get("next_owner_cursor", owner_cursor)
            emit(dict(outcome, verb="c1-worker-tick", runtime_db=runtime_db,
                      outbox_db=outbox_db))
        except Exception as exc:  # noqa: BLE001 -- fail closed but stay observable
            emit({"status": "REFUSED", "reason": "tick", "detail": type(exc).__name__,
                  "verb": "c1-worker-tick"})
            if once:
                return 1
        if once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
