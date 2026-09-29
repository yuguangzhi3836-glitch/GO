"""Keep payment success guards and receipts while combining related reads."""
from datetime import datetime, timezone
import pytest
from sqlalchemy import delete, event, select

from go_hotel.db.models import (
    OmnichannelPaymentIntentRow as Intent,
    OmnichannelPaymentAttemptRow as Attempt,
    PaymentOrderFactBindingRow as Binding,
    OrderSupplierFulfillmentRow as Fulfillment,
    OrderSupplierFulfillmentEventRow as FulfillmentEvent,
)
from go_hotel.db.session import SessionLocal, engine
from go_hotel.services.omnichannel_payment import omnichannel_payment_service as payments
from test_multi_instance_payment_regressions import prepared


def copy_values(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


@pytest.mark.parametrize('conflict', ['attempt', 'intent', 'both'])
def test_combined_success_checks_still_reject_each_conflict_and_roll_back(conflict):
    _, iid, aid = prepared()
    with SessionLocal.begin() as s:
        if conflict in {'attempt', 'both'}:
            values = copy_values(s.get(Attempt, aid))
            values.update(payment_attempt_id='other-successful-attempt', attempt_no=2,
                          channel_idempotency_key='other-successful-attempt', state='SUCCEEDED')
            s.add(Attempt(**values))
        if conflict in {'intent', 'both'}:
            values = copy_values(s.get(Intent, iid))
            values.update(payment_intent_id='other-successful-intent',
                          idempotency_key='other-successful-intent', state='SUCCEEDED')
            s.add(Intent(**values))
    expected = ('ORDER_ALREADY_HAS_SUCCESSFUL_PAYMENT' if conflict == 'intent'
                else 'DUPLICATE_ROOT_PAYMENT_SUCCESS_BLOCKED')
    with pytest.raises(ValueError, match=expected):
        payments.simulate_result(aid, 'SUCCEEDED')
    with SessionLocal() as s:
        assert s.get(Intent, iid).state == 'CONTRACT_READY_NOT_EXTERNAL'
        assert s.get(Attempt, aid).state == 'CONTRACT_READY_NOT_EXTERNAL'
        assert not list(s.scalars(select(Fulfillment).where(Fulfillment.payment_intent_id == iid)))


@pytest.mark.parametrize('case', ['bound', 'missing_binding', 'existing_fulfillment'])
def test_success_reads_preserve_evidence_and_single_fulfillment(case):
    _, iid, aid = prepared()
    with SessionLocal.begin() as s:
        binding = s.scalar(select(Binding).where(Binding.payment_intent_id == iid))
        expected_reference = binding.evidence_reference
        if case == 'missing_binding':
            s.execute(delete(Binding).where(Binding.payment_intent_id == iid))
            expected_reference = 'payment://confirmed'
        elif case == 'existing_fulfillment':
            intent = s.get(Intent, iid)
            expected_reference = 'isolated://existing-receipt'
            s.add(Fulfillment(order_supplier_fulfillment_id='existing-fulfillment',
                payment_intent_id=iid, business_type=intent.business_type, business_id=intent.business_id,
                supplier_id=intent.payee_id, supplier_idempotency_key='existing-supplier-key',
                state='PAYMENT_CONFIRMED_AWAITING_MONEY_GRAPH', evidence_reference=expected_reference,
                created_at=intent.created_at, updated_at=intent.updated_at))

    reads = []
    def observed(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            reads.append(statement)
    event.listen(engine, 'before_cursor_execute', observed)
    try:
        result = payments.simulate_result(aid, 'SUCCEEDED')
    finally:
        event.remove(engine, 'before_cursor_execute', observed)
    assert result['intent']['state'] == result['attempt']['state'] == 'SUCCEEDED'
    # Two locked row reads, one conflict probe, one binding/fulfillment read.
    assert len(reads) == 4
    replay = payments.simulate_result(aid, 'SUCCEEDED')
    # SQLite reloads DateTime without its UTC offset; compare the instants too.
    for section in ('intent', 'attempt'):
        for key, value in result[section].items():
            repeated = replay[section][key]
            if value is not None and key.endswith('_at'):
                value = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
                repeated = datetime.fromisoformat(repeated).replace(tzinfo=timezone.utc)
            assert repeated == value, (section, key)
    with SessionLocal() as s:
        rows = list(s.scalars(select(Fulfillment).where(Fulfillment.payment_intent_id == iid)))
        assert len(rows) == 1 and rows[0].evidence_reference == expected_reference
        events = list(s.scalars(select(FulfillmentEvent).where(
            FulfillmentEvent.order_supplier_fulfillment_id == rows[0].order_supplier_fulfillment_id)))
        assert len(events) == (0 if case == 'existing_fulfillment' else 1)
        if case == 'existing_fulfillment':
            assert rows[0].order_supplier_fulfillment_id == 'existing-fulfillment'
        else:
            assert events[0].evidence_reference == expected_reference
