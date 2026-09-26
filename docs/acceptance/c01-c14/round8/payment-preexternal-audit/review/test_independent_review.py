from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import select
from go_hotel.db.models import AuditEventRow
from go_hotel.services import payment_sandbox_cutover as module
from go_hotel.services import payment_sandbox_runtime as runtime
from test_payment_sandbox_audit_integrity import audit

@pytest.mark.parametrize("field", ["resource_type", "resource_id"])
def test_changed_identity_cannot_hide_corruption_and_allow_new_grant(audit, field):
    service, sessions, event_id = audit
    with sessions.begin() as s:
        setattr(s.get(AuditEventRow, event_id), field, "TAMPERED")
    with pytest.raises(ValueError, match="EVIDENCE_CHAIN_INVALID"):
        with sessions.begin() as s:
            service.record_certification_grant(s, channel="ALIPAY", actor="review",
                evidence_reference="evidence://review/new", external_evidence_reference="isolated://review",
                scenario_results={"INTERNAL": "PASS"})

def test_preflight_cannot_report_certification_for_corrupted_chain(audit, monkeypatch):
    service, sessions, event_id = audit
    monkeypatch.setattr(runtime, "SessionLocal", sessions)
    with sessions.begin() as s:
        s.get(AuditEventRow, event_id).actor_id = "TAMPERED"
    assert not service.status()["certification_valid"]
    assert runtime.payment_sandbox_runtime_service.certification_preflight()["payment_sandbox_certified"] is False

def test_concurrent_append_cannot_commit_a_fork(audit, monkeypatch):
    service, sessions, event_id = audit
    original = service._events
    barrier = Barrier(2)
    def synchronized_read(s, channel):
        events = original(s, channel)
        barrier.wait(timeout=10)
        return events
    monkeypatch.setattr(service, "_events", synchronized_read)
    def append(index):
        with sessions.begin() as s:
            service._append_event(s, channel="ALIPAY", actor="review", action="REVIEW",
                payload={"index": index}, evidence_reference=f"evidence://review/{index}")
        return "committed"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(append, [1, 2]))
    monkeypatch.setattr(service, "_events", original)
    assert outcomes == ["committed", "committed"]
    assert service.evidence_ledger()["chain_valid"], "Two concurrent appends both committed but created a broken chain"
