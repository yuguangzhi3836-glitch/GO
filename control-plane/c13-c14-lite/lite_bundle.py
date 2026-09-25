"""Sealed C14 / C13 bundle records and their roots (task sections 14, 15, 20, 22).

One record type for C14 covers PASS_SCOPED / FAIL / BLOCKED / NOT_APPLICABLE; the
NOT_APPLICABLE variant is the only one allowed to carry the ``not_applicable``
stanza, and it is mandatory there. ``NOT_APPLICABLE`` is a recorded terminal state
with scope, basis and rule version — never a silent skip.

A bundle is *self-contained*: the root is computed over the record excluding its
own root field. GitHub run/artifact identity deliberately lives in the separate
execution record (``execution_record.py``) so that sealing is not circular.
"""
from __future__ import annotations

from datetime import datetime

from lite_canonical import digest, is_git_sha, is_sha256
from lite_errors import (
    AI_QUOTA_EXHAUSTED,
    BLOCKED,
    C13_VERDICTS,
    C14_VERDICTS,
    FAILURE_CLASSES,
    Reject,
)

SCHEMA_VERSION_C14 = "go.c13c14.lite.c14_bundle.v1"
SCHEMA_VERSION_C13 = "go.c13c14.lite.c13_bundle.v1"

C14_ROOT_FIELD = "C14_ROOT"
C13_ROOT_FIELD = "C13_ROOT"

REMEDIATION_STATUSES = ("OPEN", "PARTIAL", "CLOSED", "NOT_REQUIRED")
SEVERITIES = ("BLOCKER", "MAJOR", "MINOR", "INFO")

LEDGER_REFERENCE_FIELDS = ("round_id", "cell_id", "task_id")

C14_FIELDS = (
    "schema_version",
    "cell_id",
    "task_id",
    "issue_number",
    "ledger_reference",
    "candidate_sha",
    "application_tree",
    "nonce",
    "rule_review_scope_sha256",
    "applicable_rules",
    "applicable_rule_versions",
    "not_applicable",
    "github_run_id",
    "github_run_attempt",
    "workflow_ref",
    "workflow_sha",
    "ai_provider",
    "ai_model",
    "ai_execution_id",
    "principal_id",
    "review_execution_id",
    "prompt_sha256",
    "input_sha256",
    "opinion_sha256",
    "findings",
    "blocking_issues",
    "remediation_status",
    "verdict",
    "failure_class",
    "issued_at",
    "authorizes_any_action",
    C14_ROOT_FIELD,
)

C13_FIELDS = (
    "schema_version",
    "cell_id",
    "task_id",
    "issue_number",
    "ledger_reference",
    "candidate_sha",
    "application_tree",
    "nonce",
    "quality_test_scope_sha256",
    "c14_prerequisite",
    "machine_job",
    "github_run_id",
    "github_run_attempt",
    "workflow_ref",
    "workflow_sha",
    "ai_provider",
    "ai_model",
    "ai_execution_id",
    "principal_id",
    "review_execution_id",
    "prompt_sha256",
    "input_sha256",
    "opinion_sha256",
    "junit_sha256",
    "stdout_sha256",
    "manifest_sha256",
    "quality_findings",
    "remaining_risks",
    "verdict",
    "failure_class",
    "issued_at",
    "authorizes_any_action",
    C13_ROOT_FIELD,
)

PREREQUISITE_FIELDS = (
    "c14_root",
    "c14_verdict",
    "c14_candidate_sha",
    "c14_rule_scope_sha256",
    "c14_remediation_closed",
)

MACHINE_JOB_FIELDS = (
    "runner",
    "runner_os",
    "postgres_version",
    "docker_used",
    "test_inventory_sha256",
    "junit_sha256",
    "stdout_sha256",
    "manifest_sha256",
)

NOT_APPLICABLE_FIELDS = (
    "review_scope",
    "basis",
    "applicable_rule_set",
    "applicable_rule_version",
    "why_not_applicable",
)


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


