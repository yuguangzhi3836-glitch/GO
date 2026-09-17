"""Real local database/process evidence; no claim of PostgreSQL or live provider acceptance."""
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import os
import sqlite3
import time

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from go_hotel.db.models import RegionalQueueRow as Row, HotelAutoPageEventRow as Event
from go_hotel.queue.durable_regional import DurableRegionalQueue, RegionalLeaseLost, processing

TOPIC='hotel-regional-build'


def make_queue(path, lease_ms=300_000, max_attempts=5):
    engine=create_engine('sqlite+pysqlite:///'+str(path), connect_args={'timeout':30})
    return DurableRegionalQueue(sessionmaker(bind=engine, expire_on_commit=False), lease_ms=lease_ms, max_attempts=max_attempts)


@pytest.fixture
def queue(tmp_path):
    q=make_queue(tmp_path/'queue.sqlite3')
    Row.__table__.create(q.factory.kw['bind'])
    Event.__table__.create(q.factory.kw['bind'])
    yield q
    q.factory.kw['bind'].dispose()


def payload(task='ROOT', run='r1', **kw):
    return {'run_id':run, 'task':task, 'mode':'REGION', 'city':'Synthetic City', 'actor':'test-admin', **kw}


@pytest.mark.no_db
def test_parallel_submissions_and_claims_keep_one_owner_and_one_job(queue):
    def submit(_): return queue.enqueue(TOPIC, 'one', payload())
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(submit, range(16))) == ['one']*16
        claimed=list(pool.map(lambda _:queue.claim(TOPIC), range(16)))
    owners=[r for r in claimed if r]
    assert len(owners)==1 and owners[0].attempt==1
    assert queue.status('r1')['running']==1
    queue.ack(owners[0], {'state':'processed'})
    assert queue.claim(TOPIC) is None
    assert queue.status('r1')['succeeded']==1
    assert queue.enqueue(TOPIC, 'one', payload()) == 'one'
    assert queue.claim(TOPIC) is None


@pytest.mark.no_db
def test_same_id_different_payload_is_rejected(queue):
    queue.enqueue(TOPIC,'one',payload())
    with pytest.raises(ValueError, match='PAYLOAD_CONFLICT'):
        queue.enqueue(TOPIC,'one',payload(city='Other City'))
    assert queue.claim(TOPIC).payload['city']=='Synthetic City'


@pytest.mark.no_db
def test_expired_claim_is_recovered_and_old_owner_cannot_ack_or_renew(queue):
    queue.lease_ms=100
    queue.enqueue(TOPIC,'one',payload())
    old=queue.claim(TOPIC)
    time.sleep(.15)
    new=queue.claim(TOPIC)
    assert new.message_id==old.message_id and new.lease_token!=old.lease_token and new.attempt==2
    for method in (queue.ack, queue.heartbeat):
        with pytest.raises(RegionalLeaseLost): method(old)
    with pytest.raises(RegionalLeaseLost): queue.fail(old,'stale')
    queue.ack(new)
    assert queue.status('r1')['succeeded']==1


@pytest.mark.no_db
def test_heartbeat_extends_current_claim(queue):
    queue.lease_ms=200
    queue.enqueue(TOPIC,'one',payload())
    owner=queue.claim(TOPIC)
    time.sleep(.12)
    queue.heartbeat(owner)
    time.sleep(.12)
    assert queue.claim(TOPIC) is None
    queue.ack(owner)


@pytest.mark.no_db
def test_failed_and_expired_work_has_bounded_retry_and_terminal_evidence(queue):
    queue.lease_ms=100
    queue.max_attempts=2
    queue.enqueue(TOPIC,'one',payload())
    first=queue.claim(TOPIC)
    queue.fail(first,'PROVIDER_TIMEOUT')
    assert queue.claim(TOPIC) is None # backoff prevents hot loops
    with queue.factory.begin() as s:
        s.get(Row,'one').available_ms=0
    second=queue.claim(TOPIC)
    assert second.attempt==2
    time.sleep(.15)
    assert queue.claim(TOPIC) is None
    with queue.factory() as s:
        row=s.get(Row,'one')
        assert row.status=='DEAD' and row.last_code=='ATTEMPTS_EXHAUSTED'
    assert queue.status('r1')['dead']==1


