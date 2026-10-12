"""C09 evidence gap: recommendation support expiry cannot be enforced without a contract field."""
from datetime import datetime, timedelta, timezone

from go_hotel.judgment.service import RECOMMENDATION_DIMENSIONS, judgment_service


def assessment():
    return {
        "verdict": "GO_RECOMMENDED",
        "worth_the_journey": "YES",
        "commercial_independence_attested": True,
        "dimensions": {
            key: {"state": "PRESENT", "evidence_summary": "Independent support: " + key}
            for key in RECOMMENDATION_DIMENSIONS
        },
    }


def test_recommendation_support_contract_has_no_expiry_boundary(monkeypatch):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    later = start + timedelta(days=30)

    monkeypatch.setattr("go_hotel.judgment.service.now_utc", lambda: start)
    first = judgment_service.reevaluate(
        "support-validity-gap-hotel",
        {"recommendation_assessment": assessment()},
    )

    persisted = first["evidence_package"]["feature_snapshot"]["recommendation_assessment"]
    assert first["recommendation"]["status"] == "GO_RECOMMENDED"
    assert "valid_until" not in persisted
    assert "support_valid_until" not in persisted
    assert all("valid_until" not in item and "support_valid_until" not in item for item in persisted["dimensions"].values())

    monkeypatch.setattr("go_hotel.judgment.service.now_utc", lambda: later)
    second = judgment_service.reevaluate(
        "support-validity-gap-hotel",
        {"recommendation_assessment": assessment()},
    )

    assert second["judgment_id"] == first["judgment_id"]
    assert second["recommendation"] == first["recommendation"]
    assert second["evidence_package"]["package_id"] == first["evidence_package"]["package_id"]
