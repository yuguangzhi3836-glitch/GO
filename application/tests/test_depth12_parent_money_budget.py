import pytest
from datetime import datetime,timezone
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OmnichannelPaymentIntentRow as Intent
from go_hotel.services.unified_money_movement import unified_money_movement_service as money


def root():
    t=datetime.now(timezone.utc)
    with SessionLocal.begin() as s:s.add(Intent(payment_intent_id='split-root',business_type='TEST_SPLIT',business_id='budget',payer_id='guest',payee_id='supplier',operation='PAY',amount_minor=10000,currency='CNY',channel_priority_json=['LOCAL_MARKET'],selected_channel='LOCAL_MARKET',state='SUCCEEDED',idempotency_key='split-root',automatic_fallback_allowed=False,user_channel_consent_at=t,created_at=t,updated_at=t))


def move(kind,amount,key,parent=None):return money.create('split-root',{'movement_type':kind,'amount_minor':amount,'parent_movement_id':parent,'mode':'CONTRACT_SIMULATOR','evidence':['test://split-parent']},key,'test')


def test_refund_cannot_borrow_another_capture_budget_within_same_root():
    root();auth=move('AUTHORIZATION',10000,'auth');first=move('CAPTURE',6000,'cap-one',auth['money_movement_id']);move('CAPTURE',4000,'cap-two',auth['money_movement_id'])
    with pytest.raises(ValueError,match='PARENT_CAPTURE_REFUND_BUDGET_EXCEEDED'):move('REFUND',7000,'bad-parent-refund',first['money_movement_id'])
    move('REFUND',6000,'full-parent-refund',first['money_movement_id'])
    with pytest.raises(ValueError,match='PARENT_CAPTURE_REFUND_BUDGET_EXCEEDED'):move('COMPENSATION',1,'bad-parent-compensation',first['money_movement_id'])


def test_capture_cannot_borrow_another_authorization_budget_within_same_root():
    root();first=move('AUTHORIZATION',6000,'auth-one');move('AUTHORIZATION',4000,'auth-two')
    with pytest.raises(ValueError,match='PARENT_AUTHORIZATION_BUDGET_EXCEEDED'):move('CAPTURE',7000,'bad-parent-capture',first['money_movement_id'])
