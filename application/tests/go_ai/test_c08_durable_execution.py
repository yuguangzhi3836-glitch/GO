"""C08 GO AI-specific durable ownership, fencing, checkpoint and recovery boundaries."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from go_hotel.db.models import Base, GoAIExecutionRow, GoAIInvocationRow, GoAIRequestRow
from go_hotel.go_ai import service as service_module
from go_hotel.go_ai.registry import GOAIProviderRegistry

pytestmark = pytest.mark.no_db


@pytest.fixture
def durable_service(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'c08-durable.sqlite'}")
    Base.metadata.create_all(
        engine,
        tables=[GoAIRequestRow.__table__, GoAIExecutionRow.__table__, GoAIInvocationRow.__table__],
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(service_module, "SessionLocal", factory)
    now = datetime(2026, 9, 16, 3, 0, tzinfo=timezone.utc)
    with factory.begin() as session:
        session.add(GoAIRequestRow(
            go_ai_request_id="goai_c08_durable",
            account_id="c08_owner",
            task="ORCHESTRATION",
            region="GLOBAL",
            locale="und",
            state="ROUTING",
            request_hash="a" * 64,
            selected_provider=None,
            selected_model=None,
            response_hash=None,
            failure_code=None,
            created_at=now,
            updated_at=now,
        ))
    clock = {"now": now}
    monkeypatch.setattr(service_module.GOAIService, "_database_now", classmethod(lambda cls, session: clock["now"]))
    yield service_module.GOAIService(GOAIProviderRegistry([])), factory, clock
    engine.dispose()


def test_live_go_ai_lease_rejects_competing_owner(durable_service):
    service, _, clock = durable_service
    now = clock["now"]
    first = service.claim_execution(
        "goai_c08_durable", worker_id="go-ai-worker-a", lease_seconds=60,
    )
    assert first["fencing_token"] == 1
    assert first["automatic_replay_started"] is False
    clock["now"] = now + timedelta(seconds=30)
    with pytest.raises(ValueError, match="GO_AI_EXECUTION_LEASE_HELD"):
        service.claim_execution(
            "goai_c08_durable", worker_id="go-ai-worker-b", lease_seconds=60,
        )


def test_expiry_alone_never_authorizes_takeover(durable_service):
    service, _, clock = durable_service
    now = clock["now"]
    service.claim_execution(
        "goai_c08_durable", worker_id="go-ai-worker-a", lease_seconds=10,
    )
    clock["now"] = now + timedelta(seconds=11)
    with pytest.raises(ValueError, match="GO_AI_PREVIOUS_OWNER_TERMINATION_NOT_PROVEN"):
        service.claim_execution(
            "goai_c08_durable", worker_id="go-ai-worker-b", lease_seconds=60,
        )


def test_complete_checkpoint_and_verified_termination_issue_new_fence(durable_service):
    service, _, clock = durable_service
    now = clock["now"]
    lease = service.claim_execution(
        "goai_c08_durable", worker_id="go-ai-worker-a", lease_seconds=10,
    )
    checkpoint = {
        "plan_hash": "b" * 64,
        "completed_task_ids": [],
        "pending_task_ids": ["task_1"],
        "replayable_result_refs": [],
    }
    clock["now"] = now + timedelta(seconds=1)
    saved = service.save_execution_checkpoint(
        "goai_c08_durable",
        worker_id="go-ai-worker-a",
        fencing_token=lease["fencing_token"],
        checkpoint=checkpoint,
        complete=True,
        provider_outcome="NOT_STARTED",
    )
    assert saved["checkpoint_complete"] is True
    clock["now"] = now + timedelta(seconds=11)
    takeover = service.claim_execution(
        "goai_c08_durable",
        worker_id="go-ai-worker-b",
        lease_seconds=60,
        verified_previous_owner_terminated=True,
    )
    assert takeover["fencing_token"] == 2
    assert takeover["automatic_replay_started"] is False
    with pytest.raises(ValueError, match="GO_AI_EXECUTION_FENCE_MISMATCH"):
        service.save_execution_checkpoint(
            "goai_c08_durable",
            worker_id="go-ai-worker-a",
            fencing_token=1,
            checkpoint=checkpoint,
            complete=True,
        )


def test_same_worker_renewal_requires_exact_fence(durable_service):
    service, factory, clock = durable_service
    lease = service.claim_execution("goai_c08_durable", worker_id="go-ai-worker-a", lease_seconds=60)
    with pytest.raises(ValueError, match="GO_AI_EXECUTION_FENCE_MISMATCH"):
        service.claim_execution("goai_c08_durable", worker_id="go-ai-worker-a", lease_seconds=60)
    with pytest.raises(ValueError, match="GO_AI_EXECUTION_FENCE_MISMATCH"):
        service.claim_execution("goai_c08_durable", worker_id="go-ai-worker-a", lease_seconds=60, fencing_token=999)
    renewed = service.claim_execution(
        "goai_c08_durable", worker_id="go-ai-worker-a", lease_seconds=60,
        fencing_token=lease["fencing_token"],
    )
    assert renewed["fencing_token"] == lease["fencing_token"]
    with factory() as session:
        assert session.get(GoAIExecutionRow, "goai_c08_durable").owner_id == "go-ai-worker-a"


def test_public_api_has_no_caller_clock_override():
    import inspect
    assert "observed_at" not in inspect.signature(service_module.GOAIService.claim_execution).parameters
    assert "observed_at" not in inspect.signature(service_module.GOAIService.save_execution_checkpoint).parameters


def test_unknown_provider_outcome_blocks_takeover_and_assessment_stays_read_only(durable_service):
    service, factory, clock = durable_service
    now = clock["now"]
    lease = service.claim_execution(
        "goai_c08_durable", worker_id="go-ai-worker-a", lease_seconds=10,
    )
    checkpoint = {
        "plan_hash": "c" * 64,
        "completed_task_ids": ["task_1"],
        "pending_task_ids": [],
        "replayable_result_refs": [],
    }
    clock["now"] = now + timedelta(seconds=1)
    service.save_execution_checkpoint(
        "goai_c08_durable",
        worker_id="go-ai-worker-a",
        fencing_token=lease["fencing_token"],
        checkpoint=checkpoint,
        complete=True,
        provider_outcome="UNKNOWN",
    )
    clock["now"] = now + timedelta(seconds=11)
    with pytest.raises(ValueError, match="GO_AI_PROVIDER_OUTCOME_UNRESOLVED"):
        service.claim_execution(
            "goai_c08_durable",
            worker_id="go-ai-worker-b",
            lease_seconds=60,
            verified_previous_owner_terminated=True,
        )
    before = service.request_audit("goai_c08_durable")
    assessment = service.assess_recovery("goai_c08_durable")
    assert assessment["gate"] == "HOLD"
    assert assessment["checkpoint_complete"] is True
    assert assessment["provider_outcome"] == "UNKNOWN"
    assert assessment["model_replay_allowed"] is False
    assert assessment["database_mutation_performed"] is False
    assert "PROVIDER_EXECUTION_OUTCOME_MAY_BE_UNCOMMITTED" in assessment["missing_recovery_facts"]
    assert service.request_audit("goai_c08_durable") == before
    with factory() as session:
        row = session.get(GoAIExecutionRow, "goai_c08_durable")
        assert row.owner_id == "go-ai-worker-a"
        assert row.fencing_token == 1


@pytest.mark.parametrize(
    ("checkpoint", "provider_outcome", "error"),
    [
        ({"plan_hash": "short", "completed_task_ids": [], "pending_task_ids": [], "replayable_result_refs": []},
         "NOT_STARTED", "GO_AI_CHECKPOINT_PLAN_HASH_INVALID"),
        ({"plan_hash": "d" * 64, "completed_task_ids": ["task_1", "task_1"], "pending_task_ids": [], "replayable_result_refs": []},
         "NOT_STARTED", "GO_AI_CHECKPOINT_TASK_SET_INVALID"),
        ({"plan_hash": "d" * 64, "completed_task_ids": ["task_1"], "pending_task_ids": ["task_1"], "replayable_result_refs": []},
         "NOT_STARTED", "GO_AI_CHECKPOINT_TASK_SET_OVERLAP"),
        ({"plan_hash": "d" * 64, "completed_task_ids": ["task_1"], "pending_task_ids": [], "replayable_result_refs": []},
         "SUCCEEDED", "GO_AI_SUCCEEDED_RESULT_REFERENCE_REQUIRED"),
    ],
)
def test_complete_checkpoint_rejects_unrecoverable_plan_shapes(
    durable_service, checkpoint, provider_outcome, error
):
    service, factory, _ = durable_service
    lease = service.claim_execution(
        "goai_c08_durable", worker_id="go-ai-worker-a", lease_seconds=60,
    )
    with pytest.raises(ValueError, match=error):
        service.save_execution_checkpoint(
            "goai_c08_durable",
            worker_id="go-ai-worker-a",
            fencing_token=lease["fencing_token"],
            checkpoint=checkpoint,
            complete=True,
            provider_outcome=provider_outcome,
        )
    with factory() as session:
        row = session.get(GoAIExecutionRow, "goai_c08_durable")
        assert row.checkpoint_complete is False
        assert row.checkpoint_hash is None


def test_succeeded_complete_checkpoint_requires_and_retains_result_reference(durable_service):
    service, _, _ = durable_service
    lease = service.claim_execution(
        "goai_c08_durable", worker_id="go-ai-worker-a", lease_seconds=60,
    )
    saved = service.save_execution_checkpoint(
        "goai_c08_durable",
        worker_id="go-ai-worker-a",
        fencing_token=lease["fencing_token"],
        checkpoint={
            "plan_hash": "e" * 64,
            "completed_task_ids": ["task_1"],
            "pending_task_ids": [],
            "replayable_result_refs": ["result:task_1:sha256:" + "f" * 64],
        },
        complete=True,
        provider_outcome="SUCCEEDED",
    )
    assert saved["checkpoint_complete"] is True
    assert saved["provider_outcome"] == "SUCCEEDED"
    assert saved["automatic_replay_started"] is False
