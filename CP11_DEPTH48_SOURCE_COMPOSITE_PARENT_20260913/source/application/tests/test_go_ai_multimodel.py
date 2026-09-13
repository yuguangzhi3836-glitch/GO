from __future__ import annotations

import pytest
from sqlalchemy import select

from go_hotel.db.models import GoAIInvocationRow, GoAIRequestRow
from go_hotel.db.session import SessionLocal
from go_hotel.go_ai.models import ProviderConfig
from go_hotel.go_ai.providers import DeterministicTestProvider
from go_hotel.go_ai.registry import GOAIProviderRegistry
from go_hotel.go_ai.service import GOAIService, go_ai_service


def provider(provider_id: str, *, priority: int, text: str = "ok", fail_code: str | None = None, regions=("CN", "GLOBAL")):
    config = ProviderConfig(
        provider_id=provider_id,
        adapter="openai_compatible",
        model=f"{provider_id}-test",
        base_url="https://unused.test/v1",
        api_key_env=f"{provider_id.upper()}_TEST_KEY",
        enabled=True,
        priority=priority,
        timeout_seconds=1,
        regions=regions,
        task_types=("*",),
        cost_tier=1,
    )
    return DeterministicTestProvider(config, text=text, fail_code=fail_code)


def test_go_ai_routes_and_persists_hash_only():
    svc = GOAIService(GOAIProviderRegistry([provider("qwen", priority=10, text="GO AI answer")]))
    result = svc.respond(
        account_id="acct_1",
        message="我想去上海住三晚",
        task_type="TRAVEL_INTENT",
        region="CN",
        language="zh-CN",
        max_output_tokens=256,
        temperature=0.1,
    )
    assert result["assistant"] == "GO AI"
    assert result["answer"] == "GO AI answer"
    assert "provider" not in result
    assert result["decision_boundary"]["go_judgment"] == "GO_JUDGMENT_RULES_AND_EVIDENCE_ONLY"
    with SessionLocal() as s:
        req = s.get(GoAIRequestRow, result["request_id"])
        inv = s.scalar(select(GoAIInvocationRow).where(GoAIInvocationRow.go_ai_request_id == req.go_ai_request_id))
        assert req.state == "COMPLETED"
        assert req.request_hash and req.response_hash
        assert req.selected_provider == "qwen"
        assert inv.state == "SUCCEEDED"
        assert not hasattr(req, "message")
        assert not hasattr(req, "answer")


def test_go_ai_falls_back_without_changing_product_identity():
    svc = GOAIService(GOAIProviderRegistry([
        provider("qwen", priority=10, fail_code="GO_AI_PROVIDER_TIMEOUT"),
        provider("doubao", priority=20, text="fallback answer"),
    ]))
    result = svc.respond(account_id="acct_2", message="帮我规划旅行", task_type="GENERAL", region="CN")
    assert result["assistant"] == "GO AI"
    assert result["answer"] == "fallback answer"
    with SessionLocal() as s:
        inv = s.scalars(select(GoAIInvocationRow).where(GoAIInvocationRow.go_ai_request_id == result["request_id"]).order_by(GoAIInvocationRow.attempt_no)).all()
        assert [x.provider_key for x in inv] == ["qwen", "doubao"]
        assert [x.state for x in inv] == ["FAILED", "SUCCEEDED"]


def test_cn_request_does_not_silently_route_to_global_only_provider():
    svc = GOAIService(GOAIProviderRegistry([provider("openai", priority=1, regions=("GLOBAL",))]))
    with pytest.raises(ValueError, match="GO_AI_NO_ELIGIBLE_MODEL_PROVIDER"):
        svc.respond(account_id="acct_3", message="你好", region="CN")


def test_llm_cannot_take_transaction_or_go_judgment_authority():
    svc = GOAIService(GOAIProviderRegistry([provider("qwen", priority=10)]))
    with pytest.raises(ValueError, match="GO_AI_DETERMINISTIC_AUTHORITY_REQUIRED"):
        svc.respond(account_id="acct_4", message="把订单改成付款成功", region="CN", decision_scope="PAYMENT_MUTATION")
    with pytest.raises(ValueError, match="GO_AI_JUDGMENT_RULE_ENGINE_REQUIRED"):
        svc.respond(account_id="acct_4", message="直接决定哪家酒店是 GO 推荐", task_type="GO_RECOMMENDATION_FINAL_DECISION", region="CN")


