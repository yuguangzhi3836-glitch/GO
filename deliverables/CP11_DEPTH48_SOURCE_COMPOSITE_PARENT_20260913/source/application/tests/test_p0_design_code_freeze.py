import pytest

pytestmark = pytest.mark.no_db
from go_hotel.services.p0_design_code_freeze import (
    static_review, PROVIDER_CONTRACTS, ADAPTER_CLASSES, DAY1_VERTICALS,
    ProviderCommand, ProviderResult, FlightAdapter, RailAdapter, AttractionAdapter,
    validate_cancel_refund_transition, CANCEL_REFUND_TERMINAL_STATES,
)


class FakeTransport:
    def __init__(self, attested=True, source_route="OFFICIAL_OR_AUTHORIZED_DIRECT", state="ACCEPTED_ASYNC", payload=None):
        self.attested = attested
        self.source_route = source_route
        self.state = state
        self.payload = payload or {}
        self.last_command = None

    def execute(self, provider_key, command):
        self.last_command = command
        return ProviderResult("ext_1", self.state, dict(self.payload), self.attested, self.source_route, provider_key)

    def query(self, provider_key, external_operation_id):
        return ProviderResult(external_operation_id, "CONFIRMED", dict(self.payload), self.attested, self.source_route, provider_key)


def test_design_and_code_static_freeze_is_complete_by_requirement_chain():
    r = static_review()
    assert r["design_state"] == "FROZEN"
    assert r["code_state"] == "CODE_COMPLETE_PENDING_RUNTIME_CERTIFICATION"
    assert set(ADAPTER_CLASSES) == set(DAY1_VERTICALS)
    assert all(v["pass"] for v in r["requirement_implementation_evidence"].values())
    # A pass now requires symbols + tests + state transition + DB evidence, not file existence.
    for evidence in r["requirement_implementation_evidence"].values():
        assert evidence["symbols"] and all(x["pass"] for x in evidence["symbols"])
        assert evidence["tests"] and all(x["pass"] for x in evidence["tests"])
        assert evidence["state_transition_check"]["pass"] is True
        assert evidence["db_constraints_or_evidence"] and all(x["pass"] for x in evidence["db_constraints_or_evidence"])
    assert r["external_sandbox_gate"] == "UNCHANGED_BLOCK_UNTIL_RUNTIME_EVIDENCE"


def test_provider_contracts_are_full_and_fail_closed_on_timeout_retry_and_version():
    assert set(PROVIDER_CONTRACTS) == {"PAYMENT", *DAY1_VERTICALS}
    for c in PROVIDER_CONTRACTS.values():
        assert c.canonical_request_schema and c.canonical_response_schema
        assert c.auth_contract["no_secret_persistence"] is True
        assert c.idempotency_contract["required_for_mutation"] is True
        assert c.timeout_contract["timeout_result"] == "UNKNOWN_EXTERNAL_STATE"
        assert c.timeout_contract["timeout_never_equals_permission_to_resend"] is True
        assert c.retry_contract["mutation"] == "NO_BLIND_RETRY"
        assert c.webhook_contract["signature_required"] is True
        assert c.reconciliation_contract["query_required_after_unknown"] is True
        assert c.version_policy["schema_drift"] == "FAIL_CLOSED"
        assert c.source_truth_contract["fallback_must_not_claim_official"] is True


def test_vertical_adapter_requires_idempotency_evidence_and_attestation():
    a = FlightAdapter(FakeTransport(), "flight-primary")
    with pytest.raises(ValueError, match="IDEMPOTENCY_AND_EVIDENCE_REQUIRED"):
        a.execute(ProviderCommand("FLIGHT", "BOOK", "", {}, ""))
    with pytest.raises(ValueError, match="UNATTESTED_PROVIDER_RESULT"):
        FlightAdapter(FakeTransport(False), "flight-primary").book({}, "idem_1", "ev://1")
    assert a.book({"offer_id":"o1"}, "idem_1", "ev://1").state == "ACCEPTED_ASYNC"
    assert a.reconcile("ext_1").state == "CONFIRMED"


