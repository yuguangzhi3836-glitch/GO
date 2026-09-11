"""Strict, non-executing task-routing data contracts for GO Command Center."""

from __future__ import annotations

from copy import deepcopy


MESSAGE_TYPES = {"discussion", "question", "task_candidate"}
COMPLEXITY_LEVELS = {"L1", "L2", "L3", "L4"}
RISK_LEVELS = {"low", "medium", "high", "critical"}
TASK_DRAFT_FIELDS = {
    "title",
    "objective",
    "task_type",
    "scope_in",
    "scope_out",
    "constraints",
    "acceptance_criteria",
    "complexity",
    "risk",
    "domains",
    "recommended_model_alias",
    "recommended_reasoning_level",
    "agent_plan",
    "requires_human_approval",
    "reason_summary",
}
AGENT_PLAN_FIELDS = {"role", "objective", "deliverables"}


class TaskRoutingValidationError(ValueError):
    """Raised when model or user data does not match the routing contract."""


def _text(value: object, field: str, maximum: int = 4000) -> str:
    if not isinstance(value, str):
        raise TaskRoutingValidationError(f"{field}_must_be_string")
    value = value.strip()
    if not value or len(value) > maximum:
        raise TaskRoutingValidationError(f"{field}_invalid_length")
    return value


def _text_list(value: object, field: str, maximum_items: int = 20) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum_items:
        raise TaskRoutingValidationError(f"{field}_must_be_list")
    return [_text(item, field, 1000) for item in value]


def validate_task_draft(value: object) -> dict:
    """Validate the exact persisted task-draft JSON shape."""
    if not isinstance(value, dict) or set(value) != TASK_DRAFT_FIELDS:
        raise TaskRoutingValidationError("task_draft_schema_mismatch")

    if value["complexity"] not in COMPLEXITY_LEVELS:
        raise TaskRoutingValidationError("invalid_complexity")
    if value["risk"] not in RISK_LEVELS:
        raise TaskRoutingValidationError("invalid_risk")
    if value["requires_human_approval"] is not True:
        raise TaskRoutingValidationError("requires_human_approval_must_be_true")

    agent_plan = value["agent_plan"]
    if not isinstance(agent_plan, list) or not agent_plan or len(agent_plan) > 12:
        raise TaskRoutingValidationError("agent_plan_must_be_nonempty_list")
    normalized_plan = []
    for item in agent_plan:
        if not isinstance(item, dict) or set(item) != AGENT_PLAN_FIELDS:
            raise TaskRoutingValidationError("agent_plan_schema_mismatch")
        normalized_plan.append({
            "role": _text(item["role"], "agent_role", 120),
            "objective": _text(item["objective"], "agent_objective", 1000),
            "deliverables": _text_list(item["deliverables"], "agent_deliverables", 12),
        })

    return {
        "title": _text(value["title"], "title", 160),
        "objective": _text(value["objective"], "objective", 2000),
        "task_type": _text(value["task_type"], "task_type", 80),
        "scope_in": _text_list(value["scope_in"], "scope_in"),
        "scope_out": _text_list(value["scope_out"], "scope_out"),
        "constraints": _text_list(value["constraints"], "constraints"),
        "acceptance_criteria": _text_list(value["acceptance_criteria"], "acceptance_criteria"),
        "complexity": value["complexity"],
        "risk": value["risk"],
        "domains": _text_list(value["domains"], "domains", 12),
        "recommended_model_alias": _text(value["recommended_model_alias"], "recommended_model_alias", 120),
        "recommended_reasoning_level": _text(value["recommended_reasoning_level"], "recommended_reasoning_level", 80),
        "agent_plan": normalized_plan,
        "requires_human_approval": value["requires_human_approval"],
        "reason_summary": _text(value["reason_summary"], "reason_summary", 1000),
    }


def validate_model_envelope(value: object, force_task_candidate: bool = False) -> dict:
    """Validate model classification without ever parsing a free-text draft."""
    required = {"message_type", "assistant_reply", "task_draft"}
    if not isinstance(value, dict) or set(value) != required:
        raise TaskRoutingValidationError("model_envelope_schema_mismatch")
    message_type = value["message_type"]
    if message_type not in MESSAGE_TYPES:
        raise TaskRoutingValidationError("invalid_message_type")
    if force_task_candidate and message_type != "task_candidate":
        raise TaskRoutingValidationError("forced_task_candidate_required")

    reply = _text(value["assistant_reply"], "assistant_reply", 12000)
    if message_type == "task_candidate":
        return {
            "message_type": message_type,
            "assistant_reply": reply,
            "task_draft": validate_task_draft(value["task_draft"]),
        }
    if value["task_draft"] is not None:
        raise TaskRoutingValidationError("non_task_message_must_not_have_draft")
    return {"message_type": message_type, "assistant_reply": reply, "task_draft": None}


def display_draft(value: dict) -> dict:
    """Return an isolated, JSON-safe copy for templates and API output."""
    return deepcopy(value)
