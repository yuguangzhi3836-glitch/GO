from __future__ import annotations
from dataclasses import dataclass
import uuid

from go_hotel.core.config import settings
from .contracts import CAPABILITIES, PRIVACY_CLASSES

QUALITY_FLOOR_CONFIDENCE = 0.82
QUALITY_FLOOR_EVAL_SCORE = 0.85
MAX_COST_PER_CALL_USD = 0.08
MAX_COST_PER_SESSION_USD = 0.50
MAX_INPUT_TOKENS = 32000
MAX_OUTPUT_TOKENS = 6000
TIMEOUT_MS = 30000
FALLBACK_ORDER = (0, 1, 2, 3)

@dataclass(frozen=True)
class RouteDecision:
    routing_decision_id: str
    capability: str
    tier: int
    tier_name: str
    external_egress: bool
    reason_codes: tuple[str, ...]
    cost_budget_usd: float
    latency_budget_ms: int
    quality_floor: float
    estimated_quality: float
    estimated_call_cost_usd: float
    session_spend_before_usd: float
    session_spend_after_usd: float
    input_tokens: int
    output_tokens: int
    price_snapshot_id: str
    model_version: str
    fallback_order: tuple[int, ...]
    circuit_open: bool

class ModelCostGovernor:
    TIER_NAMES={0:"RULE_SEARCH_DATABASE",1:"LOCAL_LIGHTWEIGHT_MODEL",2:"SELF_HOSTED_MEDIUM_MODEL",3:"EXTERNAL_FRONTIER_MODEL"}

    def route(
        self, *, capability:str, complexity:float, privacy_class:str,
        latency_budget_ms:int|None=None, cost_budget_usd:float|None=None,
        local_capability_available:bool=True, lightweight_available:bool=False,
        self_hosted_available:bool=False, explicit_external_policy:bool=False,
        estimated_quality:float=1.0, estimated_call_cost_usd:float=0.0,
        session_spend_usd:float=0.0, input_tokens:int=0, output_tokens:int=0,
        price_snapshot_id:str="LOCAL_ZERO_COST_V1", model_version:str="RULE_SEARCH_DATABASE",
        circuit_open:bool=False,
    ) -> RouteDecision:
        capability=capability.upper(); privacy_class=privacy_class.upper()
        if capability not in CAPABILITIES: raise ValueError("MODEL_GATEWAY_CAPABILITY_UNSUPPORTED")
        if privacy_class not in PRIVACY_CLASSES: raise ValueError("MODEL_GATEWAY_PRIVACY_CLASS_INVALID")
        complexity=max(0.0,min(float(complexity),1.0))
        estimated_quality=max(0.0,min(float(estimated_quality),1.0))
        call_cost=max(0.0,float(estimated_call_cost_usd))
        session_spend=max(0.0,float(session_spend_usd))
        input_tokens=max(0,int(input_tokens)); output_tokens=max(0,int(output_tokens))
        latency=min(max(1,int(latency_budget_ms or TIMEOUT_MS)),TIMEOUT_MS)
        cost=min(max(0.0,float(cost_budget_usd if cost_budget_usd is not None else MAX_COST_PER_CALL_USD)),MAX_COST_PER_CALL_USD)
        if input_tokens > MAX_INPUT_TOKENS: raise ValueError("MODEL_GATEWAY_INPUT_TOKEN_BUDGET_EXCEEDED")
        if output_tokens > MAX_OUTPUT_TOKENS: raise ValueError("MODEL_GATEWAY_OUTPUT_TOKEN_BUDGET_EXCEEDED")
        if call_cost > MAX_COST_PER_CALL_USD or call_cost > cost: raise ValueError("MODEL_GATEWAY_CALL_COST_BUDGET_EXCEEDED")
        if session_spend + call_cost > MAX_COST_PER_SESSION_USD: raise ValueError("MODEL_GATEWAY_SESSION_COST_BUDGET_EXCEEDED")
        if not price_snapshot_id: raise ValueError("MODEL_GATEWAY_PRICE_SNAPSHOT_REQUIRED")
        if not model_version: raise ValueError("MODEL_GATEWAY_MODEL_VERSION_REQUIRED")

        reasons=[]
        quality_met=estimated_quality >= QUALITY_FLOOR_CONFIDENCE
        # Always begin at the lowest-cost path and stop as soon as its quality floor is met.
        if local_capability_available and quality_met:
            tier=0; reasons.extend(("LOWEST_COST_RELIABLE_PATH","QUALITY_FLOOR_MET_STOP_ESCALATION"))
        elif lightweight_available and quality_met:
            tier=1; reasons.append("LOCAL_LIGHTWEIGHT_QUALITY_FLOOR_MET")
        elif self_hosted_available:
            tier=2; reasons.append("SELF_HOSTED_ESCALATION_AFTER_LOWER_TIER_QUALITY_MISS")
        elif local_capability_available:
            # A local deterministic path exists but quality was estimated below floor: fail closed rather than silently overspend.
            raise ValueError("MODEL_GATEWAY_QUALITY_FLOOR_NOT_MET")
        else:
            if circuit_open: raise ValueError("MODEL_GATEWAY_CIRCUIT_OPEN")
            external_allowed=(settings.model_gateway_external_egress_enabled and explicit_external_policy and privacy_class != "SENSITIVE")
            if not external_allowed: raise ValueError("MODEL_GATEWAY_EXTERNAL_EGRESS_DENIED")
            tier=3; reasons.append("EXPLICIT_EXTERNAL_ESCALATION_AFTER_LOCAL_UNAVAILABLE")

        external=tier==3
        if external and privacy_class=="SENSITIVE": raise ValueError("MODEL_GATEWAY_SENSITIVE_EXTERNAL_EGRESS_DENIED")
        if external and circuit_open: raise ValueError("MODEL_GATEWAY_CIRCUIT_OPEN")
        return RouteDecision(
            f"route_{uuid.uuid4().hex}", capability, tier, self.TIER_NAMES[tier], external, tuple(reasons),
            cost, latency, QUALITY_FLOOR_CONFIDENCE, estimated_quality, call_cost,
            session_spend, session_spend + call_cost, input_tokens, output_tokens,
            price_snapshot_id, model_version, FALLBACK_ORDER, circuit_open,
        )

model_cost_governor=ModelCostGovernor()
