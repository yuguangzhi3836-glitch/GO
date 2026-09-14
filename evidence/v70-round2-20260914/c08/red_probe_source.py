"""C08 transient audit-commit failure; deterministic provider and real SQLite."""
import pytest
from sqlalchemy import event, select

from go_hotel.db.models import GoAIRequestRow
from go_hotel.go_ai import service as service_module
from go_hotel.go_ai.registry import GOAIProviderRegistry
from test_c08_synthesis_audit_finalization import SynthesisProvider, audit_session

pytestmark = pytest.mark.no_db


def test_success_audit_commit_failure_finalizes_failed_without_repeating_compute(audit_session):
    class CountingProvider(SynthesisProvider):
        calls = 0

        def generate(self, request):
            self.calls += 1
            return super().generate(request)

    provider = CountingProvider()
    service = service_module.GOAIService(GOAIProviderRegistry([provider]))
    injected = []

    def fail_success_commit_once(session):
        if not injected and any(isinstance(row, GoAIRequestRow) and row.state == "COMPLETED" for row in session.dirty):
            injected.append("success_commit_failed")
            raise RuntimeError("ISOLATED_AUDIT_COMMIT_FAILURE")

    event.listen(audit_session, "before_commit", fail_success_commit_once)
    try:
        with pytest.raises(RuntimeError, match="ISOLATED_AUDIT_COMMIT_FAILURE"):
            service.orchestrate(message="Hello", account_id="c08_owner")
    finally:
        event.remove(audit_session, "before_commit", fail_success_commit_once)

    assert injected == ["success_commit_failed"]
    assert provider.calls == 2  # One subtask plus synthesis; neither repeated.
    with audit_session() as session:
        request = session.scalar(select(GoAIRequestRow))
        assert request.state == "FAILED"
        assert request.failure_code == "GO_AI_AUDIT_FINALIZATION_FAILED"
        assert request.response_hash is None
        assert request.selected_provider is None


def test_persistent_audit_outage_never_returns_false_success(audit_session):
    service = service_module.GOAIService(GOAIProviderRegistry([SynthesisProvider()]))
    attempts = []

    def fail_every_finalization(session):
        if any(isinstance(row, GoAIRequestRow) for row in session.dirty):
            attempts.append("commit_failed")
            raise RuntimeError("ISOLATED_PERSISTENT_AUDIT_OUTAGE")

    event.listen(audit_session, "before_commit", fail_every_finalization)
    try:
        with pytest.raises(RuntimeError, match="ISOLATED_PERSISTENT_AUDIT_OUTAGE"):
            service.orchestrate(message="Hello", account_id="c08_owner")
    finally:
        event.remove(audit_session, "before_commit", fail_every_finalization)
    assert len(attempts) <= 2  # Bounded fail-closed handling, no unbounded retry.
    with audit_session() as session:
        request = session.scalar(select(GoAIRequestRow))
        assert request.state == "ROUTING"  # Explicit unresolved recovery scope.
        assert request.response_hash is None
