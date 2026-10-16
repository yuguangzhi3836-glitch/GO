"""C11 scoped high-concurrency baseline harness for the 2026-10-10 restart.

This file does not claim HK runtime truth or historical PASS transfer. It binds
the current source tree, proves the real money service entrypoints remain
executable on the local Builder sandbox, and runs bounded PostgreSQL diagnostics
only when a real isolated PG environment is explicitly provided.
"""
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


APPLICATION_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = APPLICATION_ROOT.parent
PAYEE_ID = "perf-baseline-airline"
OWNER = "perf-baseline-owner"
RESULT_PREFIX = "C11_PERF_BASELINE_20261010 "
RELATED_PAYMENT_FIX_PR = {
    "pr": 570,
    "issue": 569,
    "head_sha": "bad911f252b9469dc3c4686bb27b695f135a5592",
    "note": "Unmerged scoped payment integration candidate; not imported or claimed here.",
}


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


def _pg_url_from_env() -> str | None:
    direct = os.getenv("POSTGRES_TEST_DATABASE_URL")
    if direct:
        return direct
    parts = {key: os.getenv(key) for key in ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE")}
    if not all(parts.values()):
        return None
    return (
        "postgresql+psycopg://"
        f"{parts['PGUSER']}:{parts['PGPASSWORD']}@{parts['PGHOST']}:{parts['PGPORT']}/{parts['PGDATABASE']}"
    )


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


def _report(payload: dict[str, Any]) -> dict[str, Any]:
    print(RESULT_PREFIX + json.dumps(payload, sort_keys=True))
    return payload


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
    auth_key = f"perf:{tag}:auth"
    cap_key = f"perf:{tag}:cap"
    auth_body = {
        "movement_type": "AUTHORIZATION",
        "amount_minor": 10_000,
        "evidence": [f"baseline://sqlite/{tag}/auth"],
        "mode": "CONTRACT_SIMULATOR",
    }
    auth = money.create(intent_id, auth_body, auth_key, "perf-baseline")
    auth_replay = money.create(intent_id, auth_body, auth_key, "perf-baseline")
    with SessionLocal.begin() as session:
        cap_body = {
            "movement_type": "CAPTURE",
            "parent_movement_id": auth["money_movement_id"],
            "amount_minor": 10_000,
            "evidence": [f"baseline://sqlite/{tag}/cap"],
            "mode": "CONTRACT_SIMULATOR",
        }
        cap = money.create_in_session(session, intent_id, cap_body, cap_key, "perf-baseline")
    with SessionLocal.begin() as session:
        cap_replay = money.create_in_session(session, intent_id, cap_body, cap_key, "perf-baseline")
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
        "current_tree": "current-main-candidate-only",
        "entrypoints": ["UnifiedMoneyMovementService.create", "UnifiedMoneyMovementService.create_in_session"],
        "money_types": [row.movement_type for row in movements],
        "replay_preserved": auth["money_movement_id"] == auth_replay["money_movement_id"]
        and cap["money_movement_id"] == cap_replay["money_movement_id"],
        "related_unmerged_payment_fix": RELATED_PAYMENT_FIX_PR,
    }


def test_perf_baseline_20261010_local_money_entrypoints_are_executable():
    result = _sqlite_money_smoke()
    assert result["status"] == "PASS"
    assert result["money_types"] == ["AUTHORIZATION", "CAPTURE"]
    assert result["replay_preserved"] is True


