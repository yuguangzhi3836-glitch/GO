import os,threading,uuid,hashlib,json
from datetime import datetime,timezone
import pytest
from sqlalchemy import create_engine,text,select
from sqlalchemy.orm import sessionmaker
from go_hotel.db.models import (
 PaymentOrderRootRow as Root,ExternalTruthWebhookReceiptRow as Webhook,PostgresRaceProofEvidenceRow as Proof,
 OmnichannelPaymentIntentRow as Intent,OmnichannelMoneyMovementRow as Movement,FinanceScopedCloseBatchRow as Close,
 OmnichannelLedgerEntryRow as Ledger,
)

pytestmark=[pytest.mark.postgres,pytest.mark.concurrency]
URL=os.getenv('POSTGRES_TEST_DATABASE_URL')

def session_factory():
    eng=create_engine(URL,pool_pre_ping=True,isolation_level='READ COMMITTED');return eng,sessionmaker(bind=eng,expire_on_commit=False,autoflush=False)
def evhash(v):return hashlib.sha256(json.dumps(v,sort_keys=True,default=str).encode()).hexdigest()
def record(Session,key,workers,commits,rejects):
    with Session() as s:
        payload={'scenario':key,'workers':workers,'commits':commits,'rejects':rejects,'nonce':uuid.uuid4().hex}
        version=s.execute(text('select version()')).scalar_one()
        s.add(Proof(postgres_race_proof_evidence_id='prp-'+uuid.uuid4().hex,scenario_key=key,database_version=version[:128],worker_count=workers,commit_count=commits,reject_count=rejects,assertion_state='PASS',evidence_hash=evhash(payload),created_at=datetime.now(timezone.utc)));s.commit()

@pytest.mark.skipif(not URL,reason='POSTGRES_TEST_DATABASE_URL not configured')
def test_0101_order_payment_root_exactly_once_postgres():
    eng,Session=session_factory();business_id='p0101-'+uuid.uuid4().hex;barrier=threading.Barrier(8);results=[]
    def w():
        try:
            with Session() as s:
                barrier.wait(timeout=10);s.add(Root(payment_order_root_id='por-'+uuid.uuid4().hex,business_type='HOTEL_ORDER',business_id=business_id,payment_intent_id='pi-'+uuid.uuid4().hex,legal_entity_id='GO_CN',state='ACTIVE',root_hash=uuid.uuid4().hex,created_at=datetime.now(timezone.utc)));s.commit();results.append('COMMIT')
        except Exception:results.append('REJECT')
    ts=[threading.Thread(target=w) for _ in range(8)];[t.start() for t in ts];[t.join(20) for t in ts]
    assert results.count('COMMIT')==1 and results.count('REJECT')==7;record(Session,'ORDER_PAYMENT_ROOT_EXACTLY_ONCE',8,1,7);eng.dispose()

@pytest.mark.skipif(not URL,reason='POSTGRES_TEST_DATABASE_URL not configured')
def test_0101_webhook_delivery_replay_unique_postgres():
    eng,Session=session_factory();delivery='delivery-'+uuid.uuid4().hex;barrier=threading.Barrier(8);results=[]
    def w():
        try:
            with Session() as s:
                barrier.wait(timeout=10);s.add(Webhook(external_truth_webhook_receipt_id='etw-'+uuid.uuid4().hex,external_truth_operation_id='op-race',source_vertical='PAYMENT',delivery_id=delivery,signature_scheme='TEST',signature_verified=True,supplier_state='SUCCEEDED',payload_hash=uuid.uuid4().hex,received_at=datetime.now(timezone.utc)));s.commit();results.append('COMMIT')
        except Exception:results.append('REJECT')
    ts=[threading.Thread(target=w) for _ in range(8)];[t.start() for t in ts];[t.join(20) for t in ts]
    assert results.count('COMMIT')==1 and results.count('REJECT')==7;record(Session,'WEBHOOK_REPLAY_UNIQUE',8,1,7);eng.dispose()

