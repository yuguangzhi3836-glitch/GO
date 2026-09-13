import pytest


def test_c07_prepares_evidence_only_and_never_judgment_truth():
    from go_hotel.travel_intelligence.service import travel_intelligence_service as svc
    result = svc.prepare_judgment_evidence(
        intent_id="intent-wave03",
        candidate_entity_ids=["hotel-b", "hotel-a"],
        context={"candidate_scores":{"hotel-b":0.9,"hotel-a":0.2},"commission":8},
        correlation_id="corr-wave03-c07-c09",
    )
    assert result["evidence_scope"] == "C07_TRAVELER_CONTEXT_ONLY"
    assert result["final_judgment_authority"] == "C09"
    assert result["admission_or_recommendation"] is None
    assert "ranked_candidates" not in result
    assert [x["entity_id"] for x in result["candidate_context"]] == ["hotel-b", "hotel-a"]
    assert result["commercial_signals_excluded"] == ["commission"]


def test_c07_legacy_judgment_entrypoints_fail_closed():
    from go_hotel.travel_intelligence.service import travel_intelligence_service as svc
    with pytest.raises(ValueError, match="C07_JUDGMENT_AUTHORITY_FORBIDDEN"):
        svc.evaluate_judgment(intent_id="i", candidate_entity_ids=["h"], context={}, correlation_id="c")
    with pytest.raises(ValueError, match="C07_JUDGMENT_AUTHORITY_FORBIDDEN"):
        svc.independent_judgment(intent_id="i", candidate_entity_ids=["h"], context={}, correlation_id="c")


def test_c09_rejects_traveler_fit_context_as_recommendation_input():
    from go_hotel.judgment.service import judgment_service
    for forbidden in (
        {"traveler_fit":0.99},
        {"traveler_context":{"purpose":"honeymoon"}},
        {"candidate_scores":{"hotel-a":1.0}},
        {"personalization_score":0.88},
    ):
        with pytest.raises(Exception):
            judgment_service._assert_no_forbidden_features(forbidden)


def test_wave03_contract_registry_keeps_c09_as_final_owner():
    import json
    from pathlib import Path
    data=json.loads(Path("governance/workbench/waves/PARALLEL_WAVE_03_20260831/C07_C09_AUTHORITY_CONTRACT.json").read_text())
    assert data["from_cell"] == "C07"
    assert data["to_cell"] == "C09"
    assert data["final_truth_owner"] == "C09"
    assert data["cross_domain_truth_mutation"] == "PROHIBITED"


def test_c07_autonomy_registry_has_context_evidence_but_not_judgment_capability():
    from go_hotel.autonomy import ALL_CELL_REGISTRY
    c07=ALL_CELL_REGISTRY.cell("C07")
    assert "TRAVELER_CONTEXT_EVIDENCE" in c07.capabilities
    assert "GO_RECOMMENDATION" not in c07.capabilities
    assert "QUALITY_JUDGMENT" not in c07.capabilities
    assert "RECOMMENDATION_TRUTH_MUTATION" in c07.forbidden_capabilities
    assert ALL_CELL_REGISTRY.owner_for("GO_JUDGMENT").cell_id == "C09"
