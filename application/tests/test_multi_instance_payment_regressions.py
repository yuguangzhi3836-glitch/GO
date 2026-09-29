"""Regression boundaries exposed by the independent-process checkout gate."""
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OmnichannelPaymentAttemptRow as Attempt,OmnichannelMoneyMovementRow as Money
from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service as sources
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge as bridge
from go_hotel.services.omnichannel_payment import omnichannel_payment_service as payments
from test_depth24_expiry import pending

def prepared():
    oid=pending('RAIL')['order_id']
    candidates=[{'source_id':'isolated','source_type':'RAIL_OPERATOR_OFFICIAL','authorized':True,'available':True,'evidence_reference':'isolated://multi-instance-regression'}]
    first=sources.decide('RAIL',oid,candidates)
    assert sources.decide('RAIL',oid,candidates)==first
    i=payments.create_intent({'business_type':'RAIL_ORDER','business_id':oid,'channel_priority':['LOCAL_MARKET']},'rail-checkout:'+oid,'owner')
    payments.select_channel(i['payment_intent_id'],'LOCAL_MARKET','owner',True)
    a=payments.execute(i['payment_intent_id'],'CONTRACT_SIMULATOR')
    return oid,i['payment_intent_id'],a['payment_attempt_id']

def test_committed_simulator_attempt_resumes_without_reset_or_second_attempt():
    oid,iid,aid=prepared()
    with pytest.raises(ValueError,match='CHANNEL_SWITCH_BLOCKED_BY_PAYMENT_STATE'):
        payments.select_channel(iid,'LOCAL_MARKET','owner',True)
    with pytest.raises(ValueError,match='PAYMENT_INTENT_NOT_READY'):
        payments.execute(iid,'CONTRACT_SIMULATOR')
    result=bridge.checkout_contract('RAIL',oid,'owner','isolated','isolated://resume')
    assert bridge.checkout_contract('RAIL',oid,'owner','isolated','isolated://resume')==result
    with SessionLocal() as s:
        attempts=list(s.scalars(select(Attempt).where(Attempt.payment_intent_id==iid)))
        assert len(attempts)==1 and attempts[0].payment_attempt_id==aid and attempts[0].state=='SUCCEEDED'
        moves=list(s.scalars(select(Money).where(Money.root_payment_intent_id==iid)))
        assert len(moves)==2 and {x.movement_type for x in moves}=={'AUTHORIZATION','CAPTURE'}

@pytest.mark.parametrize('result',['TIMEOUT','FAILED'])
def test_unknown_or_failed_payment_cannot_be_promoted_by_checkout_retry(result):
    oid,iid,aid=prepared();payments.simulate_result(aid,result)
    with pytest.raises(ValueError,match='PAYMENT_RECONCILIATION_REQUIRED'):
        bridge.checkout_contract('RAIL',oid,'owner','isolated','isolated://retry')
    with SessionLocal() as s:
        assert len(list(s.scalars(select(Attempt).where(Attempt.payment_intent_id==iid))))==1
        assert not list(s.scalars(select(Money).where(Money.root_payment_intent_id==iid)))

def test_another_payer_cannot_resume_a_committed_attempt():
    oid,iid,aid=prepared()
    with pytest.raises(ValueError,match='PAYMENT_PAYER_ORDER_MISMATCH'):
        bridge.checkout_contract('RAIL',oid,'other-owner','isolated','isolated://retry')
    with SessionLocal() as s:
        assert s.get(Attempt,aid).state=='CONTRACT_READY_NOT_EXTERNAL'
        assert not list(s.scalars(select(Money).where(Money.root_payment_intent_id==iid)))