def _check_common(record, *, fields, schema_version, expected_cell, root_field) -> None:
    if not isinstance(record, dict):
        raise Reject("bundle_not_an_object")
    if set(record) != set(fields):
        missing = sorted(set(fields) - set(record))
        extra = sorted(set(record) - set(fields))
        raise Reject("bundle_field_set_mismatch", f"missing={missing} extra={extra}")
    if record["schema_version"] != schema_version:
        raise Reject("bundle_schema_version_mismatch")
    if record["cell_id"] != expected_cell:
        raise Reject("cell_id_mismatch", f"expected={expected_cell} got={record['cell_id']}")
    if not _nonempty(record["task_id"]):
        raise Reject("bundle_task_id_missing")
    for field in ("candidate_sha", "application_tree", "workflow_sha"):
        if not is_git_sha(record[field]):
            raise Reject("bundle_git_sha_invalid", field)
    if not _nonempty(record["nonce"]) or len(record["nonce"]) < 16:
        raise Reject("bundle_nonce_weak_or_missing")
    for field in ("prompt_sha256", "input_sha256", "opinion_sha256"):
        if not is_sha256(record[field]):
            raise Reject("bundle_sha256_invalid", field)

    run_id = record["github_run_id"]
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
        raise Reject("bundle_github_run_id_invalid")
    attempt = record["github_run_attempt"]
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise Reject("bundle_github_run_attempt_invalid")
    for field in ("workflow_ref", "ai_provider", "ai_model", "ai_execution_id", "principal_id", "review_execution_id"):
        if not _nonempty(record[field]):
            raise Reject("bundle_identity_field_missing", field)

    if record["authorizes_any_action"] is not False:
        raise Reject("authorizes_any_action_must_be_false")

    failure_class = record["failure_class"]
    if failure_class is not None and failure_class not in FAILURE_CLASSES:
        raise Reject("bundle_failure_class_invalid")
    if record["verdict"] == "PASS_SCOPED" and failure_class is not None:
        raise Reject("bundle_pass_with_failure_class")
    if failure_class == AI_QUOTA_EXHAUSTED and record["verdict"] != BLOCKED:
        raise Reject("ai_quota_exhausted_must_be_blocked")

    issue_number = record["issue_number"]
    ledger_reference = record["ledger_reference"]
    if issue_number is None and ledger_reference is None:
        raise Reject("bundle_task_reference_missing")
    if issue_number is not None and (isinstance(issue_number, bool) or not isinstance(issue_number, int) or issue_number <= 0):
        raise Reject("bundle_issue_number_invalid")
    if ledger_reference is not None:
        if not isinstance(ledger_reference, dict) or set(ledger_reference) != set(LEDGER_REFERENCE_FIELDS):
            raise Reject("bundle_ledger_reference_invalid")
        if ledger_reference["cell_id"] != expected_cell:
            raise Reject("bundle_ledger_cell_mismatch")
        if ledger_reference["task_id"] != record["task_id"]:
            raise Reject("bundle_ledger_task_mismatch")

    _instant(record["issued_at"], "bundle_issued_at_invalid")
    if not is_sha256(record[root_field]):
        raise Reject("bundle_root_invalid", root_field)


