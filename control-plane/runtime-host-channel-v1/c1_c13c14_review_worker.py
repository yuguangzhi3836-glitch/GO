"""The C13/C14 review executor: the third and last executor on this channel.

Why this is a third component and not a mode of `c1_ghaw_builder_worker`
-----------------------------------------------------------------------
Both are gh-aw executions, and that is where the resemblance stops:

    Builder            inspect / edit / test -> a Draft PR -> a result file
    C13/C14 review     read-only review      -> a sealed bundle -> no Draft PR

Different input (a frozen candidate and a round, not an objective and a scope), different
acceptance rule (a sealed Lite bundle and its root, not "any non-empty model output"),
different workflow per cell, and a different result protocol. Folding either into the
other would mean one executor claiming work whose result it cannot even validate. So this
is a third executor - and, deliberately, still ONE of them:

    kinds       C14_REVIEW_V1 (owner C14), C13_REVIEW_V1 (owner C13)
    outbox      /var/lib/go-runtime-c1/outbox-c13c14-review.db
    worker id   go-runtime-host-c13c14-review-worker
    dispatches  c14-rule-compliance.yml, c13-quality-acceptance.yml (the EXISTING ones)
    executes    the existing Lite review workflows, unchanged in what they review

One worker for two cells, for the same reason the Builder is one worker for twelve: a cell
is not an execution mechanism, and a second worker would be a second copy of the
exactly-once model - the one thing on this channel that must never fork. What is per-cell
is the OWNER, and the owner comes from the task.

C14 FIRST, then C13
-------------------
`claim()` returns whatever the Runtime hands out, so "C14 before C13" cannot be a
statement about the queue order. It is enforced where it is actually decided: a C13 task
exists only because a C14 execution created it, in `enqueue_c13_when_c14_admits`, and
never because a caller enqueued one. The claim scan simply asks C14 first so that a
runnable C14 is never queued behind an unrelated C13.

One review in flight, globally
------------------------------
The shared loop resumes what is unfinished before it claims anything, and claims at most
ONE task per tick. That is the whole concurrency policy, and it is the one this channel
already had.

What this file deliberately does NOT do
---------------------------------------
* No new Runtime kernel, no new scheduler, no new registry, no new queue service, no
  second outbox, no second worker. One of each, and the cell is carried by the task.
* No review logic. The verdicts, the rule sources, the prerequisite gate, the sealed
  bundle and its root all live in `control-plane/c13-c14-lite/**` and are CALLED from
  `c1_c13c14_review`, never restated.
* No second ambiguous-dispatch state machine: the dispatch leg is `DispatchOutbox`'s, so
  `dispatches_sent <= 1` holds here for the same reason it holds for the Builder.
* No admission logic of its own, and no automatic review of every Builder PR. A round is
  admitted by an Owner's `C14 · REVIEW · ...` issue, or - for the normal path - by the
  Builder's OWN completion: `c1_builder_candidate` enqueues the C14 half of a candidate the
  Builder run itself produced, and only a run that created a Draft pull request has one.
  This worker reviews what the Runtime hands it and never decides what enters a round.

Usage is `c1_worker`'s, unchanged:

    c1_c13c14_review_worker.py                 # resident: tick, sleep, repeat
    c1_c13c14_review_worker.py --once          # one tick, then exit
    c1_c13c14_review_worker.py --check         # report readiness only; claims nothing
"""
from __future__ import annotations

import sys
import time

