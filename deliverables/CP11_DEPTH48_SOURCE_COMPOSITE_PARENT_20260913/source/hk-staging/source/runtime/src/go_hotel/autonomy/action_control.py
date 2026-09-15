from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .policy import RiskFactors, classify_risk
from .registry import AutonomyQualificationRegistry, DomainOwnershipRegistry, GovernanceViolation
from .types import (
    AIActionEnvelope,
    ActionControlResult,
    AuthorityDecision,
    Environment,
    LegalDecision,
    LegalReviewResult,
    ProductionReality,
    QualificationKey,
    RiskClass,
)


SELF_EMPOWERMENT_CAPABILITIES = frozenset({
    "GRANT_SELF_PERMISSION",
    "EXPAND_OWN_AUTHORITY",
    "MODIFY_OWN_RISK_BOUNDARY",
    "MODIFY_CONSTITUTION",
    "BYPASS_MODEL_GATEWAY",
    "BYPASS_FINANCIAL_SECURITY",
    "CREATE_UNAUTHORIZED_DATA_EGRESS",
    "CLAIM_OTHER_DOMAIN_TRUTH_AUTHORITY",
})


@dataclass(frozen=True)
class AuthorityConstitutionGate:
    """C14 mandatory constitutional/authority legal gate for every AI action.

    GO Constitution is GO internal supreme law. This deterministic C14 gate applies to 100%
    of AI actions. The acting AI never self-declares or expands authority.
    """

    cells: DomainOwnershipRegistry
    qualifications: AutonomyQualificationRegistry | None = None

    def check(self, action: AIActionEnvelope) -> AuthorityDecision:
        try:
            cell = self.cells.cell(action.cell_id)
        except GovernanceViolation as exc:
            return AuthorityDecision(False, "UNKNOWN_CELL", str(exc), None)

        if action.capability in SELF_EMPOWERMENT_CAPABILITIES:
            return AuthorityDecision(False, "SELF_EMPOWERMENT_PROHIBITED", action.capability, RiskClass.R4)
        if action.capability in cell.forbidden_capabilities:
            return AuthorityDecision(False, "FORBIDDEN_CAPABILITY", action.capability, RiskClass.R4)
        if action.capability not in cell.capabilities:
            return AuthorityDecision(False, "CAPABILITY_NOT_OWNED", action.capability, None)

        risk_class = classify_risk(action.risk_factors)
        if risk_class is RiskClass.R4:
            return AuthorityDecision(False, "R4_PROHIBITED", "risk engine classified action as prohibited", risk_class)

        # Any requested Truth mutation is checked against final Domain ownership.
        if action.truth_mutation:
            try:
                owner = self.cells.owner_for(action.target_domain)
            except GovernanceViolation as exc:
                return AuthorityDecision(False, "UNKNOWN_TARGET_DOMAIN", str(exc), risk_class)
            if owner.cell_id != action.cell_id:
                return AuthorityDecision(
                    False,
                    "CROSS_DOMAIN_TRUTH_MUTATION_DENIED",
                    f"{action.cell_id}->{action.target_domain};owner={owner.cell_id}",
                    risk_class,
                )

        # R3 may exist only under deterministic/system control, never ordinary domain autonomy.
        if risk_class is RiskClass.R3 and action.require_autonomous_execution:
            return AuthorityDecision(False, "R3_NOT_DOMAIN_AUTONOMOUS", "deterministic control required", risk_class)

        # When an action asks to execute under standing autonomous authority, qualification must exist.
        if action.require_autonomous_execution and self.qualifications is not None:
            key = QualificationKey(action.cell_id, action.capability, risk_class, action.environment)
            record = self.qualifications.get(key)
            if record is None:
                return AuthorityDecision(False, "AUTONOMY_QUALIFICATION_MISSING", str(key), risk_class)
            if record.reality is not ProductionReality.AUTONOMOUS_QUALIFIED:
                return AuthorityDecision(False, "AUTONOMY_NOT_CURRENTLY_QUALIFIED", record.reality.value, risk_class)

        return AuthorityDecision(True, "AUTHORITY_ALLOW", "within proven cell/capability/domain boundary", risk_class)


