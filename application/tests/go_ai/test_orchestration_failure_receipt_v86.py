"""C08 verification-stage orchestration failure receipts and preserved fallback."""

import pytest
from sqlalchemy import select

from go_hotel.go_ai import service as service_module
from go_hotel.go_ai.complexity import ComplexityAssessment
from go_hotel.go_ai.models import ProviderConfig
from go_hotel.go_ai.planner import PlannedTask
from go_hotel.go_ai.providers import DeterministicTestProvider, GOAIProviderError
from go_hotel.go_ai.registry import GOAIProviderRegistry
from test_c08_synthesis_audit_finalization import SynthesisProvider, audit_session

pytestmark = pytest.mark.no_db


def _force_verification_path(monkeypatch, service):
    assessment = ComplexityAssessment(
        tier="TIER_3_DEEP_REASONING",
        score=5,
        reasons=("TEST_VERIFICATION_PATH",),
        max_parallel_tasks=1,
        requires_model_verification=True,
        requires_deterministic_gate=False,
    )
    monkeypatch.setattr(
        service.complexity_classifier,
        "classify",
        lambda message, *, context=None: assessment,
    )
    monkeypatch.setattr(
        service.task_planner,
        "plan",
        lambda message, current_assessment: [
            PlannedTask("task_main", "GENERAL", f"Answer:\n{message}")
        ],
    )


class SecondaryProvider(DeterministicTestProvider):
    def __init__(self, provider_id: str, *, fail_code: str | None = None, crash: str | None = None):
        super().__init__(
            ProviderConfig(
                provider_id=provider_id,
                adapter="openai_compatible",
                model=f"{provider_id}-model",
                base_url="https://unused.test/v1",
                api_key_env=f"{provider_id.upper()}_UNUSED_TEST_KEY",
                cost_tier=2,
                priority=200,
            ),
            text="verification-ok",
            fail_code=fail_code,
        )
        self._crash = crash

    def generate(self, request):
        if self._crash:
            raise RuntimeError(self._crash)
        return super().generate(request)


def test_verification_provider_crash_finalizes_failed_receipt(audit_session, monkeypatch):
    service = service_module.GOAIService(GOAIProviderRegistry([
        SynthesisProvider(),
        SecondaryProvider("c08_verification_crash", crash="C08_VERIFICATION_PROVIDER_CRASH"),
    ]))
    _force_verification_path(monkeypatch, service)

    with pytest.raises(ValueError, match="^GO_AI_VERIFICATION_FAILED$"):
        service.orchestrate(message="Need an itinerary", account_id="c08_owner")

    with audit_session() as session:
        request = session.scalar(select(service_module.GoAIRequestRow))
        assert request.state == "FAILED"
        assert request.failure_code == "GO_AI_VERIFICATION_FAILED"
        assert request.selected_provider is None
        assert request.response_hash is None

    assessment = service.assess_recovery(request.go_ai_request_id)
    assert assessment["gate"] == "NO_RECOVERY_REQUIRED"
    assert assessment["recovery_action"] == "PRESERVE_TERMINAL_AUDIT"
    assert assessment["state"] == "FAILED"


def test_verification_gate_crash_finalizes_failed_receipt(audit_session, monkeypatch):
    service = service_module.GOAIService(GOAIProviderRegistry([SynthesisProvider()]))
    _force_verification_path(monkeypatch, service)
    monkeypatch.setattr(
        service.verification_gate,
        "verify",
        lambda *, answer, assessment, model_check_completed: (_ for _ in ()).throw(
            RuntimeError("C08_VERIFICATION_GATE_CRASH")
        ),
    )

    with pytest.raises(ValueError, match="^GO_AI_VERIFICATION_FAILED$"):
        service.orchestrate(message="Need an itinerary", account_id="c08_owner")

    with audit_session() as session:
        request = session.scalar(select(service_module.GoAIRequestRow))
        assert request.state == "FAILED"
        assert request.failure_code == "GO_AI_VERIFICATION_FAILED"
        assert request.selected_provider is None
        assert request.response_hash is None

    assessment = service.assess_recovery(request.go_ai_request_id)
    assert assessment["gate"] == "NO_RECOVERY_REQUIRED"
    assert assessment["recovery_action"] == "PRESERVE_TERMINAL_AUDIT"
    assert assessment["state"] == "FAILED"


def test_verification_provider_error_keeps_existing_fallback_and_completes(audit_session, monkeypatch):
    service = service_module.GOAIService(GOAIProviderRegistry([
        SynthesisProvider(),
        SecondaryProvider("c08_verification_soft_fail", fail_code="GO_AI_PROVIDER_TIMEOUT"),
    ]))
    _force_verification_path(monkeypatch, service)

    result = service.orchestrate(message="Need an itinerary", account_id="c08_owner")

    with audit_session() as session:
        request = session.get(service_module.GoAIRequestRow, result["request_id"])
        assert request.state == "COMPLETED"
        assert request.failure_code is None
        assert request.response_hash is not None
        assert request.selected_provider == "c08_isolated_test"

    assessment = service.assess_recovery(result["request_id"])
    assert assessment["gate"] == "NO_RECOVERY_REQUIRED"
    assert assessment["recovery_action"] == "PRESERVE_TERMINAL_AUDIT"
    assert assessment["state"] == "COMPLETED"
