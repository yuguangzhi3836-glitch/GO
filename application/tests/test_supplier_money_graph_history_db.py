"""Database-backed supplier money projection with substantial refund history."""
from datetime import datetime, timezone
from sqlalchemy import insert, select, event
from go_hotel.db.models import MobilityRideOrderRow as Ride
from go_hotel.db.models import OrderSupplierFulfillmentRow as Fulfillment
from go_hotel.db.models import OmnichannelMoneyMovementRow as Movement
from go_hotel.db.session import SessionLocal, engine
from go_hotel.services.order_supplier_fulfillment import _payment_state
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge as bridge
from tests.test_transaction_read_optimization import ride


def test_refund_history_projects_bound_money_and_rejects_corrupt_parent(record_property):
    oid=ride()
    tx=bridge.checkout_contract('RIDE',oid,'query-owner','isolated','isolated://history')
    now=datetime.now(timezone.utc)
    with SessionLocal.begin() as s:
        cap=s.get(Movement,tx['capture_id'])
        s.execute(insert(Movement),[dict(money_movement_id=f'history-refund-{n}',
            root_payment_intent_id=tx['payment_intent_id'],parent_movement_id=cap.money_movement_id,
            movement_type='REFUND' if n%2 else 'COMPENSATION',amount_minor=1,
            business_type=cap.business_type,business_id=cap.business_id,currency=cap.currency,
            state='CONFIRMED',idempotency_key=f'history-refund-key-{n}',
            evidence_json=['isolated://synthetic-money-graph'],created_at=now,updated_at=now)
            for n in range(2000)])
    statements=[]
    def before(conn,cursor,statement,parameters,context,many):statements.append(statement)
    with SessionLocal() as s:
        f=s.get(Fulfillment,tx['supplier_fulfillment_id']);order=s.get(Ride,oid)
        event.listen(engine,'before_cursor_execute',before)
        try:assert _payment_state(s,f,order)=='PARTIALLY_REFUNDED'
        finally:event.remove(engine,'before_cursor_execute',before)
        assert len(statements)==2 and all(q.lstrip().upper().startswith('SELECT') for q in statements)
        assert len(s.scalars(select(Movement).where(Movement.root_payment_intent_id==tx['payment_intent_id'])).all())==2002
    with SessionLocal.begin() as s:
        s.get(Movement,'history-refund-1999').parent_movement_id='missing-parent'
    with SessionLocal() as s:
        assert _payment_state(s,s.get(Fulfillment,tx['supplier_fulfillment_id']),s.get(Ride,oid))=='UNKNOWN_EXTERNAL_STATE'
    record_property('database',engine.dialect.name)
    record_property('movement_history_rows',2002)
    record_property('decision_selects',len(statements))
    record_property('scope','Synthetic stored graph projection; not external refunds or a throughput benchmark')
