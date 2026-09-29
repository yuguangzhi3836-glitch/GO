"""Query shapes may be reused; payer and committed payment facts may not be cached."""
import pytest
from go_hotel.db.models import OmnichannelPaymentIntentRow as Intent, OmnichannelPaymentAttemptRow as Attempt
from go_hotel.db.session import SessionLocal
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge as bridge
from test_multi_instance_payment_regressions import prepared


@pytest.mark.parametrize('extra', [1, 3])
def test_multiple_pending_attempts_still_require_reconciliation(extra):
    oid, iid, aid = prepared()
    with SessionLocal.begin() as session:
        original = session.get(Attempt, aid)
        values = {column.name: getattr(original, column.name) for column in original.__table__.columns}
        for number in range(extra):
            session.add(Attempt(**(values | {'payment_attempt_id': f'extra-{number}',
                'attempt_no': number + 2, 'channel_idempotency_key': f'extra-{number}'})))
    with pytest.raises(ValueError, match='PAYMENT_RECONCILIATION_REQUIRED'):
        bridge._confirm_contract_payment(iid, 'owner')
    with SessionLocal() as session:
        assert session.get(Intent, iid).state == 'CONTRACT_READY_NOT_EXTERNAL'


def test_external_attempt_cannot_be_confirmed_by_simulator():
    _, iid, aid = prepared()
    with SessionLocal.begin() as session:
        session.get(Attempt, aid).external_invoked = True
    with pytest.raises(ValueError, match='PAYMENT_RECONCILIATION_REQUIRED'):
        bridge._confirm_contract_payment(iid, 'owner')
    with SessionLocal() as session:
        assert session.get(Intent, iid).state == 'CONTRACT_READY_NOT_EXTERNAL'


def test_reused_read_observes_new_state_and_owner_and_new_bind_values():
    oid, iid, _ = prepared()
    assert bridge._existing_intent('RAIL', oid, 'owner')['state'] == 'CONTRACT_READY_NOT_EXTERNAL'
    assert bridge._existing_intent('RAIL', 'missing-order', 'owner') is None
    with SessionLocal.begin() as session:
        row = session.get(Intent, iid)
        row.state = 'UNKNOWN_EXTERNAL_STATE'
        row.payer_id = 'new-owner'
    with pytest.raises(ValueError, match='PAYMENT_PAYER_ORDER_MISMATCH'):
        bridge._existing_intent('RAIL', oid, 'owner')
    assert bridge._existing_intent('RAIL', oid, 'new-owner')['state'] == 'UNKNOWN_EXTERNAL_STATE'
    with pytest.raises(ValueError, match='PAYMENT_RECONCILIATION_REQUIRED'):
        bridge._confirm_contract_payment(iid, 'new-owner')
