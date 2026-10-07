from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from go_hotel.db.models import ConnectorCertificationRow
from go_hotel.db.session import SessionLocal
from go_hotel.services.connectors import connector_service
from go_hotel.services.onboarding import onboarding_service


def _report(connector_id: str, passed: bool) -> dict:
    return {
        "connector_id": connector_id,
        "passed": passed,
        "checks": [{"name": "health", "passed": passed, "detail": "ok" if passed else "failed"}],
    }


def _prepare_onboarding(supplier_id: str) -> str:
    created = onboarding_service.create(supplier_id, "conn_mock_hotel", "SANDBOX")
    onboarding_id = created["onboarding_id"]
    onboarding_service.store_credential_reference(onboarding_id, f"vault://providers/hotel/{supplier_id}", "ops")
    mapping = onboarding_service.propose_mapping(onboarding_id, f"ext_{supplier_id}", "htl_001", confidence_bps=10000)
    onboarding_service.review_mapping(mapping["mapping_id"], "APPROVE", "mapper")
    assert onboarding_service._row(onboarding_id)["status"] == "CERTIFICATION_PENDING"
    return onboarding_id


def _insert_certification(certification_id: int, connector_id: str, passed: bool, *, at: datetime) -> None:
    with SessionLocal.begin() as s:
        s.add(
            ConnectorCertificationRow(
                certification_id=certification_id,
                connector_id=connector_id,
                passed=passed,
                report=_report(connector_id, passed),
                certified_at=at,
            )
        )


def test_certify_binds_to_unique_passed_row_from_this_run_even_if_newer_failed_row_exists(monkeypatch):
    onboarding_id = _prepare_onboarding("sup_bind_exact")

    async def fake_certify(connector_id: str):
        _insert_certification(900, connector_id, True, at=datetime(2026, 1, 2, tzinfo=timezone.utc))
        _insert_certification(901, connector_id, False, at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        return _report(connector_id, True)

    monkeypatch.setattr(connector_service, "certify", fake_certify)

    report = asyncio.run(onboarding_service.certify(onboarding_id, "certifier"))

    assert report["passed"] is True
    onboarding = onboarding_service._row(onboarding_id)
    assert onboarding["status"] == "CERTIFIED"
    assert onboarding["last_certification_id"] == 900
    assert onboarding_service.request_activation(onboarding_id, "ops")["status"] == "ACTIVATION_PENDING"


def test_certify_rejects_missing_persisted_record_and_clears_activation_readiness(monkeypatch):
    onboarding_id = _prepare_onboarding("sup_bind_missing")

    async def fake_certify(connector_id: str):
        return _report(connector_id, True)

    monkeypatch.setattr(connector_service, "certify", fake_certify)

    with pytest.raises(ValueError, match="CERTIFICATION_RECORD_BINDING_MISSING"):
        asyncio.run(onboarding_service.certify(onboarding_id, "certifier"))

    onboarding = onboarding_service._row(onboarding_id)
    assert onboarding["status"] == "CERTIFICATION_PENDING"
    assert onboarding["last_certification_id"] is None
    with pytest.raises(ValueError, match="PASSED_CERTIFICATION_REQUIRED"):
        onboarding_service.request_activation(onboarding_id, "ops")


def test_certify_rejects_ambiguous_duplicate_matches_and_leaves_onboarding_non_activatable(monkeypatch):
    onboarding_id = _prepare_onboarding("sup_bind_ambiguous")

    async def fake_certify(connector_id: str):
        _insert_certification(920, connector_id, True, at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        _insert_certification(921, connector_id, True, at=datetime(2026, 1, 2, tzinfo=timezone.utc))
        return _report(connector_id, True)

    monkeypatch.setattr(connector_service, "certify", fake_certify)

    with pytest.raises(ValueError, match="CERTIFICATION_RECORD_BINDING_AMBIGUOUS"):
        asyncio.run(onboarding_service.certify(onboarding_id, "certifier"))

    onboarding = onboarding_service._row(onboarding_id)
    assert onboarding["status"] == "CERTIFICATION_PENDING"
    assert onboarding["last_certification_id"] is None
    with pytest.raises(ValueError, match="PASSED_CERTIFICATION_REQUIRED"):
        onboarding_service.request_activation(onboarding_id, "ops")
