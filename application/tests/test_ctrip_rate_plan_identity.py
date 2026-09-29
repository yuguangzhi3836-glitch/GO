"""Real SQLite persistence regression for official rate identity; no network."""
import os
os.environ.setdefault('DATABASE_URL', 'sqlite+pysqlite:///:memory:')

import unittest
from unittest.mock import patch
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from go_hotel.services import aoluguya_supply_truth as service_module
from go_hotel.db.models import (
    Base, HostedDirectHotelRow as Hotel, HostedDirectInventoryPoolRow as Pool,
    HostedDirectRoomOfferRow as Offer, HostedDirectRateVariantRow as Variant,
    ProductionConnectorRow as Connector, ConnectorCapabilityMatrixRow as Matrix,
)


class RateIdentityTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite+pysqlite:///:memory:')
        Base.metadata.create_all(self.engine,tables=[x.__table__ for x in (Hotel,Pool,Offer,Variant,Connector,Matrix)])
        self.sessions=sessionmaker(self.engine,expire_on_commit=False)
        self.patch=patch.object(service_module,'SessionLocal',self.sessions)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.engine.dispose)
        self.service=service_module.AoluguyaSupplyTruthService()
        with self.sessions.begin() as s:
            s.add(Hotel(hosted_hotel_id='hotel',supplier_name=service_module.AOLUGUYA_SUPPLIER,
                page_slug=service_module.AOLUGUYA_SLUG,city='哈尔滨',contact_json={},state='DRAFT',updated_at=service_module.now()))
            s.add(Pool(inventory_pool_id='pool',hosted_hotel_id='hotel',physical_room_key='room',
                physical_room_name='old',room_details_json={},capacity_total=5,capacity_available=5,updated_at=service_module.now()))
            for i in range(2):
                s.add(Offer(hosted_offer_id=f'o{i}',hosted_hotel_id='hotel',room_name='old',rate_name=f'old{i}',
                    price_minor=100+i,currency='CNY',inventory=5,cancellation_policy='old policy',state='ACTIVE',updated_at=service_module.now()))
                s.add(Variant(rate_variant_id=f'v{i}',inventory_pool_id='pool',hosted_offer_id=f'o{i}',
                    breakfast_count=2,benefits_json=[],payment_mode='PREPAY',state='ACTIVE'))
    def body(self, keys):
        return {'source_type':'HOTEL_OFFICIAL_SUPPLIER_CONSOLE','evidence_reference':'hotel-submission',
            'source_updated_at':service_module.now().isoformat(),'supplier_legal_name':service_module.AOLUGUYA_SUPPLIER,
            'property_key':service_module.AOLUGUYA_SLUG,'rooms':[{'room_key':'room','room_name':'Room','inventory':4,
                'rates':[{'rate_plan_key':key,'breakfast_count':2,'rate_name':f'rate{i}',
                    'price_minor':1000+i*500,'currency':'CNY','cancellation_policy':f'policy{i}',
                    'breakfast':{'count':2},'taxes_fees':{'included_in_total':True},'sell_state':'OPEN'} for i,key in enumerate(keys)]}]}
    def ingest(self, keys): return self.service.ingest_official_truth(self.body(keys),'owner')
    def test_ingest_same_breakfast_distinct_plans(self):
        result=self.ingest(['flex','prepaid'])
        self.assertEqual(result['state'],'HOTEL_OFFICIAL_TRUTH_RECEIVED')
        self.assertEqual(self.service.evaluate()['state'],'PASS')
    def test_duplicate_plan_key_rejected(self):
        with self.assertRaisesRegex(ValueError,'UNIQUE_RATE_PLAN'):
            self.ingest(['same','same'])
    def test_negative_breakfast_rejected(self):
        body=self.body(['flex']);body['rooms'][0]['rates'][0]['breakfast_count']=-1
        with self.assertRaises(ValueError): self.service.ingest_official_truth(body,'owner')
    def test_projection_keeps_distinct_prices_and_policy(self):
        self.ingest(['room:offer:o0','room:offer:o1'])
        result=self.service.project_to_hosted_direct('owner')
        self.assertEqual(result['active_offers'],2)
        with self.sessions() as s:
            self.assertEqual([s.get(Offer,f'o{i}').price_minor for i in range(2)],[1000,1500])
            self.assertEqual([s.get(Offer,f'o{i}').cancellation_policy for i in range(2)],['policy0','policy1'])
            self.assertEqual(len(s.get(Hotel,'hotel').contact_json['official_rate_map']),2)
            matrix=s.scalar(select(Matrix).order_by(Matrix.version_no.desc()))
            backup=matrix.capabilities_json['aoluguya_cutover_backup']
            self.assertEqual(backup['offers']['o0']['price_minor'],100)
            self.assertEqual(backup['pools']['pool']['capacity_total'],5)
        self.service.rollback_cutover('owner')
        with self.sessions() as s:
            self.assertEqual(s.get(Offer,'o0').price_minor,100)
            self.assertEqual(s.get(Pool,'pool').capacity_total,5)
    def test_reprojection_uses_rate_keys_after_reordering(self):
        self.ingest(['room:offer:o0','room:offer:o1']);self.service.project_to_hosted_direct('owner')
        self.ingest(['room:offer:o1','room:offer:o0']);self.service.project_to_hosted_direct('owner')
        with self.sessions() as s:
            self.assertEqual(s.get(Offer,'o1').price_minor,1000)
            self.assertEqual(s.get(Offer,'o0').price_minor,1500)
    def test_closed_variant_returns_to_active_on_rollback(self):
        body=self.body(['room:offer:o0','room:offer:o1'])
        body['rooms'][0]['rates'][0]['sell_state']='CLOSED'
        self.service.ingest_official_truth(body,'owner')
        self.service.project_to_hosted_direct('owner')
        with self.sessions() as s:
            self.assertEqual(s.get(Variant,'v0').state,'INACTIVE')
            self.assertEqual(s.get(Offer,'o0').state,'INACTIVE')
        result=self.service.rollback_cutover('owner')
        self.assertTrue(result['variant_states_restored'])
        with self.sessions() as s:
            self.assertEqual(s.get(Variant,'v0').state,'ACTIVE')
            self.assertEqual(s.get(Offer,'o0').state,'ACTIVE')
    def test_legacy_backup_reports_variant_restoration_gap(self):
        self.ingest(['room:offer:o0','room:offer:o1'])
        self.service.project_to_hosted_direct('owner')
        with self.sessions.begin() as s:
            matrix=s.scalar(select(Matrix).order_by(Matrix.version_no.desc()))
            caps=dict(matrix.capabilities_json)
            backup=dict(caps['aoluguya_cutover_backup']);backup.pop('variants')
            backup['schema']='go.aoluguya-cutover-backup.v1'
            caps['aoluguya_cutover_backup']=backup;matrix.capabilities_json=caps
        result=self.service.rollback_cutover('owner')
        self.assertEqual(result['state'],'AOLUGUYA_CUTOVER_PARTIALLY_ROLLED_BACK')
        self.assertFalse(result['variant_states_restored'])
        self.assertEqual(result['limitations'],['LEGACY_BACKUP_VARIANT_STATE_UNAVAILABLE'])
    def test_ambiguous_mapping_rolls_back_without_changes(self):
        self.ingest(['flex','prepaid'])
        with self.assertRaisesRegex(ValueError,'AMBIGUOUS'):
            self.service.project_to_hosted_direct('owner')
        with self.sessions() as s:
            self.assertEqual(s.get(Pool,'pool').capacity_total,5)
            self.assertEqual(s.get(Offer,'o0').price_minor,100)
            self.assertEqual(s.get(Hotel,'hotel').state,'DRAFT')
    def test_existing_external_keys_are_preserved(self):
        with self.sessions.begin() as s:
            s.get(Hotel,'hotel').contact_json={'official_rate_map':{
                'o0':{'room_key':'room','rate_plan_key':'flex'},'o1':{'room_key':'room','rate_plan_key':'prepaid'}}}
        self.ingest(['prepaid','flex']);self.service.project_to_hosted_direct('owner')
        with self.sessions() as s:
            self.assertEqual(s.get(Offer,'o1').price_minor,1000)
            self.assertEqual(s.get(Offer,'o0').price_minor,1500)
    def test_partial_snapshot_keeps_identity_and_original_can_resume(self):
        with self.sessions.begin() as s:
            s.get(Hotel,'hotel').contact_json={'official_rate_map':{
                'o0':{'room_key':'room','rate_plan_key':'flex'},'o1':{'room_key':'room','rate_plan_key':'prepaid'}}}
        self.ingest(['flex']);self.service.project_to_hosted_direct('owner')
        with self.sessions() as s:
            binding=s.get(Hotel,'hotel').contact_json['official_rate_map']['o1']
            self.assertEqual(binding['rate_plan_key'],'prepaid')
            self.assertEqual(binding['projection_state'],'INACTIVE')
            self.assertEqual(s.get(Variant,'v1').state,'INACTIVE')
        self.ingest(['flex','new-plan'])
        with self.assertRaisesRegex(ValueError,'AMBIGUOUS'):
            self.service.project_to_hosted_direct('owner')
        with self.sessions() as s:
            self.assertEqual(s.get(Hotel,'hotel').contact_json['official_rate_map']['o1']['rate_plan_key'],'prepaid')
            self.assertEqual(s.get(Offer,'o1').state,'INACTIVE')
        self.ingest(['flex','prepaid']);self.service.project_to_hosted_direct('owner')
        with self.sessions() as s:
            self.assertEqual(s.get(Offer,'o1').state,'ACTIVE')
            self.assertEqual(s.get(Variant,'v1').state,'ACTIVE')
            self.assertEqual(s.get(Offer,'o1').price_minor,1500)
    def test_legacy_single_breakfast_variant_still_projects(self):
        with self.sessions.begin() as s: s.get(Variant,'v1').breakfast_count=0
        self.ingest(['legacy']);self.service.project_to_hosted_direct('owner')
        with self.sessions() as s:
            self.assertEqual(s.get(Offer,'o0').price_minor,1000)
            self.assertEqual(s.get(Offer,'o1').state,'INACTIVE')
    def test_bound_rate_cannot_be_rebound_by_breakfast(self):
        with self.sessions.begin() as s:
            s.get(Variant,'v1').breakfast_count=0
            s.get(Hotel,'hotel').contact_json={'official_rate_map':{'o0':{'room_key':'room','rate_plan_key':'existing'}}}
        self.ingest(['replacement'])
        with self.assertRaises(ValueError):self.service.project_to_hosted_direct('owner')
    def test_duplicate_bound_keys_fail_closed(self):
        with self.sessions.begin() as s:
            s.get(Hotel,'hotel').contact_json={'official_rate_map':{
                f'o{i}':{'room_key':'room','rate_plan_key':'same'} for i in range(2)}}
        self.ingest(['same'])
        with self.assertRaisesRegex(ValueError,'DUPLICATE_HOSTED'):
            self.service.project_to_hosted_direct('owner')
    def test_template_duplicate_breakfast_has_stable_unique_keys(self):
        with self.sessions.begin() as s:
            for i, count in enumerate([2,2,2,1],start=1):
                s.add(Pool(inventory_pool_id=f'pool{i}',hosted_hotel_id='hotel',physical_room_key=f'room{i}',
                    physical_room_name=f'Room{i}',room_details_json={},capacity_total=5,capacity_available=5,updated_at=service_module.now()))
                for j in range(count):
                    s.add(Variant(rate_variant_id=f'v{i}_{j}',inventory_pool_id=f'pool{i}',hosted_offer_id=f'o{i}_{j}',
                        breakfast_count=j,benefits_json=[],payment_mode='PREPAY',state='ACTIVE'))
        template=self.service.official_snapshot_template()
        keys=[rate['rate_plan_key'] for room in template['rooms'] for rate in room['rates']]
        self.assertEqual(len(keys),9)
        self.assertEqual(len(set(keys)),9)
        self.assertIn('room:offer:o0',keys)
        self.assertIn('room:offer:o1',keys)
        self.assertEqual(template,self.service.official_snapshot_template())


if __name__=='__main__':unittest.main()