@pytest.mark.no_db
def test_perf_baseline_20261010_postgres_diagnostic_or_deferred():
    pg_url = _pg_url_from_env()
    if not pg_url:
        result = _report(
            {
                "status": "DEFERRED",
                "source_sha": _git_head(),
                "pg_status": "MISSING_ENV",
                "http_full_request": "UNPROVEN",
                "next_cut": "NO-GO",
                "reason": "Builder sandbox has no isolated PostgreSQL environment; only local money smoke ran here.",
                "related_unmerged_payment_fix": RELATED_PAYMENT_FIX_PR,
            }
        )
        assert result["status"] == "DEFERRED"
        return

    env = {
        **os.environ,
        "PYTHONPATH": str(APPLICATION_ROOT / "src"),
        "GO_C11_PERF_BASELINE_PG_URL": pg_url,
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    worker = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--pg-worker"],
        cwd=APPLICATION_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if worker.returncode:
        raise AssertionError(
            "PG worker failed\n"
            f"exit={worker.returncode}\n"
            f"stdout:\n{worker.stdout}\n"
            f"stderr:\n{worker.stderr}"
        )
    line = next((x for x in worker.stdout.splitlines() if x.startswith(RESULT_PREFIX)), None)
    assert line is not None, worker.stdout
    payload = json.loads(line[len(RESULT_PREFIX):])
    assert payload["status"] == "PASS"
    assert payload["postgres"]["server_version_num"] == "180004"
    assert payload["http_full_request"] == "UNPROVEN"
    assert payload["next_cut"]["decision"] == "NO-GO"


def _measure_operation(kind: str, concurrency: int) -> dict[str, Any]:
    from go_hotel.db.session import SessionLocal
    from go_hotel.services.unified_money_movement import unified_money_movement_service as money

    barrier = threading.Barrier(concurrency)
    durations_ns: list[int] = []
    failures: list[str] = []
    replay_keys: list[str] = []
    replay_results: list[str] = []

    def worker(index: int) -> None:
        tag = f"{kind.lower()}-{concurrency}-{index}-{uuid.uuid4().hex[:8]}"
        try:
            intent_id = _seed_paid_flight(f"perf-pg-{tag}")
            if kind == "AUTHORIZATION":
                key = f"perf:{tag}:auth"
                body = {
                    "movement_type": "AUTHORIZATION",
                    "amount_minor": 10_000,
                    "evidence": [f"baseline://pg/{tag}/auth"],
                    "mode": "CONTRACT_SIMULATOR",
                }
                barrier.wait(timeout=30)
                start = time.monotonic_ns()
                result = money.create(intent_id, body, key, "perf-baseline")
                durations_ns.append(time.monotonic_ns() - start)
                replay_keys.append(key)
                replay_results.append(result["money_movement_id"])
                return

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
            if kind == "CAPTURE":
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

            if kind == "REPLAY":
                key = f"perf:{tag}:replay"
                body = {
                    "movement_type": "AUTHORIZATION",
                    "amount_minor": 10_000,
                    "evidence": [f"baseline://pg/{tag}/replay"],
                    "mode": "CONTRACT_SIMULATOR",
                }
                first = money.create(intent_id, body, key, "perf-baseline")
                barrier.wait(timeout=30)
                start = time.monotonic_ns()
                second = money.create(intent_id, body, key, "perf-baseline")
                durations_ns.append(time.monotonic_ns() - start)
                replay_keys.append(key)
                replay_results.append(first["money_movement_id"] + ":" + second["money_movement_id"])
                return

            raise ValueError(f"unsupported workload kind {kind}")
        except Exception as exc:  # pragma: no cover - diagnostic path
            failures.append(f"{kind}:{index}:{type(exc).__name__}:{exc}")

    cpu_start = time.process_time_ns()
    wall_start = time.monotonic_ns()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(worker, index) for index in range(concurrency)]
        for future in futures:
            future.result(timeout=120)
    cpu_ns = time.process_time_ns() - cpu_start
    wall_ns = time.monotonic_ns() - wall_start
    return {
        "kind": kind,
        "concurrency": concurrency,
        "workers": concurrency,
        "completed": len(durations_ns),
        "failures": failures,
        "request_p50_ms": _percentile_ms(durations_ns, 0.50),
        "request_p95_ms": _percentile_ms(durations_ns, 0.95),
        "request_p99_ms": _percentile_ms(durations_ns, 0.99),
        "throughput_per_sec": round((len(durations_ns) * 1_000_000_000) / wall_ns, 2) if wall_ns else 0.0,
        "process_cpu_ms": round(cpu_ns / 1_000_000, 2),
        "wall_ms": round(wall_ns / 1_000_000, 2),
        "replay_identity_preserved": all(
            item.split(":", 1)[0] == item.split(":", 1)[1] if ":" in item else True for item in replay_results
        ),
        "idempotency_keys": replay_keys[:3],
    }


