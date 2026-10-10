from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import create_engine, text


RESULT_PREFIX = "RESULT_PREFIX "
DEFAULT_TIMEOUT_SECONDS = 10.0
SOURCE_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REPO_ROOT = Path(__file__).resolve().parents[4]
TEST_PATH = REPO_ROOT / "application" / "tests" / "payments" / "test_perf_baseline_20261010.py"


@dataclass(frozen=True)
class BenchmarkProfile:
    name: str
    operation: str
    concurrency: int


@dataclass(frozen=True)
class SourceEvidence:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class WorkerFailure:
    worker_index: int
    phase: str
    error_type: str


@dataclass(frozen=True)
class WorkerOutcome:
    worker_index: int
    operation_id: str
    replay: bool


@dataclass(frozen=True)
class ExecutionArtifacts:
    prepare_phase_ms: float
    measured_wall_ms: float
    measured_cpu_ms: float
    throughput_per_second: float
    failure_count: int
    outcomes: tuple[WorkerOutcome, ...]
    failures: tuple[WorkerFailure, ...]


FIXED_PROFILES = (
    BenchmarkProfile("AUTHORIZATION_20", "AUTHORIZATION", 20),
    BenchmarkProfile("AUTHORIZATION_100", "AUTHORIZATION", 100),
    BenchmarkProfile("CAPTURE_20", "CAPTURE", 20),
    BenchmarkProfile("CAPTURE_100", "CAPTURE", 100),
    BenchmarkProfile("REPLAY_20", "REPLAY", 20),
    BenchmarkProfile("REPLAY_100", "REPLAY", 100),
)


class Backend(Protocol):
    def runtime_evidence(self) -> dict[str, Any]:
        ...

    def setup_profile(self, profile: BenchmarkProfile) -> None:
        ...

    def cleanup_profile(self, profile: BenchmarkProfile) -> None:
        ...

    def prepare(self, profile: BenchmarkProfile, worker_index: int) -> dict[str, Any]:
        ...

    def measure(
        self,
        profile: BenchmarkProfile,
        worker_index: int,
        prepared: dict[str, Any],
    ) -> dict[str, Any]:
        ...


class DemoBackend:
    def __init__(self) -> None:
        self.prepare_delay_ms = int(os.getenv("GO_PERF_BASELINE_PREPARE_DELAY_MS", "0"))
        self.measure_delay_ms = int(os.getenv("GO_PERF_BASELINE_MEASURE_DELAY_MS", "0"))
        self.fail_prepare_worker = _parse_optional_int(os.getenv("GO_PERF_BASELINE_FAIL_PREPARE_WORKER"))
        self.shared_replay_id = f"demo-replay-{uuid4().hex[:12]}"
        self.stderr_lure = os.getenv("GO_PERF_BASELINE_CHILD_STDERR", "")

    def runtime_evidence(self) -> dict[str, Any]:
        return {"dialect": "postgresql", "driver": "psycopg", "server_version_num": 180004}

    def setup_profile(self, profile: BenchmarkProfile) -> None:
        if self.stderr_lure:
            sys.stderr.write(self.stderr_lure)
            sys.stderr.flush()

    def cleanup_profile(self, profile: BenchmarkProfile) -> None:
        return None

    def prepare(self, profile: BenchmarkProfile, worker_index: int) -> dict[str, Any]:
        if self.prepare_delay_ms:
            time.sleep(self.prepare_delay_ms / 1000.0)
        if self.fail_prepare_worker == worker_index:
            raise RuntimeError("DEMO_PREPARE_FAILURE")
        auth_id = f"demo-auth-{profile.name.lower()}-{worker_index}"
        if profile.operation == "REPLAY":
            return {"request_key": "shared-replay-key", "authorization_id": auth_id}
        return {"request_key": f"{profile.name.lower()}-{worker_index}", "authorization_id": auth_id}

    def measure(
        self,
        profile: BenchmarkProfile,
        worker_index: int,
        prepared: dict[str, Any],
    ) -> dict[str, Any]:
        if self.measure_delay_ms:
            time.sleep(self.measure_delay_ms / 1000.0)
        if profile.operation == "REPLAY":
            return {"operation_id": self.shared_replay_id, "replay": worker_index > 0}
        return {
            "operation_id": f"{profile.operation.lower()}-{prepared['request_key']}",
            "replay": False,
        }