@pytest.mark.no_db
def test_nonretryable_failure_is_not_replayed(queue):
    queue.enqueue(TOPIC,'one',payload())
    queue.fail(queue.claim(TOPIC),'PROVIDER_SCHEMA',retryable=False)
    assert queue.status('r1')['dead']==1 and queue.claim(TOPIC) is None


def _take_and_wait(path, connection):
    queue=make_queue(path,lease_ms=200)
    claim=queue.claim(TOPIC)
    connection.send(claim.message_id)
    connection.recv()


@pytest.mark.no_db
@pytest.mark.skipif(os.name!='posix', reason='requires SIGKILL')
def test_sigkill_after_claim_keeps_work_for_a_new_process(queue):
    queue.enqueue(TOPIC,'one',payload())
    ctx=multiprocessing.get_context('fork')
    parent, child=ctx.Pipe()
    path=queue.factory.kw['bind'].url.database
    proc=ctx.Process(target=_take_and_wait,args=(path,child))
    proc.start();child.close()
    try:
        assert parent.poll(10) and parent.recv()=='one'
        proc.kill();proc.join(5)
        assert proc.exitcode==-9
        time.sleep(.25)
        reopened=make_queue(path)
        claim=reopened.claim(TOPIC)
        assert claim.message_id=='one' and claim.attempt==2
        reopened.ack(claim)
        assert reopened.status('r1')['succeeded']==1
        reopened.factory.kw['bind'].dispose()
    finally:
        if proc.is_alive():proc.kill()
        proc.join(5);parent.close()


@pytest.mark.no_db
def test_queue_and_enqueue_evidence_commit_or_rollback_together(queue):
    def broken(s,mid):
        s.add(Event(hotel_auto_page_event_id='bad', event_type='TEST', evidence_json={}, actor='test', created_at=__import__('datetime').datetime.now()))
        raise RuntimeError('event storage failed')
    with pytest.raises(RuntimeError):queue.enqueue(TOPIC,'one',payload(),on_create=broken)
    assert queue.claim(TOPIC) is None
    with queue.factory() as s:
        assert s.get(Event,'bad') is None


@pytest.mark.no_db
def test_stale_parent_cannot_enqueue_children(queue):
    queue.lease_ms=100
    queue.enqueue(TOPIC,'one',payload())
    old=queue.claim(TOPIC)
    time.sleep(.15)
    # Keep the replacement claim valid independently of runner scheduling.
    # The initial 100 ms lease still proves that the first owner is stale.
    queue.lease_ms=5_000
    new=queue.claim(TOPIC)
    with processing(queue,old), pytest.raises(RegionalLeaseLost):
        queue.enqueue(TOPIC,'child',payload('CITY'))
    with processing(queue,new):
        queue.enqueue(TOPIC,'child',payload('CITY'))
    queue.ack(new)
    assert queue.claim(TOPIC).message_id=='child'


@pytest.fixture
def regional(queue, monkeypatch):
    from go_hotel.services import regional_hotel_build as region
    from go_hotel.workers import regional_hotel_build_worker as worker
    monkeypatch.setattr(region,'SessionLocal',queue.factory)
    monkeypatch.setattr(region,'_queue',lambda:queue)
    monkeypatch.setattr(worker,'_queue',lambda:queue)
    monkeypatch.setattr(region,'_providers',lambda:[])
    return region,worker


@pytest.mark.no_db
def test_root_replay_has_identical_children_and_single_enqueue_evidence(regional,queue):
    region,_=regional
    p=payload()
    region.regional_hotel_build_service.process_message(p)
    region.regional_hotel_build_service.process_message(p)
    assert queue.status('r1')['queued']==1
    with queue.factory() as s:
        events=s.scalars(select(Event).where(Event.event_type=='REGIONAL_BUILD_CITY_ENQUEUED')).all()
        assert len(events)==1
    assert queue.claim(TOPIC).payload['task']=='CITY'


