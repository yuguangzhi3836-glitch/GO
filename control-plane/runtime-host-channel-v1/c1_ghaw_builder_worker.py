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

    AI_WORK_V1, AI_TASK_V1   -> c1_worker.py               (Responses-API executor, C1)
    GHAW_BUILDER_V1          -> this file                  (gh-aw Builder, C1..C12)

The two sets are disjoint, and `test_c1_executor_boundary` asserts it rather than trusting
whoever edits this file next.

One executor, twelve cells
--------------------------
This worker serves every normal engineering cell, not just C01. That is deliberately ONE
worker and not twelve: a cell is not an execution mechanism, and eleven extra copies of
this file would be eleven extra copies of the exactly-once model - the one thing on this
channel that must never fork. What is per-cell is the *owner*, and the owner comes from
the task, not from the process:

    owners      C1..C12  (from the contract's BUILDER_OWNER_CS; C13/C14 excluded)
    kind        GHAW_BUILDER_V1, and nothing else
    outbox      /var/lib/go-runtime-c1/outbox-ghaw-builder.db
    worker id   go-runtime-host-ghaw-builder-worker
    dispatches  c1-gh-aw-builder-v1.lock.yml
    executes    a gh-aw Builder run

`C13` and `C14` are excluded in three independent places - this worker's owner list, the
contract's payload validator, and the workflow's pre-agent gate - because they are the
control-only cells and a Builder is not their executor. Any one of the three refusing is
enough; none of them relies on the others.

`RUNTIME_DB` is deliberately NOT overridden: the two executors are two workers of ONE
Runtime. What is separate is the dispatch outbox, because the outbox is what remembers
work in progress, and an execution this executor dispatched must never be resumed by the
other one. The outbox remembers, beside each identity, the request it was born with -
including the task kind AND the owner cell - so `resume()` re-checks the kind against the
set passed in below and the completion is returned to the owner the request names.
Isolation is thus a contract rather than a convention about paths: a row of a kind this
executor does not own is refused rather than executed (the wrong executor running a task)
or settled (destroying another executor's in-flight state).

A completed Builder hands its own candidate to the review
--------------------------------------------------------
A Builder run that created a Draft pull request is what a C13/C14 round is FOR, and the
hand-over is no longer a person's job: this executor's sealed-result hook resolves the
candidate its own run produced and enqueues the C14 half, before the Builder task is
completed. `c1_builder_candidate` owns that, and the ordering - enqueue, then complete - is
the same one C14 -> C13 already uses, for the same reason. A run that created no pull
request completes with no review task, and a run whose candidate cannot be established does
not complete at all.

What this file deliberately does NOT do
---------------------------------------
* It does not add a worker per cell, an outbox per cell, a workflow per cell or a
  systemd unit per cell. One of each, and the cell is carried by the task.
* It does not reimplement the loop. `tick`, `main`, the credential gate, the status-line
  vocabulary and the transport are `c1_worker`'s - importing them is the point. A second
  copy of the exactly-once model is how the exactly-once model forks, and the outbox, the
  dispatch counter and the result seal must exist once and only once.
* It does not review anything itself, and it never dispatches a review. It enqueues ONE
  Runtime task of the C14 kind and stops; what runs it is the review executor, exactly as
  if an Owner had admitted the round by hand.
* It does not install itself. A unit candidate is added beside it
  (`systemd/go-runtime-host-ghaw-builder-worker.service`), pinned to these same values,
  but adding a unit file is not installing one.

Usage is `c1_worker`'s, unchanged:

    c1_ghaw_builder_worker.py                 # resident: tick, sleep, repeat
    c1_ghaw_builder_worker.py --once          # one tick, then exit
    c1_ghaw_builder_worker.py --check         # report readiness only; claims nothing
    c1_ghaw_builder_worker.py --interval 10   # resident with an explicit bounded interval
"""
from __future__ import annotations

import sys
import time

from c1_execution_contract import (
    GHAW_BUILDER_KIND,
    GHAW_BUILDER_WORKFLOW_FILE,
    allowed_owner_cs_for_kind,
)
from c1_worker import (
    DEFAULT_LEASE_S,
    DEFAULT_RESUME_LIMIT,
    RUNTIME_DB,
    build_client as _shared_build_client,
    main as _shared_main,
    tick as _shared_tick,
)

# ------------------------------------------------------------------ executor boundary
# These constants ARE this executor. They are deliberately not derived from
# `c1_worker`'s: an executor that inherited its kind set, its outbox or its dispatch
# target could never be isolated from the executor it inherited them from.
WORKER_ID = "go-runtime-host-ghaw-builder-worker"
OUTBOX_DB = "/var/lib/go-runtime-c1/outbox-ghaw-builder.db"
CLAIM_KINDS = (GHAW_BUILDER_KIND,)
# The cells this executor may claim for. Derived from the contract rather than listed
# here, so "which cells may a Builder run" has exactly one definition - the one the
# payload validator and the workflow gate also read. C13/C14 are not in it, and nothing
# in this file could add them without changing the contract.
CLAIM_OWNER_CS = allowed_owner_cs_for_kind(GHAW_BUILDER_KIND)
# The workflow this executor's dispatches land on. The same value the contract records on
# every GHAW_BUILDER_V1 request, and the only one this executor's client will send to.
WORKFLOW_FILE = GHAW_BUILDER_WORKFLOW_FILE


def build_client():
    """The transport, bound to the gh-aw Builder workflow and to nothing else.

    This is the whole of the transport half of U1: one argument, fixed by the executor.
    A GHAW_BUILDER_V1 request carries `workflow_file = c1-gh-aw-builder-v1.lock.yml`, so
    the client accepts it; the same client would refuse a request aimed at the Responses
    backend, and the Responses client refuses this one.
    """
    return _shared_build_client(workflow_file=WORKFLOW_FILE)


def builder_hooks(outbox):
    """The Builder-specific sealed-result hook the shared loop is parameterised with.

    Returned as a factory rather than as a plain hook because the hook needs the outbox the
    loop opens, and a Builder executor that ran without its completion hook would look
    perfectly healthy while every PR it produced quietly got no review at all.
    """
    return {"on_result_sealed": _sealed_hook}


def _sealed_hook(document, binding, outbox, runtime, *, client=None):
    from c1_builder_candidate import enqueue_review_when_the_builder_has_a_candidate
    return enqueue_review_when_the_builder_has_a_candidate(
        document, binding, outbox, runtime, client=client)


def builder_readiness(*, client=None) -> dict:
    """What this executor needs in order to COMPLETE a task, checked without side effects.

    The Builder's completion is no longer the end of the story: a sealed result that carries
    a candidate has to be turned into a review round, and that needs the read-only candidate
    vocabulary on the transport plus the module that composes it. Checking them here is what
    keeps that failure cheap - a worker that could not resolve a candidate would run the
    Builder (a paid execution), create a real Draft pull request, and only THEN discover
    that its task cannot be completed.

    No claim, no outbox, no POST, no model: building a client reads no token and opens no
    socket, so everything here is inert.
    """
    missing = []
    try:
        import c1_builder_candidate  # noqa: F401
        import c1_candidate_reads  # noqa: F401
    except ImportError as exc:
        missing.append(type(exc).__name__)
    transport = client if client is not None else build_client()
    for name in ("read_pull", "read_pull_files", "read_commit_tree", "read_tree"):
        if not callable(getattr(transport, name, None)):
            missing.append(name)
    if missing:
        return {"status": "REFUSED", "reason": "BUILDER_COMPLETION_CAPABILITY_MISSING",
                "detail": "missing=" + ",".join(missing)}
    return {"detail": "candidate_reads=4 builder_hook=present"}


def tick(runtime, outbox, client, *, worker_id=WORKER_ID, lease_s=DEFAULT_LEASE_S,
         clock=time.time, claim_kinds=CLAIM_KINDS, claim_owner_cs=CLAIM_OWNER_CS,
         owner_cursor=0, resume_limit=DEFAULT_RESUME_LIMIT, **kwargs) -> dict:
    """One bounded tick: resume what is in flight here, and only then claim new work.

    Identical to `c1_worker.tick` except for its defaults, which is the whole design: the
    loop is shared, the boundary is not. Both the resume leg and the claim leg are handed
    this executor's kind set, and the claim leg walks this executor's owner cells, so
    neither can reach the other executor's work.

    The completion hook is bound here so that every path into the loop - resident, `--once`
    and a test - gets it. `kwargs` is for the hooks a caller wants to override, which is how
    the crash and refusal cases are exercised offline.
    """
    hooks = builder_hooks(outbox)
    hooks.update(kwargs)
    return _shared_tick(runtime, outbox, client, worker_id=worker_id, lease_s=lease_s,
                        clock=clock, claim_kinds=claim_kinds,
                        claim_owner_cs=claim_owner_cs, owner_cursor=owner_cursor,
                        resume_limit=resume_limit, **hooks)


def main(argv=None, **kwargs) -> int:
    """The shared resident loop, with this executor's boundary filled in."""
    kwargs.setdefault("worker_id", WORKER_ID)
    kwargs.setdefault("claim_kinds", CLAIM_KINDS)
    kwargs.setdefault("claim_owner_cs", CLAIM_OWNER_CS)
    kwargs.setdefault("outbox_db", OUTBOX_DB)
    kwargs.setdefault("runtime_db", RUNTIME_DB)
    kwargs.setdefault("workflow_file", WORKFLOW_FILE)
    kwargs.setdefault("hooks_factory", builder_hooks)
    kwargs.setdefault("readiness", builder_readiness)
    return _shared_main(sys.argv if argv is None else argv, **kwargs)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
