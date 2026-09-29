"""Lean projections must retain tamper detection and avoid hidden lazy queries."""
import pytest
from sqlalchemy import event, select

from go_hotel.db.models import (
    JourneyRecoveryEvidenceChainRow as Evidence,
    MobilityRideOrderRow as Ride,
    OmnichannelMoneyMovementRow as Movement,
    OrderSupplierFulfillmentRow as Fulfillment,
    RailOrderRow as Rail,
)
from go_hotel.db.session import SessionLocal, engine
from go_hotel.mobility.ride.cancellation_policy import accepted_in
from go_hotel.services.mobility_refund_consent import verified_records
from go_hotel.services.order_supplier_fulfillment import _payment_state
from test_transaction_read_optimization import ride
from tests.test_depth20_api_fulfillment import captured


def test_consent_projection_keeps_unflushed_session_tamper_visible():
    oid = ride()
    with SessionLocal() as session:
        order = session.get(Ride, oid)
        rows = verified_records(session, order, 'RIDE')
        rows[0].evidence_hash = 'unflushed-tampering'
        with pytest.raises(ValueError, match='REFUND_OPERATION_INTEGRITY_INVALID'):
            accepted_in(session, order)
        session.rollback()
        assert accepted_in(session, order)['order_id'] == oid


def test_consent_validation_needs_one_query_even_with_full_policy_payload():
    oid = ride()
    statements = []
    def observed(conn, cursor, sql, parameters, context, many):
        statements.append(sql)
    with SessionLocal() as session:
        order = session.get(Ride, oid)
        event.listen(engine, 'before_cursor_execute', observed)
        try:
            assert accepted_in(session, order)['order_id'] == oid
        finally:
            event.remove(engine, 'before_cursor_execute', observed)
    assert len(statements) == 1  # No deferred-field N+1 reads during validation.


@pytest.mark.parametrize('corrupt', [False, True])
def test_money_projection_has_two_queries_and_preserves_parent_check(client, corrupt):
    _, order, _, fid, _ = captured(client)
    with SessionLocal.begin() as session:
        fulfillment = session.get(Fulfillment, fid)
        capture = session.scalar(select(Movement).where(
            Movement.root_payment_intent_id == fulfillment.payment_intent_id,
            Movement.movement_type == 'CAPTURE'))
        # This payload is not a projection input; the parent edge still is.
        capture.evidence_json = ['isolated://' + 'x' * 10000]
        if corrupt:
            capture.parent_movement_id = 'missing-authorization'
    statements = []
    def observed(conn, cursor, sql, parameters, context, many):
        statements.append(sql)
    with SessionLocal() as session:
        fulfillment = session.get(Fulfillment, fid)
        native = session.get(Rail, order['order_id'])
        event.listen(engine, 'before_cursor_execute', observed)
        try:
            assert _payment_state(session, fulfillment, native) == (
                'UNKNOWN_EXTERNAL_STATE' if corrupt else 'PAID')
        finally:
            event.remove(engine, 'before_cursor_execute', observed)
    assert len(statements) == 2


def test_projection_imports_do_not_prewarm_mappers():
    import os
    import subprocess
    import sys
    code = """
from go_hotel.db.models import Base
from go_hotel.services import mobility_refund_consent, order_supplier_fulfillment
assert not any(mapper.configured for mapper in Base.registry.mappers)
"""
    subprocess.run([sys.executable, '-c', code], env=dict(os.environ), check=True)
