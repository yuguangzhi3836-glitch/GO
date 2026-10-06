"""Admit the fixed #533 correction only after reading original durable review facts."""
import json

import c1_c13_supplement_contract as fixed
from c1_execution_contract import (C13_REVIEW_KIND, C14_REVIEW_KIND, Refused,
    canonical, sha256_hex, validate_review_task_payload, validate_review_result)


def plan_from_outbox(parsed, outbox, *, enabled):
    if parsed != {"issue_number": fixed.ISSUE, "candidate_pr_number": fixed.PR,
                  "candidate_sha": fixed.CANDIDATE}:
        raise Refused("C13_SUPPLEMENT_ISSUE_NOT_AUTHORIZED")
    envelopes = {}
    for cell, task, kind, run, root, verdict in (
        ("C13", fixed.C13_RUNTIME, C13_REVIEW_KIND, fixed.C13_RUN, fixed.C13_ROOT, "BLOCKED"),
        ("C14", fixed.C14_RUNTIME, C14_REVIEW_KIND, fixed.C14_RUN, fixed.C14_ROOT, "PASS_SCOPED"),
    ):
        prior = outbox.terminal_for_task(task)
        if prior is None:
            raise Refused("C13_SUPPLEMENT_ORIGINAL_RESULT_MISSING:" + cell)
        doc = prior["result"]
        if sha256_hex(prior["result_json"]) != prior["result_sha256"]:
            raise Refused("C13_SUPPLEMENT_OUTBOX_DIGEST_MISMATCH")
        if json.loads(prior["result_json"]) != doc:
            raise Refused("C13_SUPPLEMENT_OUTBOX_DOCUMENT_MISMATCH")
        validate_review_result(doc, runtime_task_id=task, attempt=1,
                               execution_request_id_=prior["execution_request_id"], task_kind=kind)
        if (prior["attempt"] != 1 or doc["github_run_id"] != run
                or doc["github_run_attempt"] != 1 or doc["review_verdict"] != verdict
                or doc["sealed_bundle_root"] != root or doc["accepted"] is not True
                or doc["candidate_sha"] != fixed.CANDIDATE
                or doc["application_tree"] != fixed.APPLICATION_TREE
                or doc["issue_number"] != fixed.ISSUE or doc["ledger_round_id"] != fixed.ROUND):
            raise Refused("C13_SUPPLEMENT_ORIGINAL_RESULT_MISMATCH:" + cell)
        envelopes[cell] = doc
    request = outbox.stored_request(fixed.C13_RUNTIME, 1)
    if (not request or request.get("task_kind") != C13_REVIEW_KIND
            or request.get("execution_request_id") != envelopes["C13"]["execution_request_id"]):
        raise Refused("C13_SUPPLEMENT_ORIGINAL_REQUEST_MISSING")
    payload = validate_review_task_payload(request["payload"], allowed_owner_cs=("C13",))
    if payload["review_request_id"] != envelopes["C13"]["review_request_id"]:
        raise Refused("C13_SUPPLEMENT_ORIGINAL_REQUEST_BINDING_MISMATCH")
    if "supplement" in payload:
        raise Refused("C13_SUPPLEMENT_CANNOT_CHAIN")
    # Preserve the model, task/round ids, request and prerequisite; only the
    # authorised machine scope and explicit correction provenance are new.
    payload.update(machine_inventory=fixed.INVENTORY, supplement=dict(fixed.ENVELOPE))
    payload = validate_review_task_payload(payload, allowed_owner_cs=("C13",))
    return {"action": "SHADOW_PLAN" if enabled else "DISABLED", "enabled": enabled,
            "enqueued": False, **parsed, "application_tree": fixed.APPLICATION_TREE,
            "ledger_round_id": fixed.ROUND, "machine_inventory": fixed.INVENTORY,
            "machine_inventory_source": fixed.PROFILE, "payload_sha256": sha256_hex(canonical(payload)),
            "would_enqueue": {"owner_c": "C13", "kind": C13_REVIEW_KIND, "payload": payload,
                              "idempotency_key": fixed.IDEMPOTENCY_KEY, "max_attempts": 1}}


def installed_plan(parsed, *, enabled):
    # Read the existing review outbox without creating, migrating or updating it.
    from c1_dispatch_outbox import DispatchOutbox
    try:
        outbox = DispatchOutbox("/var/lib/go-runtime-c1/outbox-c13c14-review.db", read_only=True)
        try:
            return plan_from_outbox(parsed, outbox, enabled=enabled)
        finally:
            outbox.close()
    except Refused:
        raise
    except Exception:
        raise Refused("C13_SUPPLEMENT_ORIGINAL_OUTBOX_UNAVAILABLE") from None
