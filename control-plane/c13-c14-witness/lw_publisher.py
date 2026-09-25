"""Controlled publisher: the only component allowed to touch a ledger task.

The AI reviewer never holds a write scope. The chain is:

    reviewer -> sealed bundle -> read-only verification -> controlled publisher -> ledger / Issue

This module is the last hop. It writes **only** the cell/task/candidate the round
was dispatched for, it never touches another cell, it never rewrites a historical
task, and it never overwrites a newer first-seen result with an older one.

Posting to a GitHub Issue is deliberately *not* implemented here: the module
returns the exact comment payload it would post, so the write scope stays separate
from the reviewer and a human can see the payload before it is posted.
"""
from __future__ import annotations

import copy

import lw_paths

lw_paths.install()

import lite_ledger_binding as lb  # noqa: E402
from lite_errors import Reject  # noqa: E402

SCHEMA_VERSION = "go.c13c14.witness.writeback.v1"

SAFETY_CHECKS = (
    "expected_cell_equals_bundle_cell",
    "expected_task_equals_bundle_task",
    "expected_candidate_equals_bundle_candidate",
    "expected_ledger_reference_equals_bundle_reference",
    "task_is_not_replaced_or_stale",
    "no_cross_cell_write",
    "no_historical_task_rewrite",
    "no_duplicate_conflicting_result",
    "no_older_result_overwriting_newer_first_seen",
)

GATE_BY_VERDICT = lb.VERDICT_TO_GATE_STATUS


def _cell(ledger, cell_id):
    for cell in ledger.get("cells", []):
        if cell.get("cell_id") == cell_id:
            return cell
    raise Reject("ledger_cell_missing", cell_id)


def _bound_records(task):
    """Records this task already carries, newest first by issued_at."""
    records = []
    for item in task.get("writeback_records", []) or []:
        records.append(item)
    return sorted(records, key=lambda entry: entry.get("issued_at", ""), reverse=True)


def check_safety(*, ledger, records, expectation) -> list:
    """Return the refusal reasons. Empty means the writeback is allowed."""
    refusals = []
    cell_id = expectation["cell_id"]
    task_id = expectation["task_id"]
    candidate_sha = expectation["candidate_sha"]

    role = "c14" if cell_id == "C14" else "c13"
    if role not in records:
        # The expectation names a cell this plan holds no record for. That is the
        # refusal itself (a cross-cell attempt, or an incomplete plan) - never a crash.
        return ["record_for_expected_cell_missing", "no_cross_cell_write"]
    record = records[role]
    if record["cell_id"] != cell_id:
        refusals.append("expected_cell_equals_bundle_cell")
    if record["task_id"] != task_id:
        refusals.append("expected_task_equals_bundle_task")
    if record["candidate_sha"] != candidate_sha:
        refusals.append("expected_candidate_equals_bundle_candidate")
    if expectation.get("ledger_reference") is not None and \
            record.get("ledger_reference") != expectation["ledger_reference"]:
        refusals.append("expected_ledger_reference_equals_bundle_reference")

    cell = _cell(ledger, cell_id)
    task = cell.get("task") or {}
    if task.get("id") != task_id:
        refusals.append("task_is_not_replaced_or_stale")

    for existing in _bound_records(task):
        if existing.get("candidate_sha") != candidate_sha:
            continue
        same_result = (existing.get("verdict") == record["verdict"]
                       and existing.get("root_hash") == record["root_hash"]
                       and existing.get("github_run_id") == record["github_run_id"])
        if same_result and existing.get("issued_at", "") > record["issued_at"]:
            refusals.append("no_older_result_overwriting_newer_first_seen")
        elif same_result:
            # An identical repeat is a no-op, not a conflict: nothing to write.
            refusals.append("duplicate_identical_result")
        else:
            # A different result for the same candidate is a real conflict.
            refusals.append("no_duplicate_conflicting_result")

    if cell_id not in ("C13", "C14"):
        refusals.append("no_cross_cell_write")
    return refusals


