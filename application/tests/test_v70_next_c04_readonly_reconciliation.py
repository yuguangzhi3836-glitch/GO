"""C04-02: diagnose historical state/ledger contradictions without writing or money calls."""
import pytest
from sqlalchemy import select, event, delete
from go_hotel.db.session import SessionLocal, engine
from go_hotel.db.models import (MobilityRentalOrderRow as Order, MobilityRefundRow as Refund,
    JourneyRecoveryEvidenceChainRow as Evidence)
from go_hotel.mobility.rental.reconciliation import inspect_refund
from go_hotel.services.vertical_money_bridge import vertical_money_bridge as money
from tests.test_depth33_mobility_refund_consent import booked


@pytest.mark.parametrize('scenario,expected', [
    ('matched', 'MATCHED_COMPLETED'), ('contradiction', 'CONTRADICTION'),
    ('after_money_crash', 'MONEY_CONFIRMED_ORDER_PENDING'),
    ('unexecuted', 'PENDING_MONEY'), ('missing_evidence', 'UNPROVEN_HISTORICAL'),
    ('plan_corruption', 'UNPROVEN_HISTORICAL')])
def test_readonly_diagnosis_never_repairs_order_or_executes_money(monkeypatch, scenario, expected):
    svc, owner, oid = booked('RENTAL')
    quote = svc.refund_quote(owner, oid)
    real_execute = money.execute_refund_plan
    if scenario in {'after_money_crash', 'unexecuted'}:
        def fail(*args, **kwargs):
            if scenario == 'after_money_crash':
                real_execute(*args, **kwargs)
            raise RuntimeError('ISOLATED_INTERRUPTION')
        monkeypatch.setattr(money, 'execute_refund_plan', fail)
        with pytest.raises(RuntimeError):
            svc.cancel(owner, oid, quote['quote_hash'])
    else:
        svc.cancel(owner, oid, quote['quote_hash'])
    with SessionLocal.begin() as session:
        refund = session.scalar(select(Refund).where(Refund.order_id == oid))
        rid = refund.refund_id
        if scenario == 'contradiction':
            session.get(Order, oid).status = 'CONFIRMED'
        elif scenario == 'missing_evidence':
            session.execute(delete(Evidence).where(Evidence.execution_id == 'rc20:RENTAL:' + oid))
        elif scenario == 'plan_corruption':
            refund.settlement_plan_json = []
    before = svc.get(owner, oid)
    def never_execute(*args, **kwargs):
        pytest.fail('Read-only diagnosis attempted a money operation')
    monkeypatch.setattr(money, 'execute_refund_plan', never_execute)
    def read_only(connection, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().split()[0].upper() in {'SELECT', 'PRAGMA'}, statement
    event.listen(engine, 'before_cursor_execute', read_only)
    try:
        result = inspect_refund(owner, oid, rid)
        assert inspect_refund(owner, oid, rid) == result
    finally:
        event.remove(engine, 'before_cursor_execute', read_only)
    assert result['status'] == expected
    assert result['read_only'] and result['automatic_repair'] is False
    assert svc.get(owner, oid) == before
    if scenario == 'contradiction':
        assert result['money_confirmed']
        assert 'COMPLETED_REFUND_ORDER_STATE_MISMATCH' in result['findings']
    if scenario in {'missing_evidence', 'plan_corruption'}:
        assert not result['plan_proven'] and not result['money_confirmed']


def test_foreign_account_cannot_read_refund_diagnosis():
    svc, owner, oid = booked('RENTAL')
    quote = svc.refund_quote(owner, oid)
    refund = svc.cancel(owner, oid, quote['quote_hash'])
    with pytest.raises(ValueError, match='NOT_FOUND'):
        inspect_refund('another-owner', oid, refund['refund_id'])
