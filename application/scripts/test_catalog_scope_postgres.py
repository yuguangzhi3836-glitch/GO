"""Real PostgreSQL 18.4 race gates for catalog reset, isolated GitHub CI only.

Run from application with PYTHONPATH=src and CATALOG_SCOPE_TEST_DATABASE_URL
pointing at the ephemeral database go_catalog_scope_ci. Each test owns a fresh
random schema. Production functions/SQLAlchemy models run unchanged; scheduling
hooks pause inside actual transactions to force both lock orderings.
"""
from __future__ import annotations
import os
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import patch
from sqlalchemy import create_engine, select, text, func
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


def validated_url():
    if os.getenv('GITHUB_ACTIONS') != 'true' or os.getenv('CI') != 'true':
        raise RuntimeError('GITHUB_ISOLATED_CI_REQUIRED')
    raw=os.environ.get('CATALOG_SCOPE_TEST_DATABASE_URL','')
    url=make_url(raw)
    if (url.drivername != 'postgresql+psycopg' or url.host not in {'127.0.0.1','localhost','postgres'}
            or url.database != 'go_catalog_scope_ci' or url.query):
        raise RuntimeError('EPHEMERAL_LOCAL_CI_POSTGRES_DATABASE_REQUIRED')
    return url


# Validate before importing application modules or creating application engines.
URL=validated_url()
os.environ['DATABASE_URL']=URL.render_as_string(hide_password=False)
os.environ['APP_ENV']='test'
from go_hotel.db.models import (HotelAutoPageEventRow as Event, HotelCanonicalProfileRow as Profile,
    RegionalQueueRow as Queue, HotelContactPointRow as Contact)
from go_hotel.services import catalog_scope as scope
from go_hotel.services import hotel_autopage_factory as factory_module
from go_hotel.queue.durable_regional import DurableRegionalQueue


class CatalogScopePostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.control=create_engine(URL,pool_pre_ping=True,connect_args={'connect_timeout':5})
        with cls.control.connect() as c:
            version=int(c.scalar(text('SHOW server_version_num')))
            if version != 180004:
                raise RuntimeError('POSTGRESQL_18_4_REQUIRED')
        print('Verified PostgreSQL 18.4; all writes restricted to per-test random schemas',flush=True)

    @classmethod
    def tearDownClass(cls):
        cls.control.dispose()

    def setUp(self):
        self.schema='catalog_scope_ci_'+uuid.uuid4().hex
        with self.control.begin() as c:
            c.execute(text('CREATE SCHEMA '+self.schema))
        self.engine=create_engine(URL,pool_size=8,max_overflow=0,connect_args={
            'connect_timeout':5,'options':f'-csearch_path={self.schema} -cstatement_timeout=15000 -clock_timeout=10000'})
        self.addCleanup(self.cleanup_schema)
        self.session=sessionmaker(bind=self.engine,expire_on_commit=False,autoflush=False)
        with self.engine.connect() as c:
            self.assertEqual(c.scalar(text('SELECT current_schema()')),self.schema)
        for model in (Event,Profile,Queue,Contact):model.__table__.create(self.engine)
        self.scope_factory=patch.object(scope,'SessionLocal',self.session)
        self.factory_factory=patch.object(factory_module,'SessionLocal',self.session)
        self.scope_factory.start();self.factory_factory.start()
        self.addCleanup(self.scope_factory.stop);self.addCleanup(self.factory_factory.stop)
        self.queue=DurableRegionalQueue(self.session,lease_ms=300000)
        self.keep=sorted(scope.PROTECTED_IDS)[0]
        self.pool=ThreadPoolExecutor(max_workers=5)
        self.addCleanup(self.pool.shutdown,wait=True,cancel_futures=True)
        self.gates=[]
        self.addCleanup(self.release_gates)
        now=datetime.now(timezone.utc)
        with self.session.begin() as s:
            for i,hid in enumerate([*sorted(scope.PROTECTED_IDS),'old-hotel']):
                s.add(Profile(hotel_id=hid,slug='fixture-'+str(i),canonical_json={'name':'敖麓谷雅' if hid in scope.PROTECTED_IDS else 'Old hotel'},field_provenance_json={},source_snapshot_ids_json=[],version=1,created_at=now,updated_at=now))
            for name,hid in [('keep-contact',self.keep),('old-contact','old-hotel')]:
                s.add(Contact(hotel_contact_point_id=name,hotel_id=hid,contact_type='BUSINESS',channel='EMAIL',value=name+'@example.invalid',normalized_value=name+'@example.invalid',source_type='OWNED',created_at=now,updated_at=now))
            for name,hid,target in [('old-run','old-hotel','Other hotel'),('keep-run',self.keep,'敖麓谷雅')]:
                s.add(Event(hotel_auto_page_event_id='event-'+name,hotel_id=hid,event_type='REGIONAL_BUILD_CREATED',evidence_json={'run_id':name,'target_name':target},actor='ISOLATED_CI',created_at=now))
        self.queue.enqueue('catalog-test','old-message',{'run_id':'old-run','target_name':'Other hotel'})

    def cleanup_schema(self):
        self.engine.dispose()
        with self.control.begin() as c:
            c.execute(text('DROP SCHEMA '+self.schema+' CASCADE'))

    def release_gates(self):
        for gate in self.gates:gate.set()

    def gate(self):
        entered,release=threading.Event(),threading.Event()
        self.gates.append(release)
        return entered,release

    def wait_entered(self,entered):
        self.assertTrue(entered.wait(5),'transaction scheduling hook was not reached')

    def wait_for_advisory_waiters(self,count):
        # Real lock-table evidence, not merely a thread-start/sleep assumption.
        deadline=time.monotonic()+5
        high,low=scope.LOCK >> 32,scope.LOCK & 0xffffffff
        while time.monotonic()<deadline:
            with self.control.connect() as c:
                waiting=c.scalar(text("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND classid::bigint=:hi AND objid::bigint=:lo AND NOT granted AND database=(SELECT oid FROM pg_database WHERE datname=current_database())"),{'hi':high,'lo':low})
            if waiting>=count:return
            time.sleep(.02)
        self.fail(f'Expected {count} real PostgreSQL advisory-lock waiters')

    def run_activation_paused(self,digest):
        entered,release=self.gate()
        real_plan=scope.plan
        def pause_plan(session):
            result=real_plan(session)
            entered.set()
            if not release.wait(8):raise RuntimeError('TEST_SCHEDULING_TIMEOUT')
            return result
        def activate():
            with patch.object(scope,'plan',pause_plan):
                return scope.activate(digest,'ISOLATED_CI')
        future=self.pool.submit(activate)
        self.wait_entered(entered)
        return future,release

    def test_activation_wins_stale_enqueue_claim_and_protected_writer(self):
        digest=scope.preview()['scope_sha256']
        activation,release=self.run_activation_paused(digest)
        stale=self.pool.submit(self.queue.enqueue,'catalog-test','stale-message',{'run_id':'old-run','target_name':'Other hotel'})
        claim=self.pool.submit(self.queue.claim,'catalog-test')
        writer=self.pool.submit(factory_module.hotel_autopage_factory_service.suppress_contact,'keep-contact','ISOLATED_CI','scope-race-test')
        self.wait_for_advisory_waiters(3)
        release.set()
        self.assertEqual(activation.result(8)['scope_sha256'],digest)
        with self.assertRaisesRegex(ValueError,'CATALOG_RUN_ARCHIVED'):stale.result(8)
        self.assertIsNone(claim.result(8))
        self.assertTrue(writer.result(8)['do_not_contact'])
        with self.session() as s:
            self.assertIsNone(s.get(Queue,'stale-message'))
            self.assertEqual(s.get(Queue,'old-message').status,'QUEUED')
            self.assertEqual(s.get(Queue,'old-message').attempt,0)
            self.assertFalse(s.get(Contact,'old-contact').do_not_contact)
            self.assertEqual(s.scalar(select(func.count()).select_from(Profile)),3)
            self.assertEqual(s.scalar(select(func.count()).select_from(Event).where(Event.event_type=='CONTACT_SUPPRESSED')),1)
            self.assertFalse(scope.visible_hotel(s,'old-hotel'))
        # A protected build remains executable after the same activation.
        self.queue.enqueue('protected-test','protected-message',{'run_id':'keep-run','target_name':'敖麓谷雅'})
        protected=self.queue.claim('protected-test')
        self.assertEqual(protected.message_id,'protected-message')
        self.queue.ack(protected,{'protected_write':'retained'})

    def test_enqueue_wins_invalidates_reviewed_snapshot(self):
        digest=scope.preview()['scope_sha256']
        entered,release=self.gate()
        def on_create(session,message_id):
            entered.set()
            if not release.wait(8):raise RuntimeError('TEST_SCHEDULING_TIMEOUT')
        enqueue=self.pool.submit(self.queue.enqueue,'catalog-test','new-before-reset',{'run_id':'new-run','target_name':'Other hotel'},on_create=on_create)
        self.wait_entered(entered)
        activation=self.pool.submit(scope.activate,digest,'ISOLATED_CI')
        self.wait_for_advisory_waiters(1)
        release.set();self.assertEqual(enqueue.result(8),'new-before-reset')
        with self.assertRaisesRegex(ValueError,'CATALOG_SCOPE_CHANGED_REVIEW_AGAIN'):activation.result(8)
        with self.session() as s:
            self.assertIsNone(scope.state(s))
            self.assertIsNotNone(s.get(Queue,'new-before-reset'))
            self.assertTrue(scope.visible_hotel(s,'old-hotel'))

    def test_claim_wins_and_active_lease_blocks_even_fresh_activation(self):
        digest=scope.preview()['scope_sha256']
        entered,release=self.gate()
        real_state=scope.state
        claim_thread_id=[]
        def paused_state(session):
            result=real_state(session)
            if threading.get_ident() in claim_thread_id:
                entered.set()
                if not release.wait(8):raise RuntimeError('TEST_SCHEDULING_TIMEOUT')
            return result
        def claim_now():
            claim_thread_id.append(threading.get_ident())
            return self.queue.claim('catalog-test')
        with patch.object(scope,'state',paused_state):
            claim_future=self.pool.submit(claim_now)
            self.wait_entered(entered)
            activation=self.pool.submit(scope.activate,digest,'ISOLATED_CI')
            self.wait_for_advisory_waiters(1)
            release.set();claim=claim_future.result(8)
            self.assertEqual(claim.message_id,'old-message')
            with self.assertRaisesRegex(ValueError,'CATALOG_SCOPE_CHANGED_REVIEW_AGAIN'):activation.result(8)
        fresh=scope.preview()
        self.assertEqual(fresh['running_queue_count'],1)
        with self.assertRaisesRegex(ValueError,'CATALOG_ACTIVE_BUILD_MUST_FINISH'):
            scope.activate(fresh['scope_sha256'],'ISOLATED_CI')
        with self.session() as s:self.assertIsNone(scope.state(s))
        self.queue.ack(claim,{'completed_before_reset':True})
        scope.activate(scope.preview()['scope_sha256'],'ISOLATED_CI')
        with self.session() as s:
            self.assertIsNotNone(scope.state(s))
            self.assertEqual(s.get(Queue,'old-message').status,'SUCCEEDED')

    def test_explicit_rollback_restores_queue_and_preserves_audit(self):
        digest=scope.preview()['scope_sha256']
        scope.activate(digest,'ISOLATED_CI')
        self.assertIsNone(self.queue.claim('catalog-test'))
        with self.assertRaisesRegex(ValueError,'CATALOG_SCOPE_RELEASE_REASON_REQUIRED'):
            scope.release(digest,'ISOLATED_CI','')
        with self.assertRaisesRegex(ValueError,'CATALOG_SCOPE_CHANGED_REVIEW_AGAIN'):
            scope.release('0'*64,'ISOLATED_CI','wrong candidate')
        scope.release(digest,'ISOLATED_CI','Reviewed rollback test')
        with self.session() as s:
            self.assertIsNone(scope.state(s))
            self.assertTrue(scope.visible_hotel(s,'old-hotel'))
            self.assertEqual(s.scalar(select(func.count()).select_from(Event).where(Event.event_type.in_(scope.KINDS))),2)
            self.assertEqual(s.scalar(select(func.count()).select_from(Profile)),3)
        claim=self.queue.claim('catalog-test')
        self.assertEqual(claim.message_id,'old-message')
        self.queue.ack(claim,{'rollback_restored':True})
        self.assertEqual(self.queue.status('old-run')['succeeded'],1)


if __name__=='__main__':unittest.main(verbosity=2)
