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
from c1_execution_loop import DEFAULT_LEASE_S, advance, resume

# Fixed installed locations. Constants, never caller inputs - the same pattern the
# bridge service uses, so the two components cannot disagree about where the Runtime is.
RUNTIME_SOURCE_DIR = "/opt/go/c1-c14-runtime"
RUNTIME_DB = "/var/lib/go-c-runtime/runtime.db"
OUTBOX_DB = "/var/lib/go-runtime-c1/outbox.db"

WORKER_ID = "go-runtime-host-c1-worker"
OWNER_C = "C1"
# The two kinds this worker owns. RUNTIME_PROBE / RUNTIME_C1_PROBE_V1 are not in this set
# and never will be: those belong to the probe path and its own worker. `AI_TASK_V1` is a
# real task - its payload carries the task's own objective and scope, and its prompt is
# derived from that payload by the shared contract rather than from a fixed literal.
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
    "claimed_kinds", "runtime_db", "outbox_db", "credential",
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


def build_client():
    from c1_github_actions_client import GitHubActionsClient, configured_token_loader
    return GitHubActionsClient(token_loader=configured_token_loader())


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


def tick(runtime, outbox, client, *, worker_id=WORKER_ID, lease_s=DEFAULT_LEASE_S,
         clock=time.time, claim_kinds=CLAIM_KINDS,
         resume_limit=DEFAULT_RESUME_LIMIT) -> dict:
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
    has - no new claim, no new dispatch, the stored counter still in charge.

    Phase 2 runs only when nothing is unfinished, which is also why a task is never
    claimed while an execution of ours is still in flight.

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
                             clock=clock)
        except Exception as exc:  # noqa: BLE001 -- one bad task must not stop the worker
            return {"status": "BLOCKED", "claimed": False, "resumed": True,
                    "unfinished": len(unfinished),
                    "runtime_task_id": row["runtime_task_id"], "attempt": row["attempt"],
                    "reason": type(exc).__name__}
        return {"status": "RESUMED", "claimed": False, "resumed": True,
                "unfinished": len(unfinished),
                "runtime_task_id": row["runtime_task_id"], "attempt": row["attempt"],
                "action": outcome.get("action"),
                "dispatch_status": outcome.get("state"),
                "reason": outcome.get("reason"),
                "reused": bool(outcome.get("reused")),
                "renewed": bool(outcome.get("renewed"))}

    claimed = runtime.claim(OWNER_C, worker_id=worker_id, lease_s=lease_s,
                            kinds=claim_kinds)
    if claimed is None:
        return {"status": "IDLE", "claimed": False, "resumed": False, "unfinished": 0}
    try:
        outcome = advance(outbox, runtime, claimed, worker_id=worker_id, client=client,
                          lease_s=lease_s, clock=clock)
    except Exception as exc:  # noqa: BLE001 -- one bad task must not stop the worker
        # Nothing is completed here. The outbox keeps its durable state, so the next
        # tick resumes from it - and because the dispatch counter survives, a failure
        # after a POST can only lead to a lookup, never to a second POST.
        return {"status": "FAILED", "claimed": True, "resumed": False, "unfinished": 0,
                "kind": claimed.kind, "runtime_task_id": claimed.task_id,
                "attempt": claimed.attempts, "reason": type(exc).__name__}
    return {"status": "ADVANCED", "claimed": True, "resumed": False, "unfinished": 0,
            "kind": claimed.kind, "runtime_task_id": claimed.task_id,
            "attempt": claimed.attempts,
            "action": outcome.get("action"),
            "dispatch_status": outcome.get("state"),
            "reused": bool(outcome.get("reused")),
            "renewed": bool(outcome.get("renewed"))}


def main(argv, *, runtime=None, client=None, outbox=None, clock=time.time,
         token_loader=None) -> int:
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
        emit({"status": "READY", "verb": "check", "credential": "present",
              "claimed_kinds": list(CLAIM_KINDS), "runtime_db": RUNTIME_DB,
              "outbox_db": OUTBOX_DB})
        return 0

    if runtime is None:
        runtime = open_runtime()
    if outbox is None:
        outbox = open_outbox()
    if client is None:
        client = build_client()

    while True:
        try:
            emit(dict(tick(runtime, outbox, client, clock=clock),
                      verb="c1-worker-tick", runtime_db=RUNTIME_DB, outbox_db=OUTBOX_DB))
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