@pytest.mark.no_db
def test_worker_ack_only_after_processing_and_structured_failures_retry(regional,queue,monkeypatch):
    region,worker=regional
    mid=region.enqueue(payload('CITY'))
    monkeypatch.setattr(region,'_provider_items',lambda *a,**kw:(_ for _ in ()).throw(TimeoutError('provider timeout')))
    assert worker.run_once(0)==mid
    with queue.factory() as s:
        row=s.get(Row,mid)
        assert row.status=='QUEUED' and row.attempt==1 and row.last_code=='PROVIDER_TIMEOUT'
    with queue.factory.begin() as s:s.get(Row,mid).available_ms=0
    monkeypatch.setattr(region,'_provider_items',lambda *a,**kw:[])
    assert worker.run_once(0)==mid
    assert queue.status('r1')['succeeded']==1


@pytest.mark.no_db
def test_worker_exception_keeps_retryable_work(regional,queue,monkeypatch):
    region,worker=regional
    mid=region.enqueue(payload())
    def fail(_):raise RuntimeError('injected process failure')
    monkeypatch.setattr(region.regional_hotel_build_service,'process_message',fail)
    with pytest.raises(RuntimeError):worker.run_once(0)
    with queue.factory() as s:
        row=s.get(Row,mid)
        assert row.status=='QUEUED' and row.attempt==1


@pytest.mark.no_db
def test_manual_retry_replays_same_failure_once_and_preserves_failed_tier(regional,queue):
    region,_=regional
    region.event('REGIONAL_BUILD_CREATED', {'run_id':'r1','mode':'NATIONAL_TIERED','tier':5})
    region.event('REGIONAL_BUILD_FAILURE', {'run_id':'r1','scope':'CITY','province':'Test','city':'Synthetic City','tier':4,'retryable':True})
    for _ in range(2):region.regional_hotel_build_service.retry_failures('r1','test-admin')
    assert queue.status('r1')['queued']==1
    claim=queue.claim(TOPIC)
    assert claim.payload['tier']==4 and claim.payload['retry_generation']


@pytest.mark.no_db
def test_tier_acceptance_and_next_root_are_atomic_without_redis(regional,queue):
    region,_=regional
    region.event('REGIONAL_BUILD_CREATED', {'run_id':'r1','mode':'NATIONAL_TIERED','tier':5,'country':'CN'})
    region.event('REGIONAL_BUILD_TIER_PAUSED', {'run_id':'r1','tier':5})
    with pytest.raises(ValueError,match='CONFIRMATION_REQUIRED'):
        region.regional_hotel_build_service.advance_after_acceptance('r1','test-admin','')
    first=region.regional_hotel_build_service.advance_after_acceptance('r1','test-admin','TIER5_ACCEPTED_UNLOCK_TIER4')
    replay=region.regional_hotel_build_service.advance_after_acceptance('r1','test-admin','TIER5_ACCEPTED_UNLOCK_TIER4')
    assert not first['idempotent'] and replay['idempotent']
    assert queue.status('r1')['queued']==1
    claim=queue.claim(TOPIC)
    assert claim.payload['task']=='ROOT' and claim.payload['tier']==4
    with queue.factory() as s:
        assert len(s.scalars(select(Event).where(Event.event_type=='REGIONAL_BUILD_TIER_ACCEPTED')).all())==1


@pytest.mark.no_db
def test_status_never_calls_pending_delivery_complete_and_deduplicates_old_events(regional,queue):
    region,_=regional
    region.event('REGIONAL_BUILD_CREATED', {'run_id':'r1','mode':'REGION'})
    region.event('REGIONAL_BUILD_CITY_ENQUEUED', {'run_id':'r1','city':'Synthetic City'})
    region.event('REGIONAL_BUILD_CITY_DISCOVERY_FINISHED', {'run_id':'r1','city':'Synthetic City','deduped':1})
    for _ in range(2):region.event('REGIONAL_BUILD_HOTEL_ENQUEUED', {'run_id':'r1','city':'Synthetic City','candidate_key':'hotel-a'})
    region.event('REGIONAL_BUILD_HOTEL_FINISHED', {'run_id':'r1','city':'Synthetic City','candidate_key':'hotel-a','hotel_id':'h1','state':'COMPLETED','page':True,'completeness_gate':{'passed':True}})
    assert region.regional_hotel_build_service.status('r1')['runs'][0]['state']=='COMPLETED'
    region.enqueue(payload('CITY'))
    assert region.regional_hotel_build_service.status('r1')['runs'][0]['state']=='RUNNING'
    queue.fail(queue.claim(TOPIC),'PERMANENT',retryable=False)
    result=region.regional_hotel_build_service.status('r1')['runs'][0]
    assert result['state']=='NEEDS_ATTENTION' and result['delivery']['dead']==1


