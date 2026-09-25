"""Execution record: how one execution of a cell task is identified (task section 10).

Cell identity and task identity come from the Owner's 14-Cell model and the
existing ledger. This record only adds the *execution* identity:

    C14 -> task/issue -> GitHub run N -> AI execution X

When the run ends, the C14 cell still exists; the next candidate is a new task on
the same cell. Nothing here creates a second registry.
"""
from __future__ import annotations

from lite_canonical import is_git_sha, is_sha256
from lite_errors import Reject

SCHEMA_VERSION = "go.c13c14.lite.execution_record.v1"

FIELDS = (
    "schema_version",
    "cell_id",
    "task_id",
    "issue_number",
    "ledger_reference",
    "candidate_sha",
    "application_tree",
    "github_run_id",
    "github_run_attempt",
    "workflow_ref",
    "workflow_sha",
    "ai_execution_id",
    "principal_id",
    "review_execution_id",
    "verdict",
    "failure_class",
    "root_hash",
    "artifact",
    "evidence_path",
    "issued_at",
    "authorizes_any_action",
)

ARTIFACT_FIELDS = ("name", "id", "digest")


def build(bundle, *, artifact: dict, evidence_path: str) -> dict:
    """Derive the ledger-facing execution record from a sealed bundle."""
    if not isinstance(bundle, dict):
        raise Reject("bundle_not_an_object")
    root_field = "C14_ROOT" if bundle.get("cell_id") == "C14" else "C13_ROOT"
    record = {
        "schema_version": SCHEMA_VERSION,
        "cell_id": bundle["cell_id"],
        "task_id": bundle["task_id"],
        "issue_number": bundle["issue_number"],
        "ledger_reference": bundle["ledger_reference"],
        "candidate_sha": bundle["candidate_sha"],
        "application_tree": bundle["application_tree"],
        "github_run_id": bundle["github_run_id"],
        "github_run_attempt": bundle["github_run_attempt"],
        "workflow_ref": bundle["workflow_ref"],
        "workflow_sha": bundle["workflow_sha"],
        "ai_execution_id": bundle["ai_execution_id"],
        "principal_id": bundle["principal_id"],
        "review_execution_id": bundle["review_execution_id"],
        "verdict": bundle["verdict"],
        "failure_class": bundle["failure_class"],
        "root_hash": bundle[root_field],
        "artifact": artifact,
        "evidence_path": evidence_path,
        "issued_at": bundle["issued_at"],
        "authorizes_any_action": False,
    }
    validate(record)
    return record


def validate(record) -> None:
    if not isinstance(record, dict) or set(record) != set(FIELDS):
        raise Reject("execution_record_field_set_mismatch")
    if record["schema_version"] != SCHEMA_VERSION:
        raise Reject("execution_record_schema_version_mismatch")
    if record["cell_id"] not in ("C13", "C14"):
        raise Reject("cell_id_mismatch")
    if not is_git_sha(record["candidate_sha"]) or not is_git_sha(record["application_tree"]):
        raise Reject("execution_record_git_sha_invalid")
    if not is_sha256(record["root_hash"]):
        raise Reject("execution_record_root_invalid")
    if not isinstance(record["artifact"], dict) or set(record["artifact"]) != set(ARTIFACT_FIELDS):
        raise Reject("execution_record_artifact_invalid")
    if not isinstance(record["artifact"]["digest"], str) or not record["artifact"]["digest"].startswith("sha256:"):
        raise Reject("execution_record_artifact_digest_invalid")
    if record["authorizes_any_action"] is not False:
        raise Reject("authorizes_any_action_must_be_false")
