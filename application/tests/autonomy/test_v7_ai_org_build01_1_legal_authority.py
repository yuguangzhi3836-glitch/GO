from go_hotel.autonomy import (
    ALL_CELL_REGISTRY,
    ALL_CELLS,
    AILegalPolicyRegistry,
    AIActionEnvelope,
    AuthorityConstitutionGate,
    Environment,
    LegalDecision,
    LegalExposureProfile,
    LegalPolicyRule,
    RiskFactors,
    evaluate_ai_action,
)


def rf(**kw):
    base = dict(reversibility=0, blast_radius=0, money_exposure=0, pii_exposure=0, truth_mutation=0, customer_impact=0, supplier_impact=0, regulatory_impact=0, cross_domain_impact=0)
    base.update(kw)
    return RiskFactors(**base)


def action(**kw):
    base = dict(
        action_id="a-1", cell_id="C02", capability="FLIGHT_SEARCH", target_domain="FLIGHT",
        environment=Environment.TEST, risk_factors=rf(), legal_exposure=LegalExposureProfile(),
    )
    base.update(kw)
    return AIActionEnvelope(**base)


def test_build01_1_adds_c14_without_changing_13_existing_cells():
    assert len(ALL_CELLS) == 14
    assert ALL_CELL_REGISTRY.cell("C14").name == "AI Constitutional, Legal & Regulatory Control Cell"
    assert ALL_CELL_REGISTRY.cell("C14").truth_owned == "CONSTITUTIONAL_LEGAL_COMPLIANCE_DECISION_TRUTH"


def test_all_actions_must_pass_authority_even_when_no_legal_review_is_required():
    gate = AuthorityConstitutionGate(ALL_CELL_REGISTRY)
    result = evaluate_ai_action(action(), authority_gate=gate, legal_registry=AILegalPolicyRegistry())
    assert result.authority.allowed is True
    assert result.legal_review_required is False
    assert result.legal.decision is LegalDecision.NOT_REQUIRED
    assert result.executable is True


def test_unowned_capability_is_blocked_before_legal_review():
    gate = AuthorityConstitutionGate(ALL_CELL_REGISTRY)
    result = evaluate_ai_action(action(capability="REFUND"), authority_gate=gate, legal_registry=AILegalPolicyRegistry())
    assert result.authority.allowed is False
    assert result.authority.code == "CAPABILITY_NOT_OWNED"
    assert result.legal is None
    assert result.executable is False


def test_cross_domain_truth_mutation_is_blocked_by_authority_gate():
    gate = AuthorityConstitutionGate(ALL_CELL_REGISTRY)
    result = evaluate_ai_action(
        action(target_domain="TRANSACTION_FINANCE", truth_mutation=True, risk_factors=rf(truth_mutation=2, cross_domain_impact=2)),
        authority_gate=gate,
        legal_registry=AILegalPolicyRegistry(),
    )
    assert result.authority.allowed is False
    assert result.authority.code == "CROSS_DOMAIN_TRUTH_MUTATION_DENIED"


def test_self_empowerment_is_hard_blocked():
    gate = AuthorityConstitutionGate(ALL_CELL_REGISTRY)
    a = action(cell_id="C12", capability="EXPAND_OWN_AUTHORITY", target_domain="PLATFORM_SECURITY_MODEL_GATEWAY")
    result = evaluate_ai_action(a, authority_gate=gate, legal_registry=AILegalPolicyRegistry())
    assert result.authority.allowed is False
    assert result.authority.code == "SELF_EMPOWERMENT_PROHIBITED"


def test_legal_exposure_routes_to_c14_and_no_policy_fails_closed_to_hold():
    gate = AuthorityConstitutionGate(ALL_CELL_REGISTRY)
    exposed = action(
        legal_exposure=LegalExposureProfile(marketing_or_public_claim=True),
        jurisdiction="SG",
        risk_factors=rf(customer_impact=1, regulatory_impact=1),
    )
    result = evaluate_ai_action(exposed, authority_gate=gate, legal_registry=AILegalPolicyRegistry())
    assert result.legal_review_required is True
    assert result.legal.decision is LegalDecision.LEGAL_HOLD
    assert result.executable is False


def test_legally_exposed_action_requires_jurisdiction():
    gate = AuthorityConstitutionGate(ALL_CELL_REGISTRY)
    exposed = action(legal_exposure=LegalExposureProfile(contract_interpretation=True))
    result = evaluate_ai_action(exposed, authority_gate=gate, legal_registry=AILegalPolicyRegistry())
    assert result.legal.decision is LegalDecision.LEGAL_HOLD
    assert result.legal.reason == "JURISDICTION_REQUIRED"


def test_approved_machine_rule_returns_immediate_legal_allow():
    gate = AuthorityConstitutionGate(ALL_CELL_REGISTRY)
    registry = AILegalPolicyRegistry((
        LegalPolicyRule(
            "TEST_APPROVED_PUBLIC_CLAIM_RULE",
            LegalDecision.LEGAL_ALLOW,
            jurisdictions=frozenset({"SG"}),
            required_exposure_tags=frozenset({"marketing_or_public_claim"}),
            reason="approved machine policy",
        ),
    ))
    exposed = action(
        legal_exposure=LegalExposureProfile(marketing_or_public_claim=True),
        jurisdiction="SG",
        risk_factors=rf(customer_impact=1, regulatory_impact=1),
    )
    result = evaluate_ai_action(exposed, authority_gate=gate, legal_registry=registry)
    assert result.legal.decision is LegalDecision.LEGAL_ALLOW
    assert result.executable is True


def test_green_operation_label_cannot_bypass_dynamic_legal_exposure():
    gate = AuthorityConstitutionGate(ALL_CELL_REGISTRY)
    exposed = action(
        metadata={"operation_label": "GREEN"},
        legal_exposure=LegalExposureProfile(consumer_rights=True),
        jurisdiction="SG",
        risk_factors=rf(customer_impact=1),
    )
    result = evaluate_ai_action(exposed, authority_gate=gate, legal_registry=AILegalPolicyRegistry())
    assert result.legal_review_required is True
    assert result.legal.decision is LegalDecision.LEGAL_HOLD


def test_c14_constitutional_review_is_mandatory_for_green_actions_too():
    gate = AuthorityConstitutionGate(ALL_CELL_REGISTRY)
    result = evaluate_ai_action(action(metadata={"operation_label": "GREEN"}), authority_gate=gate, legal_registry=AILegalPolicyRegistry())
    assert result.authority.code == "AUTHORITY_ALLOW"
    assert result.authority.allowed is True
    # External legal review may be unnecessary, but the C14 constitutional/authority gate was still mandatory.
    assert result.legal_review_required is False


def test_go_constitution_prohibition_blocks_even_without_external_legal_exposure():
    gate = AuthorityConstitutionGate(ALL_CELL_REGISTRY)
    result = evaluate_ai_action(action(capability="EXPAND_OWN_AUTHORITY", cell_id="C12", target_domain="PLATFORM_SECURITY_MODEL_GATEWAY"), authority_gate=gate, legal_registry=AILegalPolicyRegistry())
    assert result.authority.allowed is False
    assert result.authority.code == "SELF_EMPOWERMENT_PROHIBITED"
    assert result.executable is False
