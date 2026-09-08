from datetime import datetime, timezone
import pytest

from go_hotel.control.hk_control_protocol import build_envelope, verify_envelope

SECRET = b"s" * 32
SHA = "a" * 64
NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


def env(**overrides):
    value = build_envelope(
        task_id="task-001", task_type="HYATT_10_REAL_E2E",
        authority="STAGING_CONTROLLED_EXECUTE", candidate_sha256=SHA,
        payload={"candidate":"depth10"}, node_id="hk-staging-01",
        nonce="abcdefghijklmnop", issued_at="2026-09-08T12:00:00Z", secret=SECRET,
    )
    value.update(overrides)
    return value


def test_valid_signed_task_verifies():
    got = verify_envelope(env(), secret=SECRET, expected_node_id="hk-staging-01", now=NOW)
    assert got.task_type == "HYATT_10_REAL_E2E"


def test_arbitrary_task_is_rejected():
    value = env(task_type="SHELL")
    with pytest.raises(ValueError, match="NOT_ALLOWLISTED"):
        verify_envelope(value, secret=SECRET, expected_node_id="hk-staging-01", now=NOW)


def test_production_environment_is_rejected():
    value = env(environment="PRODUCTION")
    with pytest.raises(ValueError, match="ENVIRONMENT_NOT_ALLOWED"):
        verify_envelope(value, secret=SECRET, expected_node_id="hk-staging-01", now=NOW)


def test_payload_tamper_is_rejected():
    value = env(); value["payload"] = {"candidate":"tampered"}
    with pytest.raises(ValueError, match="TASK_SHA_MISMATCH"):
        verify_envelope(value, secret=SECRET, expected_node_id="hk-staging-01", now=NOW)


def test_signature_tamper_is_rejected():
    value = env(); value["signature"] = "0" * 64
    with pytest.raises(ValueError, match="SIGNATURE_INVALID"):
        verify_envelope(value, secret=SECRET, expected_node_id="hk-staging-01", now=NOW)


def test_wrong_node_is_rejected():
    with pytest.raises(ValueError, match="NODE_MISMATCH"):
        verify_envelope(env(), secret=SECRET, expected_node_id="other-node", now=NOW)


def test_readonly_cannot_run_mutating_acceptance():
    value = build_envelope(
        task_id="task-002", task_type="HYATT_10_REAL_E2E", authority="STAGING_READONLY",
        candidate_sha256=SHA, payload={}, node_id="hk-staging-01",
        nonce="qrstuvwxyzABCDEF", issued_at="2026-09-08T12:00:00Z", secret=SECRET,
    )
    with pytest.raises(ValueError, match="READONLY_AUTHORITY_INSUFFICIENT"):
        verify_envelope(value, secret=SECRET, expected_node_id="hk-staging-01", now=NOW)
