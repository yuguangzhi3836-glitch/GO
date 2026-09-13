from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable

from .policy import RiskFactors, classify_risk
from .condition_evidence import ConditionEvidence
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
    policy_version: str = "V7.0-BUILD01"

    def check(self, action: AIActionEnvelope, *, at: datetime | None = None) -> AuthorityDecision:
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

        # Declared action facts impose a minimum. A zero supplied score cannot erase them.
        exposure = action.legal_exposure
        risk_class = classify_risk(replace(action.risk_factors,
            money_exposure=max(action.risk_factors.money_exposure, 2 if exposure.money_or_refund else 0),
            pii_exposure=max(action.risk_factors.pii_exposure, 2 if exposure.pii_or_identity_use or exposure.cross_border_data else 0),
            truth_mutation=max(action.risk_factors.truth_mutation, 2 if action.truth_mutation else 0)))
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
        if action.require_autonomous_execution and self.qualifications is None:
            return AuthorityDecision(False, "AUTONOMY_QUALIFICATION_REGISTRY_REQUIRED", "standing authority cannot be inferred without qualification evidence", risk_class)
        if action.require_autonomous_execution:
            key = QualificationKey(action.cell_id, action.capability, risk_class, action.environment)
            denial = self.qualifications.current_denial(key, at=at or datetime.now(timezone.utc),
                policy_version=self.policy_version)
            if denial:
                return AuthorityDecision(False, denial, str(key), risk_class)

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
    covered_exposure_tags: frozenset[str] | None = None

    def __post_init__(self) -> None:
        from .types import LegalExposureProfile
        known = frozenset(LegalExposureProfile.__dataclass_fields__)
        required = frozenset(self.required_exposure_tags)
        covered = required if self.covered_exposure_tags is None else frozenset(self.covered_exposure_tags)
        if not self.rule_id or not isinstance(self.decision, LegalDecision) or self.decision is LegalDecision.NOT_REQUIRED:
            raise ValueError("EXTERNAL_POLICY_DECISION_REQUIRED")
        if not required <= known or not covered <= known:
            raise ValueError("UNKNOWN_LEGAL_EXPOSURE_TAG")
        if any(not isinstance(c, str) or not c.strip() for c in self.conditions):
            raise ValueError("NONEMPTY_POLICY_CONDITION_REQUIRED")
        if self.decision is LegalDecision.LEGAL_ALLOW_WITH_CONDITIONS and not self.conditions:
            raise ValueError("CONDITIONAL_POLICY_REQUIRES_CONDITIONS")
        object.__setattr__(self, "required_exposure_tags", required)
        object.__setattr__(self, "covered_exposure_tags", covered)
        object.__setattr__(self, "jurisdictions", frozenset(self.jurisdictions))
        object.__setattr__(self, "conditions", tuple(dict.fromkeys(self.conditions)))

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
        self._rules = tuple(rules)
        if len({r.rule_id for r in self._rules}) != len(self._rules):
            raise ValueError("DUPLICATE_LEGAL_POLICY_ID")

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
        if selected.decision in {LegalDecision.LEGAL_BLOCK, LegalDecision.LEGAL_HOLD}:
            return LegalReviewResult(selected.decision, selected.reason or selected.rule_id, rule_ids, selected.conditions)
        covered = frozenset().union(*(r.covered_exposure_tags for r in matches))
        if not action.legal_exposure.active_tags <= covered:
            return LegalReviewResult(LegalDecision.LEGAL_HOLD, "LEGAL_EXPOSURE_NOT_FULLY_COVERED", rule_ids, ())
        requirements = tuple(sorted({(r.rule_id, c) for r in matches for c in r.conditions}))
        conditions = tuple(sorted({c for _, c in requirements}))
        decision = LegalDecision.LEGAL_ALLOW_WITH_CONDITIONS if requirements else LegalDecision.LEGAL_ALLOW
        return LegalReviewResult(decision, selected.reason or selected.rule_id, rule_ids, conditions, requirements)


def evaluate_ai_action(
    action: AIActionEnvelope,
    *,
    authority_gate: AuthorityConstitutionGate,
    legal_registry: AILegalPolicyRegistry,
    condition_resolver: Callable[[AIActionEnvelope, str, str], ConditionEvidence | None] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ActionControlResult:
    """Single mandatory entry point for governed AI actions.

    Invariant:
      1. 100% of AI actions are reviewed by C14 under GO Constitution via the authority gate.
      2. Actions with external legal exposure receive additional law/regulation/contract review.
      3. No action can self-authorize or self-expand authority.
      4. GO Constitution is internal supreme law, but never overrides mandatory applicable external law.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    authority = authority_gate.check(action, at=clock())
    if not authority.allowed:
        return ActionControlResult(authority, False, None, False)

    legal_required = requires_legal_review(action)
    legal = legal_registry.review(action, authority=authority) if legal_required else LegalReviewResult(
        LegalDecision.NOT_REQUIRED, "NO_LEGAL_EXPOSURE", (), ()
    )
    if legal.decision not in {LegalDecision.NOT_REQUIRED, LegalDecision.LEGAL_ALLOW, LegalDecision.LEGAL_ALLOW_WITH_CONDITIONS}:
        return ActionControlResult(authority, legal_required, legal, False)
    proofs = {}
    for rule_id, condition in legal.condition_requirements:
        try:
            proofs[(rule_id, condition)] = condition_resolver(action, rule_id, condition) if condition_resolver else None
        except Exception:
            # An unavailable fact verifier cannot turn a conditional permit into an allow.
            proofs[(rule_id, condition)] = None
    final_time = clock()
    authority = authority_gate.check(action, at=final_time)
    if not authority.allowed:
        return ActionControlResult(authority, legal_required, legal, False)
    # Conditions may perform lookups; recheck policy and every proof at the final decision time.
    current_legal = legal_registry.review(action, authority=authority)
    if current_legal != legal:
        return ActionControlResult(authority, legal_required,
            LegalReviewResult(LegalDecision.LEGAL_HOLD, "LEGAL_POLICY_CHANGED_DURING_REVIEW"), False)
    blocked = tuple(f"{rid}:{cid}" for (rid, cid), proof in proofs.items()
        if not isinstance(proof, ConditionEvidence) or not proof.valid_for(
            action=action, policy_rule_id=rid, condition_id=cid, at=final_time))
    refs = tuple(sorted({p.evidence_ref for key, p in proofs.items()
        if isinstance(p, ConditionEvidence) and f"{key[0]}:{key[1]}" not in blocked}))
    return ActionControlResult(authority, legal_required, legal, not blocked, refs, blocked)