def validate_c14(record) -> None:
    _check_common(
        record,
        fields=C14_FIELDS,
        schema_version=SCHEMA_VERSION_C14,
        expected_cell="C14",
        root_field=C14_ROOT_FIELD,
    )
    if record["verdict"] not in C14_VERDICTS:
        raise Reject("c14_verdict_invalid")
    if not is_sha256(record["rule_review_scope_sha256"]):
        raise Reject("c14_rule_scope_sha256_invalid")
    if not isinstance(record["applicable_rules"], list) or not all(_nonempty(x) for x in record["applicable_rules"]):
        raise Reject("c14_applicable_rules_invalid")
    if not isinstance(record["applicable_rule_versions"], dict) or set(record["applicable_rule_versions"]) != set(record["applicable_rules"]):
        raise Reject("c14_applicable_rule_versions_mismatch")
    for name, version in record["applicable_rule_versions"].items():
        if not _nonempty(version):
            raise Reject("c14_applicable_rule_version_missing", name)
    if record["remediation_status"] not in REMEDIATION_STATUSES:
        raise Reject("c14_remediation_status_invalid")
    if not isinstance(record["findings"], list):
        raise Reject("c14_findings_invalid")
    for finding in record["findings"]:
        if not isinstance(finding, dict) or set(finding) != {"id", "severity", "statement"}:
            raise Reject("c14_finding_shape_invalid")
        if finding["severity"] not in SEVERITIES:
            raise Reject("c14_finding_severity_invalid")
        if not _nonempty(finding["id"]) or not _nonempty(finding["statement"]):
            raise Reject("c14_finding_incomplete")
    if not isinstance(record["blocking_issues"], list) or not all(_nonempty(x) for x in record["blocking_issues"]):
        raise Reject("c14_blocking_issues_invalid")

    not_applicable = record["not_applicable"]
    if record["verdict"] == "NOT_APPLICABLE":
        if not isinstance(not_applicable, dict) or set(not_applicable) != set(NOT_APPLICABLE_FIELDS):
            raise Reject("c14_not_applicable_record_incomplete")
        if not _nonempty(not_applicable["review_scope"]):
            raise Reject("c14_not_applicable_without_scope")
        if not _nonempty(not_applicable["basis"]):
            raise Reject("c14_not_applicable_without_basis")
        for field in ("applicable_rule_set", "applicable_rule_version", "why_not_applicable"):
            if not _nonempty(not_applicable[field]):
                raise Reject("c14_not_applicable_missing_field", field)
    elif not_applicable is not None:
        raise Reject("c14_not_applicable_stanza_on_non_na_verdict")

    if record["verdict"] == "PASS_SCOPED":
        if record["blocking_issues"]:
            raise Reject("c14_pass_with_blocking_issues")
        if record["remediation_status"] not in ("CLOSED", "NOT_REQUIRED"):
            raise Reject("c14_pass_without_remediation_closure")

    # A non-pass verdict must carry EVIDENCE, and it must never be made to impersonate a
    # provider failure. Two different things reach this point:
    #
    #   * a provider / quota / transport failure genuinely has a failure_class, and no AI
    #     opinion was ever produced;
    #   * the AI reviewed normally and returned FAIL or BLOCKED, in which case there is no
    #     provider failure to name - what it must supply is its own reasons.
    #
    # The previous rule demanded a failure_class for both, which made a model-authored
    # BLOCKED unsealable: the run died at the seal and, because the opinion had not been
    # published yet, the only copy of the reviewer's reasoning was destroyed with it
    # (CCV1-145B D-4).
    if record["verdict"] == "BLOCKED" and record["failure_class"] is None:
        # The AI itself blocked: it has to say what blocked it.
        if not record["blocking_issues"]:
            raise Reject("c14_model_blocked_without_blocking_issues")
    if record["verdict"] == "FAIL":
        # A FAIL with no evidence is an assertion, not a verdict. Blocking evidence is either
        # an explicit blocking issue or a finding serious enough to justify a failure.
        blocking_findings = [f for f in record["findings"] if f["severity"] in ("BLOCKER", "MAJOR")]
        if not record["blocking_issues"] and not blocking_findings:
            raise Reject("c14_fail_without_findings_or_blocking_issues")


