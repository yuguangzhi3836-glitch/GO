"""Local SQLite regression; run with DATABASE_URL=sqlite+pysqlite:///:memory:."""
import unittest
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, func
from go_hotel.db.session import engine, SessionLocal
from go_hotel.db.models import (Base, TravelEntityRow, TravelEntityAliasRow, TravelEntityFactRow,
    HotelAutoPageEventRow, HotelContentSourceSnapshotRow)
from go_hotel.travel_intelligence.service import travel_intelligence_service as ti
from go_hotel.services.hotel_infrastructure_p0 import hotel_infrastructure_p0_service as infra


class CatalogGraphVisibility(unittest.TestCase):
    def setUp(self):
        if engine.url.get_backend_name() != 'sqlite' or engine.url.database != ':memory:':
            raise RuntimeError('ISOLATED_SQLITE_MEMORY_DATABASE_REQUIRED')
        self.tables=[r.__table__ for r in (TravelEntityRow,TravelEntityAliasRow,TravelEntityFactRow,HotelAutoPageEventRow,HotelContentSourceSnapshotRow)]
        Base.metadata.drop_all(engine,tables=self.tables)
        Base.metadata.create_all(engine,tables=self.tables)
        self.keep=ti.create_entity(entity_type='HOTEL',canonical_name='敖麓谷雅',source_type='GO_HOTEL_CANONICAL',source_entity_id='keep')['go_entity_id']
        self.old=ti.create_entity(entity_type='HOTEL',canonical_name='Old hotel',source_type='GO_HOTEL_CANONICAL',source_entity_id='old')['go_entity_id']
        self.fact(self.keep,'HOTEL_CANONICAL_PROFILE',{'hotel_id':'keep'})
        self.fact(self.old,'HOTEL_CANONICAL_PROFILE',{'hotel_id':'old'})

    def fact(self,eid,kind,value,ref=None):
        return ti.append_entity_fact(entity_id=eid,fact_type=kind,fact_value=value,provenance='GO_CANONICAL',source_id=value.get('hotel_id'),confidence=1,verification_state='OBSERVED',evidence_ref=ref)

    def activate(self):
        with SessionLocal.begin() as s:
            s.add(HotelAutoPageEventRow(hotel_auto_page_event_id='scope-1',hotel_id=None,event_type='CATALOG_SCOPE_ACTIVATED',evidence_json={'protected_ids':['keep'],'retired_job_ids':[],'retired_run_ids':[]},actor='TEST',created_at=datetime.now(timezone.utc)))

    def shared(self):
        with SessionLocal.begin() as s:
            s.add(TravelEntityAliasRow(alias_id=uuid.uuid4(),go_entity_id=uuid.UUID(self.old),source_type='ORDER_SYSTEM',source_entity_id='shared-order-reference',normalized_name='old hotel',created_at=datetime.now(timezone.utc)))

    def test_catalog_only_hidden_without_deleting_audit_or_shared_rows(self):
        self.activate()
        with self.assertRaisesRegex(ValueError,'TRAVEL_ENTITY_NOT_FOUND'):ti.get_entity(self.old)
        with self.assertRaisesRegex(ValueError,'TRAVEL_ENTITY_ALIAS_NOT_FOUND'):ti.resolve_entity(source_type='GO_HOTEL_CANONICAL',source_entity_id='old')
        with self.assertRaisesRegex(ValueError,'TRAVEL_ENTITY_NOT_FOUND'):ti.entity_evidence(self.old)
        self.assertEqual(ti.get_entity(self.keep)['canonical_name'],'敖麓谷雅')
        self.assertEqual(len(ti.entity_evidence(self.keep)),1)
        with SessionLocal() as s:
            self.assertEqual(s.scalar(select(func.count()).select_from(TravelEntityRow)),2)
            self.assertEqual(s.scalar(select(func.count()).select_from(TravelEntityFactRow)),2)
            self.assertEqual(s.scalar(select(func.count()).select_from(TravelEntityAliasRow)),2)

    def test_shared_entity_keeps_order_alias_but_hides_catalog_fact(self):
        self.shared();self.fact(self.old,'ORDER_REFERENCE',{'order_id':'retained'})
        self.activate()
        row=ti.get_entity(self.old)
        self.assertEqual(row['aliases'],[{'source_type':'ORDER_SYSTEM','source_entity_id':'shared-order-reference'}])
        self.assertEqual(ti.resolve_entity(source_type='ORDER_SYSTEM',source_entity_id='shared-order-reference')['go_entity_id'],self.old)
        self.assertEqual([r['fact_type'] for r in ti.entity_evidence(self.old)],['ORDER_REFERENCE'])

    def test_snapshot_facts_require_visible_canonical_binding(self):
        self.shared()
        t=datetime.now(timezone.utc)
        with SessionLocal.begin() as s:
            for hid in ['old','keep']:
                s.add(HotelContentSourceSnapshotRow(content_source_snapshot_id='snap-'+hid,source_key='source-'+hid,source_type='OFFICIAL',external_hotel_id=hid,rights_status='OWNED',payload_json={},payload_hash='hash-'+hid,canonical_hotel_id=hid,observed_at=t,created_at=t))
        self.fact(self.old,'HOTEL_SOURCE_SNAPSHOT',{},'snap-old')
        self.fact(self.old,'HOTEL_SOURCE_SNAPSHOT',{},'missing-snapshot')
        self.fact(self.keep,'HOTEL_SOURCE_SNAPSHOT',{},'snap-keep')
        self.activate()
        self.assertEqual(ti.entity_evidence(self.old),[])
        self.assertEqual(len(ti.entity_evidence(self.keep)),2)

    def test_reprojection_and_writes_cannot_restore_archived_catalog(self):
        self.activate()
        with self.assertRaisesRegex(ValueError,'CATALOG_RECORD_ARCHIVED'):
            ti.create_entity(entity_type='HOTEL',canonical_name='new',source_type='GO_HOTEL_CANONICAL',source_entity_id='new')
        with self.assertRaisesRegex(ValueError,'CATALOG_RECORD_ARCHIVED'):
            ti.upsert_entity_alias(entity_type='HOTEL',canonical_name='old',source_type='GO_HOTEL_CANONICAL',source_entity_id='old')
        with self.assertRaisesRegex(ValueError,'CATALOG_RECORD_ARCHIVED'):self.fact(self.old,'HOTEL_CANONICAL_PROFILE',{'hotel_id':'old'})
        with self.assertRaisesRegex(ValueError,'CATALOG_RECORD_ARCHIVED'):infra.project_to_travel_graph('old')
        with self.assertRaisesRegex(ValueError,'CATALOG_RECORD_ARCHIVED'):infra.completeness_gate('old',tier=5)
        self.assertTrue(ti.upsert_entity_alias(entity_type='HOTEL',canonical_name='keep',source_type='GO_HOTEL_CANONICAL',source_entity_id='keep')['idempotent'])

    def test_visible_evidence_after_archived_first_page_is_not_lost(self):
        self.shared()
        self.fact(self.old,'ORDER_REFERENCE',{'order_id':'older-retained'})
        for i in range(55):
            self.fact(self.old,'HOTEL_CANONICAL_PROFILE',{'hotel_id':'old','revision':i})
        self.activate()
        rows=ti.entity_evidence(self.old,limit=1)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['value'],{'order_id':'older-retained'})

    def test_legacy_destructive_reset_cannot_bypass_scope(self):
        import os
        from unittest.mock import patch
        self.activate()
        with patch.dict(os.environ,{'APP_ENV':'staging'}):
            with self.assertRaisesRegex(ValueError,'CATALOG_SCOPE_RESET_REQUIRED'):
                infra.reset_execute(confirmation='DELETE_HARBIN_HOTEL_INFRASTRUCTURE',actor='TEST')

if __name__=='__main__':unittest.main(verbosity=2)
