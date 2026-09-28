from datetime import datetime,timedelta,timezone
import pytest
from sqlalchemy import event,select
from go_hotel.db.session import SessionLocal,engine
from go_hotel.db.models import MobilityRideOrderRow as Ride,JourneyRecoveryEvidenceChainRow as Evidence,OmnichannelPaymentIntentRow as Intent
from go_hotel.mobility.ride.service import ride_service
from go_hotel.mobility.ride.cancellation_policy import accepted_in
from go_hotel.services.mobility_refund_consent import verified_records
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge as bridge
from ride_cancellation_fixture import create_ride

def ride():
    return create_ride(ride_service,'query-owner',{'offer_id':'ride_standard','pickup':'ISOLATED_A','dropoff':'ISOLATED_B','pickup_at':(datetime.now(timezone.utc)+timedelta(days=10)).isoformat(),'passengers':[{'full_name':'SYNTHETIC'}]})['order_id']

def test_policy_reads_one_complete_chain_and_still_rejects_nonpolicy_tampering():
    oid=ride()
    with SessionLocal.begin() as s:
        append_vertical_evidence(s,'RIDE',oid,'OTHER_EVENT','PAYMENT_PENDING',{'synthetic':True})
    statements=[]
    def observed(conn,cursor,statement,parameters,context,executemany):statements.append(statement)
    with SessionLocal() as s:
        order=s.get(Ride,oid)
        event.listen(engine,'before_cursor_execute',observed)
        try:assert accepted_in(s,order)['order_id']==oid
        finally:event.remove(engine,'before_cursor_execute',observed)
    assert len(statements)==1 and 'journey_recovery_evidence_chain' in statements[0].lower()
    with SessionLocal.begin() as s:
        row=s.scalar(select(Evidence).where(Evidence.execution_id=='rc20:RIDE:'+oid,Evidence.evidence_kind=='OTHER_EVENT'))
        row.evidence_hash='tampered'
    with SessionLocal() as s:
        with pytest.raises(ValueError,match='REFUND_OPERATION_INTEGRITY_INVALID'):accepted_in(s,s.get(Ride,oid))

def test_append_fetches_only_tail_and_preserves_every_chain_link():
    oid=ride();statements=[]
    def observed(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('SELECT'):statements.append(statement)
    with SessionLocal.begin() as s:
        order=s.get(Ride,oid,with_for_update=True)
        before=len(verified_records(s,order,'RIDE'))
        event.listen(engine,'before_cursor_execute',observed)
        try:
            for i in range(3):append_vertical_evidence(s,'RIDE',oid,'TEST_APPEND','PAYMENT_PENDING',{'i':i})
        finally:event.remove(engine,'before_cursor_execute',observed)
        assert len(verified_records(s,order,'RIDE'))==before+3
    assert len(statements)==3 and all('LIMIT' in q.upper() for q in statements)
    assert all('evidence_json' not in q.lower() for q in statements)

def test_idempotency_replay_uses_one_connection_and_preserves_identity():
    from go_hotel.repositories.sql import repo
    body={'owner':'first','amount_minor':16800}
    assert repo.claim_idempotency('query-test','same-key',body)==('CLAIMED',None)
    assert repo.claim_idempotency('query-test','same-key',body)[0]=='IN_PROGRESS'
    response={'order_id':'immutable-result'}
    repo.complete_idempotency('query-test','same-key',body,response,'immutable-result')
    checkouts=[]
    def checkout(*args):checkouts.append(True)
    event.listen(engine,'checkout',checkout)
    try:
        state,record=repo.claim_idempotency('query-test','same-key',body)
    finally:event.remove(engine,'checkout',checkout)
    assert state=='REPLAY' and record['response']==response and record['resource_id']=='immutable-result'
    assert len(checkouts)==1
    with pytest.raises(ValueError,match='IDEMPOTENCY_CONFLICT'):
        repo.claim_idempotency('query-test','same-key',dict(body,amount_minor=16801))
    assert repo.claim_idempotency('different-operation','same-key',body)==('CLAIMED',None)

def test_concurrent_idempotency_claim_has_exactly_one_winner():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from go_hotel.repositories.sql import repo
    barrier=Barrier(8)
    def claim(_):
        barrier.wait(timeout=10)
        return repo.claim_idempotency('concurrent-query','one-key',{'amount_minor':16800})[0]
    with ThreadPoolExecutor(max_workers=8) as pool:states=list(pool.map(claim,range(8)))
    assert states.count('CLAIMED')==1 and states.count('IN_PROGRESS')==7

def test_unrelated_integrity_error_is_not_treated_as_replay():
    from sqlalchemy.exc import IntegrityError
    from go_hotel.repositories.sql import repo
    with pytest.raises(IntegrityError):repo.claim_idempotency(None,'invalid-operation',{})

@pytest.mark.parametrize('case',['wrong_payer','expired'])
def test_shared_checkout_snapshot_retains_payer_and_deadline_rejections(case):
    oid=ride();owner='query-owner'
    if case=='wrong_payer':owner='another-owner';code='PAYMENT_PAYER_ORDER_MISMATCH'
    else:
        from test_depth24_expiry import age
        age('RIDE',oid);code='RESERVATION_EXPIRED_NOT_PAYABLE'
    with pytest.raises(ValueError,match=code):bridge.checkout_contract('RIDE',oid,owner,'isolated','isolated://query-test')
    with SessionLocal() as s:assert not list(s.scalars(select(Intent).where(Intent.business_id==oid)))
