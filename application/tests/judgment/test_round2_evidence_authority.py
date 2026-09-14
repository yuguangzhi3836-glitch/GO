"""C09 evidence authority: supplemental assessments cannot replace persisted truth."""
from datetime import datetime, timezone

from fastapi import HTTPException
import pytest
from sqlalchemy import func, select

from go_hotel.db.models import JudgmentRuntimeRow, RiskEventRuntimeRow
from go_hotel.db.session import SessionLocal
from go_hotel.judgment.service import RECOMMENDATION_DIMENSIONS, judgment_service


def assessment():
    return {
        "verdict": "GO_RECOMMENDED",
        "worth_the_journey": "YES",
        "commercial_independence_attested": True,
        "dimensions": {
            key: {"state": "PRESENT", "evidence_summary": "Isolated independent evidence: " + key}
            for key in RECOMMENDATION_DIMENSIONS
        },
    }


def confirmed_risk():
    now = datetime.now(timezone.utc)
    with SessionLocal.begin() as session:
        session.add(RiskEventRuntimeRow(
            risk_event_id="round2-confirmed-risk", hotel_id="round2-hotel",
            order_id="round2-order", review_id="round2-review",
            risk_type="SERIOUS_HYGIENE", severity="R2", status="CONFIRMED",
            confidence_bps=9900, created_at=now, updated_at=now, confirmed_at=now,
        ))


@pytest.mark.parametrize("key,value", [
    ("confirmed_serious_risk_count", 0),
    ("completed_review_count", 100000),
    ("structured_experience_avg_milli", 5000),
    ("dimension_summary", {"SAFETY": {"positive": 100, "negative": 0}}),
    ("monitoring_risk_count", 0),
    ("verified_remediation_count", 100),
])
def test_supplement_cannot_override_persisted_evidence_or_publish(key, value):
    confirmed_risk()
    with pytest.raises(HTTPException) as caught:
        judgment_service.reevaluate("round2-hotel", {
            key: value, "recommendation_assessment": assessment(),
        })
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "JUDGMENT_EVIDENCE_FIELD_FORBIDDEN"
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(JudgmentRuntimeRow)) == 0
        assert session.get(RiskEventRuntimeRow, "round2-confirmed-risk").status == "CONFIRMED"


def test_persisted_serious_risk_vetoes_complete_independent_six_dimension_assessment():
    confirmed_risk()
    result = judgment_service.reevaluate("round2-hotel", {"recommendation_assessment": assessment()})
    assert result["recommendation"]["status"] == "GO_NOT_RECOMMENDED"
    assert result["public_go_score"] is None
    assert result["evidence_package"]["feature_snapshot"]["confirmed_serious_risk_count"] == 1
    assert "UNRESOLVED_CONFIRMED_SERIOUS_RISK" in result["recommendation"]["reason_codes"]
    assert any(ref["id"] == "round2-confirmed-risk" for ref in result["evidence_package"]["source_refs"])


@pytest.mark.parametrize("missing_dimension", RECOMMENDATION_DIMENSIONS)
def test_each_six_dimension_evidence_is_mandatory(missing_dimension):
    item = assessment()
    del item["dimensions"][missing_dimension]
    result = judgment_service.reevaluate("round2-hotel", {"recommendation_assessment": item})
    assert result["recommendation"]["status"] == "NOT_YET_RATED"
    assert result["public_go_score"] is None
    assert "RECOMMENDATION_SIX_DIMENSION_EVIDENCE_INCOMPLETE" in result["recommendation"]["reason_codes"]


@pytest.mark.parametrize("attestation", [False, None, "true"])
def test_commercial_independence_requires_explicit_boolean_attestation(attestation):
    item = assessment()
    item["commercial_independence_attested"] = attestation
    result = judgment_service.reevaluate("round2-hotel", {"recommendation_assessment": item})
    assert result["recommendation"]["status"] == "NOT_YET_RATED"
    assert result["public_go_score"] is None
    assert "COMMERCIAL_INDEPENDENCE_ATTESTATION_REQUIRED" in result["recommendation"]["reason_codes"]