@pytest.mark.no_db
def test_migration_roundtrip_preserves_data_and_blocks_loss_of_queue_evidence(tmp_path):
    from alembic import command
    from alembic.config import Config
    from go_hotel.core.config import settings
    db=tmp_path/'migration.sqlite3'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE retained (id text PRIMARY KEY, value text)')
        conn.execute("INSERT INTO retained VALUES ('booking','paid')")
    config=Config('alembic.ini')
    old=settings.database_url
    settings.database_url='sqlite+pysqlite:///'+str(db)
    try:
        command.stamp(config,'0124_autonomy_durable')
        command.upgrade(config,'0125_regional_queue')
        command.downgrade(config,'0124_autonomy_durable')
        command.upgrade(config,'0125_regional_queue')
        queue=make_queue(db)
        queue.enqueue(TOPIC,'one',payload())
        with pytest.raises(RuntimeError,match='REGIONAL_QUEUE_DATA_PRESENT'):
            command.downgrade(config,'0124_autonomy_durable')
        with sqlite3.connect(db) as conn:
            assert conn.execute('SELECT * FROM retained').fetchone()==('booking','paid')
            assert conn.execute('SELECT version_num FROM alembic_version').fetchone()[0]=='0125_regional_queue'
        assert queue.claim(TOPIC).message_id=='one'
        queue.factory.kw['bind'].dispose()
    finally:settings.database_url=old


@pytest.mark.no_db
def test_manual_retry_does_not_duplicate_auto_retry_or_completed_work(regional,queue):
    region,_=regional
    mid=region.enqueue(payload('CITY'))
    region.event('REGIONAL_BUILD_FAILURE', {'run_id':'r1','scope':'CITY','city':'Synthetic City','retryable':True,'delivery_message_id':mid})
    assert region.regional_hotel_build_service.retry_failures('r1','test-admin')['queued']==0
    queue.ack(queue.claim(TOPIC))
    assert region.regional_hotel_build_service.retry_failures('r1','test-admin')['queued']==0
    assert queue.status('r1')['succeeded']==1


@pytest.mark.no_db
def test_tier_does_not_advance_while_other_fanout_or_failed_work_remains(regional,queue):
    region,_=regional
    region.event('REGIONAL_BUILD_CREATED', {'run_id':'r1','mode':'NATIONAL_TIERED','tier':5})
    region.enqueue(payload(tier=5))
    region.regional_hotel_build_service._maybe_advance_tier('r1','test-admin')
    assert not any(e.event_type=='REGIONAL_BUILD_TIER_PAUSED' for e in region._run_events('r1'))
    owner=queue.claim(TOPIC)
    queue.fail(owner,'provider',retryable=False)
    region.regional_hotel_build_service._maybe_advance_tier('r1','test-admin')
    assert not any(e.event_type=='REGIONAL_BUILD_TIER_PAUSED' for e in region._run_events('r1'))


@pytest.mark.no_db
def test_manual_retry_supersedes_dead_delivery_only_with_durable_replacement(regional,queue):
    region,_=regional
    mid=region.enqueue(payload('CITY'))
    owner=queue.claim(TOPIC)
    queue.fail(owner,'PROVIDER_TIMEOUT',retryable=False)
    region.event('REGIONAL_BUILD_FAILURE', {'run_id':'r1','scope':'CITY','city':'Synthetic City','retryable':True,'delivery_message_id':mid})
    result=region.regional_hotel_build_service.retry_failures('r1','test-admin')
    assert result['queued']==1
    counts=queue.status('r1')
    assert counts['dead']==0 and counts['superseded']==1 and counts['queued']==1
    with queue.factory() as s:
        next_id=s.get(Row,mid).result_json['retry_message_id']
        assert s.get(Row,next_id).status=='QUEUED'
    assert region.regional_hotel_build_service.retry_failures('r1','test-admin')['queued']==0


