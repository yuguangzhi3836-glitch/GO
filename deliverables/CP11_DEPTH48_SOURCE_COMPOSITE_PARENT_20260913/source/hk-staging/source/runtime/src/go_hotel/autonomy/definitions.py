from __future__ import annotations

from .registry import ContractEventRegistry, DomainOwnershipRegistry
from .types import CellDefinition, ContractDefinition, EventDefinition


def _cell(cell_id: str, name: str, domain: str, truth: str, *capabilities: str, forbidden=()) -> CellDefinition:
    # Legal accountability intentionally remains unbound in Build 01. Production qualification is fail-closed
    # until a Named Human Role + Legal Entity are provided by the Human Constitutional Core.
    return CellDefinition(
        cell_id=cell_id,
        name=name,
        domain=domain,
        truth_owned=truth,
        capabilities=frozenset(capabilities),
        forbidden_capabilities=frozenset(forbidden),
    )


CELLS = (
    _cell("C01", "Hotel AI Operations Cell", "HOTEL", "HOTEL_DOMAIN_TRUTH", "HOTEL_ENTITY", "HOTEL_CONTENT", "HOTEL_SUPPLY", "HOTEL_RATE_INVENTORY", "HOTEL_EXCEPTION"),
    _cell("C02", "Flight AI Operations Cell", "FLIGHT", "FLIGHT_DOMAIN_TRUTH", "FLIGHT_PROVIDER", "FLIGHT_SEARCH", "FLIGHT_FARE_RULE", "FLIGHT_CHANGE_CANCEL", "FLIGHT_FULFILLMENT", "FLIGHT_EXCEPTION"),
    _cell("C03", "Rail AI Operations Cell", "RAIL", "RAIL_DOMAIN_TRUTH", "RAIL_PROVIDER", "RAIL_SEARCH", "RAIL_FARE_RULE", "RAIL_CHANGE_CANCEL", "RAIL_FULFILLMENT", "RAIL_EXCEPTION"),
    _cell("C04", "Rental AI Operations Cell", "RENTAL", "RENTAL_DOMAIN_TRUTH", "RENTAL_PROVIDER", "RENTAL_ELIGIBILITY", "RENTAL_INSURANCE_DEPOSIT", "RENTAL_PICKUP_RETURN", "RENTAL_CANCEL_FULFILLMENT"),
    _cell("C05", "Ride AI Operations Cell", "RIDE", "RIDE_DOMAIN_TRUTH", "RIDE_PROVIDER", "RIDE_BOOKING", "RIDE_DRIVER_FULFILLMENT", "RIDE_TRANSFER", "RIDE_CANCEL_EXCEPTION"),
    _cell("C06", "Attraction AI Operations Cell", "ATTRACTION", "ATTRACTION_DOMAIN_TRUTH", "ATTRACTION_PROVIDER", "ATTRACTION_INVENTORY_SLOT", "ATTRACTION_VOUCHER", "ATTRACTION_CANCEL", "ATTRACTION_FULFILLMENT"),
    _cell("C07", "Traveler Intelligence Cell", "TRAVELER_INTELLIGENCE", "TRAVELER_CONTEXT_TRUTH", "SESSION_INTENT", "TRAVELER_GRAPH", "PREFERENCE", "IDENTITY_CONTEXT", "TRAVEL_BEHAVIOR", "TRAVELER_CONTEXT_EVIDENCE", forbidden=("RECOMMENDATION_TRUTH_MUTATION",)),
    _cell("C08", "GO AI Planning & Execution Cell", "GO_AI_PLAN", "PLAN", "CONVERSATION", "INTENT_UNDERSTANDING", "PLANNING", "TRIP_COMPOSITION", "TOOL_ORCHESTRATION", "MULTI_VERTICAL_COORDINATION", forbidden=("JOURNEY_TRUTH_MUTATION", "TRANSACTION_TRUTH_MUTATION", "RECOMMENDATION_TRUTH_MUTATION")),
    _cell("C09", "GO Judgment & Trust Cell", "GO_JUDGMENT", "RECOMMENDATION_TRUTH", "GO_RECOMMENDATION", "QUALITY_JUDGMENT", "TRUST", "RECOMMENDATION_EVIDENCE", "RECOMMENDATION_EXPLANATION"),
    _cell("C10", "Unified Trips Cell", "UNIFIED_TRIPS", "JOURNEY_TRUTH", "TRIP_STATE", "JOURNEY_TIMELINE", "CROSS_VERTICAL_PROJECTION", "JOURNEY_EXCEPTION"),
    _cell("C11", "Transaction & Finance Cell", "TRANSACTION_FINANCE", "TRANSACTION_TRUTH", "ORDER_STATE", "PAYMENT_INTENT", "LEDGER", "REFUND", "SETTLEMENT", "RECONCILIATION"),
    _cell("C12", "Platform / Security / Model Gateway Cell", "PLATFORM_SECURITY_MODEL_GATEWAY", "SECURITY_AND_PLATFORM_CONTROL_TRUTH", "MODEL_GATEWAY", "MODEL_COST_GOVERNOR", "IAM", "SECRETS", "EVENT_INFRASTRUCTURE", "POLICY_ENFORCEMENT", "OBSERVABILITY"),
    _cell("C13", "Independent QA & Release Cell", "INDEPENDENT_QA_RELEASE", "RELEASE_QUALIFICATION_TRUTH", "INDEPENDENT_VALIDATION", "REGRESSION", "SECURITY_VALIDATION", "RELEASE_GATE", "ROLLBACK_VALIDATION", forbidden=("BUSINESS_FEATURE_IMPLEMENTATION",)),
)

