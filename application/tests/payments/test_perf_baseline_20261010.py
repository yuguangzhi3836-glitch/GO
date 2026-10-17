from __future__ import annotations

import json

import pytest

from go_hotel.payments.perf_baseline_20261010 import (
    audit_log_json,
    summarize_failure,
    validate_run,
)


pytestmark = pytest.mark.no_db


def _profile(operation: str, requested: int, *, replay_identity: str = "replay-1") -> dict[str, object]:
    profile = {
        "requested": requested,
        "completed": requested,
        "failure_count": 0,
        "failures": [],
        "latency_ms_samples": [11] * requested,
    }
    if operation == "REPLAY":
        profile["replay_identity"] = replay_identity
        profile["replay_identities"] = [replay_identity] * requested
    return profile


def _report() -> dict[str, object]:
    return {
        "worker_exit_code": 0,
        "worker_status": "PASS",
        "profiles": {
            "AUTHORIZATION": _profile("AUTHORIZATION", 20),
            "CAPTURE": _profile("CAPTURE", 20),
            "REPLAY": _profile("REPLAY", 20),
        },
    }


def test_validate_run_accepts_consistent_success_profile():
    assert validate_run(
        _report(),
        expected_profiles={"AUTHORIZATION": 20, "CAPTURE": 20, "REPLAY": 20},
    ) == []


def test_validate_run_rejects_single_worker_failure_even_when_status_claims_pass():
    report = _report()
    report["profiles"]["CAPTURE"]["failure_count"] = 1
    report["profiles"]["CAPTURE"]["failures"] = [
        summarize_failure(ValueError("PAYMENT_CAPTURE_DECLINED"), operation="CAPTURE", sequence=7)
    ]
    issues = validate_run(report, expected_profiles={"AUTHORIZATION": 20, "CAPTURE": 20, "REPLAY": 20})
    assert "CAPTURE: failures not empty" in issues


def test_validate_run_rejects_all_failed_profile():
    report = _report()
    report["profiles"]["AUTHORIZATION"] = {
        "requested": 20,
        "completed": 0,
        "failure_count": 20,
        "failures": [
            summarize_failure(RuntimeError("AUTHORIZATION_TIMEOUT"), operation="AUTHORIZATION", sequence=index)
            for index in range(20)
        ],
        "latency_ms_samples": [],
    }
    issues = validate_run(report, expected_profiles={"AUTHORIZATION": 20, "CAPTURE": 20, "REPLAY": 20})
    assert "AUTHORIZATION: completed mismatch" in issues
    assert "AUTHORIZATION: failures not empty" in issues
    assert "AUTHORIZATION: latency sample mismatch" in issues


def test_validate_run_rejects_incomplete_profile():
    report = _report()
    report["profiles"]["CAPTURE"]["completed"] = 19
    report["profiles"]["CAPTURE"]["latency_ms_samples"] = [9] * 19
    issues = validate_run(report, expected_profiles={"AUTHORIZATION": 20, "CAPTURE": 20, "REPLAY": 20})
    assert "CAPTURE: completed mismatch" in issues
    assert "CAPTURE: latency sample mismatch" in issues


def test_validate_run_rejects_replay_identity_mismatch():
    report = _report()
    report["profiles"]["REPLAY"]["replay_identities"] = ["replay-1"] * 19 + ["replay-2"]
    issues = validate_run(report, expected_profiles={"AUTHORIZATION": 20, "CAPTURE": 20, "REPLAY": 20})
    assert "REPLAY: replay identity mismatch" in issues


def test_validate_run_rejects_forged_pass_with_nonzero_exit_code():
    report = _report()
    report["worker_exit_code"] = 1
    report["profiles"]["AUTHORIZATION"]["latency_ms_samples"] = []
    issues = validate_run(report, expected_profiles={"AUTHORIZATION": 20, "CAPTURE": 20, "REPLAY": 20})
    assert "worker_exit_code non-zero" in issues
    assert "AUTHORIZATION: latency sample mismatch" in issues


def test_summarize_failure_and_audit_log_redact_sensitive_details():
    failure = summarize_failure(
        {"code": "CAPTURE_LEDGER_FAILURE", "message": "select * from payment where token='secret-token'"},
        operation="CAPTURE",
        sequence=3,
    )
    assert failure == {
        "operation": "CAPTURE",
        "sequence": 3,
        "error_type": "Error",
        "business_error_code": "CAPTURE_LEDGER_FAILURE",
    }

    payload = {
        "profiles": {"CAPTURE": {"failures": [failure]}},
        "sql": "select * from secrets",
        "url": "postgresql://user:pass@example.invalid/db",
        "nested": {"token": "secret-token", "safe": 3},
    }
    rendered = audit_log_json(payload)
    parsed = json.loads(rendered)
    assert parsed["sql"] == "<redacted>"
    assert parsed["url"] == "<redacted>"
    assert parsed["nested"]["token"] == "<redacted>"
    assert parsed["nested"]["safe"] == 3
    assert "secret-token" not in rendered
    assert "postgresql://" not in rendered
