from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

from go_hotel.connectors.provider_adapter_contract import ProviderContractError
from go_hotel.core.provider_adapter_contract_v2 import (
    VAULT_PREFIXES,
    VERTICAL_PROFILES,
    validate_provider_adapter_contract_v2,
)
from go_hotel.core.provider_certification_harness_v2 import provider_certification_harness_v2


STATES = (
    "DOCUMENT_RECEIVED",
    "CONTRACT_INTAKE",
    "MAPPING_IN_PROGRESS",
    "CREDENTIAL_REFERENCE_PENDING",
    "CREDENTIAL_REFERENCE_READY",
    "CERTIFICATION_READY",
    "CERTIFICATION_RUNNING",
    "CERTIFICATION_BLOCKED",
    "CERTIFIED_READINESS_ONLY",
    "RECERTIFICATION_REQUIRED",
    "ELIGIBILITY_PENDING",
    "ELIGIBLE_FOR_SANDBOX_ONLY",
)

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "DOCUMENT_RECEIVED": {"CONTRACT_INTAKE"},
    "CONTRACT_INTAKE": {"MAPPING_IN_PROGRESS"},
    "MAPPING_IN_PROGRESS": {"CREDENTIAL_REFERENCE_PENDING"},
    "CREDENTIAL_REFERENCE_PENDING": {"CREDENTIAL_REFERENCE_READY"},
    "CREDENTIAL_REFERENCE_READY": {"CERTIFICATION_READY"},
    "CERTIFICATION_READY": {"CERTIFICATION_RUNNING"},
    "CERTIFICATION_RUNNING": {"CERTIFICATION_BLOCKED", "CERTIFIED_READINESS_ONLY"},
    "CERTIFICATION_BLOCKED": {"MAPPING_IN_PROGRESS", "CREDENTIAL_REFERENCE_PENDING", "CERTIFICATION_READY"},
    "CERTIFIED_READINESS_ONLY": {"RECERTIFICATION_REQUIRED", "ELIGIBILITY_PENDING"},
    "RECERTIFICATION_REQUIRED": {"MAPPING_IN_PROGRESS", "CREDENTIAL_REFERENCE_PENDING", "CERTIFICATION_READY"},
    "ELIGIBILITY_PENDING": {"ELIGIBLE_FOR_SANDBOX_ONLY", "RECERTIFICATION_REQUIRED"},
    "ELIGIBLE_FOR_SANDBOX_ONLY": {"RECERTIFICATION_REQUIRED"},
}

BLOCKER_CODES = {
    "DOCUMENTATION_MISSING",
    "DOCUMENTATION_DRIFT",
    "MAPPING_INCOMPLETE",
    "CREDENTIAL_REFERENCE_INVALID",
    "CERTIFICATION_EVIDENCE_MISSING",
    "CERTIFICATION_FAILED",
    "CERTIFICATION_EXPIRED",
    "CERTIFICATION_REVOKED",
    "CONTRACT_VERSION_DRIFT",
    "MAPPING_VERSION_DRIFT",
    "CREDENTIAL_REFERENCE_DRIFT",
    "AI_ELIGIBILITY_GRANT_FORBIDDEN",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def validate_credential_reference(reference: str) -> str:
    value = str(reference or "").strip()
    if not value:
        raise ValueError("CREDENTIAL_REFERENCE_REQUIRED")
    if not value.startswith(VAULT_PREFIXES):
        raise ValueError("EXTERNAL_VAULT_REFERENCE_REQUIRED")
    lowered = value.lower()
    if any(marker in lowered for marker in ("?secret=", "?token=", "#secret=", "#token=")):
        raise ValueError("INLINE_PROVIDER_SECRET_FORBIDDEN")
    return value


@dataclass(frozen=True)
class MappingGovernanceResult:
    vertical: str
    complete: bool
    required_sections: tuple[str, ...]
    present_sections: tuple[str, ...]
    missing_sections: tuple[str, ...]
    documentation_hash: str
    mapping_fingerprint: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CertificationEvidenceV1:
    provider_code: str
    vertical: str
    documentation_version: str
    documentation_hash: str
    mapping_fingerprint: str
    credential_reference: str
    evidence_references: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime
    revoked: bool = False
    external_transport_verified: bool = False
    production_live: bool = False


@dataclass
class ProviderOnboardingGovernanceState:
    provider_code: str
    vertical: str
    state: str = "DOCUMENT_RECEIVED"
    blockers: set[str] = field(default_factory=set)
    documentation_version: str | None = None
    documentation_hash: str | None = None
    mapping_fingerprint: str | None = None
    credential_reference: str | None = None
    certification: CertificationEvidenceV1 | None = None
    external_transport_verified: bool = False
    production_live: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "go.provider-onboarding-governance.v1",
            "provider_code": self.provider_code,
            "vertical": self.vertical,
            "state": self.state,
            "blockers": sorted(self.blockers),
            "documentation_version": self.documentation_version,
            "documentation_hash": self.documentation_hash,
            "mapping_fingerprint": self.mapping_fingerprint,
            "credential_reference": self.credential_reference,
            "certification": asdict(self.certification) if self.certification else None,
            "external_transport_verified": False,
            "production_live": False,
            "live_eligibility": "FORBIDDEN_IN_WAVE07",
        }


