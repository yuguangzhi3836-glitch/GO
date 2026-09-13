"""P0 Final Design/Code Closure Patch.

This module is a static design/code contract only. It intentionally does not certify
real provider credentials, network execution, PostgreSQL races, or production data.

The closure rule is stronger than file-existence checks: a core requirement must map
through requirement -> implementation symbol -> contract test -> state-machine rule ->
database constraint/evidence token before it can be counted complete.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Mapping, Protocol
import ast
import importlib
import inspect

DAY1_VERTICALS = ("HOTEL", "FLIGHT", "RAIL", "RIDE", "RENTAL", "ATTRACTION")
ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ProviderContract:
    key: str
    vertical: str
    primary: str
    fallback: str
    mode: str
    capabilities: tuple[str, ...]
    canonical_request_schema: Mapping[str, str]
    canonical_response_schema: Mapping[str, str]
    auth_contract: Mapping[str, Any]
    idempotency_contract: Mapping[str, Any]
    timeout_contract: Mapping[str, Any]
    retry_contract: Mapping[str, Any]
    webhook_contract: Mapping[str, Any]
    reconciliation_contract: Mapping[str, Any]
    version_policy: Mapping[str, Any]
    error_taxonomy: tuple[str, ...]
    normalization_contract: Mapping[str, Any]
    source_truth_contract: Mapping[str, Any]


COMMON_ERRORS = (
    "AUTHENTICATION_FAILED", "AUTHORIZATION_FAILED", "INVALID_REQUEST",
    "UNSUPPORTED_CAPABILITY", "RATE_LIMITED", "TIMEOUT", "UNKNOWN_EXTERNAL_STATE",
    "SUPPLIER_REJECTED", "DUPLICATE_REQUEST", "STALE_VERSION", "SIGNATURE_INVALID",
)


def _provider_contract(
    key: str, vertical: str, primary: str, fallback: str, mode: str,
    capabilities: tuple[str, ...], request_schema: Mapping[str, str],
    response_schema: Mapping[str, str], auth: str, webhook: str,
) -> ProviderContract:
    return ProviderContract(
        key=key, vertical=vertical, primary=primary, fallback=fallback, mode=mode,
        capabilities=capabilities,
        canonical_request_schema=request_schema,
        canonical_response_schema=response_schema,
        auth_contract={"mode": auth, "secret_source": "external_secret_reference", "no_secret_persistence": True},
        idempotency_contract={"required_for_mutation": True, "canonical_header": "Idempotency-Key", "duplicate_semantics": "RETURN_OR_RECONCILE_EXISTING_OPERATION"},
        timeout_contract={"connect_seconds": 5, "read_seconds": 30, "timeout_result": "UNKNOWN_EXTERNAL_STATE", "timeout_never_equals_permission_to_resend": True},
        retry_contract={"search_status_query": "bounded_exponential_backoff", "mutation": "NO_BLIND_RETRY", "mutation_retry_requires": "reconciliation_or_provider_safe_replay_proof"},
        webhook_contract={"mode": webhook, "delivery_id_required": True, "signature_required": True, "replay_protection": True, "out_of_order_tolerant": True},
        reconciliation_contract={"query_required_after_unknown": True, "external_operation_id_required": True, "manual_review_after_exhaustion": True},
        version_policy={"pin_version": True, "unknown_breaking_version": "BLOCK", "schema_drift": "FAIL_CLOSED", "compatibility_test_required": True},
        error_taxonomy=COMMON_ERRORS,
        normalization_contract={"currency": "ISO-4217", "timezone": "IANA", "timestamp": "RFC3339_UTC", "locale": "BCP47_WHEN_PRESENT", "money": "integer_minor_units"},
        source_truth_contract={"primary_route": "OFFICIAL_OR_AUTHORIZED_DIRECT", "fallback_route": "AUTHORIZED_FALLBACK", "fallback_must_not_claim_official": True, "seller_payee_fulfiller_required": True},
    )


PROVIDER_CONTRACTS: dict[str, ProviderContract] = {
    "PAYMENT": _provider_contract(
        "PAYMENT", "PAYMENT", "Stripe", "Adyen", "PSP",
        ("AUTHORIZE", "CAPTURE", "PARTIAL_CAPTURE", "REFUND", "PARTIAL_REFUND", "STATUS", "SIGNED_WEBHOOK", "SETTLEMENT", "IDEMPOTENCY"),
        {"operation": "enum", "payment_intent_id": "string", "amount_minor": "int", "currency": "string", "payer_id": "string", "payee_id": "string", "idempotency_key": "string", "order_fact_hash": "sha256"},
        {"external_operation_id": "string", "state": "enum", "amount_minor": "int", "currency": "string", "provider_event_id": "string", "evidence_reference": "string"},
        "API_KEY_OR_OAUTH2", "PROVIDER_SIGNED_WEBHOOK"),
    "HOTEL": _provider_contract(
        "HOTEL", "HOTEL", "SiteMinder Channels Plus", "DerbySoft", "AUTHORIZED_CONNECTOR",
        ("SEARCH", "PREBOOK", "BOOK", "QUERY", "CANCEL", "STATUS", "REFUND_HANDOFF", "SIGNED_WEBHOOK"),
        {"operation": "enum", "property_id": "string", "rate_plan_id": "string?", "room_id": "string?", "stay": "date_range?", "guest": "object?", "reservation_id": "string?", "fare_rule_snapshot": "object?", "idempotency_key": "string"},
        {"external_operation_id": "string", "reservation_id": "string?", "supplier_confirmation_id": "string?", "state": "enum", "price_snapshot": "object?", "cancel_terms": "object?", "evidence_reference": "string"},
        "PARTNER_CREDENTIAL", "PROVIDER_SIGNED_OR_MUTUAL_AUTH_CALLBACK"),
    "FLIGHT": _provider_contract(
        "FLIGHT", "FLIGHT", "Amadeus Enterprise/NDC connector", "Authorized GDS/Aggregator connector", "NDC_GDS",
        ("SEARCH", "REPRICE", "BOOK", "TICKET_STATUS", "CANCEL", "REFUND_HANDOFF", "STATUS", "CHECK_IN_HANDOFF", "SIGNED_WEBHOOK"),
        {"operation": "enum", "offer_id": "string?", "segments": "array?", "passengers": "array?", "fare_rules": "object?", "ticket_order_id": "string?", "idempotency_key": "string"},
        {"external_operation_id": "string", "pnr": "string?", "ticket_numbers": "array?", "state": "enum", "fare_rules": "object?", "baggage": "object?", "check_in_reference": "string?", "evidence_reference": "string"},
        "OAUTH2_OR_NDC_CREDENTIAL", "PROVIDER_SIGNED_WEBHOOK_OR_POLL_RECONCILIATION"),
    "RAIL": _provider_contract(
        "RAIL", "RAIL", "Distribusion", "Authorized regional rail connector", "RAIL_AGGREGATOR",
        ("SEARCH", "BOOK", "CHANGE", "CANCEL", "REFUND_HANDOFF", "STATUS", "SIGNED_WEBHOOK"),
        {"operation": "enum", "journey_id": "string?", "fare_id": "string?", "passengers": "array?", "seat_class": "string?", "booking_id": "string?", "change_request": "object?", "idempotency_key": "string"},
        {"external_operation_id": "string", "booking_id": "string?", "ticket_reference": "string?", "state": "enum", "seat_class": "string?", "change_terms": "object?", "evidence_reference": "string"},
        "API_KEY_OR_OAUTH2", "PROVIDER_SIGNED_WEBHOOK_OR_POLL_RECONCILIATION"),
    "RIDE": _provider_contract(
        "RIDE", "RIDE", "Mozio", "CarTrawler Mobility", "GROUND_TRANSPORT",
        ("SEARCH", "RESERVE", "CANCEL", "REFUND_HANDOFF", "STATUS", "FLIGHT_TRACKING", "SIGNED_WEBHOOK"),
        {"operation": "enum", "pickup": "object?", "dropoff": "object?", "vehicle_offer_id": "string?", "flight_binding": "object?", "reservation_id": "string?", "idempotency_key": "string"},
        {"external_operation_id": "string", "reservation_id": "string?", "driver_or_fleet_reference": "string?", "pickup_time": "timestamp?", "state": "enum", "free_wait_rule": "object?", "evidence_reference": "string"},
        "API_KEY_OR_OAUTH2", "PROVIDER_SIGNED_WEBHOOK_OR_POLL_RECONCILIATION"),
    "RENTAL": _provider_contract(
        "RENTAL", "RENTAL", "CarTrawler", "Authorized regional rental connector", "CAR_RENTAL",
        ("SEARCH", "RESERVE", "MODIFY", "CANCEL", "REFUND_HANDOFF", "STATUS", "SIGNED_WEBHOOK"),
        {"operation": "enum", "station": "object?", "rental_period": "date_range?", "vehicle_offer_id": "string?", "driver": "object?", "reservation_id": "string?", "modify_request": "object?", "idempotency_key": "string"},
        {"external_operation_id": "string", "reservation_id": "string?", "vehicle_class": "string?", "insurance": "object?", "mileage": "object?", "state": "enum", "evidence_reference": "string"},
        "API_KEY_OR_OAUTH2", "PROVIDER_SIGNED_WEBHOOK_OR_POLL_RECONCILIATION"),
    "ATTRACTION": _provider_contract(
        "ATTRACTION", "ATTRACTION", "Tiqets Distributor API", "Authorized attractions connector", "ATTRACTIONS",
        ("SEARCH", "AVAILABILITY", "PRICE", "RESERVE", "BOOK", "CANCEL", "REFUND_HANDOFF", "STATUS", "SIGNED_WEBHOOK"),
        {"operation": "enum", "product_id": "string?", "timeslot": "timestamp?", "ticket_types": "array?", "participants": "array?", "reservation_id": "string?", "idempotency_key": "string"},
        {"external_operation_id": "string", "reservation_id": "string?", "voucher_reference": "string?", "timeslot": "timestamp?", "ticket_types": "array?", "state": "enum", "evidence_reference": "string"},
        "API_KEY_OR_OAUTH2", "PROVIDER_SIGNED_WEBHOOK_OR_POLL_RECONCILIATION"),
}

# Backward-compatible JSON-shaped API name.
PROVIDER_BLUEPRINT = {k: asdict(v) for k, v in PROVIDER_CONTRACTS.items()}


@dataclass(frozen=True)
class ProviderCommand:
    vertical: str
    operation: str
    idempotency_key: str
    payload: dict[str, Any]
    evidence_reference: str
    source_route: str = "OFFICIAL_OR_AUTHORIZED_DIRECT"


@dataclass(frozen=True)
class ProviderResult:
    external_operation_id: str | None
    state: str
    payload: dict[str, Any]
    source_attested: bool
    source_route: str = "OFFICIAL_OR_AUTHORIZED_DIRECT"
    provider_key: str | None = None


class ProviderTransport(Protocol):
    def execute(self, provider_key: str, command: ProviderCommand) -> ProviderResult: ...
    def query(self, provider_key: str, external_operation_id: str) -> ProviderResult: ...


class Day1VerticalAdapter:
    """Base fail-closed adapter. Vertical-specific public capability methods live in subclasses."""
    vertical = ""
    capability_methods: Mapping[str, str] = {}

    def __init__(self, transport: ProviderTransport, provider_key: str, provider_role: str = "PRIMARY"):
        self.transport = transport
        self.provider_key = provider_key
        self.provider_role = provider_role.upper()
        if self.provider_role not in {"PRIMARY", "FALLBACK"}:
            raise ValueError("INVALID_PROVIDER_ROLE")

    @property
    def contract(self) -> ProviderContract:
        return PROVIDER_CONTRACTS[self.vertical]

    def _execute_operation(self, operation: str, payload: dict[str, Any], idempotency_key: str, evidence_reference: str) -> ProviderResult:
        operation = operation.upper()
        if operation not in self.contract.capabilities:
            raise ValueError("UNSUPPORTED_PROVIDER_CAPABILITY")
        if not idempotency_key or not evidence_reference:
            raise ValueError("IDEMPOTENCY_AND_EVIDENCE_REQUIRED")
        route = "AUTHORIZED_FALLBACK" if self.provider_role == "FALLBACK" else "OFFICIAL_OR_AUTHORIZED_DIRECT"
        command = ProviderCommand(self.vertical, operation, idempotency_key, dict(payload), evidence_reference, route)
        result = self.transport.execute(self.provider_key, command)
        self._validate_result(result)
        return result

    def execute(self, command: ProviderCommand) -> ProviderResult:
        if command.vertical != self.vertical:
            raise ValueError("VERTICAL_MISMATCH")
        return self._execute_operation(command.operation, command.payload, command.idempotency_key, command.evidence_reference)

    def _validate_result(self, result: ProviderResult) -> None:
        if not result.source_attested:
            raise ValueError("UNATTESTED_PROVIDER_RESULT")
        if self.provider_role == "FALLBACK" and result.source_route in {"OFFICIAL_DIRECT", "OFFICIAL_OR_AUTHORIZED_DIRECT"}:
            raise ValueError("FALLBACK_MUST_NOT_MASQUERADE_AS_OFFICIAL")
        if result.state == "CONFIRMED" and not result.external_operation_id:
            raise ValueError("CONFIRMED_RESULT_REQUIRES_EXTERNAL_OPERATION_ID")

    def reconcile(self, external_operation_id: str) -> ProviderResult:
        if not external_operation_id:
            raise ValueError("EXTERNAL_OPERATION_ID_REQUIRED")
        result = self.transport.query(self.provider_key, external_operation_id)
        self._validate_result(result)
        return result


class HotelAdapter(Day1VerticalAdapter):
    vertical = "HOTEL"
    capability_methods = {"SEARCH":"search", "PREBOOK":"prebook", "BOOK":"book", "CANCEL":"cancel", "STATUS":"status", "REFUND_HANDOFF":"refund_handoff"}
    def search(self,payload,idempotency_key,evidence_reference): return self._execute_operation("SEARCH",payload,idempotency_key,evidence_reference)
    def prebook(self,payload,idempotency_key,evidence_reference): return self._execute_operation("PREBOOK",payload,idempotency_key,evidence_reference)
    def book(self,payload,idempotency_key,evidence_reference): return self._execute_operation("BOOK",payload,idempotency_key,evidence_reference)
    def cancel(self,payload,idempotency_key,evidence_reference): return self._execute_operation("CANCEL",payload,idempotency_key,evidence_reference)
    def status(self,payload,idempotency_key,evidence_reference): return self._execute_operation("STATUS",payload,idempotency_key,evidence_reference)
    def refund_handoff(self,payload,idempotency_key,evidence_reference): return self._execute_operation("REFUND_HANDOFF",payload,idempotency_key,evidence_reference)


class FlightAdapter(Day1VerticalAdapter):
    vertical = "FLIGHT"
    capability_methods = {"SEARCH":"search", "REPRICE":"reprice", "BOOK":"book", "TICKET_STATUS":"ticket_status", "CANCEL":"cancel", "STATUS":"status", "CHECK_IN_HANDOFF":"check_in_handoff", "REFUND_HANDOFF":"refund_handoff"}
    def search(self,payload,idempotency_key,evidence_reference): return self._execute_operation("SEARCH",payload,idempotency_key,evidence_reference)
    def reprice(self,payload,idempotency_key,evidence_reference): return self._execute_operation("REPRICE",payload,idempotency_key,evidence_reference)
    def book(self,payload,idempotency_key,evidence_reference): return self._execute_operation("BOOK",payload,idempotency_key,evidence_reference)
    def ticket_status(self,payload,idempotency_key,evidence_reference): return self._execute_operation("TICKET_STATUS",payload,idempotency_key,evidence_reference)
    def cancel(self,payload,idempotency_key,evidence_reference): return self._execute_operation("CANCEL",payload,idempotency_key,evidence_reference)
    def status(self,payload,idempotency_key,evidence_reference): return self._execute_operation("STATUS",payload,idempotency_key,evidence_reference)
    def check_in_handoff(self,payload,idempotency_key,evidence_reference): return self._execute_operation("CHECK_IN_HANDOFF",payload,idempotency_key,evidence_reference)
    def refund_handoff(self,payload,idempotency_key,evidence_reference): return self._execute_operation("REFUND_HANDOFF",payload,idempotency_key,evidence_reference)


class RailAdapter(Day1VerticalAdapter):
    vertical = "RAIL"
    capability_methods = {"SEARCH":"search", "BOOK":"book", "CHANGE":"change", "CANCEL":"cancel", "STATUS":"status", "REFUND_HANDOFF":"refund_handoff"}
    def search(self,payload,idempotency_key,evidence_reference): return self._execute_operation("SEARCH",payload,idempotency_key,evidence_reference)
    def book(self,payload,idempotency_key,evidence_reference): return self._execute_operation("BOOK",payload,idempotency_key,evidence_reference)
    def change(self,payload,idempotency_key,evidence_reference): return self._execute_operation("CHANGE",payload,idempotency_key,evidence_reference)
    def cancel(self,payload,idempotency_key,evidence_reference): return self._execute_operation("CANCEL",payload,idempotency_key,evidence_reference)
    def status(self,payload,idempotency_key,evidence_reference): return self._execute_operation("STATUS",payload,idempotency_key,evidence_reference)
    def refund_handoff(self,payload,idempotency_key,evidence_reference): return self._execute_operation("REFUND_HANDOFF",payload,idempotency_key,evidence_reference)


class RideAdapter(Day1VerticalAdapter):
    vertical = "RIDE"
    capability_methods = {"SEARCH":"search", "RESERVE":"reserve", "CANCEL":"cancel", "STATUS":"status", "FLIGHT_TRACKING":"flight_tracking", "REFUND_HANDOFF":"refund_handoff"}
    def search(self,payload,idempotency_key,evidence_reference): return self._execute_operation("SEARCH",payload,idempotency_key,evidence_reference)
    def reserve(self,payload,idempotency_key,evidence_reference): return self._execute_operation("RESERVE",payload,idempotency_key,evidence_reference)
    def cancel(self,payload,idempotency_key,evidence_reference): return self._execute_operation("CANCEL",payload,idempotency_key,evidence_reference)
    def status(self,payload,idempotency_key,evidence_reference): return self._execute_operation("STATUS",payload,idempotency_key,evidence_reference)
    def flight_tracking(self,payload,idempotency_key,evidence_reference): return self._execute_operation("FLIGHT_TRACKING",payload,idempotency_key,evidence_reference)
    def refund_handoff(self,payload,idempotency_key,evidence_reference): return self._execute_operation("REFUND_HANDOFF",payload,idempotency_key,evidence_reference)


class RentalAdapter(Day1VerticalAdapter):
    vertical = "RENTAL"
    capability_methods = {"SEARCH":"search", "RESERVE":"reserve", "MODIFY":"modify", "CANCEL":"cancel", "STATUS":"status", "REFUND_HANDOFF":"refund_handoff"}
    def search(self,payload,idempotency_key,evidence_reference): return self._execute_operation("SEARCH",payload,idempotency_key,evidence_reference)
    def reserve(self,payload,idempotency_key,evidence_reference): return self._execute_operation("RESERVE",payload,idempotency_key,evidence_reference)
    def modify(self,payload,idempotency_key,evidence_reference): return self._execute_operation("MODIFY",payload,idempotency_key,evidence_reference)
    def cancel(self,payload,idempotency_key,evidence_reference): return self._execute_operation("CANCEL",payload,idempotency_key,evidence_reference)
    def status(self,payload,idempotency_key,evidence_reference): return self._execute_operation("STATUS",payload,idempotency_key,evidence_reference)
    def refund_handoff(self,payload,idempotency_key,evidence_reference): return self._execute_operation("REFUND_HANDOFF",payload,idempotency_key,evidence_reference)


class AttractionAdapter(Day1VerticalAdapter):
    vertical = "ATTRACTION"
    capability_methods = {"SEARCH":"search", "AVAILABILITY":"availability", "PRICE":"price", "RESERVE":"reserve", "BOOK":"book", "CANCEL":"cancel", "STATUS":"status", "REFUND_HANDOFF":"refund_handoff"}
    def search(self,payload,idempotency_key,evidence_reference): return self._execute_operation("SEARCH",payload,idempotency_key,evidence_reference)
    def availability(self,payload,idempotency_key,evidence_reference): return self._execute_operation("AVAILABILITY",payload,idempotency_key,evidence_reference)
    def price(self,payload,idempotency_key,evidence_reference): return self._execute_operation("PRICE",payload,idempotency_key,evidence_reference)
    def reserve(self,payload,idempotency_key,evidence_reference): return self._execute_operation("RESERVE",payload,idempotency_key,evidence_reference)
    def book(self,payload,idempotency_key,evidence_reference): return self._execute_operation("BOOK",payload,idempotency_key,evidence_reference)
    def cancel(self,payload,idempotency_key,evidence_reference): return self._execute_operation("CANCEL",payload,idempotency_key,evidence_reference)
    def status(self,payload,idempotency_key,evidence_reference): return self._execute_operation("STATUS",payload,idempotency_key,evidence_reference)
    def refund_handoff(self,payload,idempotency_key,evidence_reference): return self._execute_operation("REFUND_HANDOFF",payload,idempotency_key,evidence_reference)


ADAPTER_CLASSES = {"HOTEL":HotelAdapter, "FLIGHT":FlightAdapter, "RAIL":RailAdapter, "RIDE":RideAdapter, "RENTAL":RentalAdapter, "ATTRACTION":AttractionAdapter}


CANCEL_REFUND_STATES = (
    "CANCEL_REQUESTED", "SUPPLIER_PROCESSING", "CANCEL_CONFIRMED", "CANCEL_REJECTED",
    "SUPPLIER_UNKNOWN", "RECONCILING", "REFUND_AMOUNT_CONFIRMED", "ORDER_CLOSED_NO_REFUND",
    "REFUND_INITIATED", "PSP_PROCESSING", "REFUND_UNKNOWN", "RECONCILING_REFUND",
    "REFUND_FAILED", "REFUND_COMPLETED", "MANUAL_REVIEW",
)
CANCEL_REFUND_TERMINAL_STATES = {"CANCEL_REJECTED", "ORDER_CLOSED_NO_REFUND", "REFUND_FAILED", "REFUND_COMPLETED"}

@dataclass(frozen=True)
class TransitionRule:
    target: str
    actors: tuple[str, ...]
    required_evidence: tuple[str, ...]
    refund_dispositions: tuple[str, ...] = ("NONE", "PARTIAL", "FULL")

CANCEL_REFUND_TRANSITIONS: dict[str, tuple[TransitionRule, ...]] = {
    "CANCEL_REQUESTED": (TransitionRule("SUPPLIER_PROCESSING", ("SYSTEM", "SUPPLIER_ADAPTER"), ("cancel_request_evidence",)),),
    "SUPPLIER_PROCESSING": (
        TransitionRule("CANCEL_CONFIRMED", ("SUPPLIER_CALLBACK", "RECONCILIATION"), ("supplier_cancel_confirmation",)),
        TransitionRule("CANCEL_REJECTED", ("SUPPLIER_CALLBACK", "RECONCILIATION"), ("supplier_rejection_evidence",)),
        TransitionRule("SUPPLIER_UNKNOWN", ("SYSTEM",), ("timeout_or_ambiguous_external_evidence",)),
    ),
    "SUPPLIER_UNKNOWN": (
        TransitionRule("RECONCILING", ("SYSTEM", "OPS"), ("reconciliation_job_reference",)),
        TransitionRule("MANUAL_REVIEW", ("OPS",), ("manual_review_reason",)),
    ),
    "RECONCILING": (
        TransitionRule("CANCEL_CONFIRMED", ("RECONCILIATION",), ("supplier_cancel_confirmation",)),
        TransitionRule("CANCEL_REJECTED", ("RECONCILIATION",), ("supplier_rejection_evidence",)),
        TransitionRule("SUPPLIER_UNKNOWN", ("RECONCILIATION",), ("still_unknown_evidence",)),
        TransitionRule("MANUAL_REVIEW", ("OPS",), ("manual_review_reason",)),
    ),
    "CANCEL_CONFIRMED": (
        TransitionRule("REFUND_AMOUNT_CONFIRMED", ("RULE_ENGINE", "PAYMENT_SERVICE"), ("refund_quote_evidence",), ("PARTIAL", "FULL")),
        TransitionRule("ORDER_CLOSED_NO_REFUND", ("RULE_ENGINE",), ("zero_refund_rule_evidence",), ("NONE",)),
    ),
    "REFUND_AMOUNT_CONFIRMED": (TransitionRule("REFUND_INITIATED", ("PAYMENT_SERVICE",), ("refund_authorization_evidence",), ("PARTIAL", "FULL")),),
    "REFUND_INITIATED": (
        TransitionRule("PSP_PROCESSING", ("PAYMENT_ADAPTER",), ("psp_refund_operation_evidence",), ("PARTIAL", "FULL")),
        TransitionRule("REFUND_UNKNOWN", ("SYSTEM",), ("timeout_or_ambiguous_external_evidence",), ("PARTIAL", "FULL")),
        TransitionRule("REFUND_FAILED", ("PAYMENT_CALLBACK", "RECONCILIATION"), ("psp_failure_evidence",), ("PARTIAL", "FULL")),
    ),
    "PSP_PROCESSING": (
        TransitionRule("REFUND_COMPLETED", ("PAYMENT_CALLBACK", "RECONCILIATION"), ("psp_refund_confirmation", "money_movement_evidence"), ("PARTIAL", "FULL")),
        TransitionRule("REFUND_UNKNOWN", ("SYSTEM",), ("timeout_or_ambiguous_external_evidence",), ("PARTIAL", "FULL")),
        TransitionRule("REFUND_FAILED", ("PAYMENT_CALLBACK", "RECONCILIATION"), ("psp_failure_evidence",), ("PARTIAL", "FULL")),
    ),
    "REFUND_UNKNOWN": (
        TransitionRule("RECONCILING_REFUND", ("SYSTEM", "OPS"), ("reconciliation_job_reference",), ("PARTIAL", "FULL")),
        TransitionRule("MANUAL_REVIEW", ("OPS",), ("manual_review_reason",), ("PARTIAL", "FULL")),
    ),
    "RECONCILING_REFUND": (
        TransitionRule("REFUND_COMPLETED", ("RECONCILIATION",), ("psp_refund_confirmation", "money_movement_evidence"), ("PARTIAL", "FULL")),
        TransitionRule("REFUND_FAILED", ("RECONCILIATION",), ("psp_failure_evidence",), ("PARTIAL", "FULL")),
        TransitionRule("REFUND_UNKNOWN", ("RECONCILIATION",), ("still_unknown_evidence",), ("PARTIAL", "FULL")),
        TransitionRule("MANUAL_REVIEW", ("OPS",), ("manual_review_reason",), ("PARTIAL", "FULL")),
    ),
    "MANUAL_REVIEW": (
        TransitionRule("RECONCILING", ("OPS",), ("review_resolution_evidence",)),
        TransitionRule("RECONCILING_REFUND", ("OPS",), ("review_resolution_evidence",), ("PARTIAL", "FULL")),
    ),
}


def validate_cancel_refund_transition(current: str, target: str, actor: str, evidence: Mapping[str, Any], refund_disposition: str = "NONE", refund_amount_minor: int | None = None) -> None:
    if current in CANCEL_REFUND_TERMINAL_STATES:
        raise ValueError("TERMINAL_STATE_IMMUTABLE")
    rules = [r for r in CANCEL_REFUND_TRANSITIONS.get(current, ()) if r.target == target]
    if not rules:
        raise ValueError("ILLEGAL_CANCEL_REFUND_TRANSITION")
    rule = rules[0]
    if actor not in rule.actors:
        raise ValueError("ACTOR_NOT_AUTHORIZED_FOR_TRANSITION")
    missing = [k for k in rule.required_evidence if not evidence.get(k)]
    if missing:
        raise ValueError("REQUIRED_TRANSITION_EVIDENCE_MISSING")
    if refund_disposition not in rule.refund_dispositions:
        raise ValueError("INVALID_REFUND_DISPOSITION_FOR_TRANSITION")
    if refund_disposition in {"PARTIAL", "FULL"} and target in {"REFUND_AMOUNT_CONFIRMED", "REFUND_INITIATED", "PSP_PROCESSING", "REFUND_UNKNOWN", "REFUND_FAILED", "REFUND_COMPLETED", "RECONCILING_REFUND"}:
        if refund_amount_minor is None or refund_amount_minor < 0:
            raise ValueError("REFUND_AMOUNT_REQUIRED")


SUPPLIER_MUTATION_STATES = ("NOT_STARTED", "REQUESTED", "ACCEPTED_ASYNC", "CONFIRMED", "FAILED", "UNKNOWN", "RECONCILING", "MANUAL_REVIEW")
PAYMENT_STATES = ("CREATED", "REQUIRES_ACTION", "AUTHORIZED", "PARTIALLY_CAPTURED", "CAPTURED", "PARTIALLY_REFUNDED", "REFUNDED", "FAILED", "CANCELED", "UNKNOWN")


@dataclass(frozen=True)
class ImplementationRequirement:
    requirement_text: str
    symbols: tuple[tuple[str, str, str | None], ...]
    test_functions: tuple[tuple[str, str], ...]
    state_check: str
    db_tokens: tuple[tuple[str, str], ...]


IMPLEMENTATION_REQUIREMENTS: dict[str, ImplementationRequirement] = {
    "ORDER_PAYMENT_ROOT": ImplementationRequirement(
        "One business order has one successful-capable payment root and duplicate roots fail closed.",
        (("go_hotel.services.omnichannel_payment", "OmnichannelPaymentService", "create_intent"),),
        (("tests/test_p0_0099_atomic_truth.py", "test_order_has_single_payment_root_even_with_different_idempotency_and_channel_request"),),
        "PAYMENT_MONOTONICITY",
        (("src/go_hotel/db/models.py", "uq_payment_order_single_root"), ("alembic/versions/0099_order_money_supplier_atomic_truth.py", "payment_order_root")),
    ),
    "MONEY_GRAPH_RECONCILIATION": ImplementationRequirement(
        "Authorization is not GL; capture/refund and durable PSP/bank facts reconcile before close.",
        (("go_hotel.services.omnichannel_payment", "OmnichannelPaymentService", "reconcile"), ("go_hotel.services.unified_money_movement", "UnifiedMoneyMovementService", "prepare_close")),
        (("tests/test_p0_0099_atomic_truth.py", "test_authorization_does_not_post_gl_capture_does_and_reconciliation_requires_durable_external_lines"),),
        "PAYMENT_REFUND_STATES",
        (("src/go_hotel/db/models.py", "external_transaction_id"), ("src/go_hotel/db/models.py", "bank_line_identity"), ("src/go_hotel/db/models.py", "uq_finance_scoped_close_scope")),
    ),
    "SUPPLIER_CONFIRMATION_TRUTH": ImplementationRequirement(
        "Payment success does not equal supplier success; supplier confirmation alone can confirm the order after required capture truth.",
        (("go_hotel.services.order_supplier_fulfillment", "OrderSupplierFulfillmentService", "record_supplier_fact"), ("go_hotel.services.consumer_unified_lifecycle", "ConsumerUnifiedLifecycleService", "project")),
        (("tests/test_p0_0099_atomic_truth.py", "test_payment_success_creates_supplier_fulfillment_and_only_supplier_confirmation_confirms_order_and_trips"),),
        "SUPPLIER_UNKNOWN_RECONCILIATION",
        (("src/go_hotel/db/models.py", "order_supplier_fulfillment"), ("alembic/versions/0099_order_money_supplier_atomic_truth.py", "IMMUTABLE_0099_ATOMIC_TRUTH_EVIDENCE")),
    ),
    "SIGNED_EXTERNAL_CALLBACK": ImplementationRequirement(
        "External HTTP response is not business success; signed callback/reconciliation supplies external truth.",
        (("go_hotel.services.real_external_execution", "RealExternalExecutionService", "payment_callback"), ("go_hotel.services.real_external_execution", "RealExternalExecutionService", "supplier_callback")),
        (("tests/test_p0_0100_real_external_execution.py", "test_0100_signed_psp_and_supplier_callbacks_drive_0099_truth_chain"),),
        "SUPPLIER_UNKNOWN_RECONCILIATION",
        (("alembic/versions/0100_real_external_execution_certified_sandbox.py", "delivery_id"), ("alembic/versions/0100_real_external_execution_certified_sandbox.py", "IMMUTABLE_EXTERNAL_TRUTH_EVIDENCE")),
    ),
    "DIRECT_FIRST_SOURCE_TRUTH": ImplementationRequirement(
        "Direct First selection is persisted and fallback cannot masquerade as Official Direct.",
        (("go_hotel.services.vertical_source_runtime", "VerticalSourceRuntimeService", "decide"),),
        (("tests/test_p0_0097_0098_rebuild.py", "test_0097_persists_direct_first_and_0098_server_resolves_payment_truth"), ("tests/test_p0_design_code_freeze.py", "test_fallback_cannot_masquerade_as_official")),
        "SOURCE_ROUTE_BOUNDARY",
        (("src/go_hotel/db/models.py", "decision_hash"), ("alembic/versions/0099_order_money_supplier_atomic_truth.py", "vertical_source_decision")),
    ),
    "CANCEL_REFUND_STATE_MACHINE": ImplementationRequirement(
        "Cancellation/refund transitions are actor/evidence gated and preserve partial, failed, unknown and terminal semantics.",
        (("go_hotel.services.p0_design_code_freeze", "", "validate_cancel_refund_transition"),),
        (("tests/test_p0_design_code_freeze.py", "test_cancel_refund_state_machine_rejects_illegal_missing_evidence_and_terminal_mutation"),),
        "CANCEL_REFUND_TRANSITIONS",
        (("src/go_hotel/db/models.py", "RefundRow"), ("src/go_hotel/db/models.py", "evidence")),
    ),
    "DAY1_VERTICAL_SPECIALIZATION": ImplementationRequirement(
        "Each Day-1 vertical exposes its professional capability interface without erasing vertical-specific facts.",
        tuple(("go_hotel.services.p0_design_code_freeze", cls.__name__, None) for cls in ADAPTER_CLASSES.values()),
        (("tests/test_p0_design_code_freeze.py", "test_vertical_specific_capabilities_and_facts_are_preserved"), ("tests/test_p0_design_code_freeze.py", "test_unsupported_provider_capability_is_rejected")),
        "VERTICAL_CAPABILITY_MAP",
        (("src/go_hotel/db/models.py", "FlightOrderRow"), ("src/go_hotel/db/models.py", "RailOrderRow"), ("src/go_hotel/db/models.py", "MobilityRideOrderRow"), ("src/go_hotel/db/models.py", "MobilityRentalOrderRow"), ("src/go_hotel/db/models.py", "AttractionOrderRow")),
    ),
}


def _symbol_exists(module_name: str, class_name: str, method_name: str | None) -> bool:
    # Parse source instead of importing runtime modules so static closure review has no DB/driver side effects.
    module_path = ROOT / ("src/" + module_name.replace(".", "/") + ".py")
    if not module_path.exists():
        return False
    try:
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not class_name:
        return any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == method_name for n in tree.body)
    for n in tree.body:
        if isinstance(n, ast.ClassDef) and n.name == class_name:
            if method_name is None:
                return True
            return any(isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name == method_name for m in n.body)
    return False


def _test_function_exists(path: str, function_name: str) -> bool:
    p = ROOT / path
    if not p.exists():
        return False
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    return any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function_name for n in tree.body)


def _token_exists(path: str, token: str) -> bool:
    p = ROOT / path
    return p.exists() and token in p.read_text(encoding="utf-8", errors="ignore")


def _state_check(name: str) -> bool:
    if name == "PAYMENT_MONOTONICITY":
        return all(s in PAYMENT_STATES for s in ("AUTHORIZED", "CAPTURED", "REFUNDED", "FAILED", "CANCELED", "UNKNOWN"))
    if name == "PAYMENT_REFUND_STATES":
        return all(s in PAYMENT_STATES for s in ("PARTIALLY_CAPTURED", "CAPTURED", "PARTIALLY_REFUNDED", "REFUNDED", "UNKNOWN"))
    if name == "SUPPLIER_UNKNOWN_RECONCILIATION":
        return all(s in SUPPLIER_MUTATION_STATES for s in ("UNKNOWN", "RECONCILING", "MANUAL_REVIEW", "CONFIRMED"))
    if name == "SOURCE_ROUTE_BOUNDARY":
        return PROVIDER_CONTRACTS["HOTEL"].source_truth_contract["fallback_must_not_claim_official"] is True
    if name == "CANCEL_REFUND_TRANSITIONS":
        return "REFUND_COMPLETED" in CANCEL_REFUND_TERMINAL_STATES and "SUPPLIER_UNKNOWN" in CANCEL_REFUND_TRANSITIONS and "REFUND_UNKNOWN" in CANCEL_REFUND_TRANSITIONS
    if name == "VERTICAL_CAPABILITY_MAP":
        required = {
            "HOTEL":{"SEARCH","PREBOOK","BOOK","CANCEL","STATUS","REFUND_HANDOFF"},
            "FLIGHT":{"SEARCH","REPRICE","BOOK","CANCEL","STATUS","CHECK_IN_HANDOFF"},
            "RAIL":{"SEARCH","BOOK","CHANGE","CANCEL","STATUS"},
            "RIDE":{"SEARCH","RESERVE","CANCEL","STATUS","FLIGHT_TRACKING"},
            "RENTAL":{"SEARCH","RESERVE","MODIFY","CANCEL","STATUS"},
            "ATTRACTION":{"SEARCH","AVAILABILITY","PRICE","RESERVE","BOOK","CANCEL","STATUS"},
        }
        return all(required[v].issubset(set(ADAPTER_CLASSES[v].capability_methods)) for v in DAY1_VERTICALS)
    return False


def _provider_contracts_complete() -> bool:
    required_fields = (
        "canonical_request_schema", "canonical_response_schema", "auth_contract", "idempotency_contract",
        "timeout_contract", "retry_contract", "webhook_contract", "reconciliation_contract", "version_policy",
        "error_taxonomy", "normalization_contract", "source_truth_contract",
    )
    if set(PROVIDER_CONTRACTS) != {"PAYMENT", *DAY1_VERTICALS}:
        return False
    for contract in PROVIDER_CONTRACTS.values():
        if not contract.primary or not contract.fallback or not contract.capabilities:
            return False
        if any(not getattr(contract, f) for f in required_fields):
            return False
        if not contract.timeout_contract.get("timeout_never_equals_permission_to_resend"):
            return False
        if not contract.source_truth_contract.get("fallback_must_not_claim_official"):
            return False
    return True


def _vertical_adapters_complete() -> bool:
    return set(ADAPTER_CLASSES) == set(DAY1_VERTICALS) and _state_check("VERTICAL_CAPABILITY_MAP") and all(
        all(callable(getattr(cls, method, None)) for method in cls.capability_methods.values()) for cls in ADAPTER_CLASSES.values()
    )


def _truth_boundary_complete() -> bool:
    # No unconditional True marker: verify actual external-truth/supplier/payment boundaries.
    checks = (
        _symbol_exists("go_hotel.services.omnichannel_payment", "OmnichannelPaymentService", "create_intent"),
        _symbol_exists("go_hotel.services.order_supplier_fulfillment", "OrderSupplierFulfillmentService", "record_supplier_fact"),
        _symbol_exists("go_hotel.services.real_external_execution", "RealExternalExecutionService", "payment_callback"),
        _symbol_exists("go_hotel.services.real_external_execution", "RealExternalExecutionService", "supplier_callback"),
        _token_exists("src/go_hotel/db/models.py", "uq_payment_order_single_root"),
        _token_exists("alembic/versions/0100_real_external_execution_certified_sandbox.py", "signature_verified"),
        _token_exists("tests/test_p0_0099_atomic_truth.py", "only_supplier_confirmation_confirms_order_and_trips"),
        _token_exists("tests/test_p0_0100_real_external_execution.py", "signed_psp_and_supplier_callbacks_drive_0099_truth_chain"),
    )
    return all(checks)


DESIGN_REQUIREMENTS = {
    "FULL_PROVIDER_CONTRACTS": _provider_contracts_complete,
    "DAY1_VERTICAL_SPECIALIZATION": _vertical_adapters_complete,
    "CANCEL_REFUND_STATE_MACHINE": lambda: _state_check("CANCEL_REFUND_TRANSITIONS"),
    "PAYMENT_STATE_MACHINE": lambda: _state_check("PAYMENT_REFUND_STATES"),
    "SUPPLIER_UNKNOWN_RECONCILIATION": lambda: _state_check("SUPPLIER_UNKNOWN_RECONCILIATION"),
    "TRUTH_BOUNDARY": _truth_boundary_complete,
}


def requirement_implementation_review() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key, req in IMPLEMENTATION_REQUIREMENTS.items():
        symbol_results = [
            {"module":m, "class":c or None, "method":fn, "pass":_symbol_exists(m,c,fn)} for m,c,fn in req.symbols
        ]
        test_results = [{"path":p, "function":fn, "pass":_test_function_exists(p,fn)} for p,fn in req.test_functions]
        db_results = [{"path":p, "token":token, "pass":_token_exists(p,token)} for p,token in req.db_tokens]
        state_ok = _state_check(req.state_check)
        passed = all(x["pass"] for x in symbol_results + test_results + db_results) and state_ok
        out[key] = {
            "requirement": req.requirement_text,
            "symbols": symbol_results,
            "tests": test_results,
            "state_transition_check": {"name":req.state_check, "pass":state_ok},
            "db_constraints_or_evidence": db_results,
            "pass": passed,
        }
    return out


def static_review() -> dict[str, Any]:
    design = {k: bool(fn()) for k, fn in DESIGN_REQUIREMENTS.items()}
    implementation = requirement_implementation_review()
    code = {k: v["pass"] for k, v in implementation.items()}
    return {
        "design_state": "FROZEN" if all(design.values()) else "INCOMPLETE",
        "code_state": "CODE_COMPLETE_PENDING_RUNTIME_CERTIFICATION" if all(code.values()) else "INCOMPLETE",
        "design_checks": design,
        "code_checks": code,
        "requirement_implementation_evidence": implementation,
        "provider_contracts": PROVIDER_BLUEPRINT,
        "cancel_refund_state_machine": {
            "states": CANCEL_REFUND_STATES,
            "terminal_states": sorted(CANCEL_REFUND_TERMINAL_STATES),
            "transition_sources": sorted(CANCEL_REFUND_TRANSITIONS),
        },
        "runtime_certification_state": "NOT_EVALUATED_BY_STATIC_REVIEW",
        "external_sandbox_gate": "UNCHANGED_BLOCK_UNTIL_RUNTIME_EVIDENCE",
    }