@pytest.mark.skipif(not URL,reason='POSTGRES_TEST_DATABASE_URL not configured')
def test_0101_capture_refund_serialization_postgres(monkeypatch):
    import go_hotel.services.unified_money_movement as um
    eng,Session=session_factory();iid='opi-'+uuid.uuid4().hex;auth='omm-'+uuid.uuid4().hex;cap='omm-'+uuid.uuid4().hex;now=datetime.now(timezone.utc)
    with Session() as s:
        s.add(Intent(payment_intent_id=iid,business_type='TEST_ORDER',business_id='ord-'+uuid.uuid4().hex,payer_id='payer',payee_id='payee',operation='PAY',amount_minor=1000,currency='USD',channel_priority_json=['CARD'],selected_channel='CARD',state='SUCCEEDED',idempotency_key='ik-'+uuid.uuid4().hex,automatic_fallback_allowed=False,created_at=now,updated_at=now))
        s.add(Movement(money_movement_id=auth,root_payment_intent_id=iid,parent_movement_id=None,movement_type='AUTHORIZATION',business_type='TEST_ORDER',business_id='ord-auth',amount_minor=1000,currency='USD',state='CONFIRMED',idempotency_key='auth-'+uuid.uuid4().hex,external_reference='ext-auth',evidence_json=['race://auth'],created_at=now,updated_at=now))
        s.add(Movement(money_movement_id=cap,root_payment_intent_id=iid,parent_movement_id=auth,movement_type='CAPTURE',business_type='TEST_ORDER',business_id='ord-cap',amount_minor=1000,currency='USD',state='CONFIRMED',idempotency_key='cap-'+uuid.uuid4().hex,external_reference='ext-cap',evidence_json=['race://cap'],created_at=now,updated_at=now));s.commit()
    monkeypatch.setattr(um,'SessionLocal',Session);barrier=threading.Barrier(2);results=[];errors=[]
    # This is an isolated money serialization test, with no certified external
    # callback receipt. The trusted-ingress guard must remain enforced.
    with pytest.raises(ValueError,match='EXTERNAL_CERTIFIED_FACT_TRUSTED_INGRESS_REQUIRED'):
        um.unified_money_movement_service.create(iid,{'mode':'EXTERNAL_CERTIFIED_FACT'},'forged-external','test')
    def w(n):
        try:
            barrier.wait(timeout=10);um.unified_money_movement_service.create(iid,{'movement_type':'REFUND','parent_movement_id':cap,'amount_minor':700,'evidence':[f'isolated://refund/{n}'],'mode':'CONTRACT_SIMULATOR'},f'refund-{uuid.uuid4().hex}',f'worker-{n}');results.append('COMMIT')
        except Exception as exc:results.append('REJECT');errors.append(str(exc))
    ts=[threading.Thread(target=w,args=(i,)) for i in range(2)];[t.start() for t in ts];[t.join(20) for t in ts]
    assert not any(t.is_alive() for t in ts)
    assert results.count('COMMIT')==1 and results.count('REJECT')==1,errors
    assert errors==['CUMULATIVE_REFUND_COMPENSATION_EXCEEDS_CAPTURE']
    with Session() as s:
        refunds=list(s.scalars(select(Movement).where(Movement.root_payment_intent_id==iid,Movement.movement_type=='REFUND')))
        assert len(refunds)==1 and refunds[0].amount_minor==700 and refunds[0].parent_movement_id==cap
        ledger=list(s.scalars(select(Ledger).where(Ledger.payment_intent_id==iid,Ledger.entry_type=='REFUND')))
        assert sum(x.amount_minor for x in ledger if x.direction=='DEBIT')==700
        assert sum(x.amount_minor for x in ledger if x.direction=='CREDIT')==700
    record(Session,'CAPTURE_REFUND_SERIALIZATION',2,1,1);eng.dispose()

@pytest.mark.skipif(not URL,reason='POSTGRES_TEST_DATABASE_URL not configured')
def test_0101_finance_close_approval_race_postgres(monkeypatch):
    import go_hotel.services.unified_money_movement as um
    eng,Session=session_factory();cid='fscb-'+uuid.uuid4().hex;now=datetime.now(timezone.utc)
    with Session() as s:
        s.add(Close(finance_scoped_close_batch_id=cid,legal_entity_id='GO_CN',currency='CNY',period_start='2026-01-01',period_end='2026-01-01',cutoff_at=now,state='PENDING_APPROVAL',movement_count=0,debit_minor=0,credit_minor=0,difference_minor=0,blockers_json=[],scope_hash=uuid.uuid4().hex,evidence_hash=uuid.uuid4().hex,requested_by='maker',approved_by=None,created_at=now,closed_at=None));s.commit()
    monkeypatch.setattr(um,'SessionLocal',Session);barrier=threading.Barrier(4);results=[]
    def w(n):
        try:
            barrier.wait(timeout=10);um.unified_money_movement_service.approve_close(cid,f'checker-{n}');results.append('COMMIT')
        except Exception:results.append('REJECT')
    ts=[threading.Thread(target=w,args=(i,)) for i in range(4)];[t.start() for t in ts];[t.join(20) for t in ts]
    assert results.count('COMMIT')==1 and results.count('REJECT')==3;record(Session,'FINANCE_CLOSE_APPROVAL_RACE',4,1,3);eng.dispose()

@pytest.mark.skipif(not URL,reason='POSTGRES_TEST_DATABASE_URL not configured')
def test_0101_postgres_server_is_real_postgres():
    eng,_=session_factory()
    with eng.connect() as c:v=c.execute(text('select version()')).scalar_one()
    assert 'PostgreSQL' in v;eng.dispose()
