"""C11 bounded perf baseline with real money entrypoints and guarded PG diagnostics."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from go_hotel.payments.perf_baseline_20261010 import (
    PROFILE_CASES,
    RESULT_PREFIX,
    audit_log_json,
    expected_profiles,
    parse_result_line,
    profile_key,
    redact_payload,
    summarize_failure,
    validate_run,
)

APPLICATION_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = APPLICATION_ROOT.parent
OWNER = "perf-baseline-owner"
PAYEE_ID = "perf-baseline-airline"
EXPECTED_PROFILES = expected_profiles()


def _git_head() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _configured_pg_url() -> tuple[str | None, str | None]:
    direct_sources = (
        ("POSTGRES_TEST_DATABASE_URL", os.getenv("POSTGRES_TEST_DATABASE_URL")),
        ("GO_TEST_DATABASE_URL", os.getenv("GO_TEST_DATABASE_URL")),
    )
    for name, value in direct_sources:
        if not value:
            continue
        if make_url(value).get_backend_name() != "postgresql":
            raise AssertionError(f"{name} must point to PostgreSQL, got {make_url(value).get_backend_name()}")
        return name, value
    parts = {key: os.getenv(key) for key in ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE")}
    if any(parts.values()):
        if not all(parts.values()):
            raise AssertionError("PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE must be complete")
        return (
            "PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE",
            "postgresql+psycopg://"
            f"{parts['PGUSER']}:{parts['PGPASSWORD']}@{parts['PGHOST']}:{parts['PGPORT']}/{parts['PGDATABASE']}",
        )
    return None, None


def _schema_url(base_url: str, schema: str) -> str:
    url = make_url(base_url)
    query = dict(url.query)
    query["options"] = f"-csearch_path={schema}"
    return url.set(query=query).render_as_string(hide_password=False)


def _percentile_ms(values_ns: list[int], percentile: float) -> float:
    if not values_ns:
        return 0.0
    ordered = sorted(values_ns)
    rank = max(0, math.ceil(len(ordered) * percentile) - 1)
    return round(ordered[rank] / 1_000_000, 2)


def _emit_result(report: dict[str, object], exit_code: int) -> int:
    payload = dict(report)
    payload["worker_exit_code"] = exit_code
    print(RESULT_PREFIX + json.dumps(redact_payload(payload), sort_keys=True))
    return exit_code


def _fail_report(message: str, *, details: dict[str, object] | None = None) -> dict[str, object]:
    report: dict[str, object] = {
        "source_sha": _git_head(),
        "worker_status": "FAIL",
        "reason": message,
    }
    if details:
        report.update(details)
    return report


def _seed_paid_flight(order_id: str, amount_minor: int = 10_000) -> str:
    from datetime import datetime, timezone

    from go_hotel.db.models import FlightOrderRow
    from go_hotel.db.session import SessionLocal
    from go_hotel.services.omnichannel_payment import omnichannel_payment_service as payments
    from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service as source

    with SessionLocal.begin() as session:
        session.add(
            FlightOrderRow(
                order_id=order_id,
                account_id=OWNER,
                prebook_id=f"prebook-{order_id}",
                status="PENDING_PAYMENT",
                total_amount_minor=amount_minor,
                currency="CNY",
                passengers=[],
                payment_method_id=None,
                pnr=None,
                ticket_numbers=[],
                current_itinerary=[],
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
    source.decide(
        "FLIGHT",
        order_id,
        [
            {
                "source_id": PAYEE_ID,
                "source_type": "AIRLINE_OFFICIAL",
                "authorized": True,
                "available": True,
                "evidence_reference": f"baseline://source/{order_id}",
            }
        ],
    )
    intent = payments.create_intent(
        {"business_type": "FLIGHT_ORDER", "business_id": order_id, "channel_priority": ["ALIPAY"]},
        f"perf-intent:{order_id}",
        OWNER,
    )
    payments.select_channel(intent["payment_intent_id"], "ALIPAY", OWNER)
    attempt = payments.execute(intent["payment_intent_id"])
    payments.simulate_result(attempt["payment_attempt_id"], "SUCCEEDED")
    return intent["payment_intent_id"]


def _sqlite_money_smoke() -> dict[str, Any]:
    from sqlalchemy import select

    from go_hotel.db.models import OmnichannelMoneyMovementRow as Movement
    from go_hotel.db.session import SessionLocal
    from go_hotel.services.unified_money_movement import unified_money_movement_service as money

    tag = uuid.uuid4().hex[:10]
    intent_id = _seed_paid_flight(f"perf-local-{tag}")
    auth_body = {
        "movement_type": "AUTHORIZATION",
        "amount_minor": 10_000,
        "evidence": [f"baseline://sqlite/{tag}/auth"],
        "mode": "CONTRACT_SIMULATOR",
    }
    auth_key = f"perf:{tag}:auth"
    auth = money.create(intent_id, auth_body, auth_key, "perf-baseline")
    auth_replay = money.create(intent_id, auth_body, auth_key, "perf-baseline")
    cap_body = {
        "movement_type": "CAPTURE",
        "parent_movement_id": auth["money_movement_id"],
        "amount_minor": 10_000,
        "evidence": [f"baseline://sqlite/{tag}/cap"],
        "mode": "CONTRACT_SIMULATOR",
    }
    with SessionLocal.begin() as session:
        cap = money.create_in_session(session, intent_id, cap_body, f"perf:{tag}:cap", "perf-baseline")
    with SessionLocal.begin() as session:
        cap_replay = money.create_in_session(session, intent_id, cap_body, f"perf:{tag}:cap", "perf-baseline")
    with pytest.raises(ValueError, match="MONEY_MOVEMENT_IDEMPOTENCY_CONFLICT"):
        money.create(
            intent_id,
            auth_body | {"amount_minor": 9_999},
            auth_key,
            "perf-baseline",
        )
    with SessionLocal() as session:
        movements = list(
            session.scalars(
                select(Movement)
                .where(Movement.root_payment_intent_id == intent_id)
                .order_by(Movement.created_at, Movement.money_movement_id)
            )
        )
    return {
        "status": "PASS",
        "source_sha": _git_head(),
        "entrypoints": ["UnifiedMoneyMovementService.create", "UnifiedMoneyMovementService.create_in_session"],
        "money_types": [row.movement_type for row in movements],
        "replay_preserved": auth["money_movement_id"] == auth_replay["money_movement_id"]
        and cap["money_movement_id"] == cap_replay["money_movement_id"],
    }


def _warmup_money_operation(kind: str) -> None:
    from go_hotel.db.session import SessionLocal
    from go_hotel.services.unified_money_movement import unified_money_movement_service as money

    tag = uuid.uuid4().hex[:10]
    intent_id = _seed_paid_flight(f"perf-warm-{kind.lower()}-{tag}")
    auth = money.create(
        intent_id,
        {
            "movement_type": "AUTHORIZATION",
            "amount_minor": 10_000,
            "evidence": [f"baseline://warm/{kind}/{tag}/auth"],
            "mode": "CONTRACT_SIMULATOR",
        },
        f"perf:warm:{kind}:{tag}:auth",
        "perf-baseline",
    )
    if kind == "CAPTURE":
        with SessionLocal.begin() as session:
            money.create_in_session(
                session,
                intent_id,
                {
                    "movement_type": "CAPTURE",
                    "parent_movement_id": auth["money_movement_id"],
                    "amount_minor": 10_000,
                    "evidence": [f"baseline://warm/{kind}/{tag}/cap"],
                    "mode": "CONTRACT_SIMULATOR",
                },
                f"perf:warm:{kind}:{tag}:cap",
                "perf-baseline",
            )
    if kind == "REPLAY":
        money.create(
            intent_id,
            {
                "movement_type": "AUTHORIZATION",
                "amount_minor": 10_000,
                "evidence": [f"baseline://warm/{kind}/{tag}/replay"],
                "mode": "CONTRACT_SIMULATOR",
            },
            f"perf:warm:{kind}:{tag}:replay",
            "perf-baseline",
        )


def _measure_operation(kind: str, concurrency: int) -> dict[str, object]:
    from go_hotel.db.session import SessionLocal
    from go_hotel.services.unified_money_movement import unified_money_movement_service as money

    _warmup_money_operation(kind)
    barrier = threading.Barrier(concurrency)
    durations_ns: list[int] = []
    failures: list[dict[str, object]] = []
    replay_identity = None
    replay_identities: list[str] = []

    shared_intent_id = None
    shared_body = None
    shared_key = None
    if kind == "REPLAY":
        tag = uuid.uuid4().hex[:10]
        shared_intent_id = _seed_paid_flight(f"perf-replay-{tag}")
        shared_key = f"perf:{tag}:replay"
        shared_body = {
            "movement_type": "AUTHORIZATION",
            "amount_minor": 10_000,
            "evidence": [f"baseline://pg/{tag}/replay"],
            "mode": "CONTRACT_SIMULATOR",
        }
        original = money.create(shared_intent_id, shared_body, shared_key, "perf-baseline")
        replay_identity = original["money_movement_id"]

    def worker(index: int) -> None:
        nonlocal replay_identity
        try:
            if kind == "AUTHORIZATION":
                tag = uuid.uuid4().hex[:10]
                intent_id = _seed_paid_flight(f"perf-auth-{concurrency}-{index}-{tag}")
                body = {
                    "movement_type": "AUTHORIZATION",
                    "amount_minor": 10_000,
                    "evidence": [f"baseline://pg/{tag}/auth"],
                    "mode": "CONTRACT_SIMULATOR",
                }
                barrier.wait(timeout=30)
                start = time.monotonic_ns()
                money.create(intent_id, body, f"perf:{tag}:auth", "perf-baseline")
                durations_ns.append(time.monotonic_ns() - start)
                return
            if kind == "CAPTURE":
                tag = uuid.uuid4().hex[:10]
                intent_id = _seed_paid_flight(f"perf-cap-{concurrency}-{index}-{tag}")
                auth = money.create(
                    intent_id,
                    {
                        "movement_type": "AUTHORIZATION",
                        "amount_minor": 10_000,
                        "evidence": [f"baseline://pg/{tag}/auth"],
                        "mode": "CONTRACT_SIMULATOR",
                    },
                    f"perf:{tag}:auth",
                    "perf-baseline",
                )
                body = {
                    "movement_type": "CAPTURE",
                    "parent_movement_id": auth["money_movement_id"],
                    "amount_minor": 10_000,
                    "evidence": [f"baseline://pg/{tag}/cap"],
                    "mode": "CONTRACT_SIMULATOR",
                }
                barrier.wait(timeout=30)
                start = time.monotonic_ns()
                with SessionLocal.begin() as session:
                    money.create_in_session(session, intent_id, body, f"perf:{tag}:cap", "perf-baseline")
                durations_ns.append(time.monotonic_ns() - start)
                return
            if kind == "REPLAY" and shared_intent_id and shared_body and shared_key:
                barrier.wait(timeout=30)
                start = time.monotonic_ns()
                result = money.create(shared_intent_id, shared_body, shared_key, "perf-baseline")
                durations_ns.append(time.monotonic_ns() - start)
                replay_identities.append(result["money_movement_id"])
                return
            raise ValueError(f"UNSUPPORTED_WORKLOAD_{kind}")
        except Exception as exc:  # pragma: no cover - diagnostic path
            failures.append(summarize_failure(exc, operation=kind, sequence=index))

    cpu_start = time.process_time_ns()
    wall_start = time.monotonic_ns()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(worker, index) for index in range(concurrency)]
        for future in futures:
            future.result(timeout=120)
    cpu_ns = time.process_time_ns() - cpu_start
    wall_ns = time.monotonic_ns() - wall_start
    completed = len(durations_ns)
    profile = {
        "status": "PASS" if completed == concurrency and not failures else "FAIL",
        "operation": kind,
        "requested": concurrency,
        "workers": concurrency,
        "completed": completed,
        "failure_count": len(failures),
        "failures": failures,
        "latency_ms_samples": [round(value / 1_000_000, 2) for value in durations_ns],
        "request_p50_ms": _percentile_ms(durations_ns, 0.50),
        "request_p95_ms": _percentile_ms(durations_ns, 0.95),
        "request_p99_ms": _percentile_ms(durations_ns, 0.99),
        "throughput_per_sec": round((completed * 1_000_000_000) / wall_ns, 2) if wall_ns else 0.0,
        "process_cpu_ms": round(cpu_ns / 1_000_000, 2),
        "wall_ms": round(wall_ns / 1_000_000, 2),
    }
    if kind == "REPLAY":
        profile["replay_identity"] = replay_identity
        profile["replay_identities"] = replay_identities
    return profile


def _base_synthetic_profile(operation: str, requested: int) -> dict[str, object]:
    profile = {
        "status": "PASS",
        "operation": operation,
        "requested": requested,
        "workers": requested,
        "completed": requested,
        "failure_count": 0,
        "failures": [],
        "latency_ms_samples": [1.25] * requested,
        "request_p50_ms": 1.25,
        "request_p95_ms": 1.25,
        "request_p99_ms": 1.25,
        "throughput_per_sec": float(requested),
        "process_cpu_ms": float(requested),
        "wall_ms": float(requested),
    }
    if operation == "REPLAY":
        identity = f"omm-{requested}"
        profile["replay_identity"] = identity
        profile["replay_identities"] = [identity] * requested
    return profile


def _synthetic_pass_report() -> dict[str, object]:
    return {
        "source_sha": "synthetic",
        "worker_status": "PASS",
        "profiles": {
            profile_key(operation, requested): _base_synthetic_profile(operation, requested)
            for operation, requested in PROFILE_CASES
        },
    }


def _simulated_worker_payload(mode: str) -> tuple[dict[str, object], bool]:
    report = _synthetic_pass_report()
    profiles = report["profiles"]
    assert isinstance(profiles, dict)
    if mode == "single-worker-failure":
        profile = dict(profiles["AUTHORIZATION:20"])
        profile["status"] = "FAIL"
        profile["completed"] = 19
        profile["failure_count"] = 1
        profile["failures"] = [summarize_failure(ValueError("ROOT_PAYMENT_SUCCESS_REQUIRED"), operation="AUTHORIZATION", sequence=7)]
        profile["latency_ms_samples"] = profile["latency_ms_samples"][:-1]
        profiles["AUTHORIZATION:20"] = profile
    elif mode == "all-failures":
        profile = dict(profiles["CAPTURE:20"])
        profile["status"] = "FAIL"
        profile["completed"] = 0
        profile["failure_count"] = 20
        profile["failures"] = [
            summarize_failure(ValueError("CONFIRMED_PARENT_MOVEMENT_REQUIRED"), operation="CAPTURE", sequence=index)
            for index in range(20)
        ]
        profile["latency_ms_samples"] = []
        profiles["CAPTURE:20"] = profile
    elif mode == "incomplete-profile":
        profile = dict(profiles["AUTHORIZATION:100"])
        profile["completed"] = 99
        profile["latency_ms_samples"] = profile["latency_ms_samples"][:-1]
        profiles["AUTHORIZATION:100"] = profile
    elif mode == "missing-profile":
        del profiles["REPLAY:100"]
    elif mode == "replay-identity-mismatch":
        profile = dict(profiles["REPLAY:100"])
        replay_ids = list(profile["replay_identities"])
        replay_ids[-1] = "omm-mismatch"
        profile["replay_identities"] = replay_ids
        profiles["REPLAY:100"] = profile
    elif mode == "duplicate-profile":
        report["profiles"] = list(profiles.values()) + [dict(profiles["AUTHORIZATION:20"])]
    elif mode == "parent-fake-pass":
        profile = dict(profiles["CAPTURE:100"])
        profile["completed"] = 99
        profile["latency_ms_samples"] = profile["latency_ms_samples"][:-1]
        profiles["CAPTURE:100"] = profile
        return report, False
    elif mode == "worker-fail-exit0":
        report["worker_status"] = "FAIL"
        report["reason"] = "worker_status_fail_exit_zero"
        return report, False
    else:
        raise AssertionError(f"unknown simulation mode {mode}")
    return report, True


def _run_simulated_worker(mode: str) -> int:
    report, enforce_validation = _simulated_worker_payload(mode)
    if not enforce_validation:
        return _emit_result(report, 0)
    issues = validate_run(report, expected_profile_counts=EXPECTED_PROFILES)
    if issues:
        fail_report = _fail_report(
            "simulated_validation_failed",
            details={"validation_issues": issues, "simulated_mode": mode},
        )
        return _emit_result(fail_report, 1)
    return _emit_result(report, 0)


def _pg_worker() -> int:
    simulation = os.getenv("GO_C11_PERF_BASELINE_SIMULATION")
    if simulation:
        return _run_simulated_worker(simulation)
    try:
        source_name, admin_url = _configured_pg_url()
    except AssertionError as exc:
        return _emit_result(_fail_report("invalid_pg_configuration", details={"error": summarize_failure(exc, operation="PG", sequence=0)}), 1)
    if not admin_url:
        return _emit_result(
            {
                "source_sha": _git_head(),
                "worker_status": "DEFERRED",
                "pg_status": "MISSING_ENV",
                "http_full_request": "UNPROVEN",
                "next_cut": {"decision": "NO-GO", "reason": "Builder sandbox has no isolated PostgreSQL environment."},
            },
            0,
        )

    schema = f"c11_perf_{uuid.uuid4().hex[:16]}"
    admin_engine = create_engine(admin_url, pool_pre_ping=True)
    app_engine = None
    try:
        with admin_engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            server_version_num = str(conn.execute(text("SHOW server_version_num")).scalar_one())
            server_version = str(conn.execute(text("SHOW server_version")).scalar_one())
        if server_version_num != "180004":
            raise AssertionError(f"EXPECTED_POSTGRES_18_4_GOT_{server_version_num}")

        os.environ["DATABASE_URL"] = _schema_url(admin_url, schema)

        from go_hotel.db.models import Base
        from go_hotel.db.session import SessionLocal, engine
        from go_hotel.security.service import identity_service

        app_engine = engine
        Base.metadata.create_all(engine)
        identity_service.bootstrap()

        smoke = _sqlite_money_smoke()
        profiles = {
            profile_key(operation, requested): _measure_operation(operation, requested)
            for operation, requested in PROFILE_CASES
        }
        report = {
            "source_sha": _git_head(),
            "worker_status": "PASS",
            "pg_source": source_name,
            "postgres": {
                "server_version": server_version,
                "server_version_num": server_version_num,
                "schema": schema,
            },
            "http_full_request": "UNPROVEN",
            "smoke": smoke,
            "profiles": profiles,
            "next_cut": {
                "decision": "NO-GO",
                "reason": "Internal money service baseline only; full HTTP/auth/ride chain remains unproven.",
            },
        }
        issues = validate_run(report | {"worker_exit_code": 0}, expected_profile_counts=EXPECTED_PROFILES)
        if issues:
            fail_report = _fail_report(
                "worker_validation_failed",
                details={"validation_issues": issues, "report": report},
            )
            return _emit_result(fail_report, 1)
        return _emit_result(report, 0)
    except Exception as exc:  # pragma: no cover - diagnostic path
        fail_report = _fail_report(
            "worker_exception",
            details={"error": summarize_failure(exc, operation="PG", sequence=0)},
        )
        return _emit_result(fail_report, 1)
    finally:
        try:
            if app_engine is not None:
                app_engine.dispose()
        finally:
            try:
                with admin_engine.begin() as conn:
                    conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            finally:
                admin_engine.dispose()


def _run_pg_diagnostic(simulation: str | None = None) -> dict[str, object]:
    env = {
        **os.environ,
        "PYTHONPATH": str(APPLICATION_ROOT / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if simulation:
        env["GO_C11_PERF_BASELINE_SIMULATION"] = simulation
    else:
        env.pop("GO_C11_PERF_BASELINE_SIMULATION", None)
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--pg-worker"],
        cwd=APPLICATION_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=240,
    )
    report = parse_result_line(result.stdout)
    if report.get("worker_status") == "DEFERRED":
        assert result.returncode == 0, result.stderr
        return report
    issues = validate_run(report, expected_profile_counts=EXPECTED_PROFILES)
    if result.returncode or issues:
        context = [
            f"exit={result.returncode}",
            f"issues={issues}",
            f"stdout={audit_log_json(report)}",
        ]
        if result.stderr:
            context.append(f"stderr={result.stderr.strip()}")
        raise AssertionError("\n".join(context))
    return report


def test_perf_baseline_20261010_local_money_entrypoints_are_executable():
    result = _sqlite_money_smoke()
    assert result["status"] == "PASS"
    assert result["money_types"] == ["AUTHORIZATION", "CAPTURE"]
    assert result["replay_preserved"] is True


@pytest.mark.no_db
def test_perf_baseline_20261010_validate_run_accepts_all_six_profiles():
    report = _synthetic_pass_report() | {"worker_exit_code": 0}
    assert validate_run(report, expected_profile_counts=EXPECTED_PROFILES) == []


@pytest.mark.no_db
@pytest.mark.parametrize(
    "mode",
    [
        "single-worker-failure",
        "all-failures",
        "incomplete-profile",
        "missing-profile",
        "duplicate-profile",
        "replay-identity-mismatch",
        "worker-fail-exit0",
    ],
)
def test_perf_baseline_20261010_validate_run_rejects_regressions(mode):
    report, _ = _simulated_worker_payload(mode)
    report["worker_exit_code"] = 0
    issues = validate_run(report, expected_profile_counts=EXPECTED_PROFILES)
    assert issues, audit_log_json(report)


@pytest.mark.no_db
@pytest.mark.parametrize(
    "mode",
    [
        "single-worker-failure",
        "all-failures",
        "incomplete-profile",
        "missing-profile",
        "duplicate-profile",
        "replay-identity-mismatch",
    ],
)
def test_perf_baseline_20261010_child_rejects_invalid_profiles(mode):
    env = {
        **os.environ,
        "PYTHONPATH": str(APPLICATION_ROOT / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "GO_C11_PERF_BASELINE_SIMULATION": mode,
    }
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--pg-worker"],
        cwd=APPLICATION_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    report = parse_result_line(result.stdout)
    assert result.returncode == 1, result.stdout
    assert report["worker_status"] == "FAIL"
    assert report["validation_issues"]


@pytest.mark.no_db
@pytest.mark.parametrize("mode", ["parent-fake-pass", "worker-fail-exit0"])
def test_perf_baseline_20261010_parent_rejects_fake_pass_or_fail_exit_zero(mode):
    with pytest.raises(AssertionError):
        _run_pg_diagnostic(mode)


@pytest.mark.no_db
def test_perf_baseline_20261010_postgres_diagnostic_is_pass_or_deferred():
    report = _run_pg_diagnostic()
    if report["worker_status"] == "DEFERRED":
        assert report["pg_status"] == "MISSING_ENV"
        assert report["next_cut"]["decision"] == "NO-GO"
        return
    assert report["postgres"]["server_version_num"] == "180004"
    assert report["http_full_request"] == "UNPROVEN"


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--pg-worker":
        raise SystemExit(_pg_worker())
