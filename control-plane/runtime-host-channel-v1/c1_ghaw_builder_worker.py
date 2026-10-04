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
One executor / one execution loop owns one durable outbox, one worker identity and one
kind set. For this executor that is:

    kinds       GHAW_BUILDER_V1, and nothing else
    outbox      /var/lib/go-runtime-c1/outbox-ghaw-builder.db
    worker id   go-runtime-host-ghaw-builder-worker
    executes    a gh-aw Builder run (U1; see below)

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
* It does not add, register or dispatch the gh-aw workflow. `c1_execution_contract`
  declares the target (`GHAW_BUILDER_WORKFLOW_FILE`) but no workflow file is added by this
  round, and no dispatch is sent: registration is U1, tracked separately.
* It does not reimplement the loop. `tick`, `main`, the credential gate and the
  status-line vocabulary are `c1_worker`'s - importing them is the point. A second copy of
  the exactly-once model is how the exactly-once model forks, and the outbox, the
  dispatch counter and the result seal must exist once and only once.
* It does not ship a systemd unit. Nothing installs this executor yet; the unit belongs
  with the registration it serves, not before it.

Usage is `c1_worker`'s, unchanged:

    c1_ghaw_builder_worker.py                 # resident: tick, sleep, repeat
    c1_ghaw_builder_worker.py --once          # one tick, then exit
    c1_ghaw_builder_worker.py --check         # report readiness only; claims nothing
    c1_ghaw_builder_worker.py --interval 10   # resident with an explicit bounded interval
"""
from __future__ import annotations

import sys
import time

from c1_execution_contract import GHAW_BUILDER_KIND
from c1_worker import (
    DEFAULT_LEASE_S,
    DEFAULT_RESUME_LIMIT,
    RUNTIME_DB,
    main as _shared_main,
    tick as _shared_tick,
)

# ------------------------------------------------------------------ executor boundary
# These three constants ARE this executor. They are deliberately not derived from
# `c1_worker`'s: an executor that inherited its kind set or its outbox could never be
# isolated from the executor it inherited them from.
WORKER_ID = "go-runtime-host-ghaw-builder-worker"
OUTBOX_DB = "/var/lib/go-runtime-c1/outbox-ghaw-builder.db"
CLAIM_KINDS = (GHAW_BUILDER_KIND,)

OWNER_C = "C1"


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
    return _shared_main(sys.argv if argv is None else argv, **kwargs)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
