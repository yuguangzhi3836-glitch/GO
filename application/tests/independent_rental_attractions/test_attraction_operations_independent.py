"""Independent current-development counterexamples; no application edits."""
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OmnichannelLedgerEntryRow
from tests.test_attraction_operations_runtime import workspace,prepare,command
from tests.test_rental_attraction_preinventory import money

@pytest.mark.parametrize('field,value',[('account_code','WRONG'),('evidence_hash','0'*64)])
def test_capture_ledger_corruption_cannot_verify(workspace,field,value):
    w=workspace;prepare(w);command(w,'APPLY')
    with SessionLocal.begin() as s:
        entry=s.scalar(select(OmnichannelLedgerEntryRow).where(OmnichannelLedgerEntryRow.entry_type=='CAPTURE'))
        assert entry is not None
        setattr(entry,field,value)
    before=money();command(w,'VERIFY','verifier',status=409);assert money()==before


def test_followup_cannot_close_new_pending_change(workspace):
    w=workspace;prepare(w);command(w,'APPLY');command(w,'VERIFY','verifier')
    q=w['svc'].change_quote(w['owner'],w['oid'],'2026-09-17','16:00')
    w['svc'].execute_change(w['owner'],w['oid'],q['quote_id'])
    assert w['svc'].get(w['owner'],w['oid'])['status']=='UNKNOWN_EXTERNAL_STATE'
    before=money();command(w,'FOLLOW_UP',status=409);assert money()==before


def test_closed_supplier_after_verify_cannot_close_without_refund(workspace):
    w=workspace;prepare(w);command(w,'APPLY');command(w,'VERIFY','verifier')
    w['svc'].admin_external_state(w['oid'],'CLOSED_BY_SUPPLIER','isolated://later-close','independent-admin')
    before=money();command(w,'FOLLOW_UP',status=409);assert money()==before


def test_replayed_followup_cannot_report_closed_with_corrupt_refund(workspace):
    w=workspace;prepare(w,'CLOSED_BY_SUPPLIER');command(w,'APPLY')
    q=w['svc'].refund_quote(w['owner'],w['oid']);w['svc'].refund(w['owner'],w['oid'],q['quote_hash'])
    command(w,'VERIFY','verifier');body,_=command(w,'FOLLOW_UP')
    with SessionLocal.begin() as s:
        entry=s.scalar(select(OmnichannelLedgerEntryRow).where(OmnichannelLedgerEntryRow.entry_type=='REFUND'))
        entry.account_code='WRONG'
    before=money();command(w,'FOLLOW_UP',body=body,status=409);assert money()==before
