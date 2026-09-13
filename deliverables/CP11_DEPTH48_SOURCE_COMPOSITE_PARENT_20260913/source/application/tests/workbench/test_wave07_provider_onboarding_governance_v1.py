from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from go_hotel.core.provider_adapter_contract_v2 import VERTICAL_PROFILES
from go_hotel.core.provider_onboarding_governance_v1 import (
    ProviderOnboardingGovernanceState,
    provider_onboarding_governance_v1,
    validate_credential_reference,
)
from go_hotel.services.onboarding import OnboardingService


def contract(vertical: str):
    profile = VERTICAL_PROFILES[vertical]
    return {
        "vertical": vertical,
        "provider": {"provider_code": f"TEST_{vertical}", "supplier_legal_name": "Controlled Supplier", "environment": "SANDBOX"},
        "contract_source": {"authority": "SIGNED_SUPPLIER_DOCUMENTATION", "documentation_reference": "contract://signed/v7", "documentation_version": "v7", "documentation_hash": "7" * 64},
        "transport": {"base_url": "https://sandbox.supplier.example", "auth": {"method": "BEARER", "credential_reference": f"vault://providers/{vertical.lower()}/sandbox"}},
        "operations": {op: {"method": "GET" if op in {"search", "query"} else "POST", "path": f"/contracted/{op}", "request_mapping": {"go": "supplier"}, "response_mapping": {"supplier": "go"}} for op in profile["operations"]},
        "canonical_mapping": {section: {"supplier_field": "go_field"} for section in profile["canonical"]},
        "webhook": {"callback_path": f"/internal/providers/{vertical.lower()}/webhook", "signature": {"scheme": "HMAC_SHA256", "signature_header": "X-Signature", "timestamp_header": "X-Timestamp", "secret_reference": f"vault://providers/{vertical.lower()}/webhook", "replay_tolerance_seconds": 300}},
        "error_mapping": {"supplier_to_go": {"TIMEOUT": "UPSTREAM_TIMEOUT"}, "unknown_error_policy": "FAIL_CLOSED"},
        "limits": {"requests_per_second": 5, "max_concurrency": 10, "connect_timeout_ms": 3000, "read_timeout_ms": 5000, "max_attempts": 3, "retryable_go_errors": ["UPSTREAM_TIMEOUT"]},
        "attestation": {"contract_reference": f"contract://{vertical.lower()}/sandbox", "sandbox_account_reference": "sandbox-account://provider", "test_entity_reference": f"supplier-test://{vertical.lower()}/entity", "authorized_scope": ["SANDBOX_READINESS"], "evidence_references": ["evidence://signed-docs", "evidence://mapping"], "prepared_by": "go-platform", "prepared_at": "2026-08-31T19:30:00+08:00", "external_transport_verified": False},
    }


def ready_state(vertical: str):
    c = contract(vertical)
    state = ProviderOnboardingGovernanceState(provider_code=f"TEST_{vertical}", vertical=vertical)
    normalized = provider_onboarding_governance_v1.intake_contract(state, c)
    mapping = provider_onboarding_governance_v1.evaluate_mapping(state, normalized)
    assert mapping.complete
    provider_onboarding_governance_v1.bind_credential_reference(state, normalized["transport"]["auth"]["credential_reference"])
    issued = datetime(2026, 8, 31, 11, 0, tzinfo=timezone.utc)
    provider_onboarding_governance_v1.certify_readiness(state, normalized, issued_at=issued, expires_at=issued + timedelta(days=30))
    return state, normalized, issued


def test_p1_01_legacy_secret_write_is_hard_blocked_before_db_access():
    with pytest.raises(ValueError, match="INLINE_PROVIDER_SECRET_FORBIDDEN_USE_CREDENTIAL_REFERENCE"):
        OnboardingService().reject_inline_credentials("does-not-matter", {"token": "forbidden"})
    assert validate_credential_reference("vault://providers/hotel/sandbox") == "vault://providers/hotel/sandbox"
    with pytest.raises(ValueError, match="EXTERNAL_VAULT_REFERENCE_REQUIRED"):
        validate_credential_reference("plaintext-token")


