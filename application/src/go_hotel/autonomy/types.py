from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from types import MappingProxyType
from typing import FrozenSet, Mapping, Tuple


class RiskClass(str, Enum):
    R0 = "R0_LOCAL_REVERSIBLE"
    R1 = "R1_BOUNDED_OPERATIONAL"
    R2 = "R2_MATERIAL"
    R3 = "R3_CONSTITUTIONAL_SECURITY_FINANCIAL_BOUNDARY"
    R4 = "R4_PROHIBITED"


class Environment(str, Enum):
    DEV = "DEV"
    TEST = "TEST"
    SHADOW = "SHADOW"
    STAGING = "STAGING"
    CANARY = "CANARY"
    PRODUCTION = "PRODUCTION"


class ProductionReality(str, Enum):
    SHADOW = "SHADOW"
    CANARY = "CANARY"
    AUTONOMOUS_QUALIFIED = "AUTONOMOUS_QUALIFIED"
    RESTRICTED = "RESTRICTED"
    DETERMINISTIC_CONTROLLED = "DETERMINISTIC_CONTROLLED"
    SUSPENDED = "SUSPENDED"
    PROHIBITED = "PROHIBITED"


class CollaborationMode(str, Enum):
    CONTRACT = "CONTRACT"
    EVENT = "EVENT"


class LegalDecision(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    LEGAL_ALLOW = "LEGAL_ALLOW"
    LEGAL_ALLOW_WITH_CONDITIONS = "LEGAL_ALLOW_WITH_CONDITIONS"
    LEGAL_HOLD = "LEGAL_HOLD"
    LEGAL_BLOCK = "LEGAL_BLOCK"


@dataclass(frozen=True)
class LegalExposureProfile:
    consumer_rights: bool = False
    supplier_rights: bool = False
    external_commitment: bool = False
    contract_interpretation: bool = False
    regulatory_obligation: bool = False
    pii_or_identity_use: bool = False
    cross_border_data: bool = False
    money_or_refund: bool = False
    marketing_or_public_claim: bool = False
    content_or_ip_rights: bool = False
    new_jurisdiction: bool = False
    tax_employment_insurance_or_visa: bool = False

    def __post_init__(self) -> None:
        if any(type(value) is not bool for value in vars(self).values()):
            raise ValueError("LEGAL_EXPOSURE_MUST_BE_BOOLEAN")

    @property
    def active_tags(self) -> FrozenSet[str]:
        return frozenset(name for name, value in vars(self).items() if value)

    @property
    def any_exposure(self) -> bool:
        return bool(self.active_tags)


@dataclass(frozen=True)
class AIActionEnvelope:
    action_id: str
    cell_id: str
    capability: str
    target_domain: str
    environment: Environment
    risk_factors: "RiskFactors"
    legal_exposure: LegalExposureProfile = field(default_factory=LegalExposureProfile)
    jurisdiction: str | None = None
    legal_entity: str | None = None
    truth_mutation: bool = False
    require_autonomous_execution: bool = False
    evidence_refs: Tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        from .policy import RiskFactors
        if not isinstance(self.environment, Environment) or not isinstance(self.risk_factors, RiskFactors):
            raise ValueError("TYPED_ACTION_ENVIRONMENT_AND_RISK_REQUIRED")
        if not isinstance(self.legal_exposure, LegalExposureProfile):
            raise ValueError("TYPED_LEGAL_EXPOSURE_REQUIRED")
        if type(self.truth_mutation) is not bool or type(self.require_autonomous_execution) is not bool:
            raise ValueError("ACTION_FLAGS_MUST_BE_BOOLEAN")
        if any(not isinstance(v, str) or not v.strip() for v in
               (self.action_id, self.cell_id, self.capability, self.target_domain)):
            raise ValueError("ACTION_IDENTITY_REQUIRED")
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in self.metadata.items()):
            raise ValueError("ACTION_METADATA_MUST_BE_TEXT")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        if any(not isinstance(v, str) or not v.strip() for v in self.evidence_refs):
            raise ValueError("ACTION_EVIDENCE_REFERENCE_MUST_BE_TEXT")


@dataclass(frozen=True)
class AuthorityDecision:
    allowed: bool
    code: str
    reason: str
    risk_class: RiskClass | None


@dataclass(frozen=True)
class LegalReviewResult:
    decision: LegalDecision
    reason: str
    policy_rule_ids: Tuple[str, ...] = ()
    conditions: Tuple[str, ...] = ()
    condition_requirements: Tuple[Tuple[str, str], ...] = ()
    policy_bindings: Tuple[Tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ActionControlResult:
    authority: AuthorityDecision
    legal_review_required: bool
    legal: LegalReviewResult | None
    executable: bool
    condition_evidence_refs: Tuple[str, ...] = ()
    blocked_conditions: Tuple[str, ...] = ()


@dataclass(frozen=True)
class CellDefinition:
    cell_id: str
    name: str
    domain: str
    truth_owned: str
    capabilities: FrozenSet[str]
    forbidden_capabilities: FrozenSet[str] = field(default_factory=frozenset)
    named_human_role: str | None = None
    legal_entity: str | None = None

    @property
    def accountability_bound(self) -> bool:
        return bool(self.named_human_role and self.legal_entity)


@dataclass(frozen=True)
class ContractDefinition:
    contract_id: str
    producer_cell: str
    consumer_cells: Tuple[str, ...]
    purpose: str
    version: str = "1.0"


@dataclass(frozen=True)
class EventDefinition:
    event_type: str
    producer_cell: str
    allowed_consumers: Tuple[str, ...]
    truth_reference_only: bool = True
    version: str = "1.0"


@dataclass(frozen=True)
class QualificationEvidence:
    evaluation: bool
    historical_evidence: bool
    boundary_tests: bool
    failure_tests: bool
    security_tests: bool
    confidence_calibration: bool
    rollback_capability: bool
    independent_validation: bool
    production_evidence: bool
    evidence_refs: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if any(type(v) is not bool for k, v in vars(self).items() if k != "evidence_refs"):
            raise ValueError("QUALIFICATION_EVIDENCE_FLAGS_MUST_BE_BOOLEAN")
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        if any(not isinstance(v, str) or not v.strip() for v in self.evidence_refs):
            raise ValueError("QUALIFICATION_EVIDENCE_REFERENCE_REQUIRED")

    def complete_for(self, risk: RiskClass, environment: Environment) -> bool:
        base = (
            self.evaluation
            and self.boundary_tests
            and self.failure_tests
            and self.security_tests
            and self.rollback_capability
            and self.independent_validation
        )
        if risk is RiskClass.R0:
            return base
        if risk is RiskClass.R1:
            return base and self.historical_evidence and self.confidence_calibration
        if risk is RiskClass.R2:
            return (
                base
                and self.historical_evidence
                and self.confidence_calibration
                and (self.production_evidence or environment is not Environment.PRODUCTION)
            )
        return False


@dataclass(frozen=True)
class QualificationKey:
    cell_id: str
    capability: str
    risk_class: RiskClass
    environment: Environment


@dataclass(frozen=True)
class QualificationRecord:
    key: QualificationKey
    reality: ProductionReality
    evidence: QualificationEvidence
    validator_cell: str
    releaser_cell: str | None = None
    policy_version: str = "V7.0-BUILD01"
    metadata: Mapping[str, str] = field(default_factory=dict)
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        # Keep legacy records inspectable; absence of a validity window never grants execution.
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
