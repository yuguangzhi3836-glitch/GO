"""Every GO-owned planning/verification failure leaves a terminal request audit."""
import pytest
from sqlalchemy import select

from go_hotel.db.models import GoAIInvocationRow, GoAIRequestRow
from go_hotel.go_ai import service as service_module
from go_hotel.go_ai.registry import GOAIProviderRegistry
from test_c08_synthesis_audit_finalization import SynthesisProvider, audit_session

pytestmark = pytest.mark.no_db


@pytest.mark.parametrize("stage", ["classification", "planning", "model_verification", "verification_gate"])
def test_unexpected_stage_failure_finalizes_audit_without_replay(audit_session, monkeypatch, stage):
    provider = SynthesisProvider()
    service = service_module.GOAIService(GOAIProviderRegistry([provider]))
    calls = []
    original_compute = service._execute_compute_task

    def compute(**kwargs):
        calls.append(kwargs["task_id"])
        if stage == "model_verification" and kwargs["task_id"] == "task_verification":
            raise RuntimeError("isolated verifier audit storage failure")
        return original_compute(**kwargs)

    def fail(*args, **kwargs):
        raise RuntimeError("isolated GO-owned stage failure")

    monkeypatch.setattr(service, "_execute_compute_task", compute)
    if stage == "classification":
        monkeypatch.setattr(service.complexity_classifier, "classify", fail)
    elif stage == "planning":
        monkeypatch.setattr(service.task_planner, "plan", fail)
    elif stage == "verification_gate":
        monkeypatch.setattr(service.verification_gate, "verify", fail)

    code = ("GO_AI_ORCHESTRATION_PLANNING_FAILED" if stage in {"classification", "planning"}
            else "GO_AI_ORCHESTRATION_VERIFICATION_FAILED")
    with pytest.raises(ValueError, match=f"^{code}$"):
        service.orchestrate(message="Explain refund choices", account_id="c08_owner")

    with audit_session() as session:
        request = session.scalar(select(GoAIRequestRow))
        assert request.state == "FAILED"
        assert request.failure_code == code
        assert request.response_hash is None
        assert request.selected_provider is None
        invocations = session.scalars(select(GoAIInvocationRow)).all()
        assert len({call for call in calls}) == len(calls)
        if stage in {"classification", "planning"}:
            assert calls == [] and invocations == []
        else:
            assert invocations and all(row.state == "SUCCEEDED" for row in invocations)


def test_expected_verifier_unavailability_keeps_advisory_answer(audit_session):
    # One eligible provider cannot verify its own synthesis. This availability
    # limit remains advisory; it is distinct from an unexpected execution error.
    service = service_module.GOAIService(GOAIProviderRegistry([SynthesisProvider()]))
    result = service.orchestrate(message="Explain refund choices", account_id="c08_owner")
    assert result["orchestration"]["model_verification"] == "NOT_REQUIRED_OR_UNAVAILABLE"
    assert result["decision_boundary"]["advisory_only"] is True
    assert result["decision_boundary"]["execution_allowed"] is False
    with audit_session() as session:
        assert session.get(GoAIRequestRow, result["request_id"]).state == "COMPLETED"