def test_p1_02_mapping_governance_is_vertical_neutral_for_all_six_verticals():
    for vertical in VERTICAL_PROFILES:
        c = contract(vertical)
        state = ProviderOnboardingGovernanceState(provider_code=f"TEST_{vertical}", vertical=vertical)
        normalized = provider_onboarding_governance_v1.intake_contract(state, c)
        result = provider_onboarding_governance_v1.evaluate_mapping(state, normalized)
        assert result.complete is True
        assert set(result.required_sections) == set(VERTICAL_PROFILES[vertical]["canonical"])
        assert state.state == "CREDENTIAL_REFERENCE_PENDING"


def test_mapping_missing_section_blocks_progress_with_deterministic_blocker():
    c = contract("FLIGHT")
    del c["canonical_mapping"][VERTICAL_PROFILES["FLIGHT"]["canonical"][0]]
    state = ProviderOnboardingGovernanceState(provider_code="TEST_FLIGHT", vertical="FLIGHT", state="MAPPING_IN_PROGRESS", documentation_version="v7", documentation_hash="7" * 64)
    result = provider_onboarding_governance_v1.evaluate_mapping(state, c)
    assert result.complete is False
    assert "MAPPING_INCOMPLETE" in state.blockers
    assert state.state == "MAPPING_IN_PROGRESS"


def test_p1_03_readiness_eligibility_is_sandbox_only_and_never_live():
    for vertical in VERTICAL_PROFILES:
        state, _, issued = ready_state(vertical)
        assert state.state == "CERTIFIED_READINESS_ONLY"
        result = provider_onboarding_governance_v1.evaluate_sandbox_eligibility(state, actor_kind="CONTROL_PLANE", now_at=issued + timedelta(days=1))
        assert result == "ELIGIBLE_FOR_SANDBOX_ONLY"
        assert state.external_transport_verified is False
        assert state.production_live is False
        provider_onboarding_governance_v1.assert_never_live(state)


def test_ai_cannot_grant_provider_eligibility():
    state, _, issued = ready_state("HOTEL")
    with pytest.raises(PermissionError, match="AI_ELIGIBILITY_GRANT_FORBIDDEN"):
        provider_onboarding_governance_v1.evaluate_sandbox_eligibility(state, actor_kind="AI", now_at=issued + timedelta(days=1))
    assert state.state == "CERTIFIED_READINESS_ONLY"


@pytest.mark.parametrize("drift", ["contract", "mapping", "credential", "expiry", "revocation"])
def test_recertification_trigger_is_fail_closed_for_all_governed_drift(drift):
    state, _, issued = ready_state("RAIL")
    kwargs = {
        "documentation_version": state.documentation_version,
        "documentation_hash": state.documentation_hash,
        "mapping_fingerprint": state.mapping_fingerprint,
        "credential_reference": state.credential_reference,
        "now_at": issued + timedelta(days=1),
        "revoked": False,
    }
    if drift == "contract": kwargs["documentation_version"] = "v8"
    elif drift == "mapping": kwargs["mapping_fingerprint"] = "changed"
    elif drift == "credential": kwargs["credential_reference"] = "vault://providers/rail/rotated"
    elif drift == "expiry": kwargs["now_at"] = issued + timedelta(days=31)
    elif drift == "revocation": kwargs["revoked"] = True
    blockers = provider_onboarding_governance_v1.evaluate_drift(state, **kwargs)
    assert blockers
    assert state.state == "RECERTIFICATION_REQUIRED"


def test_illegal_state_jump_is_rejected():
    state = ProviderOnboardingGovernanceState(provider_code="TEST_HOTEL", vertical="HOTEL")
    with pytest.raises(ValueError, match="INVALID_PROVIDER_ONBOARDING_TRANSITION"):
        provider_onboarding_governance_v1.transition(state, "CERTIFIED_READINESS_ONLY")