@pytest.mark.no_db
def test_legacy_snapshot_import_is_validated_before_writes_and_idempotent(regional,queue):
    import importlib.util
    import json
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('regional_import',Path('scripts/import_regional_queue_snapshot.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    region,_=regional
    records=[{'message_id':'old-a','topic':TOPIC,'payload':payload('CITY')},
             {'message_id':'old-b','topic':TOPIC,'payload':payload('CITY')}]
    raw=json.dumps([json.dumps(x) for x in records]).encode()
    assert module.import_snapshot(raw)['applied'] is False
    assert queue.status('r1')['queued']==0
    for _ in range(2):
        receipt=module.import_snapshot(raw,apply=True,submit=region.enqueue)
        assert receipt['redis_items_deleted']==0 and receipt['validated_messages']==2
    assert queue.status('r1')['queued']==1
    broken=json.dumps([records[0],{**records[1],'payload':payload('CITY',mode='NATIONAL')}]).encode()
    with pytest.raises(ValueError,match='IDENTITY_CONFLICT'):
        module.import_snapshot(broken,apply=True,submit=lambda _:pytest.fail('must validate all before write'))


@pytest.mark.no_db
def test_exhausted_delivery_has_actionable_exception_and_exact_task_retry(regional,queue):
    region,_=regional
    queue.max_attempts=1;queue.lease_ms=100
    mid=region.enqueue(payload('PROVINCE',province='Test Province'))
    queue.claim(TOPIC)
    time.sleep(.15)
    assert queue.claim(TOPIC) is None
    with queue.factory() as s:
        evidence=[e.evidence_json for e in s.scalars(select(Event).where(Event.event_type=='REGIONAL_BUILD_FAILURE')).all()]
    assert len(evidence)==1
    assert evidence[0]['delivery_message_id']==mid and evidence[0]['operator_action_required']
    assert evidence[0]['error']=='ATTEMPTS_EXHAUSTED'
    assert region.regional_hotel_build_service.status('r1')['runs'][0]['failures']==1
    assert region.regional_hotel_build_service.retry_failures('r1','recovery-admin')['queued']==1
    claim=queue.claim(TOPIC)
    assert claim.payload['task']=='PROVINCE' and claim.payload['province']=='Test Province'
    queue.ack(claim)
    counts=queue.status('r1')
    assert counts['dead']==0 and counts['superseded']==1 and counts['succeeded']==1
    assert region.regional_hotel_build_service.exceptions()['action_required']==0


@pytest.mark.no_db
def test_multiple_dead_hotels_in_same_city_each_receive_recovery(regional,queue):
    region,_=regional
    for i in range(3):
        region.enqueue(payload('HOTEL',candidate_key=f'hotel-{i}',seed={'name':f'Synthetic-{i}'}))
        queue.fail(queue.claim(TOPIC),'EXHAUSTED',retryable=False)
    assert queue.status('r1')['dead']==3
    assert region.regional_hotel_build_service.retry_failures('r1','recovery-admin')['queued']==3
    assert queue.status('r1')['queued']==3 and queue.status('r1')['superseded']==3


@pytest.mark.no_db
def test_failed_manual_recovery_does_not_hide_original_dead_task(regional,queue,monkeypatch):
    region,_=regional
    mid=region.enqueue(payload('CITY'))
    queue.fail(queue.claim(TOPIC),'EXHAUSTED',retryable=False)
    original=region.insert_once
    def failing(session,model,values,keys):
        if values.get('event_type')=='REGIONAL_BUILD_CITY_ENQUEUED':
            raise RuntimeError('injected evidence write failure')
        return original(session,model,values,keys)
    monkeypatch.setattr(region,'insert_once',failing)
    with pytest.raises(RuntimeError):region.regional_hotel_build_service.retry_failures('r1','recovery-admin')
    with queue.factory() as s:
        assert s.get(Row,mid).status=='DEAD'
        assert len(s.scalars(select(Row)).all())==1
