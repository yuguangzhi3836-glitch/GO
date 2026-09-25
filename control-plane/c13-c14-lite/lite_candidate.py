"""Frozen candidate contract (task section 12).

A candidate is frozen *before* any C13/C14 execution starts. The workflow checks
out ``candidate_commit_sha`` and never a branch head; every opinion must carry the
same ``candidate_sha``; the recorded artifact digest must equal the recomputed one.

Hardcoding is prevented structurally: nothing in this module contains a literal
candidate SHA or PR number. Binding is always checked against values supplied by
the caller (dispatch input), so a bundle cannot invent its own candidate.
"""
from __future__ import annotations

from datetime import datetime, timezone

from lite_canonical import is_git_sha, is_sha256
from lite_errors import Reject

SCHEMA_VERSION = "go.c13c14.lite.frozen_candidate.v1"

FIELDS = (
    "schema_version",
    "repository",
    "candidate_commit_sha",
    "application_tree",
    "cell_id",
    "task_id",
    "issue_number",
    "ledger_reference",
    "request_id",
    "nonce",
    "issued_at",
    "expires_at",
    "workflow_identity",
    "workflow_sha",
    "review_scope_sha256",
    "prompt_sha256",
)

LEDGER_REFERENCE_FIELDS = ("round_id", "cell_id", "task_id")

ALLOWED_CELLS = ("C13", "C14")


def _nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _instant(value, reason: str) -> datetime:
    if not _nonempty(value):
        raise Reject(reason, "timestamp missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Reject(reason, "unparseable timestamp") from exc
    if parsed.tzinfo is None:
        raise Reject(reason, "timezone required")
    return parsed


def build(
    *,
    repository: str,
    candidate_commit_sha: str,
    application_tree: str,
    cell_id: str,
    task_id: str,
    request_id: str,
    nonce: str,
    issued_at: str,
    expires_at: str,
    workflow_identity: str,
    workflow_sha: str,
    review_scope_sha256: str,
    prompt_sha256: str,
    issue_number=None,
    ledger_reference=None,
) -> dict:
    """Assemble a frozen candidate contract. Validation is separate and mandatory."""
    contract = {
        "schema_version": SCHEMA_VERSION,
        "repository": repository,
        "candidate_commit_sha": candidate_commit_sha,
        "application_tree": application_tree,
        "cell_id": cell_id,
        "task_id": task_id,
        "issue_number": issue_number,
        "ledger_reference": ledger_reference,
        "request_id": request_id,
        "nonce": nonce,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "workflow_identity": workflow_identity,
        "workflow_sha": workflow_sha,
        "review_scope_sha256": review_scope_sha256,
        "prompt_sha256": prompt_sha256,
    }
    validate(contract)
    return contract


def validate(contract, *, now=None) -> None:
    """Structural + freshness validation. Raises ``Reject`` on any violation."""
    if not isinstance(contract, dict):
        raise Reject("candidate_not_an_object")
    if set(contract) != set(FIELDS):
        missing = sorted(set(FIELDS) - set(contract))
        extra = sorted(set(contract) - set(FIELDS))
        raise Reject("candidate_field_set_mismatch", f"missing={missing} extra={extra}")
    if contract["schema_version"] != SCHEMA_VERSION:
        raise Reject("candidate_schema_version_mismatch")
    if not _nonempty(contract["repository"]):
        raise Reject("candidate_repository_missing")
    for field in ("candidate_commit_sha", "application_tree", "workflow_sha"):
        if not is_git_sha(contract[field]):
            raise Reject("candidate_git_sha_invalid", field)
    if contract["cell_id"] not in ALLOWED_CELLS:
        raise Reject("candidate_cell_id_invalid")
    if not _nonempty(contract["task_id"]):
        raise Reject("candidate_task_id_missing")
    if not _nonempty(contract["request_id"]):
        raise Reject("candidate_request_id_missing")
    if not _nonempty(contract["workflow_identity"]):
        raise Reject("candidate_workflow_identity_missing")
    if not _nonempty(contract["nonce"]) or len(contract["nonce"]) < 16:
        raise Reject("candidate_nonce_weak_or_missing")
    for field in ("review_scope_sha256", "prompt_sha256"):
        if not is_sha256(contract[field]):
            raise Reject("candidate_sha256_invalid", field)

    issue_number = contract["issue_number"]
    ledger_reference = contract["ledger_reference"]
    if issue_number is None and ledger_reference is None:
        raise Reject("candidate_task_reference_missing")
    if issue_number is not None and (isinstance(issue_number, bool) or not isinstance(issue_number, int) or issue_number <= 0):
        raise Reject("candidate_issue_number_invalid")
    if ledger_reference is not None:
        if not isinstance(ledger_reference, dict) or set(ledger_reference) != set(LEDGER_REFERENCE_FIELDS):
            raise Reject("candidate_ledger_reference_invalid")
        if not _nonempty(ledger_reference["round_id"]):
            raise Reject("candidate_ledger_round_id_missing")
        if ledger_reference["cell_id"] != contract["cell_id"]:
            raise Reject("candidate_ledger_cell_mismatch")
        if ledger_reference["task_id"] != contract["task_id"]:
            raise Reject("candidate_ledger_task_mismatch")

    issued = _instant(contract["issued_at"], "candidate_issued_at_invalid")
    expires = _instant(contract["expires_at"], "candidate_expires_at_invalid")
    if expires <= issued:
        raise Reject("candidate_expiry_not_after_issue")
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        raise Reject("candidate_reference_time_naive")
    if reference > expires:
        raise Reject("candidate_request_expired")


def check_binding(
    contract,
    *,
    expected_candidate_sha: str,
    expected_application_tree: str,
    expected_cell_id: str,
    expected_task_id: str,
    expected_issue_number=None,
    expected_request_id=None,
    now=None,
) -> None:
    """The contract must match the dispatch input exactly (no self-declared candidate)."""
    validate(contract, now=now)
    if contract["candidate_commit_sha"] != expected_candidate_sha:
        raise Reject("candidate_commit_mismatch")
    if contract["application_tree"] != expected_application_tree:
        raise Reject("candidate_application_tree_mismatch")
    if contract["cell_id"] != expected_cell_id:
        raise Reject("cell_id_mismatch")
    if contract["task_id"] != expected_task_id:
        raise Reject("task_id_mismatch")
    if expected_issue_number is not None and contract["issue_number"] != expected_issue_number:
        raise Reject("issue_number_mismatch")
    if expected_request_id is not None and contract["request_id"] != expected_request_id:
        raise Reject("request_id_mismatch")
    ledger_reference = contract["ledger_reference"]
    if ledger_reference is not None:
        if ledger_reference["task_id"] != expected_task_id:
            raise Reject("ledger_task_binding_mismatch")
        if ledger_reference["cell_id"] != expected_cell_id:
            raise Reject("ledger_cell_binding_mismatch")