def requires_legal_review(action: AIActionEnvelope) -> bool:
    """Dynamic legal-exposure routing; there is no permanent 'green operation' whitelist."""
    return action.legal_exposure.any_exposure


@dataclass(frozen=True)
class LegalPolicyRule:
    rule_id: str
    decision: LegalDecision
    jurisdictions: frozenset[str] = frozenset({"*"})
    required_exposure_tags: frozenset[str] = frozenset()
    reason: str = ""
    conditions: tuple[str, ...] = ()

    def matches(self, action: AIActionEnvelope) -> bool:
        if "*" not in self.jurisdictions and action.jurisdiction not in self.jurisdictions:
            return False
        tags = action.legal_exposure.active_tags
        return self.required_exposure_tags.issubset(tags)


class AILegalPolicyRegistry:
    """Machine-readable legal policy registry.

    Build 01.1 ships the control mechanism, not fabricated jurisdiction-specific law.
    Legally exposed actions with no applicable approved rule fail closed to LEGAL_HOLD.
    """

    def __init__(self, rules: tuple[LegalPolicyRule, ...] = ()):
        self._rules = rules

    def review(self, action: AIActionEnvelope, *, authority: AuthorityDecision) -> LegalReviewResult:
        if not authority.allowed:
            return LegalReviewResult(LegalDecision.LEGAL_BLOCK, "AUTHORITY_BLOCK_PRECEDES_LEGAL", (), ())
        if not requires_legal_review(action):
            return LegalReviewResult(LegalDecision.NOT_REQUIRED, "NO_LEGAL_EXPOSURE", (), ())
        if not action.jurisdiction:
            return LegalReviewResult(LegalDecision.LEGAL_HOLD, "JURISDICTION_REQUIRED", (), ())

        matches = tuple(rule for rule in self._rules if rule.matches(action))
        if not matches:
            return LegalReviewResult(
                LegalDecision.LEGAL_HOLD,
                "NO_APPROVED_LEGAL_POLICY_MATCH",
                (),
                ("legal_policy_required",),
            )

        # Most restrictive result wins. This prevents an ALLOW rule from masking a BLOCK/HOLD rule.
        precedence = {
            LegalDecision.LEGAL_BLOCK: 4,
            LegalDecision.LEGAL_HOLD: 3,
            LegalDecision.LEGAL_ALLOW_WITH_CONDITIONS: 2,
            LegalDecision.LEGAL_ALLOW: 1,
            LegalDecision.NOT_REQUIRED: 0,
        }
        selected = max(matches, key=lambda r: precedence[r.decision])
        rule_ids = tuple(rule.rule_id for rule in matches)
        return LegalReviewResult(selected.decision, selected.reason or selected.rule_id, rule_ids, selected.conditions)


def evaluate_ai_action(
    action: AIActionEnvelope,
    *,
    authority_gate: AuthorityConstitutionGate,
    legal_registry: AILegalPolicyRegistry,
) -> ActionControlResult:
    """Single mandatory entry point for governed AI actions.

    Invariant:
      1. 100% of AI actions are reviewed by C14 under GO Constitution via the authority gate.
      2. Actions with external legal exposure receive additional law/regulation/contract review.
      3. No action can self-authorize or self-expand authority.
      4. GO Constitution is internal supreme law, but never overrides mandatory applicable external law.
    """
    authority = authority_gate.check(action)
    if not authority.allowed:
        return ActionControlResult(authority, False, None, False)

    legal_required = requires_legal_review(action)
    legal = legal_registry.review(action, authority=authority) if legal_required else LegalReviewResult(
        LegalDecision.NOT_REQUIRED, "NO_LEGAL_EXPOSURE", (), ()
    )
    executable = legal.decision in {LegalDecision.NOT_REQUIRED, LegalDecision.LEGAL_ALLOW, LegalDecision.LEGAL_ALLOW_WITH_CONDITIONS}
    return ActionControlResult(authority, legal_required, legal, executable)