from c1_c13c14_review import (
    make_result_validator,
    review_artifact_loader,
    review_readiness,
)
from c1_execution_contract import (
    C13_REVIEW_KIND,
    C14_REVIEW_KIND,
    REVIEW_WORKFLOW_FILE,
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
# These constants ARE this executor, and they are deliberately not inherited from either
# other one: an executor that shared its kinds, its outbox or its dispatch targets could
# never be isolated from the executor it shared them with.
WORKER_ID = "go-runtime-host-c13c14-review-worker"
OUTBOX_DB = "/var/lib/go-runtime-c1/outbox-c13c14-review.db"
CLAIM_KINDS = (C14_REVIEW_KIND, C13_REVIEW_KIND)
# C14 first. Both cells are served by this one worker, and asking C14 first is what keeps a
# runnable C14 from waiting behind an unrelated C13. It cannot invert the round order: a
# C13 task only exists once a C14 execution created it.
CLAIM_OWNER_CS = (allowed_owner_cs_for_kind(C14_REVIEW_KIND)[0],
                  allowed_owner_cs_for_kind(C13_REVIEW_KIND)[0])
# The two EXISTING Lite workflows, one per cell. This executor adds transport identity to
# them; it does not add a workflow.
WORKFLOW_FILES = tuple(REVIEW_WORKFLOW_FILE[kind] for kind in CLAIM_KINDS)


def build_client():
    """The transport, bound to exactly the two review workflows and to nothing else."""
    return _shared_build_client(workflow_files=WORKFLOW_FILES)


def review_hooks(outbox):
    """The three review-specific bindings the shared loop is parameterised with.

    Returned together so a caller cannot wire up the validator and forget the loader (or
    the sealed-result hook), which would be a runtime failure discovered only on the first
    real round.
    """
    return {
        "result_validator": make_result_validator(outbox),
        "artifact_loader": review_artifact_loader(outbox),
        "on_result_sealed": _sealed_hook,
    }


def _sealed_hook(document, binding, outbox, runtime, *, client=None):
    from c1_c13c14_review import enqueue_c13_when_c14_admits
    return enqueue_c13_when_c14_admits(document, binding, outbox, runtime, client=client)


def tick(runtime, outbox, client, *, worker_id=WORKER_ID, lease_s=DEFAULT_LEASE_S,
         clock=time.time, claim_kinds=CLAIM_KINDS, claim_owner_cs=CLAIM_OWNER_CS,
         owner_cursor=0, resume_limit=DEFAULT_RESUME_LIMIT,
         confirm_lease=True, **kwargs) -> dict:
    """One bounded tick, with this executor's boundary and its review hooks filled in.

    `owner_cursor` is pinned to 0 on purpose: this worker always asks C14 first. The
    shared loop rotates the cursor to be fair between cells, which is right for a Builder
    serving twelve equivalent cells and wrong here, where the two cells are ordered.

    `confirm_lease` is ON here, and only here, and the reason is a real round: a review
    execution dispatched for a task the Runtime had already recovered and escalated is
    money spent on a verdict nothing can record. A review round is admitted by hand with
    `max_attempts=1`, so there is no later attempt that could adopt that execution - the
    result would be stranded. The Builder keeps the default, where the run really does
    happen, `runtime_told=False` records that honestly, and the settlement path bounds a
    repeat. Turning this on for a class whose delivery IS its result is the whole point.
    """
    hooks = review_hooks(outbox)
    hooks.update(kwargs)
    return _shared_tick(runtime, outbox, client, worker_id=worker_id, lease_s=lease_s,
                        clock=clock, claim_kinds=claim_kinds,
                        claim_owner_cs=claim_owner_cs, owner_cursor=0,
                        resume_limit=resume_limit, confirm_lease=confirm_lease, **hooks)


def main(argv=None, **kwargs) -> int:
    """The shared resident loop, with this executor's boundary filled in.

    `hooks_factory` is what binds the review validator, the review artifact loader and the
    C14 -> C13 sealed hook to the outbox the loop opens - so the review rules cannot be
    left unwired by running this worker the ordinary way.
    """
    kwargs.setdefault("worker_id", WORKER_ID)
    kwargs.setdefault("claim_kinds", CLAIM_KINDS)
    kwargs.setdefault("claim_owner_cs", CLAIM_OWNER_CS)
    kwargs.setdefault("outbox_db", OUTBOX_DB)
    kwargs.setdefault("runtime_db", RUNTIME_DB)
    kwargs.setdefault("workflow_files", WORKFLOW_FILES)
    kwargs.setdefault("hooks_factory", review_hooks)
    kwargs.setdefault("confirm_lease", True)
    kwargs.setdefault("readiness", review_readiness)
    return _shared_main(sys.argv if argv is None else argv, **kwargs)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
