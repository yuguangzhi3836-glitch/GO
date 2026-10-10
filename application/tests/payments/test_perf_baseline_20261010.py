from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from go_hotel.payments import perf_baseline_20261010 as perf


MODULE_PATH = Path(perf.__file__).resolve()


def run_module(*args: str, env: dict[str, str] | None = None, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(MODULE_PATH), *args]
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def test_parent_stdout_exposes_all_six_fixed_profiles_without_extra_noise():
    env = {**os.environ, "GO_PERF_BASELINE_TEST_MODE": "pass"}
    result = run_module(env=env, timeout=30.0)
    assert result.returncode == 0, result.stdout + result.stderr
    parsed = perf.parse_result_lines(result.stdout)
    assert [item["profile"] for item in parsed] == [profile.name for profile in perf.FIXED_PROFILES]
    assert all(item["status"] == "PASS" for item in parsed)
    assert result.stdout.splitlines() == [
        perf.RESULT_PREFIX + json.dumps(item, sort_keys=True) for item in parsed
    ]


def test_prepare_delay_is_excluded_from_measured_window():
    profile = perf.BenchmarkProfile("AUTHORIZATION_TEST", "AUTHORIZATION", 4)
    original_prepare = os.environ.get("GO_PERF_BASELINE_PREPARE_DELAY_MS")
    original_measure = os.environ.get("GO_PERF_BASELINE_MEASURE_DELAY_MS")
    os.environ["GO_PERF_BASELINE_PREPARE_DELAY_MS"] = "180"
    os.environ["GO_PERF_BASELINE_MEASURE_DELAY_MS"] = "20"
    try:
        execution = perf.run_profile(profile, perf.DemoBackend(), timeout_seconds=2.0)
    finally:
        if original_prepare is None:
            os.environ.pop("GO_PERF_BASELINE_PREPARE_DELAY_MS", None)
        else:
            os.environ["GO_PERF_BASELINE_PREPARE_DELAY_MS"] = original_prepare
        if original_measure is None:
            os.environ.pop("GO_PERF_BASELINE_MEASURE_DELAY_MS", None)
        else:
            os.environ["GO_PERF_BASELINE_MEASURE_DELAY_MS"] = original_measure
    assert execution.failure_count == 0
    assert execution.prepare_phase_ms >= 150.0
    assert execution.measured_wall_ms < 100.0


def test_prepare_failure_releases_waiters_without_barrier_timeout():
    profile = perf.BenchmarkProfile("AUTHORIZATION_TEST", "AUTHORIZATION", 12)
    original_fail = os.environ.get("GO_PERF_BASELINE_FAIL_PREPARE_WORKER")
    os.environ["GO_PERF_BASELINE_FAIL_PREPARE_WORKER"] = "0"
    started = time.perf_counter()
    try:
        execution = perf.run_profile(profile, perf.DemoBackend(), timeout_seconds=1.0)
    finally:
        if original_fail is None:
            os.environ.pop("GO_PERF_BASELINE_FAIL_PREPARE_WORKER", None)
        else:
            os.environ["GO_PERF_BASELINE_FAIL_PREPARE_WORKER"] = original_fail
    elapsed = time.perf_counter() - started
    assert execution.failure_count == 1
    assert execution.failures[0].phase == "prepare"
    assert elapsed < 0.6


def test_parent_does_not_leak_child_stderr_or_secret_lures():
    lure = "postgresql://user:pw@example/db SECRET=abc123 SELECT * FROM cards;"
    env = {
        **os.environ,
        "GO_PERF_BASELINE_TEST_MODE": "pass",
        "GO_PERF_BASELINE_CHILD_STDERR": lure,
    }
    result = run_module(env=env, timeout=30.0)
    assert result.returncode == 0, result.stdout + result.stderr
    assert lure not in result.stdout
    assert lure not in result.stderr


def test_source_evidence_validator_rejects_missing_empty_bad_and_mismatched_entries(tmp_path: Path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("alpha", encoding="utf-8")
    second.write_text("beta", encoding="utf-8")
    valid = [
        {"path": "first.txt", "sha256": perf.sha256_for_file(first), "size": first.stat().st_size},
        {"path": "second.txt", "sha256": perf.sha256_for_file(second), "size": second.stat().st_size},
    ]
    perf.validate_source_evidence(valid, tmp_path)
    with pytest.raises(ValueError, match="SOURCE_EVIDENCE_PATH_REQUIRED"):
        perf.validate_source_evidence([{"path": "", "sha256": valid[0]["sha256"], "size": 1}, valid[1]], tmp_path)
    with pytest.raises(ValueError, match="SOURCE_EVIDENCE_SHA256_INVALID"):
        perf.validate_source_evidence([{"path": "first.txt", "sha256": "bad", "size": 1}, valid[1]], tmp_path)
    with pytest.raises(ValueError, match="SOURCE_EVIDENCE_FILE_MISSING"):
        perf.validate_source_evidence([{"path": "missing.txt", "sha256": valid[0]["sha256"], "size": 1}, valid[1]], tmp_path)
    with pytest.raises(ValueError, match="SOURCE_EVIDENCE_SHA256_MISMATCH"):
        perf.validate_source_evidence([{"path": "first.txt", "sha256": "0" * 64, "size": 1}, valid[1]], tmp_path)


def test_source_file_hash_evidence_remains_valid_without_git_sha():
    evidence = perf.collect_source_evidence()
    payload = perf.build_result_payload(
        perf.FIXED_PROFILES[0],
        status="DEFERRED",
        source_evidence=evidence,
        database=None,
        execution=None,
        reason_code="DATABASE_UNAVAILABLE",
        source_git_sha=None,
    )
    assert payload["source_git_sha"] is None
    assert len(payload["source_evidence"]) >= 2
    assert any(item["path"].endswith("perf_baseline_20261010.py") for item in payload["source_evidence"])


def test_observe_database_runtime_uses_engine_connection_evidence_not_url_echo():
    class FakeResult:
        def scalar_one(self) -> str:
            return "180004"

    class FakeDialect:
        name = "postgresql"
        driver = "psycopg"
        server_version_info = (18, 4, 0)

    class FakeConnection:
        dialect = FakeDialect()

        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def exec_driver_sql(self, statement: str) -> FakeResult:
            assert statement == "SHOW server_version_num"
            return FakeResult()

    class FakeEngine:
        dialect = FakeDialect()

        def connect(self) -> FakeConnection:
            return FakeConnection()

    observed = perf.observe_database_runtime(FakeEngine())
    assert observed == {"dialect": "postgresql", "driver": "psycopg", "server_version_num": 180004}


def test_child_without_database_url_is_deferred_but_still_emits_auditable_result():
    env = {key: value for key, value in os.environ.items() if key not in {"GO_PERF_BASELINE_DATABASE_URL", "GO_PERF_BASELINE_TEST_MODE"}}
    result = run_module("--child", "AUTHORIZATION_20", env=env, timeout=30.0)
    assert result.returncode == 0, result.stdout + result.stderr
    parsed = perf.parse_result_lines(result.stdout)
    assert len(parsed) == 1
    assert parsed[0]["status"] == "DEFERRED"
    assert parsed[0]["reason_code"] == "DATABASE_UNAVAILABLE"
    assert len(parsed[0]["source_evidence"]) >= 2