def _pg_worker() -> dict[str, Any]:
    admin_url = os.getenv("GO_C11_PERF_BASELINE_PG_URL") or _pg_url_from_env()
    if not admin_url:
        return _report({"status": "DEFERRED", "pg_status": "MISSING_ENV", "source_sha": _git_head()})

    schema = f"c11_perf_{uuid.uuid4().hex[:16]}"
    admin_engine = create_engine(admin_url, pool_pre_ping=True)
    try:
        with admin_engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            server_version_num = str(conn.execute(text("SHOW server_version_num")).scalar_one())
            server_version = str(conn.execute(text("SHOW server_version")).scalar_one())
        if server_version_num != "180004":
            raise AssertionError(f"expected PostgreSQL 18.4, got server_version_num={server_version_num}")

        os.environ["DATABASE_URL"] = _schema_url(admin_url, schema)

        from go_hotel.db.models import Base, OmnichannelMoneyMovementRow as Movement
        from go_hotel.db.session import SessionLocal, engine
        from go_hotel.security.service import identity_service
        from go_hotel.services.unified_money_movement import unified_money_movement_service as money
        from sqlalchemy import select

        Base.metadata.create_all(engine)
        identity_service.bootstrap()

        smoke = _sqlite_money_smoke()

        conflict_tag = uuid.uuid4().hex[:10]
        conflict_intent = _seed_paid_flight(f"perf-conflict-{conflict_tag}")
        conflict_key = f"perf:{conflict_tag}:auth"
        money.create(
            conflict_intent,
            {
                "movement_type": "AUTHORIZATION",
                "amount_minor": 10_000,
                "evidence": [f"baseline://pg/{conflict_tag}/auth"],
                "mode": "CONTRACT_SIMULATOR",
            },
            conflict_key,
            "perf-baseline",
        )
        with pytest.raises(ValueError, match="MONEY_MOVEMENT_IDEMPOTENCY_CONFLICT"):
            money.create(
                conflict_intent,
                {
                    "movement_type": "AUTHORIZATION",
                    "amount_minor": 10_001,
                    "evidence": [f"baseline://pg/{conflict_tag}/auth"],
                    "mode": "CONTRACT_SIMULATOR",
                },
                conflict_key,
                "perf-baseline",
            )

        workloads = [
            _measure_operation(kind, concurrency)
            for kind in ("AUTHORIZATION", "CAPTURE", "REPLAY")
            for concurrency in (20, 100)
        ]
        with SessionLocal() as session:
            movement_count = session.scalar(select(text("count(*)")).select_from(Movement.__table__))

        return _report(
            {
                "status": "PASS",
                "source_sha": _git_head(),
                "postgres": {
                    "server_version": server_version,
                    "server_version_num": server_version_num,
                    "schema": schema,
                },
                "service_layer": "internal-money-service-only",
                "http_full_request": "UNPROVEN",
                "smoke": smoke,
                "workloads": workloads,
                "movement_rows": movement_count,
                "next_cut": {
                    "decision": "NO-GO",
                    "reason": (
                        "This baseline measures current source internal AUTH/CAPTURE/replay wall time on isolated "
                        "PostgreSQL 18.4 but does not yet attribute a dominant removable SQL/lock hotspot."
                    ),
                },
                "related_unmerged_payment_fix": RELATED_PAYMENT_FIX_PR,
            }
        )
    finally:
        with admin_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--pg-worker":
        _pg_worker()
        raise SystemExit(0)
