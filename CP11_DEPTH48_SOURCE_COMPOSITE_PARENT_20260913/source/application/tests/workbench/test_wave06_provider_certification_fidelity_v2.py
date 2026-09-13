from copy import deepcopy

from go_hotel.core.provider_adapter_contract_v2 import VERTICAL_PROFILES
from go_hotel.core.provider_certification_harness_v2 import provider_certification_harness_v2
from go_hotel.core.transaction_fidelity_simulation_v2 import contract_fidelity_simulation_runner_v2


def contract(vertical: str):
    profile = VERTICAL_PROFILES[vertical]
    return {
        "vertical": vertical,
        "provider": {
            "provider_code": f"TEST_{vertical}",
            "supplier_legal_name": "Sandbox Supplier Legal Entity",
            "environment": "SANDBOX",
        },
        "contract_source": {
            "authority": "SIGNED_SUPPLIER_DOCUMENTATION",
            "documentation_reference": "contract://signed-docs/v2",
            "documentation_version": "v2",
            "documentation_hash": "b" * 64,
        },
        "transport": {
            "base_url": "https://sandbox.supplier.example",
            "auth": {"method": "BEARER", "credential_reference": f"vault://providers/{vertical.lower()}/sandbox"},
        },
        "operations": {
            op: {
                "method": "GET" if op in {"search", "query"} else "POST",
                "path": f"/contracted/{op}",
                "request_mapping": {"go": "supplier"},
                "response_mapping": {"supplier": "go"},
            }
            for op in profile["operations"]
        },
        "canonical_mapping": {section: {"supplier_field": "go_field"} for section in profile["canonical"]},
        "webhook": {
            "callback_path": f"/internal/providers/{vertical.lower()}/webhook",
            "signature": {
                "scheme": "HMAC_SHA256",
                "signature_header": "X-Signature",
                "timestamp_header": "X-Timestamp",
                "secret_reference": f"vault://providers/{vertical.lower()}/webhook",
                "replay_tolerance_seconds": 300,
            },
        },
        "error_mapping": {"supplier_to_go": {"TIMEOUT": "UPSTREAM_TIMEOUT"}, "unknown_error_policy": "FAIL_CLOSED"},
        "limits": {
            "requests_per_second": 5,
            "max_concurrency": 10,
            "connect_timeout_ms": 3000,
            "read_timeout_ms": 5000,
            "max_attempts": 3,
            "retryable_go_errors": ["UPSTREAM_TIMEOUT"],
        },
        "attestation": {
            "contract_reference": f"contract://{vertical.lower()}/sandbox",
            "sandbox_account_reference": "sandbox-account://provider",
            "test_entity_reference": f"supplier-test://{vertical.lower()}/entity",
            "authorized_scope": ["SANDBOX_READINESS"],
            "evidence_references": ["evidence://signed-docs", "evidence://mapping-review"],
            "prepared_by": "go-platform",
            "prepared_at": "2026-08-31T19:05:00+08:00",
            "external_transport_verified": False,
        },
    }


def fixture(vertical: str):
    events = []
    for i, op in enumerate(VERTICAL_PROFILES[vertical]["operations"]):
        events.append({
            "operation": op,
            "idempotency_key": f"{vertical.lower()}-{op}-1",
            "request_fingerprint": f"fp-{vertical.lower()}-{op}",
            "delivery_id": f"delivery-{vertical.lower()}-{i}",
        })
    # repeat one delivery and one request identically to prove dedupe/idempotency behavior
    events.append(deepcopy(events[-1]))
    return {
        "fixture_source": "CONTROLLED_SYNTHETIC_FIXTURE",
        "truth_owner": vertical,
        "events": events,
        "webhook_replay_policy": "DEDUPE",
        "stale_quote": True,
        "stale_quote_policy": "REPRICE_OR_FAIL_CLOSED",
        "unknown_supplier_error": True,
        "partial_failure": True,
        "partial_failure_policy": "OUTBOX_RETRY_WITHOUT_TRUTH_MUTATION",
        "provider_outage": True,
        "provider_outage_policy": "FAIL_CLOSED",
        "external_call_executed": False,
        "money_movement_executed": False,
    }


def test_harness_v2_certifies_all_six_verticals_without_external_claim():
    assert set(VERTICAL_PROFILES) == {"HOTEL", "FLIGHT", "RAIL", "RENTAL", "RIDE", "ATTRACTION"}
    for vertical in VERTICAL_PROFILES:
        report = provider_certification_harness_v2.certify(contract(vertical)).as_dict()
        assert report["passed"] is True
        assert report["external_transport_verified"] is False
        assert report["production_live"] is False
        names = {c["name"] for c in report["checks"]}
        assert {
            "operation_coverage", "canonical_mapping_coverage", "credential_boundary",
            "webhook_replay_control", "unknown_error_fail_closed", "timeout_retry_bounds",
            "evidence_attestation", "reality_registry_readiness_only",
        } <= names


def test_harness_v2_blocks_contract_with_bad_replay_tolerance():
    bad = contract("FLIGHT")
    bad["webhook"]["signature"]["replay_tolerance_seconds"] = 3600
    report = provider_certification_harness_v2.certify(bad).as_dict()
    assert report["passed"] is False
    assert report["certification_state"] == "CONTRACT_V2_CERTIFICATION_BLOCKED"


def test_contract_fidelity_runner_passes_all_six_vertical_controlled_simulations():
    for vertical in VERTICAL_PROFILES:
        report = contract_fidelity_simulation_runner_v2.run(contract(vertical), fixture(vertical)).as_dict()
        assert report["passed"] is True
        assert report["external_call_executed"] is False
        assert report["money_movement_executed"] is False
        assert report["production_live"] is False
        assert report["simulation_state"] == "CONTRACT_FIDELITY_PASS_NOT_EXTERNAL_CERTIFIED"


def test_contract_fidelity_runner_blocks_cross_domain_truth_owner():
    f = fixture("RAIL")
    f["truth_owner"] = "FLIGHT"
    report = contract_fidelity_simulation_runner_v2.run(contract("RAIL"), f).as_dict()
    assert report["passed"] is False
    check = next(c for c in report["checks"] if c["name"] == "one_domain_one_final_owner")
    assert check["passed"] is False


def test_contract_fidelity_runner_blocks_conflicting_idempotent_replay():
    f = fixture("ATTRACTION")
    first = f["events"][0]
    f["events"].append({**first, "request_fingerprint": "different"})
    report = contract_fidelity_simulation_runner_v2.run(contract("ATTRACTION"), f).as_dict()
    assert report["passed"] is False
    check = next(c for c in report["checks"] if c["name"] == "idempotency_replay_safe")
    assert check["passed"] is False
