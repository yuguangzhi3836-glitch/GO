from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import pytest
from sqlalchemy import select
from go_hotel.db.models import OmnichannelPaymentIntentRow as Intent,OmnichannelMoneyMovementRow as Movement
from go_hotel.db.session import SessionLocal
from go_hotel.services.unified_money_movement import unified_money_movement_service as money


def intent(identity='payment-one'):
    now=datetime.now(timezone.utc)
    with SessionLocal.begin() as s:
        s.add(Intent(payment_intent_id=identity,business_type='FLIGHT_ORDER',business_id='order-'+identity,
            payer_id='isolated-payer',payee_id='isolated-supplier',operation='PAY',amount_minor=1000,currency='CNY',
            channel_priority_json=['LOCAL_MARKET'],selected_channel='LOCAL_MARKET',state='SUCCEEDED',
            idempotency_key='intent-'+identity,automatic_fallback_allowed=False,created_at=now,updated_at=now))
    return identity


def move(identity,kind,key,amount=1000,parent=None):
    return money.create(identity,{'movement_type':kind,'amount_minor':amount,'parent_movement_id':parent,
        'mode':'CONTRACT_SIMULATOR','evidence':['isolated-money-test://'+kind]},key,'isolated-test')


def test_released_authorization_cannot_be_captured_later():
    identity=intent();auth=move(identity,'AUTHORIZATION','auth')
    move(identity,'RELEASE','release',parent=auth['money_movement_id'])
    with pytest.raises(ValueError,match='UNRELEASED_AUTHORIZATION'):move(identity,'CAPTURE','late-capture',parent=auth['money_movement_id'])


def test_captured_authorization_cannot_be_released_as_unused():
    identity=intent();auth=move(identity,'AUTHORIZATION','auth')
    move(identity,'CAPTURE','capture',parent=auth['money_movement_id'])
    with pytest.raises(ValueError,match='REMAINING_AUTHORIZATION'):move(identity,'RELEASE','release',parent=auth['money_movement_id'])


@pytest.mark.parametrize('change',['root','amount','type','parent'])
def test_idempotency_key_cannot_be_reused_for_a_different_money_instruction(change):
    identity=intent();auth=move(identity,'AUTHORIZATION','auth');cap=move(identity,'CAPTURE','capture',parent=auth['money_movement_id'])
    move(identity,'REFUND','original-refund',400,cap['money_movement_id'])
    root=intent('payment-two') if change=='root' else identity
    kind='COMPENSATION' if change=='type' else 'REFUND'
    amount=401 if change=='amount' else 400
    parent=None if change=='parent' else cap['money_movement_id']
    with pytest.raises(ValueError,match='IDEMPOTENCY_CONFLICT'):move(root,kind,'original-refund',amount,parent)


@pytest.mark.parametrize('same_key',[False,True])
def test_simultaneous_refunds_preserve_budget_and_retry_identity(same_key):
    identity=intent();auth=move(identity,'AUTHORIZATION','auth');cap=move(identity,'CAPTURE','capture',parent=auth['money_movement_id'])
    def refund(key):
        try:return move(identity,'REFUND',key,600,cap['money_movement_id'])['money_movement_id']
        except ValueError as e:return str(e)
    with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(refund,['refund-one','refund-one' if same_key else 'refund-two']))
    with SessionLocal() as s:
        rows=s.scalars(select(Movement).where(Movement.movement_type=='REFUND')).all()
        assert len(rows)==1 and rows[0].amount_minor==600
        if same_key:assert result==[rows[0].money_movement_id]*2
        else:assert 'CUMULATIVE_REFUND_COMPENSATION_EXCEEDS_CAPTURE' in result