class DatabaseBackend:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, future=True)
        self.schema_name = f"perf_baseline_{uuid4().hex[:12]}"
        self._prepared = False

    def runtime_evidence(self) -> dict[str, Any]:
        return observe_database_runtime(self.engine)

    def setup_profile(self, profile: BenchmarkProfile) -> None:
        if self._prepared:
            return
        with self.engine.begin() as conn:
            conn.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{self.schema_name}"')
            conn.exec_driver_sql(
                f'''
                CREATE TABLE IF NOT EXISTS "{self.schema_name}".operations (
                    op_id TEXT PRIMARY KEY,
                    request_key TEXT NOT NULL UNIQUE,
                    operation TEXT NOT NULL,
                    amount_minor INTEGER NOT NULL,
                    authorization_key TEXT,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
        self._prepared = True

    def cleanup_profile(self, profile: BenchmarkProfile) -> None:
        if not self._prepared:
            return
        with self.engine.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{self.schema_name}" CASCADE')
        self._prepared = False

    def prepare(self, profile: BenchmarkProfile, worker_index: int) -> dict[str, Any]:
        request_key = f"{profile.name.lower()}-{worker_index}"
        auth_id = f"auth-{uuid4().hex}"
        if profile.operation == "CAPTURE":
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        f'''
                        INSERT INTO "{self.schema_name}".operations
                            (op_id, request_key, operation, amount_minor, authorization_key)
                        VALUES (:op_id, :request_key, :operation, :amount_minor, :authorization_key)
                        '''
                    ),
                    {
                        "op_id": auth_id,
                        "request_key": f"auth-{request_key}",
                        "operation": "AUTHORIZATION",
                        "amount_minor": 100,
                        "authorization_key": auth_id,
                    },
                )
        elif profile.operation == "REPLAY":
            request_key = "shared-replay-key"
        return {"request_key": request_key, "authorization_id": auth_id}

    def measure(
        self,
        profile: BenchmarkProfile,
        worker_index: int,
        prepared: dict[str, Any],
    ) -> dict[str, Any]:
        op_id = f"{profile.operation.lower()}-{uuid4().hex}"
        with self.engine.begin() as conn:
            inserted = conn.execute(
                text(
                    f'''
                    INSERT INTO "{self.schema_name}".operations
                        (op_id, request_key, operation, amount_minor, authorization_key)
                    VALUES (:op_id, :request_key, :operation, :amount_minor, :authorization_key)
                    ON CONFLICT (request_key) DO NOTHING
                    RETURNING op_id
                    '''
                ),
                {
                    "op_id": op_id,
                    "request_key": prepared["request_key"],
                    "operation": profile.operation,
                    "amount_minor": 100,
                    "authorization_key": prepared["authorization_id"],
                },
            ).scalar_one_or_none()
            if inserted is not None:
                return {"operation_id": inserted, "replay": False}
            existing = conn.execute(
                text(
                    f'''
                    SELECT op_id
                    FROM "{self.schema_name}".operations
                    WHERE request_key = :request_key
                    '''
                ),
                {"request_key": prepared["request_key"]},
            ).scalar_one()
        return {"operation_id": existing, "replay": True}


def _parse_optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def sha256_for_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_source_evidence(paths: list[Path] | None = None) -> list[dict[str, Any]]:
    selected = paths or [Path(__file__).resolve(), TEST_PATH]
    evidence: list[dict[str, Any]] = []
    for item in selected:
        resolved = item.resolve()
        relative = resolved.relative_to(REPO_ROOT).as_posix()
        evidence.append(
            {
                "path": relative,
                "sha256": sha256_for_file(resolved),
                "size": resolved.stat().st_size,
            }
        )
    validate_source_evidence(evidence, REPO_ROOT)
    return evidence


def validate_source_evidence(entries: list[dict[str, Any]], root: Path) -> None:
    if len(entries) < 2:
        raise ValueError("SOURCE_EVIDENCE_MINIMUM")
    for item in entries:
        relative_path = item.get("path")
        sha256 = item.get("sha256")
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ValueError("SOURCE_EVIDENCE_PATH_REQUIRED")
        if not isinstance(sha256, str) or not SOURCE_SHA256_RE.fullmatch(sha256):
            raise ValueError("SOURCE_EVIDENCE_SHA256_INVALID")
        resolved = (root / relative_path).resolve()
        if not resolved.is_file():
            raise ValueError("SOURCE_EVIDENCE_FILE_MISSING")
        if resolved.stat().st_size <= 0:
            raise ValueError("SOURCE_EVIDENCE_FILE_EMPTY")
        if sha256_for_file(resolved) != sha256:
            raise ValueError("SOURCE_EVIDENCE_SHA256_MISMATCH")


def observe_database_runtime(engine: Any) -> dict[str, Any]:
    with engine.connect() as conn:
        dialect_name = getattr(conn.dialect, "name", None) or getattr(engine.dialect, "name", None)
        driver_name = getattr(conn.dialect, "driver", None) or getattr(engine.dialect, "driver", None)
        version_value = _read_server_version_num(conn)
    if dialect_name is None or driver_name is None or version_value is None:
        raise ValueError("DATABASE_RUNTIME_EVIDENCE_INCOMPLETE")
    return {
        "dialect": str(dialect_name),
        "driver": str(driver_name),
        "server_version_num": int(version_value),
    }


def _read_server_version_num(conn: Any) -> int | None:
    try:
        value = conn.exec_driver_sql("SHOW server_version_num").scalar_one()
        return int(value)
    except Exception:
        pass
    version_info = getattr(conn.dialect, "server_version_info", None)
    if version_info:
        return _version_tuple_to_num(version_info)
    return None


def _version_tuple_to_num(version_info: tuple[int, ...]) -> int:
    parts = list(version_info[:3]) + [0, 0, 0]
    major, minor, patch = parts[:3]
    return int(major) * 10000 + int(minor) * 100 + int(patch)


def _execution_timeout_seconds() -> float:
    return float(os.getenv("GO_PERF_BASELINE_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))


def run_profile(profile: BenchmarkProfile, backend: Backend, timeout_seconds: float) -> ExecutionArtifacts:
    start_gate = threading.Event()
    abort_gate = threading.Event()
    condition = threading.Condition()
    prepared_count = 0
    failures: list[WorkerFailure] = []
    outcomes: list[WorkerOutcome] = []
    prepare_started = time.perf_counter()
    measure_started: float | None = None
    measured_cpu_start: float | None = None
    measured_cpu_end: float | None = None
    measure_finished: float | None = None

    def worker(worker_index: int) -> None:
        nonlocal prepared_count
        phase = "prepare"
        try:
            prepared = backend.prepare(profile, worker_index)
            phase = "wait"
            with condition:
                prepared_count += 1
                condition.notify_all()
            start_gate.wait()
            if abort_gate.is_set():
                return
            phase = "measure"
            measured = backend.measure(profile, worker_index, prepared)
            with condition:
                outcomes.append(
                    WorkerOutcome(
                        worker_index=worker_index,
                        operation_id=str(measured["operation_id"]),
                        replay=bool(measured["replay"]),
                    )
                )
                condition.notify_all()
        except Exception as exc:
            abort_gate.set()
            start_gate.set()
            with condition:
                failures.append(
                    WorkerFailure(
                        worker_index=worker_index,
                        phase=phase,
                        error_type=type(exc).__name__,
                    )
                )
                condition.notify_all()

    backend.setup_profile(profile)
    threads = [threading.Thread(target=worker, args=(index,), daemon=True) for index in range(profile.concurrency)]
    try:
        for thread in threads:
            thread.start()
        deadline = time.perf_counter() + timeout_seconds
        with condition:
            while prepared_count < profile.concurrency and not failures:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    abort_gate.set()
                    start_gate.set()
                    failures.append(WorkerFailure(worker_index=-1, phase="prepare", error_type="TimeoutError"))
                    break
                condition.wait(timeout=remaining)
        if not failures:
            measure_started = time.perf_counter()
            measured_cpu_start = time.process_time()
            start_gate.set()
        for thread in threads:
            remaining = max(0.0, deadline - time.perf_counter())
            thread.join(timeout=remaining)
        alive = [thread for thread in threads if thread.is_alive()]
        if alive:
            abort_gate.set()
            failures.append(WorkerFailure(worker_index=-1, phase="measure", error_type="TimeoutError"))
        measure_finished = time.perf_counter() if measure_started is not None else None
        measured_cpu_end = time.process_time() if measured_cpu_start is not None else None
    finally:
        start_gate.set()
        backend.cleanup_profile(profile)

    prepare_phase_ms = ((measure_started or time.perf_counter()) - prepare_started) * 1000.0
    measured_wall_ms = 0.0 if measure_started is None or measure_finished is None else (measure_finished - measure_started) * 1000.0
    measured_cpu_ms = 0.0 if measured_cpu_start is None or measured_cpu_end is None else (measured_cpu_end - measured_cpu_start) * 1000.0
    throughput = 0.0 if measured_wall_ms <= 0 else (len(outcomes) / (measured_wall_ms / 1000.0))
    return ExecutionArtifacts(
        prepare_phase_ms=prepare_phase_ms,
        measured_wall_ms=measured_wall_ms,
        measured_cpu_ms=measured_cpu_ms,
        throughput_per_second=throughput,
        failure_count=len(failures),
        outcomes=tuple(sorted(outcomes, key=lambda item: item.worker_index)),
        failures=tuple(sorted(failures, key=lambda item: item.worker_index)),
    )


def emit_result(payload: dict[str, Any]) -> None:
    sys.stdout.write(RESULT_PREFIX + json.dumps(payload, sort_keys=True) + "\n")
    sys.stdout.flush()


def build_result_payload(
    profile: BenchmarkProfile,
    status: str,
    source_evidence: list[dict[str, Any]],
    database: dict[str, Any] | None,
    execution: ExecutionArtifacts | None,
    reason_code: str | None = None,
    source_git_sha: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "profile": profile.name,
        "operation": profile.operation,
        "concurrency": profile.concurrency,
        "status": status,
        "source_evidence": source_evidence,
        "database": database,
        "source_git_sha": source_git_sha,
    }
    if reason_code is not None:
        payload["reason_code"] = reason_code
    if execution is not None:
        payload["prepare_phase_ms"] = round(execution.prepare_phase_ms, 3)
        payload["measured_wall_ms"] = round(execution.measured_wall_ms, 3)
        payload["measured_cpu_ms"] = round(execution.measured_cpu_ms, 3)
        payload["throughput_per_second"] = round(execution.throughput_per_second, 3)
        payload["failure_count"] = execution.failure_count
        payload["replay_count"] = sum(1 for item in execution.outcomes if item.replay)
        payload["outcomes"] = [
            {
                "worker_index": item.worker_index,
                "operation_id": item.operation_id,
                "replay": item.replay,
            }
            for item in execution.outcomes
        ]
        payload["failures"] = [
            {
                "worker_index": item.worker_index,
                "phase": item.phase,
                "error_type": item.error_type,
            }
            for item in execution.failures
        ]
    return payload


def run_child(profile_name: str) -> int:
    profile = next(item for item in FIXED_PROFILES if item.name == profile_name)
    source_evidence = collect_source_evidence()
    database_url = os.getenv("GO_PERF_BASELINE_DATABASE_URL")
    test_mode = os.getenv("GO_PERF_BASELINE_TEST_MODE")
    if test_mode:
        backend: Backend = DemoBackend()
    elif not database_url:
        emit_result(
            build_result_payload(
                profile,
                "DEFERRED",
                source_evidence=source_evidence,
                database=None,
                execution=None,
                reason_code="DATABASE_UNAVAILABLE",
            )
        )
        return 0
    else:
        backend = DatabaseBackend(database_url)
    try:
        database = backend.runtime_evidence()
        execution = run_profile(profile, backend, _execution_timeout_seconds())
        status = "PASS" if execution.failure_count == 0 else "FAIL"
        reason_code = None if status == "PASS" else "PROFILE_EXECUTION_FAILED"
        emit_result(build_result_payload(profile, status, source_evidence, database, execution, reason_code))
        return 0 if status == "PASS" else 1
    except Exception as exc:
        emit_result(
            build_result_payload(
                profile,
                "FAIL",
                source_evidence=source_evidence,
                database=None,
                execution=None,
                reason_code=type(exc).__name__,
            )
        )
        return 1


def _run_parent_child(profile: BenchmarkProfile) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--child", profile.name],
        capture_output=True,
        text=True,
        timeout=_execution_timeout_seconds(),
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    parsed = parse_result_lines(result.stdout)
    if parsed:
        return parsed[-1]
    source_evidence = collect_source_evidence()
    return build_result_payload(
        profile,
        "FAIL",
        source_evidence=source_evidence,
        database=None,
        execution=None,
        reason_code="RESULT_PREFIX_MISSING",
    )


def parse_result_lines(stdout: str) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for raw_line in stdout.splitlines():
        if not raw_line.startswith(RESULT_PREFIX):
            continue
        parsed.append(json.loads(raw_line[len(RESULT_PREFIX):]))
    return parsed


def run_parent() -> int:
    exit_code = 0
    for profile in FIXED_PROFILES:
        try:
            payload = _run_parent_child(profile)
        except subprocess.TimeoutExpired:
            payload = build_result_payload(
                profile,
                "FAIL",
                source_evidence=collect_source_evidence(),
                database=None,
                execution=None,
                reason_code="SUBPROCESS_TIMEOUT",
            )
        emit_result(payload)
        if payload["status"] == "FAIL":
            exit_code = 1
    return exit_code


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Concurrent payment perf baseline runner.")
    parser.add_argument("--child", choices=[profile.name for profile in FIXED_PROFILES])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.child:
        return run_child(args.child)
    return run_parent()


if __name__ == "__main__":
    raise SystemExit(main())
