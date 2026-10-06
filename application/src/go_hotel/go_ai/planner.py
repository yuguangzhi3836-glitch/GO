from __future__ import annotations

from dataclasses import dataclass

from .complexity import ComplexityAssessment


@dataclass(frozen=True)
class PlannedTask:
    task_id: str
    task_type: str
    instruction: str
    required: bool = True


class GOAITaskPlanner:
    """GO-owned deterministic task planner for multi-model orchestration."""

    def plan(self, message: str, assessment: ComplexityAssessment) -> list[PlannedTask]:
        text = (message or "").lower()
        if assessment.tier == "TIER_0_DETERMINISTIC":
            return []
        if assessment.tier in {"TIER_1_FAST", "TIER_2_STANDARD"}:
            return [PlannedTask("task_main", "GENERAL", f"Answer the user request accurately and concisely:\n{message}")]

        tasks: list[PlannedTask] = []
        verticals = [
            (("机票", "航班", "flight"), "task_flight", "TRIP_PLANNING", "Analyze flight/air-travel options, constraints and trade-offs."),
            (("酒店", "hotel"), "task_hotel", "HOTEL_JUDGMENT_SUPPORT", "Analyze hotel/stay needs, constraints and decision factors. Do not make final GO Recommendation authority claims."),
            (("火车", "高铁", "rail", "train"), "task_rail", "TRIP_PLANNING", "Analyze rail options, timing and trade-offs."),
            (("接送", "租车", "用车", "transfer", "rental", "car"), "task_mobility", "TRIP_PLANNING", "Analyze ground transport, transfer and rental needs."),
            (("门票", "景点", "attraction", "ticket"), "task_attraction", "TRIP_PLANNING", "Analyze attraction/ticket needs and schedule constraints."),
            (("预算", "budget", "价格", "cost"), "task_budget", "EXPLANATION", "Analyze budget allocation and cost trade-offs without inventing prices."),
        ]
        for terms, task_id, task_type, instruction in verticals:
            if any(term in text for term in terms):
                tasks.append(PlannedTask(task_id, task_type, f"{instruction}\nUser request:\n{message}"))

        tasks.append(PlannedTask(
            "task_constraints",
            "EXTRACTION",
            "Extract the user's explicit constraints, preferences, uncertainties and must-not-assume items.\nUser request:\n" + message,
        ))
        if assessment.tier in {"TIER_3_DEEP_REASONING", "TIER_4_MULTI_AGENT", "TIER_5_HIGH_ASSURANCE"}:
            tasks.append(PlannedTask(
                "task_reasoning",
                "EXPLANATION",
                "Independently reason about the request, identify missing facts, conflicts and decision trade-offs. Do not invent external facts.\nUser request:\n" + message,
            ))
        if assessment.tier == "TIER_5_HIGH_ASSURANCE":
            tasks.append(PlannedTask(
                "task_risk",
                "VERIFICATION",
                "Identify transaction, payment, refund, supplier-fact or authorization risks. Advisory only; deterministic GO systems retain authority.\nUser request:\n" + message,
            ))

        # Preserve the full deterministic plan. The service already enforces the
        # parallel worker budget, so truncating here silently drops required
        # high-assurance stages.
        dedup: dict[str, PlannedTask] = {t.task_id: t for t in tasks}
        return list(dedup.values())