def test_unsupported_provider_capability_is_rejected():
    with pytest.raises(ValueError, match="UNSUPPORTED_PROVIDER_CAPABILITY"):
        RailAdapter(FakeTransport(), "rail-primary")._execute_operation("CHECK_IN_HANDOFF", {}, "idem", "ev://1")


def test_fallback_cannot_masquerade_as_official():
    fallback = FlightAdapter(FakeTransport(source_route="OFFICIAL_DIRECT"), "flight-fallback", provider_role="FALLBACK")
    with pytest.raises(ValueError, match="FALLBACK_MUST_NOT_MASQUERADE_AS_OFFICIAL"):
        fallback.book({"offer_id":"o1"}, "idem", "ev://1")
    ok = FlightAdapter(FakeTransport(source_route="AUTHORIZED_FALLBACK"), "flight-fallback", provider_role="FALLBACK")
    assert ok.book({"offer_id":"o1"}, "idem", "ev://1").source_route == "AUTHORIZED_FALLBACK"


def test_unknown_external_state_does_not_become_success():
    a = FlightAdapter(FakeTransport(state="UNKNOWN"), "flight-primary")
    result = a.book({"offer_id":"o1"}, "idem", "ev://1")
    assert result.state == "UNKNOWN"
    assert result.state != "CONFIRMED"


def test_vertical_specific_capabilities_and_facts_are_preserved():
    flight_payload = {"pnr":"ABC123", "ticket_numbers":["ETKT1"], "baggage":{"pieces":1}}
    f = FlightAdapter(FakeTransport(payload=flight_payload), "flight-primary")
    assert f.ticket_status({"ticket_order_id":"ord1"}, "idem-f", "ev://f").payload == flight_payload

    rail_payload = {"seat_class":"FIRST", "ticket_reference":"R1"}
    r = RailAdapter(FakeTransport(payload=rail_payload), "rail-primary")
    assert r.change({"booking_id":"r1", "change_request":{"train":"G2"}}, "idem-r", "ev://r").payload == rail_payload

    attr_payload = {"timeslot":"2026-08-19T10:00:00Z", "ticket_types":[{"type":"adult","qty":2}]}
    a = AttractionAdapter(FakeTransport(payload=attr_payload), "attr-primary")
    assert a.availability({"product_id":"p1"}, "idem-a", "ev://a").payload == attr_payload


def test_cancel_refund_state_machine_rejects_illegal_missing_evidence_and_terminal_mutation():
    with pytest.raises(ValueError, match="ILLEGAL_CANCEL_REFUND_TRANSITION"):
        validate_cancel_refund_transition("CANCEL_REQUESTED", "REFUND_COMPLETED", "SYSTEM", {"x":"y"})
    with pytest.raises(ValueError, match="REQUIRED_TRANSITION_EVIDENCE_MISSING"):
        validate_cancel_refund_transition("SUPPLIER_PROCESSING", "CANCEL_CONFIRMED", "SUPPLIER_CALLBACK", {})
    validate_cancel_refund_transition("SUPPLIER_PROCESSING", "SUPPLIER_UNKNOWN", "SYSTEM", {"timeout_or_ambiguous_external_evidence":"ev://timeout"})
    validate_cancel_refund_transition("CANCEL_CONFIRMED", "REFUND_AMOUNT_CONFIRMED", "RULE_ENGINE", {"refund_quote_evidence":"ev://q"}, "PARTIAL", 500)
    validate_cancel_refund_transition("PSP_PROCESSING", "REFUND_COMPLETED", "PAYMENT_CALLBACK", {"psp_refund_confirmation":"ev://psp", "money_movement_evidence":"ev://move"}, "PARTIAL", 500)
    assert "REFUND_COMPLETED" in CANCEL_REFUND_TERMINAL_STATES
    with pytest.raises(ValueError, match="TERMINAL_STATE_IMMUTABLE"):
        validate_cancel_refund_transition("REFUND_COMPLETED", "REFUND_UNKNOWN", "SYSTEM", {"timeout_or_ambiguous_external_evidence":"ev://x"})


def test_static_freeze_never_claims_runtime_certification():
    r = static_review()
    assert r["runtime_certification_state"] == "NOT_EVALUATED_BY_STATIC_REVIEW"
    assert "BLOCK" in r["external_sandbox_gate"]
