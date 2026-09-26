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
    original = service._append_event
    barrier = Barrier(2)
    def synchronized_append(s, **kwargs):
        barrier.wait(timeout=10)
        return original(s, **kwargs)
    monkeypatch.setattr(service, "_append_event", synchronized_append)
    def append(index):
        with sessions.begin() as s:
            service._append_event(s, channel="ALIPAY", actor="review", action="REVIEW",
                payload={"index": index}, evidence_reference=f"evidence://review/{index}")
        return "committed"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(append, [1, 2]))
    monkeypatch.setattr(service, "_append_event", original)
    assert outcomes == ["committed", "committed"]
    assert service.evidence_ledger()["chain_valid"], "Two concurrent appends both committed but created a broken chain"

@pytest.mark.parametrize("position", ["root", "middle", "tail"])
@pytest.mark.parametrize("field", ["resource_type", "resource_id"])
def test_linked_identity_damage_is_detected(audit, position, field):
    service, sessions, event_id = audit
    ids = {"root": event_id}
    with sessions.begin() as s:
        for name in ["middle", "tail"]:
            event = service._append_event(s, channel="ALIPAY", actor="review", action="REVIEW",
                payload={"position": name}, evidence_reference=f"evidence://review/{name}")
            ids[name] = event.audit_id
    with sessions.begin() as s:
        setattr(s.get(AuditEventRow, ids[position]), field, "WECHAT_PAY")
    assert not service.evidence_ledger()["chain_valid"]
    assert not service.status()["certification_valid"]

def test_separate_channel_chains_remain_independent(audit):
    service, sessions, event_id = audit
    with sessions.begin() as s:
        service._append_event(s, channel="WECHAT_PAY", actor="review", action="REVIEW",
            payload={"channel": "WECHAT_PAY"}, evidence_reference="evidence://review/wechat")
    assert service.evidence_ledger("ALIPAY")["chain_valid"]
    assert service.evidence_ledger("ALIPAY")["entry_count"] == 1
    assert service.evidence_ledger("WECHAT_PAY")["chain_valid"]
    assert service.evidence_ledger("WECHAT_PAY")["entry_count"] == 1

def test_concurrent_conflicting_reference_cannot_double_commit(audit):
    service, sessions, event_id = audit
    barrier = Barrier(2)
    def append(index):
        barrier.wait(timeout=10)
        try:
            with sessions.begin() as s:
                service._append_event(s, channel="ALIPAY", actor=f"review-{index}", action="REVIEW",
                    payload={"same": True}, evidence_reference="evidence://review/conflict")
            return "committed"
        except ValueError as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(append, [1, 2]))
    assert sorted(outcomes) == ["PAYMENT_SANDBOX_EVIDENCE_REFERENCE_CONFLICT", "committed"]
    assert service.evidence_ledger()["chain_valid"]
    assert service.evidence_ledger()["entry_count"] == 2
