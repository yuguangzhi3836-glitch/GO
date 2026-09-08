import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


def _admin_headers():
    from go_hotel.security.service import identity_service
    token = identity_service.login("go_admin", "change-me-admin")
    return {"Authorization": "Bearer " + token["access_token"]}


def test_travel_intelligence_api_idempotency_replays_and_conflicts(client):
    from go_hotel.core.config import settings
    old = settings.travel_intelligence_enabled
    settings.travel_intelligence_enabled = True
    try:
        h = _admin_headers() | {"Idempotency-Key": "ti-entity-real-idem-1"}
        payload = {"entity_type": "HOTEL", "canonical_name": "Idempotency Hotel"}
        first = client.post("/internal/v1/travel-entities", headers=h, json=payload)
        second = client.post("/internal/v1/travel-entities", headers=h, json=payload)
        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        assert second.json() == first.json()
        assert second.json()["data"]["go_entity_id"] == first.json()["data"]["go_entity_id"]

        conflict = client.post(
            "/internal/v1/travel-entities",
            headers=h,
            json={"entity_type": "HOTEL", "canonical_name": "Different Hotel"},
        )
        assert conflict.status_code == 409, conflict.text
        assert conflict.json()["detail"] == "IDEMPOTENCY_CONFLICT"
    finally:
        settings.travel_intelligence_enabled = old


def test_ti_mutation_routes_all_use_request_idempotency_guard():
    source = Path("src/go_hotel/api/routes/travel_intelligence.py").read_text()
    for operation in (
        "ti.create_intent",
        "ti.refine_intent",
        "ti.resolve_entity",
        "ti.create_entity",
        "ti.evaluate_judgment",
        "ti.model_invoke",
    ):
        assert f'_idem("{operation}"' in source


def test_cost_governor_hard_budgets_quality_price_and_circuit(monkeypatch):
    from go_hotel.core.config import settings
    from go_hotel.travel_intelligence.cost_governor import model_cost_governor

    with pytest.raises(ValueError, match="MODEL_GATEWAY_SESSION_COST_BUDGET_EXCEEDED"):
        model_cost_governor.route(
            capability="QUERY_REWRITE", complexity=0.1, privacy_class="INTERNAL",
            local_capability_available=True, session_spend_usd=0.49,
            estimated_call_cost_usd=0.02,
        )
    with pytest.raises(ValueError, match="MODEL_GATEWAY_INPUT_TOKEN_BUDGET_EXCEEDED"):
        model_cost_governor.route(
            capability="QUERY_REWRITE", complexity=0.1, privacy_class="INTERNAL",
            local_capability_available=True, input_tokens=32001,
        )
    with pytest.raises(ValueError, match="MODEL_GATEWAY_PRICE_SNAPSHOT_REQUIRED"):
        model_cost_governor.route(
            capability="QUERY_REWRITE", complexity=0.1, privacy_class="INTERNAL",
            local_capability_available=True, price_snapshot_id="",
        )
    with pytest.raises(ValueError, match="MODEL_GATEWAY_QUALITY_FLOOR_NOT_MET"):
        model_cost_governor.route(
            capability="QUERY_REWRITE", complexity=0.1, privacy_class="INTERNAL",
            local_capability_available=True, estimated_quality=0.5,
        )

    old = settings.model_gateway_external_egress_enabled
    settings.model_gateway_external_egress_enabled = True
    try:
        with pytest.raises(ValueError, match="MODEL_GATEWAY_CIRCUIT_OPEN"):
            model_cost_governor.route(
                capability="TRAVEL_REASONING", complexity=1.0, privacy_class="INTERNAL",
                local_capability_available=False, self_hosted_available=False,
                explicit_external_policy=True, circuit_open=True,
                price_snapshot_id="frontier-price-20260829", model_version="frontier-test",
            )
    finally:
        settings.model_gateway_external_egress_enabled = old


