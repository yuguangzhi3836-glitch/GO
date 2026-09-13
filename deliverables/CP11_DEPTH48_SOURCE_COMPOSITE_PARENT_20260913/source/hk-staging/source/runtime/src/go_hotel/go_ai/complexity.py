from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ComplexityAssessment:
    tier: str
    score: int
    reasons: tuple[str, ...]
    max_parallel_tasks: int
    requires_model_verification: bool
    requires_deterministic_gate: bool


class GOAIComplexityClassifier:
    """Deterministic first-pass complexity/risk classifier owned by GO.

    It does not ask an external model to decide routing authority. The goal is
    to spend cheap compute on simple requests and reserve multi-model work for
    genuinely complex tasks.
    """

    _HIGH_ASSURANCE_TERMS = (
        "付款", "支付", "退款", "扣款", "改订单", "取消订单", "修改订单",
        "pay", "payment", "refund", "charge", "cancel order", "modify order",
    )
    _MULTI_DOMAIN_TERMS = (
        "酒店", "机票", "航班", "火车", "高铁", "接送", "租车", "门票", "景点",
        "hotel", "flight", "rail", "train", "transfer", "rental", "attraction",
    )
    _COMPLEX_CONNECTORS = (
        "同时", "并且", "另外", "预算", "比较", "权衡", "如果", "但是", "以及",
        "and", "also", "budget", "compare", "tradeoff", "if", "but",
    )

    def classify(self, message: str, *, context: dict | None = None) -> ComplexityAssessment:
        text = (message or "").strip().lower()
        ctx = context or {}
        if ctx.get("deterministic_only") is True:
            return ComplexityAssessment("TIER_0_DETERMINISTIC", 0, ("CONTEXT_DETERMINISTIC_ONLY",), 0, False, True)

        score = 0
        reasons: list[str] = []
        if len(text) > 900:
            score += 3; reasons.append("LONG_INPUT")
        elif len(text) > 350:
            score += 2; reasons.append("MEDIUM_INPUT")
        elif len(text) > 120:
            score += 1; reasons.append("NONTRIVIAL_INPUT")

        domains = sum(1 for term in self._MULTI_DOMAIN_TERMS if term in text)
        if domains >= 4:
            score += 4; reasons.append("MULTI_VERTICAL_4_PLUS")
        elif domains >= 2:
            score += 2; reasons.append("MULTI_VERTICAL")

        connectors = sum(1 for term in self._COMPLEX_CONNECTORS if term in text)
        if connectors >= 4:
            score += 3; reasons.append("MANY_CONSTRAINTS")
        elif connectors >= 2:
            score += 1; reasons.append("MULTIPLE_CONSTRAINTS")

        high_assurance = any(term in text for term in self._HIGH_ASSURANCE_TERMS)
        if high_assurance:
            return ComplexityAssessment(
                "TIER_5_HIGH_ASSURANCE",
                max(score, 9),
                tuple(reasons + ["TRANSACTION_OR_MONEY_SENSITIVE"]),
                4,
                True,
                True,
            )
        if score >= 7:
            return ComplexityAssessment("TIER_4_MULTI_AGENT", score, tuple(reasons), 6, True, False)
        if score >= 5:
            return ComplexityAssessment("TIER_3_DEEP_REASONING", score, tuple(reasons), 4, True, False)
        if score >= 2:
            return ComplexityAssessment("TIER_2_STANDARD", score, tuple(reasons), 2, False, False)
        return ComplexityAssessment("TIER_1_FAST", score, tuple(reasons or ["SIMPLE_REQUEST"]), 1, False, False)