def validate_c13(record) -> None:
    _check_common(
        record,
        fields=C13_FIELDS,
        schema_version=SCHEMA_VERSION_C13,
        expected_cell="C13",
        root_field=C13_ROOT_FIELD,
    )
    if record["verdict"] not in C13_VERDICTS:
        raise Reject("c13_verdict_invalid")
    if not is_sha256(record["quality_test_scope_sha256"]):
        raise Reject("c13_quality_test_scope_sha256_invalid")
    for field in ("junit_sha256", "stdout_sha256", "manifest_sha256"):
        if not is_sha256(record[field]):
            raise Reject("c13_machine_digest_invalid", field)

    prerequisite = record["c14_prerequisite"]
    if not isinstance(prerequisite, dict) or set(prerequisite) != set(PREREQUISITE_FIELDS):
        raise Reject("c13_c14_prerequisite_missing")
    # Shape only. Whether the recorded C14 state is *admissible* is decided by the
    # prerequisite gate (BLOCK for FAIL/BLOCKED, not a structural rejection), so
    # that "C13 attempted on top of a failed C14" reads as BLOCKED, not as tamper.
    if prerequisite["c14_verdict"] not in C14_VERDICTS:
        raise Reject("c13_c14_prerequisite_verdict_invalid")
    if not isinstance(prerequisite["c14_remediation_closed"], bool):
        raise Reject("c13_c14_prerequisite_remediation_flag_invalid")
    if not is_sha256(prerequisite["c14_root"]):
        raise Reject("c13_c14_prerequisite_root_invalid")
    if not is_git_sha(prerequisite["c14_candidate_sha"]):
        raise Reject("c13_c14_prerequisite_candidate_invalid")
    if not is_sha256(prerequisite["c14_rule_scope_sha256"]):
        raise Reject("c13_c14_prerequisite_scope_invalid")
    if prerequisite["c14_candidate_sha"] != record["candidate_sha"]:
        raise Reject("c14_candidate_a_c13_candidate_b")

    machine_job = record["machine_job"]
    if not isinstance(machine_job, dict) or set(machine_job) != set(MACHINE_JOB_FIELDS):
        raise Reject("c13_machine_job_incomplete")
    if not _nonempty(machine_job["runner"]) or not _nonempty(machine_job["runner_os"]):
        raise Reject("c13_machine_job_runner_missing")
    if not _nonempty(machine_job["postgres_version"]):
        raise Reject("c13_machine_job_postgres_missing")
    if type(machine_job["docker_used"]) is not bool:
        raise Reject("c13_machine_job_docker_flag_invalid")
    for field in ("test_inventory_sha256", "junit_sha256", "stdout_sha256", "manifest_sha256"):
        if not is_sha256(machine_job[field]):
            raise Reject("c13_machine_job_digest_invalid", field)
    if machine_job["junit_sha256"] != record["junit_sha256"]:
        raise Reject("c13_junit_digest_mismatch")
    if machine_job["stdout_sha256"] != record["stdout_sha256"]:
        raise Reject("c13_stdout_digest_mismatch")
    if machine_job["manifest_sha256"] != record["manifest_sha256"]:
        raise Reject("c13_manifest_digest_mismatch")

    if not isinstance(record["quality_findings"], list):
        raise Reject("c13_quality_findings_invalid")
    if not isinstance(record["remaining_risks"], list) or not all(_nonempty(x) for x in record["remaining_risks"]):
        raise Reject("c13_remaining_risks_invalid")


def validate(record) -> None:
    """Dispatch on ``cell_id``; a C13 record claiming C14 (or vice versa) is rejected."""
    if not isinstance(record, dict):
        raise Reject("bundle_not_an_object")
    if record.get("cell_id") == "C14":
        validate_c14(record)
    elif record.get("cell_id") == "C13":
        validate_c13(record)
    else:
        raise Reject("cell_id_mismatch", "cell_id must be C13 or C14")


def compute_root(record, root_field: str) -> str:
    body = {key: value for key, value in record.items() if key != root_field}
    return digest(body)


def seal(record) -> dict:
    """Validate, attach the root, validate again, and return the sealed record."""
    root_field = C14_ROOT_FIELD if record.get("cell_id") == "C14" else C13_ROOT_FIELD
    record[root_field] = "0" * 64
    validate(record)
    record[root_field] = compute_root(record, root_field)
    validate(record)
    return record


def verify_root(record) -> None:
    """Recompute the root over the received bytes. Never trust a self-declared root."""
    root_field = C14_ROOT_FIELD if record.get("cell_id") == "C14" else C13_ROOT_FIELD
    validate(record)
    if record[root_field] != compute_root(record, root_field):
        raise Reject("root_recompute_mismatch", root_field)