def test_cost_governor_session_scope_and_revenue_metrics():
    from go_hotel.travel_intelligence.service import travel_intelligence_service as svc

    first = svc.model_invoke(
        capability="QUERY_REWRITE", input_data={"query": "  tokyo   hotel "}, privacy_class="INTERNAL",
        latency_budget_ms=5000, cost_budget_usd=0.08, complexity=0.1, correlation_id="corr-cost-1",
        session_id="session-cost-1", cost_scope="RECOMMENDATION", business_reference_id="rec-1",
        attributed_revenue_usd=1.0, estimated_quality=1.0, estimated_call_cost_usd=0.01,
        input_tokens=10, output_tokens=5, price_snapshot_id="local-price-20260829", circuit_open=False,
    )
    second = svc.model_invoke(
        capability="QUERY_REWRITE", input_data={"query": "kyoto hotel"}, privacy_class="INTERNAL",
        latency_budget_ms=5000, cost_budget_usd=0.08, complexity=0.1, correlation_id="corr-cost-2",
        session_id="session-cost-1", cost_scope="BOOKING", business_reference_id="booking-1",
        attributed_revenue_usd=4.0, estimated_quality=1.0, estimated_call_cost_usd=0.02,
        input_tokens=10, output_tokens=5, price_snapshot_id="local-price-20260829", circuit_open=False,
    )
    summary = svc.model_cost_summary(session_id="session-cost-1")
    rec = svc.model_cost_summary(session_id="session-cost-1", cost_scope="RECOMMENDATION", business_reference_id="rec-1")
    booking = svc.model_cost_summary(session_id="session-cost-1", cost_scope="BOOKING", business_reference_id="booking-1")
    assert first["session_cost_usd"] == pytest.approx(0.01)
    assert second["session_cost_usd"] == pytest.approx(0.03)
    assert summary["cost_usd"] == pytest.approx(0.03)
    assert summary["attributed_revenue_usd"] == pytest.approx(5.0)
    assert summary["ai_cost_over_revenue"] == pytest.approx(0.006)
    assert rec["cost_usd"] == pytest.approx(0.01)
    assert booking["cost_usd"] == pytest.approx(0.02)


@pytest.mark.no_db
def test_current_source_head_and_upgrade_downgrade_roundtrip(tmp_path):
    db = tmp_path / "ti_migration_roundtrip.db"
    conn = sqlite3.connect(db)
    conn.execute("create table alembic_version (version_num varchar(32) not null)")
    conn.execute("insert into alembic_version(version_num) values (?)", ("0111_test_account_expiry",))
    # Synthetic pre-0112 database must include the pre-0113 reconciliation table
    # because 0113/0114 are additive governance migrations over that existing schema.
    conn.execute(
        "create table connector_runtime_reconciliation ("
        "reconciliation_id varchar(64) primary key, "
        "runtime_operation_id varchar(64) not null unique, "
        "state varchar(32) not null, "
        "attempt_count integer not null default 0, "
        "max_attempts integer not null default 8, "
        "next_attempt_at datetime, "
        "manual_review_reason varchar(256), "
        "updated_at datetime not null"
        ")"
    )
    conn.commit(); conn.close()

    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+pysqlite:///{db}"
    env["PYTHONPATH"] = "src"

    heads = subprocess.run([sys.executable, "-m", "alembic", "heads"], env=env, text=True, capture_output=True, check=True)
    head_lines = [line.strip() for line in heads.stdout.splitlines() if line.strip().endswith("(head)")]
    assert head_lines == ["0130_vertical_capacity (head)"]

    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "0114_ext_truth_incident_hard"], env=env, text=True, capture_output=True, check=True)
    conn = sqlite3.connect(db)
    assert conn.execute("select version_num from alembic_version").fetchone()[0] == "0114_ext_truth_incident_hard"
    required = {"travel_entity", "travel_intent", "travel_behavior_event", "ai_decision", "ai_decision_model_call", "transaction_relation"}
    tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    assert required <= tables
    cols = {r[1] for r in conn.execute("pragma table_info(ai_decision_model_call)")}
    assert {"session_id", "cost_scope", "price_snapshot_id", "estimated_quality", "input_tokens", "output_tokens", "attributed_revenue_usd"} <= cols
    recon_cols = {r[1] for r in conn.execute("pragma table_info(connector_runtime_reconciliation)")}
    assert {"claimed_by", "lease_expires_at", "evidence_due_at", "resolution_requested_by", "checker_id", "escalation_level", "operator_sla_due_at", "resolved_at", "resolution_payload_json", "resolution_evidence_digest", "checker_evidence_reference", "resolution_result_json", "resolved_by", "superseded_reason"} <= recon_cols
    conn.close()

    subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0111_test_account_expiry"], env=env, text=True, capture_output=True, check=True)
    conn = sqlite3.connect(db)
    assert conn.execute("select version_num from alembic_version").fetchone()[0] == "0111_test_account_expiry"
    tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    assert not (required & tables)
    recon_cols = {r[1] for r in conn.execute("pragma table_info(connector_runtime_reconciliation)")}
    assert not ({"claimed_by", "lease_expires_at", "evidence_due_at", "resolution_requested_by", "checker_id", "escalation_level", "operator_sla_due_at", "resolved_at", "resolution_payload_json", "resolution_evidence_digest", "checker_evidence_reference", "resolution_result_json", "resolved_by", "superseded_reason"} & recon_cols)
    conn.close()
