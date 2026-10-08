"""C08 request audit finalization with deterministic, non-network providers."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from go_hotel.db.models import Base, GoAIInvocationRow, GoAIRequestRow
from go_hotel.go_ai.complexity import ComplexityAssessment
from go_hotel.go_ai.planner import GOAITaskPlanner
from go_hotel.go_ai import service as service_module
from go_hotel.go_ai.models import ProviderConfig
from go_hotel.go_ai.providers import DeterministicTestProvider, GOAIProviderError
from go_hotel.go_ai.registry import GOAIProviderRegistry


pytestmark = pytest.mark.no_db


class SynthesisProvider(DeterministicTestProvider):
    def __init__(self, error=None):
        super().__init__(ProviderConfig(
            provider_id="c08_isolated_test", adapter="openai_compatible",
            model="c08-test-only", base_url="https://unused.test/v1",
            api_key_env="C08_UNUSED_TEST_KEY", cost_tier=1,
        ), text="GO AI advisory response")
        self.error = error

    def generate(self, request):
        if request.task_type == "SYNTHESIS" and self.error:
            raise self.error
        return super().generate(request)


@pytest.fixture
def planner():
    return GOAITaskPlanner()


@pytest.fixture
def tier_5_assessment():
    return ComplexityAssessment(
        tier="TIER_5_HIGH_ASSURANCE",
        score=9,
        reasons=("TRANSACTION_OR_MONEY_SENSITIVE",),
        max_parallel_tasks=4,
        requires_model_verification=True,
        requires_deterministic_gate=True,
    )


@pytest.fixture
def audit_session(monkeypatch, tmp_path):
    # File-backed SQLite lets the service's genuine worker thread persist its
    # own invocation audit; this never connects to a configured business DB.
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'c08-audit.sqlite'}")
    Base.metadata.create_all(
        engine, tables=[GoAIRequestRow.__table__, GoAIInvocationRow.__table__],
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(service_module, "SessionLocal", factory)
    yield factory
    engine.dispose()


def test_tier_5_planning_keeps_required_stages_under_parallel_budget(
    planner, tier_5_assessment,
):
    plan = planner.plan(
        "请比较 flight hotel rail budget 方案，并评估 payment refund 风险与约束",
        tier_5_assessment,
    )

    assert [task.task_id for task in plan] == [
        "task_flight",
        "task_hotel",
        "task_rail",
        "task_budget",
        "task_constraints",
        "task_reasoning",
        "task_risk",
    ]


def test_lower_tier_planning_stays_single_general_task(planner):
    assessment = ComplexityAssessment(
        tier="TIER_2_STANDARD",
        score=2,
        reasons=("NONTRIVIAL_INPUT",),
        max_parallel_tasks=2,
        requires_model_verification=False,
        requires_deterministic_gate=False,
    )

    plan = planner.plan("Hello", assessment)

    assert [task.task_id for task in plan] == ["task_main"]
    assert [task.task_type for task in plan] == ["GENERAL"]


@pytest.mark.parametrize(
    ("error", "expected_exception", "expected_invocations"),
    [
        (
            GOAIProviderError("GO_AI_PROVIDER_TIMEOUT"),
            "GO_AI_PROVIDER_TIMEOUT",
            ["SUCCEEDED", "FAILED"],
        ),
        (
            RuntimeError("synthetic unexpected provider failure"),
            "GO_AI_ORCHESTRATION_TASK_FAILED",
            ["SUCCEEDED"],
        ),
    ],
)
def test_synthesis_failure_finalizes_request_after_successful_subtask(
    audit_session, error, expected_exception, expected_invocations,
):
    service = service_module.GOAIService(GOAIProviderRegistry([SynthesisProvider(error)]))
    with pytest.raises(ValueError, match=f"^{expected_exception}$"):
        service.orchestrate(message="Hello", account_id="c08_owner")

    with audit_session() as session:
        request = session.scalar(select(GoAIRequestRow))
        invocations = session.scalars(
            select(GoAIInvocationRow).order_by(GoAIInvocationRow.attempt_no)
        ).all()
        assert request.state == "FAILED"
        assert request.failure_code == "GO_AI_ORCHESTRATION_TASK_FAILED"
        assert request.selected_provider is None
        assert request.response_hash is None
        assert [row.state for row in invocations] == expected_invocations
        assert all(row.go_ai_request_id == request.go_ai_request_id for row in invocations)


def test_successful_synthesis_keeps_completed_hash_only_audit(audit_session):
    service = service_module.GOAIService(GOAIProviderRegistry([SynthesisProvider()]))
    result = service.orchestrate(message="Hello", account_id="c08_owner")
    assert result["answer"] == "GO AI advisory response"
    assert result["decision_boundary"]["advisory_only"] is True
    assert "provider" not in result and "model" not in result
    with audit_session() as session:
        request = session.get(GoAIRequestRow, result["request_id"])
        invocations = session.scalars(
            select(GoAIInvocationRow).order_by(GoAIInvocationRow.attempt_no)
        ).all()
        assert request.state == "COMPLETED"
        assert request.failure_code is None
        assert request.selected_provider == "c08_isolated_test"
        assert request.request_hash and request.response_hash
        assert not hasattr(request, "message") and not hasattr(request, "answer")
        assert [row.state for row in invocations] == ["SUCCEEDED", "SUCCEEDED"]