class ProviderOnboardingGovernanceV1:
    """Wave 07 provider-governance lifecycle.

    This control plane is deliberately provider-neutral and transport-free. It accepts
    only provider contract metadata, Vault/KMS references, deterministic mapping facts,
    and certification evidence. It cannot grant LIVE eligibility or execute transport.
    """

    @staticmethod
    def transition(state: ProviderOnboardingGovernanceState, to_state: str) -> ProviderOnboardingGovernanceState:
        if to_state not in STATES:
            raise ValueError("UNKNOWN_PROVIDER_ONBOARDING_STATE")
        allowed = ALLOWED_TRANSITIONS.get(state.state, set())
        if to_state not in allowed:
            raise ValueError(f"INVALID_PROVIDER_ONBOARDING_TRANSITION:{state.state}->{to_state}")
        state.state = to_state
        return state

    def intake_contract(self, state: ProviderOnboardingGovernanceState, contract: dict[str, Any]) -> dict[str, Any]:
        if state.state == "DOCUMENT_RECEIVED":
            self.transition(state, "CONTRACT_INTAKE")
        if state.state != "CONTRACT_INTAKE":
            raise ValueError("CONTRACT_INTAKE_STATE_REQUIRED")
        try:
            normalized = validate_provider_adapter_contract_v2(contract)
        except ProviderContractError as exc:
            state.blockers.add("DOCUMENTATION_MISSING")
            raise ValueError(f"CONTRACT_INTAKE_BLOCKED:{exc}") from exc
        if normalized["vertical"] != state.vertical or str(normalized["provider"]["provider_code"]) != state.provider_code:
            raise ValueError("PROVIDER_CONTRACT_IDENTITY_MISMATCH")
        source = normalized["contract_source"]
        state.documentation_version = str(source["documentation_version"])
        state.documentation_hash = str(source["documentation_hash"])
        state.blockers.discard("DOCUMENTATION_MISSING")
        self.transition(state, "MAPPING_IN_PROGRESS")
        return normalized

    def evaluate_mapping(self, state: ProviderOnboardingGovernanceState, contract: dict[str, Any]) -> MappingGovernanceResult:
        if state.state != "MAPPING_IN_PROGRESS":
            raise ValueError("MAPPING_IN_PROGRESS_STATE_REQUIRED")
        vertical = str(contract.get("vertical") or "").upper()
        if vertical != state.vertical or vertical not in VERTICAL_PROFILES:
            raise ValueError("VERTICAL_MAPPING_IDENTITY_MISMATCH")
        required = tuple(VERTICAL_PROFILES[vertical]["canonical"])
        canonical = contract.get("canonical_mapping") or {}
        present = tuple(sorted(k for k in required if canonical.get(k) not in (None, {}, [])))
        missing = tuple(k for k in required if k not in present)
        source = contract.get("contract_source") or {}
        doc_hash = str(source.get("documentation_hash") or "")
        import hashlib, json
        fingerprint = hashlib.sha256(json.dumps({k: canonical.get(k) for k in required}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        result = MappingGovernanceResult(vertical, not missing, required, present, missing, doc_hash, fingerprint)
        if missing:
            state.blockers.add("MAPPING_INCOMPLETE")
            return result
        state.blockers.discard("MAPPING_INCOMPLETE")
        state.mapping_fingerprint = fingerprint
        self.transition(state, "CREDENTIAL_REFERENCE_PENDING")
        return result

    def bind_credential_reference(self, state: ProviderOnboardingGovernanceState, reference: str) -> str:
        if state.state != "CREDENTIAL_REFERENCE_PENDING":
            raise ValueError("CREDENTIAL_REFERENCE_PENDING_STATE_REQUIRED")
        try:
            value = validate_credential_reference(reference)
        except ValueError:
            state.blockers.add("CREDENTIAL_REFERENCE_INVALID")
            raise
        state.blockers.discard("CREDENTIAL_REFERENCE_INVALID")
        state.credential_reference = value
        self.transition(state, "CREDENTIAL_REFERENCE_READY")
        self.transition(state, "CERTIFICATION_READY")
        return value

    def certify_readiness(
        self,
        state: ProviderOnboardingGovernanceState,
        contract: dict[str, Any],
        *,
        issued_at: datetime,
        expires_at: datetime,
    ) -> CertificationEvidenceV1:
        if state.state != "CERTIFICATION_READY":
            raise ValueError("CERTIFICATION_READY_STATE_REQUIRED")
        if expires_at <= issued_at:
            raise ValueError("CERTIFICATION_EXPIRY_INVALID")
        self.transition(state, "CERTIFICATION_RUNNING")
        report = provider_certification_harness_v2.certify(contract).as_dict()
        if not report["passed"]:
            state.blockers.add("CERTIFICATION_FAILED")
            self.transition(state, "CERTIFICATION_BLOCKED")
            raise ValueError("CERTIFICATION_FAILED")
        if not state.mapping_fingerprint or not state.credential_reference or not state.documentation_hash:
            state.blockers.add("CERTIFICATION_EVIDENCE_MISSING")
            self.transition(state, "CERTIFICATION_BLOCKED")
            raise ValueError("CERTIFICATION_EVIDENCE_MISSING")
        evidence = CertificationEvidenceV1(
            provider_code=state.provider_code,
            vertical=state.vertical,
            documentation_version=str(state.documentation_version),
            documentation_hash=str(state.documentation_hash),
            mapping_fingerprint=state.mapping_fingerprint,
            credential_reference=state.credential_reference,
            evidence_references=tuple((contract.get("attestation") or {}).get("evidence_references") or ()),
            issued_at=issued_at,
            expires_at=expires_at,
        )
        state.certification = evidence
        state.blockers.discard("CERTIFICATION_FAILED")
        state.blockers.discard("CERTIFICATION_EVIDENCE_MISSING")
        self.transition(state, "CERTIFIED_READINESS_ONLY")
        return evidence

    def evaluate_drift(
        self,
        state: ProviderOnboardingGovernanceState,
        *,
        documentation_version: str,
        documentation_hash: str,
        mapping_fingerprint: str,
        credential_reference: str,
        now_at: datetime,
        revoked: bool = False,
    ) -> set[str]:
        cert = state.certification
        if cert is None:
            state.blockers.add("CERTIFICATION_EVIDENCE_MISSING")
        else:
            if revoked or cert.revoked:
                state.blockers.add("CERTIFICATION_REVOKED")
            if now_at >= cert.expires_at:
                state.blockers.add("CERTIFICATION_EXPIRED")
            if documentation_version != cert.documentation_version or documentation_hash != cert.documentation_hash:
                state.blockers.add("CONTRACT_VERSION_DRIFT")
            if mapping_fingerprint != cert.mapping_fingerprint:
                state.blockers.add("MAPPING_VERSION_DRIFT")
            if validate_credential_reference(credential_reference) != cert.credential_reference:
                state.blockers.add("CREDENTIAL_REFERENCE_DRIFT")
        if state.blockers and state.state in {"CERTIFIED_READINESS_ONLY", "ELIGIBILITY_PENDING", "ELIGIBLE_FOR_SANDBOX_ONLY"}:
            self.transition(state, "RECERTIFICATION_REQUIRED")
        return set(state.blockers)

    def evaluate_sandbox_eligibility(
        self,
        state: ProviderOnboardingGovernanceState,
        *,
        actor_kind: str,
        now_at: datetime,
    ) -> str:
        if actor_kind.upper() == "AI":
            state.blockers.add("AI_ELIGIBILITY_GRANT_FORBIDDEN")
            raise PermissionError("AI_ELIGIBILITY_GRANT_FORBIDDEN")
        if state.state != "CERTIFIED_READINESS_ONLY":
            raise ValueError("CERTIFIED_READINESS_ONLY_REQUIRED")
        cert = state.certification
        if cert is None:
            state.blockers.add("CERTIFICATION_EVIDENCE_MISSING")
            raise ValueError("CERTIFICATION_EVIDENCE_MISSING")
        self.evaluate_drift(
            state,
            documentation_version=str(state.documentation_version),
            documentation_hash=str(state.documentation_hash),
            mapping_fingerprint=str(state.mapping_fingerprint),
            credential_reference=str(state.credential_reference),
            now_at=now_at,
            revoked=False,
        )
        if state.blockers:
            raise ValueError("PROVIDER_ELIGIBILITY_BLOCKED:" + ",".join(sorted(state.blockers)))
        self.transition(state, "ELIGIBILITY_PENDING")
        self.transition(state, "ELIGIBLE_FOR_SANDBOX_ONLY")
        state.external_transport_verified = False
        state.production_live = False
        return state.state

    @staticmethod
    def assert_never_live(state: ProviderOnboardingGovernanceState) -> None:
        if state.production_live or state.external_transport_verified:
            raise ValueError("WAVE07_LIVE_PROMOTION_FORBIDDEN")


provider_onboarding_governance_v1 = ProviderOnboardingGovernanceV1()
