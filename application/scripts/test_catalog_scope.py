import unittest
from datetime import datetime, timezone
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from go_hotel.services import catalog_scope as scope
from go_hotel.db.models import HotelCanonicalProfileRow as Profile, HotelAutoPageEventRow as Event, RegionalQueueRow as Queue
from go_hotel.queue.durable_regional import DurableRegionalQueue

class CatalogScopeTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://')
        for table in (Profile.__table__, Event.__table__, Queue.__table__): table.create(self.engine)
        self.sessions=sessionmaker(bind=self.engine,expire_on_commit=False)
        self.old=scope.SessionLocal;scope.SessionLocal=self.sessions
        self.q=DurableRegionalQueue(self.sessions)
        now=datetime.now(timezone.utc)
        with self.sessions.begin() as s:
            for i,hid in enumerate(sorted(scope.PROTECTED_IDS)+['hotel_other']):
                s.add(Profile(hotel_id=hid,slug='s'+str(i),canonical_json={'name':'敖麓谷雅' if hid in scope.PROTECTED_IDS else '其他酒店'},field_provenance_json={},source_snapshot_ids_json=[],completeness_bps=0,go_direct_state='NOT_REGISTERED',page_state='DRAFT',version=1,created_at=now,updated_at=now))
            for eid,kind,data,hid in [('e1','DISCOVERY_JOB_CREATED',{'job_id':'old','seed':{'name':'其他酒店'}},None),('e2','DISCOVERY_JOB_CREATED',{'job_id':'keep','seed':{'name':'敖麓谷雅'}},None),('e3','REGIONAL_BUILD_CREATED',{'run_id':'oldrun','target_name':None},None)]:
                s.add(Event(hotel_auto_page_event_id=eid,hotel_id=hid,event_type=kind,evidence_json=data,actor='test',created_at=now))
        self.q.enqueue('hotel-regional-build','old-message',{'run_id':'oldrun','target_name':None})
    def tearDown(self):
        scope.SessionLocal=self.old;self.engine.dispose()
    def activate(self):
        plan=scope.preview();return scope.activate(plan['scope_sha256'],'test')
    def test_preserves_rows_hides_unprotected_and_fences_queue(self):
        result=self.activate()
        self.assertEqual(result['archived_ids'],['hotel_other'])
        self.assertFalse(result['physical_deletion'])
        with self.sessions() as s:
            self.assertEqual(len(s.scalars(select(Profile)).all()),3)
            self.assertFalse(scope.visible_hotel(s,'hotel_other'))
            self.assertTrue(all(scope.visible_hotel(s,x) for x in scope.PROTECTED_IDS))
            visible=scope.visible_events(s,s.scalars(select(Event)).all())
            self.assertNotIn('e1',{e.hotel_auto_page_event_id for e in visible})
            self.assertIn('e2',{e.hotel_auto_page_event_id for e in visible})
            self.assertEqual(s.get(Queue,'old-message').status,'QUEUED')
        self.assertIsNone(self.q.claim('hotel-regional-build'))
        with self.assertRaisesRegex(ValueError,'CATALOG_RUN_ARCHIVED'):
            self.q.enqueue('hotel-regional-build','replay',{'run_id':'oldrun','target_name':'敖麓谷雅'})
        self.q.enqueue('hotel-regional-build','golden',{'run_id':'newrun','target_name':'敖麓谷雅'})
        self.assertEqual(self.q.claim('hotel-regional-build').message_id,'golden')
    def test_fingerprint_drift_rejected_and_no_scope_written(self):
        plan=scope.preview()
        with self.sessions.begin() as s:s.get(Profile,'hotel_other').version+=1
        with self.assertRaisesRegex(ValueError,'SCOPE_CHANGED'):scope.activate(plan['scope_sha256'],'test')
        with self.sessions() as s:self.assertIsNone(scope.state(s))
    def test_active_claim_blocks_activation(self):
        self.q.claim('hotel-regional-build')
        with self.assertRaisesRegex(ValueError,'ACTIVE_BUILD'):self.activate()
    def test_protected_missing_blocks(self):
        with self.sessions.begin() as s:s.delete(s.get(Profile,sorted(scope.PROTECTED_IDS)[0]))
        with self.assertRaisesRegex(ValueError,'PROTECTED_IDENTITY_MISSING'):scope.preview()
    def test_release_restores_visibility_without_deleting_audit(self):
        result=self.activate()
        scope.release(result['scope_sha256'],'test','reviewed rollback')
        with self.sessions() as s:
            self.assertIsNone(scope.state(s))
            self.assertTrue(scope.visible_hotel(s,'hotel_other'))
            self.assertEqual(len(s.scalars(select(Event).where(Event.event_type.in_(scope.KINDS))).all()),2)
        self.assertEqual(self.q.claim('hotel-regional-build').message_id,'old-message')
    def test_factory_and_discovery_direct_reads_are_hidden(self):
        from go_hotel.services import hotel_autopage_factory as factory
        from go_hotel.services import hotel_discovery_orchestrator as discovery
        from unittest.mock import patch
        self.activate()
        with patch.object(factory,'SessionLocal',self.sessions), patch.object(discovery,'SessionLocal',self.sessions):
            for method,arg in [(factory.hotel_autopage_factory_service.factory_detail,'hotel_other'),(factory.hotel_autopage_factory_service.public_page,'s2'),(factory.hotel_autopage_factory_service.contact_graph,'hotel_other')]:
                with self.assertRaisesRegex(ValueError,'CATALOG_RECORD_ARCHIVED'):method(arg)
            seeds=discovery.hotel_discovery_orchestrator_service.list_seeds()
            self.assertEqual(seeds,[])
            with self.assertRaisesRegex(ValueError,'CATALOG_JOB_ARCHIVED'):
                discovery.hotel_discovery_orchestrator_service.run_job('old')
    def test_archived_media_routes_and_retry_have_no_side_effects(self):
        from go_hotel.api.routes import hotel_autopage_factory as routes
        from go_hotel.db import session as db_session
        from go_hotel.services import hotel_discovery_orchestrator as discovery
        from unittest.mock import patch, Mock
        from fastapi import HTTPException
        self.activate()
        with patch.object(db_session,'SessionLocal',self.sessions), patch.object(discovery,'SessionLocal',self.sessions):
            with patch.object(routes.media_svc,'get',return_value={'hotel_id':'hotel_other'}), patch.object(routes.media_svc,'content_path') as content:
                with self.assertRaises(HTTPException) as error:routes.media_admin_content('old-asset',None)
                self.assertEqual(error.exception.status_code,404)
                content.assert_not_called()
            mutate=Mock()
            with self.assertRaisesRegex(ValueError,'CATALOG_RECORD_ARCHIVED'):routes.scoped_media(['hotel_other'],mutate)
            mutate.assert_not_called()
            with self.sessions() as s:before=len(s.scalars(select(Event)).all())
            with self.assertRaisesRegex(ValueError,'CATALOG_JOB_ARCHIVED'):discovery.hotel_discovery_orchestrator_service.retry_job('old')
            with self.sessions() as s:self.assertEqual(len(s.scalars(select(Event)).all()),before)
    def test_old_contact_and_registration_ids_cannot_write(self):
        from go_hotel.db.models import HotelContactPointRow as Contact, HotelRegistrationDirectRow as Registration
        from go_hotel.services import hotel_autopage_factory as factory
        from unittest.mock import patch
        for table in (Contact.__table__,Registration.__table__):table.create(self.engine)
        now=datetime.now(timezone.utc)
        with self.sessions.begin() as s:
            s.add(Contact(hotel_contact_point_id='contact',hotel_id='hotel_other',contact_type='GENERAL',channel='PHONE',value='123',normalized_value='123',source_type='PUBLIC_SOURCE',created_at=now,updated_at=now))
            s.add(Registration(hotel_registration_direct_id='registration',hotel_id='hotel_other',supplier_id='supplier',state='SUBMITTED',requested_by='user',created_at=now))
        self.activate()
        with patch.object(factory,'SessionLocal',self.sessions):
            for method,args in [(factory.hotel_autopage_factory_service.suppress_contact,('contact','test')),(factory.hotel_autopage_factory_service.decide_registration_direct,('registration','test',{'decision':'APPROVE'})),(factory.hotel_autopage_factory_service.register_for_go_direct,('hotel_other','supplier','test',{}))]:
                with self.assertRaisesRegex(ValueError,'CATALOG_RECORD_ARCHIVED'):method(*args)
        with self.sessions() as s:
            self.assertFalse(s.get(Contact,'contact').do_not_contact)
            self.assertEqual(s.get(Registration,'registration').state,'SUBMITTED')
    def test_archived_rows_do_not_displace_retained_seed_before_limit(self):
        from go_hotel.services import hotel_discovery_orchestrator as discovery
        from unittest.mock import patch
        with self.sessions.begin() as s:
            for eid,jid,year in [('seed-keep','keep',2020),('seed-old','old',2026)]:
                s.add(Event(hotel_auto_page_event_id=eid,hotel_id=None,event_type='DISCOVERY_SEED_REGISTERED',evidence_json={'job_id':jid},actor='test',created_at=datetime(year,1,1,tzinfo=timezone.utc)))
        self.activate()
        with patch.object(discovery,'SessionLocal',self.sessions):
            rows=discovery.hotel_discovery_orchestrator_service.list_seeds(1)
        self.assertEqual([r['job_id'] for r in rows],['keep'])
    def test_idempotence_and_admission(self):
        result=self.activate()
        self.assertTrue(scope.activate(result['scope_sha256'],'test')['idempotent'])
        with self.sessions() as s:
            for fn,arg in [(scope.require_job,'old'),(scope.require_hotel,'new')]:
                with self.assertRaises(ValueError):fn(s,arg)
            with self.assertRaises(ValueError):scope.require_seed(s,{'name':'Other'})
            scope.require_seed(s,{'name':'哈尔滨敖麓谷雅酒店'})
            scope.require_job(s,'keep')

if __name__=='__main__':unittest.main()
