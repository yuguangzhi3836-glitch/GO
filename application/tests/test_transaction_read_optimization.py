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

def test_reused_chain_queries_keep_orders_separate_and_read_new_entries():
    first,second=ride(),ride()
    with SessionLocal.begin() as s:
        a=s.get(Ride,first);b=s.get(Ride,second)
        a_before=verified_records(s,a,'RIDE');b_before=verified_records(s,b,'RIDE')
        append_vertical_evidence(s,'RIDE',first,'ONLY_FIRST','PAYMENT_PENDING',{'order':first})
        assert len(verified_records(s,a,'RIDE'))==len(a_before)+1
        assert len(verified_records(s,b,'RIDE'))==len(b_before)
        append_vertical_evidence(s,'RIDE',second,'ONLY_SECOND','PAYMENT_PENDING',{'order':second})
        assert verified_records(s,a,'RIDE')[-1].evidence_kind=='ONLY_FIRST'
        assert verified_records(s,b,'RIDE')[-1].evidence_kind=='ONLY_SECOND'

def test_reused_clock_query_reads_fresh_database_time():
    import time
    from go_hotel.autonomy.durable import db_now_ms
    with SessionLocal() as s:
        before=db_now_ms(s)
        time.sleep(.03)
        assert db_now_ms(s)>before

@pytest.mark.parametrize('case',['wrong_payer','expired'])
def test_shared_checkout_snapshot_retains_payer_and_deadline_rejections(case):
    oid=ride();owner='query-owner'
    if case=='wrong_payer':owner='another-owner';code='PAYMENT_PAYER_ORDER_MISMATCH'
    else:
        from test_depth24_expiry import age
        age('RIDE',oid);code='RESERVATION_EXPIRED_NOT_PAYABLE'
    with pytest.raises(ValueError,match=code):bridge.checkout_contract('RIDE',oid,owner,'isolated','isolated://query-test')
    with SessionLocal() as s:assert not list(s.scalars(select(Intent).where(Intent.business_id==oid)))

@pytest.mark.parametrize('source_present',[True,False])
def test_checkout_reads_source_on_guard_connection_and_repairs_missing_source(monkeypatch,source_present):
    from sqlalchemy import delete
    from go_hotel.db.models import VerticalSourceDecisionRow as Decision
    from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service as sources
    oid=ride()
    if not source_present:
        with SessionLocal.begin() as s:
            s.execute(delete(Decision).where(Decision.vertical=='RIDE',Decision.business_id==oid))
    checked=[]
    original=sources.latest_in
    def observed(s,vertical,business_id):
        # The order and intent guard already use this transaction's connection.
        assert s.in_transaction()
        acquisitions=[]
        def checkout(*args):acquisitions.append(True)
        event.listen(engine,'checkout',checkout)
        try:result=original(s,vertical,business_id)
        finally:event.remove(engine,'checkout',checkout)
        assert not acquisitions
        checked.append(result)
        return result
    monkeypatch.setattr(sources,'latest_in',observed)
    result=bridge.checkout_contract('RIDE',oid,'query-owner','isolated','isolated://query-test')
    assert result['state']=='PAYMENT_CONFIRMED_AWAITING_SUPPLIER'
    assert len(checked)==1 and bool(checked[0])==source_present
    with SessionLocal() as s:
        records=list(s.scalars(select(Decision).where(Decision.vertical=='RIDE',Decision.business_id==oid)))
        assert len(records)==1
        assert records[0].selected_source_id==('ride-engineering-source' if source_present else 'isolated')

def test_source_read_in_session_does_not_commit_caller_changes():
    from go_hotel.db.models import VerticalSourceDecisionRow as Decision
    from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service as sources
    oid=ride()
    with SessionLocal() as s:
        order=s.get(Ride,oid)
        order.pickup='UNCOMMITTED';s.flush()
        assert sources.latest_in(s,'RIDE',oid)['business_id']==oid
        assert sources.latest_in(s,'RIDE','missing') is None
        s.rollback()
    with SessionLocal() as s:assert s.get(Ride,oid).pickup=='ISOLATED_A'
