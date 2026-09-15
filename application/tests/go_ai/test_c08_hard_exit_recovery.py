"""Real process death evidence and fail-closed, read-only recovery assessment."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from go_hotel.db.models import GoAIRequestRow
from go_hotel.go_ai import service as service_module
from go_hotel.go_ai.registry import GOAIProviderRegistry

pytestmark = pytest.mark.no_db


@pytest.mark.parametrize("checkpoint,expected_state,invocations,calls", [
    ("before_invocation_commit", "ROUTING", 0, 1),
    ("after_invocation_commit", "ROUTING", 1, 1),
    ("after_completion_commit", "COMPLETED", 2, 2),
])
def test_hard_exit_recovery_never_replays_or_invents_terminal_state(tmp_path, monkeypatch, checkpoint, expected_state, invocations, calls):
    database, calls_path = tmp_path / "audit.sqlite", tmp_path / "compute-calls.txt"
    worker = Path(__file__).with_name("c08_hard_exit_worker.py")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"), "DATABASE_URL": f"sqlite+pysqlite:///{database}", "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, str(worker), str(database), str(calls_path), checkpoint], env=env, capture_output=True, text=True, timeout=45)
    print(f"C08_HARD_EXIT checkpoint={checkpoint} actual_exit={result.returncode} persisted_compute_calls={calls_path.read_text() if calls_path.exists() else 'NONE'}")
    assert result.returncode == 73, result.stderr
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(service_module, "SessionLocal", factory)
    service = service_module.GOAIService(GOAIProviderRegistry([]))
    try:
        with factory() as session:
            request_id = session.scalar(select(GoAIRequestRow.go_ai_request_id))
        before = service.request_audit(request_id)
        assert before["state"] == expected_state
        assert len(before["invocations"]) == invocations
        call_bytes = calls_path.read_bytes()
        assert len(call_bytes.splitlines()) == calls
        assessment = service.assess_recovery(request_id)
        assert assessment["model_replay_allowed"] is False
        assert assessment["database_mutation_performed"] is False
        assert assessment["state"] == expected_state
        if expected_state == "ROUTING":
            assert assessment["gate"] == "HOLD"
            assert assessment["safe_to_finalize"] is False
            assert "EXECUTION_OWNERSHIP_AND_TERMINATION_NOT_PROVEN" in assessment["missing_recovery_facts"]
            assert "COMPLETE_REPLAYABLE_RESULT_NOT_PERSISTED" in assessment["missing_recovery_facts"]
        else:
            assert assessment["gate"] == "NO_RECOVERY_REQUIRED"
        assert service.assess_recovery(request_id) == assessment
        assert service.request_audit(request_id) == before
        assert calls_path.read_bytes() == call_bytes
    finally:
        engine.dispose()