def plan(*, ledger, records, evidence_root, evidence, expectation, completed_at,
         issue_comment=True) -> dict:
    """Return the writeback plan: refusals, the new ledger, and the Issue payload.

    ``records`` maps ``"c14"`` / ``"c13"`` to execution records; ``evidence`` maps
    the same keys to ``(relative_path, raw_bytes)`` for the sealed bundles.
    """
    refusals = check_safety(ledger=ledger, records=records, expectation=expectation)
    for role in records:
        if role not in evidence:
            raise Reject("evidence_missing_for_recorded_cell", role)
    result = {
        "schema_version": SCHEMA_VERSION,
        "allowed": not refusals,
        "refusals": refusals,
        "idempotent": bool(refusals) and all(item == "duplicate_identical_result" for item in refusals),
        "safety_checks": list(SAFETY_CHECKS),
        "issue_comment": None,
        "new_ledger": None,
        "applied": False,
        "authorizes_any_action": False,
    }
    if refusals:
        return result

    new_ledger = copy.deepcopy(ledger)
    root = evidence_root
    entries = {}
    for role, record in records.items():
        relative_path, raw = evidence[role]
        path = (root / relative_path)
        if not path.is_file() or path.read_bytes() != raw:
            raise Reject("ledger_evidence_not_materialised", relative_path)
        entries[role] = lb.evidence_entry(relative_path, raw, record["task_id"])

    cell_id = expectation["cell_id"]
    cell = _cell(new_ledger, cell_id)
    task = cell["task"]
    role = "c14" if cell_id == "C14" else "c13"
    record = records[role]
    task.setdefault("evidence", []).append(entries[role])
    task.setdefault("writeback_records", []).append({
        "cell_id": record["cell_id"],
        "task_id": record["task_id"],
        "candidate_sha": record["candidate_sha"],
        "github_run_id": record["github_run_id"],
        "ai_execution_id": record["ai_execution_id"],
        "verdict": record["verdict"],
        "root_hash": record["root_hash"],
        "artifact": record["artifact"],
        "issued_at": record["issued_at"],
        "authorizes_any_action": False,
    })
    gates = task.setdefault("gates", {})
    # Assign rather than setdefault: the ledger template carries these gates as HOLD,
    # and a later gate cannot pass while its predecessor is still HOLD.
    gates["tests"] = lb.gate_record("PASS_SCOPED", [entries[role]["path"]],
                                    record["review_execution_id"], completed_at)
    gates["evidence"] = lb.gate_record("PASS_SCOPED", [entries[role]["path"]],
                                       record["review_execution_id"], completed_at)
    if role == "c14":
        gates["c14"] = lb.gate_record(record["verdict"], [entries[role]["path"]],
                                      record["review_execution_id"], completed_at)
        task["status"] = "RUNNING"
        task["completion"] = {"percent": 50,
                              "definition": task.get("completion", {}).get(
                                  "definition", "C14 closed; C13 acceptance pending")}
        task["execution_evidence_refs"] = [entries[role]["path"]]
    else:
        # The C13 cell's own c14 gate records the prerequisite it consumed, so the
        # C14 bundle is referenced from this cell too (same file, its own task binding).
        if "c14" not in records or "c14" not in evidence:
            raise Reject("c13_writeback_requires_the_c14_record")
        c14_relative, c14_raw = evidence["c14"]
        c14_path = root / c14_relative
        if not c14_path.is_file() or c14_path.read_bytes() != c14_raw:
            raise Reject("ledger_evidence_not_materialised", c14_relative)
        c14_entry = lb.evidence_entry(c14_relative, c14_raw, record["task_id"])
        task["evidence"].append(c14_entry)
        gates["c14"] = lb.gate_record(records["c14"]["verdict"], [c14_entry["path"]],
                                      records["c14"]["review_execution_id"], completed_at)
        gates["c13"] = lb.gate_record(record["verdict"], [entries[role]["path"]],
                                      record["review_execution_id"], completed_at)
        task["status"] = "DONE_SCOPED"
        task["completion"] = {"percent": 100,
                              "definition": task.get("completion", {}).get(
                                  "definition", "C13 and C14 both bound to the same candidate")}
        task["execution_evidence_refs"] = [c14_entry["path"], entries[role]["path"]]
        cell["executable_gap"] = False
        cell["next_task"] = None

    result["new_ledger"] = new_ledger
    result["applied"] = True
    if issue_comment:
        result["issue_comment"] = {
            "issue_number": expectation.get("issue_number"),
            "body_lines": [
                f"cell_id: {record['cell_id']}",
                f"task_id: {record['task_id']}",
                f"candidate_sha: {record['candidate_sha']}",
                f"github_run_id: {record['github_run_id']}",
                f"ai_execution_id: {record['ai_execution_id']}",
                f"verdict: {record['verdict']}",
                f"{'C14_ROOT' if role == 'c14' else 'C13_ROOT'}: {record['root_hash']}",
                f"artifact: {record['artifact']['name']} ({record['artifact']['digest']})",
                f"review_timestamp: {record['issued_at']}",
                "authorizes_any_action: false",
            ],
            "posted": False,
            "note": "prepared only: the reviewer holds no issue write scope",
        }
    return result


def validate_with_repository_validator(ledger, evidence_root) -> dict:
    """The writeback must still satisfy the repository's own ledger validator."""
    return lb.validate_with_repository_validator(ledger, evidence_root)