DOMAIN_OWNERSHIP = DomainOwnershipRegistry(CELLS)

CONTRACTS = (
    ContractDefinition("VERTICAL_TO_TRIPS_STATE_V1", "C10", ("C01", "C02", "C03", "C04", "C05", "C06"), "Canonical contract schema for vertical state projection into Journey Truth."),
    ContractDefinition("PLAN_TO_VERTICAL_TASK_V1", "C08", ("C01", "C02", "C03", "C04", "C05", "C06"), "Plan-owned task dispatch without cross-domain truth mutation."),
    ContractDefinition("TRANSACTION_COMMAND_V1", "C11", ("C01", "C02", "C03", "C04", "C05", "C06", "C10"), "Governed transaction command/result boundary."),
    ContractDefinition("JUDGMENT_EVIDENCE_V1", "C09", ("C08", "C10"), "Recommendation Truth evidence consumption without commercial mutation."),
    ContractDefinition("TRAVELER_CONTEXT_V1", "C07", ("C08", "C09"), "Purpose-bound traveler/context evidence only; never GO Judgment or Recommendation truth."),
)

EVENTS = (
    EventDefinition("VERTICAL_STATE_VERIFIED", "C01", ("C10", "C11")),
    EventDefinition("FLIGHT_STATE_VERIFIED", "C02", ("C10", "C05", "C11")),
    EventDefinition("RAIL_STATE_VERIFIED", "C03", ("C10", "C11")),
    EventDefinition("RENTAL_STATE_VERIFIED", "C04", ("C10", "C11")),
    EventDefinition("RIDE_STATE_VERIFIED", "C05", ("C10", "C11")),
    EventDefinition("ATTRACTION_STATE_VERIFIED", "C06", ("C10", "C11")),
    EventDefinition("RECOMMENDATION_DECISION_VERIFIED", "C09", ("C08", "C10")),
    EventDefinition("TRANSACTION_STATE_VERIFIED", "C11", ("C10",)),
)

CONTRACT_EVENT_REGISTRY = ContractEventRegistry(cells=DOMAIN_OWNERSHIP, contracts=CONTRACTS, events=EVENTS)


C14_AI_LEGAL = _cell(
    "C14",
    "AI Constitutional, Legal & Regulatory Control Cell",
    "AI_CONSTITUTIONAL_LEGAL_REGULATORY_CONTROL",
    "CONSTITUTIONAL_LEGAL_COMPLIANCE_DECISION_TRUTH",
    "GO_CONSTITUTION_REVIEW",
    "AUTHORITY_CONSTITUTION_REVIEW",
    "LEGAL_EXPOSURE_ROUTING",
    "JURISDICTION_RESOLUTION",
    "LAW_REGULATION_POLICY_MAPPING",
    "CONTRACT_COMPLIANCE",
    "AI_ACTION_LEGAL_REVIEW",
    "LEGAL_EVIDENCE_AUDIT",
    "REGULATORY_CHANGE_ANALYSIS",
    forbidden=("BUSINESS_DOMAIN_TRUTH_MUTATION", "SELF_AUTHORITY_EXPANSION"),
)

# Build 01's CELLS remains the 13 existing permanent cells for backward-compatible verification.
# Build 01.1 adds C14 as an independent control cell.
ALL_CELLS = CELLS + (C14_AI_LEGAL,)
ALL_CELL_REGISTRY = DomainOwnershipRegistry(ALL_CELLS)