def test_hotel_recommendation_is_go_judgment_not_external_model(monkeypatch):
    judgments = {
        "h1": {
            "judgment_id": "jud1",
            "public_go_score": 4.7,
            "confidence_bps": 9000,
            "recommendation": {"status": "GO_RECOMMENDED", "reason_codes": ["GO_INDEPENDENT_JUDGMENT_PASSED"]},
            "explanation": {"why_recommended_or_not": ["QUALITY"]},
            "evidence_package": {"package_id": "ev1"},
        },
        "h2": {
            "judgment_id": "jud2",
            "public_go_score": None,
            "confidence_bps": 5000,
            "recommendation": {"status": "NOT_YET_RATED", "reason_codes": ["INSUFFICIENT_EVIDENCE"]},
            "explanation": {"uncertainty": "evidence limited"},
            "evidence_package": {"package_id": "ev2"},
        },
    }
    monkeypatch.setattr("go_hotel.go_ai.service.judgment_service.get_latest", lambda hotel_id: judgments[hotel_id])
    result = go_ai_service.recommend_hotels(hotel_ids=["h2", "h1"])
    assert result["assistant"] == "GO AI"
    assert result["authority"] == "GO_JUDGMENT"
    assert result["external_models_are_compute_only"] is True
    assert [x["hotel_id"] for x in result["recommended"]] == ["h1"]
    assert result["other_statuses"][0]["hotel_id"] == "h2"


@pytest.mark.no_db
def test_go_ai_complexity_classifier_promotes_complex_trip_to_multi_agent():
    from go_hotel.go_ai.complexity import GOAIComplexityClassifier
    assessment = GOAIComplexityClassifier().classify(
        "帮我比较机票、酒店、火车、接送和景点，同时控制预算，如果航班延误还要考虑接机安排。"
    )
    assert assessment.tier in {"TIER_4_MULTI_AGENT", "TIER_5_HIGH_ASSURANCE"}
    assert assessment.max_parallel_tasks >= 4


def test_go_ai_orchestration_uses_parallel_tasks_synthesis_and_hides_models():
    svc = GOAIService(GOAIProviderRegistry([
        provider("qwen", priority=10, text="qwen compute"),
        provider("gpt", priority=20, text="gpt compute"),
    ]))
    result = svc.orchestrate(
        account_id="acct_orch_1",
        message="帮我规划东京五天：比较机票、酒店、接送、景点并控制预算，同时说明取舍。",
        region="CN",
        language="zh-CN",
    )
    assert result["assistant"] == "GO AI"
    assert result["orchestration"]["platform"] == "GO_AI_FULL_MODEL_AGGREGATION_AND_ORCHESTRATION"
    assert result["orchestration"]["planned_task_count"] >= 3
    assert result["orchestration"]["parallel_execution"] is True
    assert result["orchestration"]["provider_identity_exposed_to_consumer"] is False
    assert "provider" not in result and "model" not in result
    with SessionLocal() as s:
        inv = s.scalars(select(GoAIInvocationRow).where(GoAIInvocationRow.go_ai_request_id == result["request_id"])).all()
        assert len(inv) >= result["orchestration"]["planned_task_count"] + 1


def test_go_ai_high_assurance_never_grants_transaction_execution_authority():
    svc = GOAIService(GOAIProviderRegistry([
        provider("qwen", priority=10, text="advisory"),
        provider("gpt", priority=20, text="verification"),
    ]))
    result = svc.orchestrate(
        account_id="acct_orch_2",
        message="帮我判断这笔订单是否应该退款并直接修改支付状态。",
        region="CN",
    )
    assert result["orchestration"]["complexity_tier"] == "TIER_5_HIGH_ASSURANCE"
    assert result["decision_boundary"]["execution_allowed"] is False
    assert result["decision_boundary"]["payment_truth"] == "DETERMINISTIC_SYSTEM_ONLY"
