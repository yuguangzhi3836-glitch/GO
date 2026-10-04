#!/usr/bin/env python3
"""One-shot delivery of ONE C13/C14 review round into the Persistent Runtime.

This is an ADMISSION, not a scheduler. Whether a candidate enters a review round is a
decision a human makes, and this script is where that decision is recorded: it is run by
hand, for one explicitly named candidate, and it exits. There is no resident loop, no
watcher over open pull requests, and no rule that every Builder PR is reviewed - all three
would spend paid review on work nobody asked to review.

It enqueues the C14 half and ONLY the C14 half. The C13 half is not this script's business:
it is created by the review executor from a sealed, admissible C14, in that order, and
enqueueing both here would make "C13 follows C14" a caller's promise instead of a property
of the system.

Usage
-----
    deliver_review_round.py --candidate-sha <40hex> --application-tree <40hex> \
        --issue-number <n> --round-id <id> --c14-task-id <id> --c13-task-id <id> \
        [--machine-inventory <path>] [--ai-model <name>] [--request-id <id>] [--dry-run]

The Lite identity (`request_id`, `ledger_round_id`, the two task ids) is REQUIRED and is
never invented here: it is the review identity the existing Lite chain binds the bundles
to, and a round whose ids do not match the ones the ledger/issue already uses would seal a
bundle nothing can verify. `--request-id` defaults to a deterministic value derived from
the candidate and the round id, because it only has to be stable, not chosen.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

from c1_execution_contract import (
    C14_REVIEW_KIND,
    REVIEW_OWNER_C,
    build_review_task_payload,
    canonical,
    task_idempotency_key,
)

RUNTIME_SOURCE_DIR = os.environ.get("C13C14_RUNTIME_SOURCE_DIR", "/opt/go/c1-c14-runtime")
RUNTIME_DB = os.environ.get("C13C14_RUNTIME_DB", "/var/lib/go-c-runtime/runtime.db")
# One attempt, for the same reason the other classes use one: a second attempt of the same
# review is a second paid AI execution, and owning that decision is an operator's.
MAX_ATTEMPTS = 1


def deterministic_request_id(candidate_sha: str, round_id: str) -> str:
    """The review request id, derived so it is stable and cannot be chosen arbitrarily."""
    return "REV-" + hashlib.sha256(("%s|%s" % (candidate_sha, round_id)).encode("utf-8")
                                   ).hexdigest()[:24]


def build(argv=None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--application-tree", required=True)
    parser.add_argument("--issue-number", required=True, type=int)
    parser.add_argument("--round-id", required=True)
    parser.add_argument("--c14-task-id", required=True)
    parser.add_argument("--c13-task-id", required=True)
    parser.add_argument("--machine-inventory", default=None)
    parser.add_argument("--ai-model", default=None)
    parser.add_argument("--request-id", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    request_id = args.request_id or deterministic_request_id(args.candidate_sha, args.round_id)
    payload = build_review_task_payload(
        cell_id=REVIEW_OWNER_C[C14_REVIEW_KIND],
        external_task_id=args.c14_task_id,
        candidate_sha=args.candidate_sha,
        application_tree=args.application_tree,
        issue_number=args.issue_number,
        review_request_id=request_id,
        ledger_round_id=args.round_id,
        c14_task_id=args.c14_task_id,
        c13_task_id=args.c13_task_id,
        machine_inventory=args.machine_inventory,
        ai_model=args.ai_model,
        allowed_owner_cs=(REVIEW_OWNER_C[C14_REVIEW_KIND],),
    )
    return {"action": "C14_REVIEW_ROUND", "payload": payload, "dry_run": args.dry_run,
            "idempotency_key": task_idempotency_key(
                C14_REVIEW_KIND, payload["cell_id"], payload["external_task_id"])}


def deliver(plan) -> dict:
    if RUNTIME_SOURCE_DIR not in sys.path:
        sys.path.insert(0, RUNTIME_SOURCE_DIR)
    import runtime  # noqa: E402 - resolved from the installed Runtime directory

    rt = runtime.Runtime(RUNTIME_DB)
    task_id = rt.enqueue(plan["payload"]["cell_id"], C14_REVIEW_KIND, plan["payload"],
                         idempotency_key=plan["idempotency_key"], max_attempts=MAX_ATTEMPTS)
    return dict(plan, runtime_task_id=task_id)


def main(argv=None) -> int:
    plan = build(argv)
    if plan["dry_run"]:
        print(canonical({k: v for k, v in plan.items() if k != "dry_run"}))
        return 0
    print(canonical(deliver(plan)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
