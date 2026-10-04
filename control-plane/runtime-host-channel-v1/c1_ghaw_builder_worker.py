"""The C1 gh-aw Builder executor: the second executor on this channel.

Why this is a second component and not a mode of `c1_worker.py`
--------------------------------------------------------------
`c1_worker.py` executes a C1 task by making one OpenAI Responses call. The gh-aw Builder
executes the same task shape a completely different way: it dispatches a GitHub Agentic
Workflows run, which brings its own agent, its own prompt and its own model. Those are not
two configurations of one executor - they are two executors, and the difference has to be
visible to the Runtime, because the Runtime is what decides who gets which task.

The Runtime decides by task kind. `claim(kinds=...)` filters the queue, so a kind is not a
label - it IS the routing. Two executors claiming one kind is therefore not a shared duty:
it is a race, and the loser is whichever executor was restarted last, which is exactly the
class of defect this file exists to make impossible. So:

    AI_WORK_V1, AI_TASK_V1   -> c1_worker.py               (Responses-API executor)
    GHAW_BUILDER_V1          -> this file                  (gh-aw Builder executor)

The two sets are disjoint, and `test_c1_executor_boundary` asserts it rather than trusting
whoever edits this file next.

The ownership boundary, stated once
-----------------------------------
One executor / one execution loop owns one durable outbox, one worker identity, one kind
set and one dispatch target. For this executor that is:

    kinds       GHAW_BUILDER_V1, and nothing else
    outbox      /var/lib/go-runtime-c1/outbox-ghaw-builder.db
    worker id   go-runtime-host-ghaw-builder-worker
    dispatches  c1-gh-aw-builder-v1.lock.yml
    executes    a gh-aw Builder run

The dispatch target is part of that list rather than a property of a task: the workflow a
task is sent to is decided by the executor that owns its kind, and a task that records one
target and is sent to another is a task run by the wrong executor.

`RUNTIME_DB` is deliberately NOT overridden: the two executors are two workers of ONE
Runtime. What is separate is the dispatch outbox, because the outbox is what remembers
work in progress, and an execution this executor dispatched must never be resumed by the
other one. The outbox remembers, beside each identity, the request it was born with -
including the task kind - so `resume()` in `c1_execution_loop` re-checks the kind against
the set passed in below. Isolation is thus a contract rather than a convention about paths:
a row of a kind this executor does not own is refused rather than executed (the wrong
executor running a task) or settled (destroying another executor's in-flight state).

What this file deliberately does NOT do
---------------------------------------
* It does not dispatch anything, and this round sends no dispatch. The workflow it targets
  is registered in the tree beside it (`c1-gh-aw-builder-v1.md` + the compiled `.lock.yml`)
  and is dispatch-only, so it cannot fire by itself; actually running one is the next
  round's work.
* It does not reimplement the loop. `tick`, `main`, the credential gate, the status-line
  vocabulary and now the transport are `c1_worker`'s - importing them is the point. A
  second copy of the exactly-once model is how the exactly-once model forks, and the
  outbox, the dispatch counter and the result seal must exist once and only once.
* It does not install itself. A unit candidate is added beside it
  (`systemd/go-runtime-host-ghaw-builder-worker.service`), pinned to these same four
  values, but adding a unit file is not installing one.

Usage is `c1_worker`'s, unchanged:

    c1_ghaw_builder_worker.py                 # resident: tick, sleep, repeat
    c1_ghaw_builder_worker.py --once          # one tick, then exit
    c1_ghaw_builder_worker.py --check         # report readiness only; claims nothing
    c1_ghaw_builder_worker.py --interval 10   # resident with an explicit bounded interval
"""
from __future__ import annotations

import sys
import time

from c1_execution_contract import GHAW_BUILDER_KIND, GHAW_BUILDER_WORKFLOW_FILE
from c1_worker import (
    DEFAULT_LEASE_S,
    DEFAULT_RESUME_LIMIT,
    RUNTIME_DB,
    build_client as _shared_build_client,
    main as _shared_main,
    tick as _shared_tick,
)

# ------------------------------------------------------------------ executor boundary
# These four constants ARE this executor. They are deliberately not derived from
# `c1_worker`'s: an executor that inherited its kind set, its outbox or its dispatch
# target could never be isolated from the executor it inherited them from.
WORKER_ID = "go-runtime-host-ghaw-builder-worker"
OUTBOX_DB = "/var/lib/go-runtime-c1/outbox-ghaw-builder.db"
CLAIM_KINDS = (GHAW_BUILDER_KIND,)
# The workflow this executor's dispatches land on. The same value the contract records on
# every GHAW_BUILDER_V1 request, and the only one this executor's client will send to.
WORKFLOW_FILE = GHAW_BUILDER_WORKFLOW_FILE

OWNER_C = "C1"


def build_client():
    """The transport, bound to the gh-aw Builder workflow and to nothing else.

    This is the whole of the transport half of U1: one argument, fixed by the executor.
    A GHAW_BUILDER_V1 request carries `workflow_file = c1-gh-aw-builder-v1.lock.yml`, so
    the client accepts it; the same client would refuse a request aimed at the Responses
    backend, and the Responses client refuses this one.
    """
    return _shared_build_client(workflow_file=WORKFLOW_FILE)


def tick(runtime, outbox, client, *, worker_id=WORKER_ID, lease_s=DEFAULT_LEASE_S,
         clock=time.time, claim_kinds=CLAIM_KINDS,
         resume_limit=DEFAULT_RESUME_LIMIT) -> dict:
    """One bounded tick: resume what is in flight here, and only then claim new work.

    Identical to `c1_worker.tick` except for its defaults, which is the whole design: the
    loop is shared, the boundary is not. Both the resume leg and the claim leg are handed
    this executor's kind set, so neither can reach the other executor's work.
    """
    return _shared_tick(runtime, outbox, client, worker_id=worker_id, lease_s=lease_s,
                        clock=clock, claim_kinds=claim_kinds, resume_limit=resume_limit)


def main(argv=None, **kwargs) -> int:
    """The shared resident loop, with this executor's boundary filled in."""
    kwargs.setdefault("worker_id", WORKER_ID)
    kwargs.setdefault("claim_kinds", CLAIM_KINDS)
    kwargs.setdefault("outbox_db", OUTBOX_DB)
    kwargs.setdefault("runtime_db", RUNTIME_DB)
    kwargs.setdefault("workflow_file", WORKFLOW_FILE)
    return _shared_main(sys.argv if argv is None else argv, **kwargs)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
