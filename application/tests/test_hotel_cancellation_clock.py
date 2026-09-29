"""Exact deadlines and persisted confirmation evidence; isolated SQLite only."""
import os
os.environ.setdefault('DATABASE_URL','sqlite+pysqlite:///:memory:')
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from go_hotel.services import hotel_cancellation_clock as clock
from go_hotel.services import hosted_fare_rules as hosted
from go_hotel.services import catalog_fare_snapshot as catalog
from go_hotel.db.models import Base, HostedDirectReservationEventRow as HostedEvent
from go_hotel.db.models import OrderSupplierFulfillmentRow as Fulfillment, OrderSupplierFulfillmentEventRow as Event


def moment(value):return datetime.fromisoformat(value)


def rules():
    return {'fare_family':'EXPLICIT_TEST','timezone':'Asia/Shanghai','check_in_hour':14,
        'cooling_off_minutes':30,'cancellation_tiers':[{'min_hours':24,'fee_basis_points':0},{'min_hours':0,'fee_basis_points':10000}],
        'change_allowed':True,'change_fee_minor':0,'stay_credit_enabled':False,'stay_credit_days':365,
        'stay_credit_scope':'PROPERTY_ONLY','no_show_grace_hours':0,'no_show_fee_basis_points':10000}


class CancellationClockTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite+pysqlite:///:memory:')
        Base.metadata.create_all(self.engine,tables=[m.__table__ for m in (HostedEvent,Fulfillment,Event)])
        self.sessions=sessionmaker(self.engine,expire_on_commit=False)
        self.addCleanup(self.engine.dispose)
        self.created=moment('2026-09-19T10:00:00+08:00')
        self.confirmed=self.created+timedelta(hours=1)
        self.reservation=SimpleNamespace(hosted_reservation_id='r',check_in='2026-09-20',created_at=self.created)
        self.order=SimpleNamespace(order_id='o',supplier_id='supplier')
    def hosted_terms(self, policy, at):
        with self.sessions() as s:return hosted.cancellation_terms_in_session(s,self.reservation,policy,at)
    def insert_hosted_event(self, at, kind='HOTEL_CONFIRM', rid='r', eid='event'):
        with self.sessions.begin() as s:
            s.add(HostedEvent(hosted_event_id=eid,hosted_reservation_id=rid,event_type=kind,
                actor_id='hotel',payload_json={'payment_captured':False},occurred_at=at.astimezone(timezone.utc)))
    def insert_catalog_event(self,at,supplier='supplier',state='SUPPLIER_CONFIRMED'):
        with self.sessions.begin() as s:
            s.add(Fulfillment(order_supplier_fulfillment_id='f',payment_intent_id='payment',business_type='HOTEL_ORDER',
                business_id='o',supplier_id=supplier,supplier_idempotency_key='key',state=state,
                evidence_reference='hotel-evidence',created_at=self.created.astimezone(timezone.utc),updated_at=at.astimezone(timezone.utc)))
            s.add(Event(order_supplier_fulfillment_event_id='event',order_supplier_fulfillment_id='f',
                event_type='SUPPLIER_FACT_RECORDED',state=state,evidence_reference='hotel-evidence',payload_hash='a'*64,occurred_at=at.astimezone(timezone.utc)))
    def catalog_terms(self,policy,at):
        with patch.object(catalog,'SessionLocal',self.sessions):
            return catalog.cancellation_terms(self.order,'2026-09-20',{'rules':policy,'order_created_at':self.created.isoformat()},at)
    def test_legacy_validation_preserves_exact_content_and_no_anchor(self):
        original=rules();before=deepcopy(original)
        self.assertEqual(hosted.validated(original),before)
        self.assertNotIn('cooling_off_anchor',hosted.validated(original))
        self.assertEqual(original,before)
    def test_invalid_anchor_types_fail_validation(self):
        for anchor in (None, [], {}, True, 'CONFIRMED'):
            policy=rules();policy['cooling_off_anchor']=anchor
            with self.assertRaisesRegex(ValueError,'INVALID_COOLING_OFF_ANCHOR'):
                hosted.validated(policy)
    def test_legacy_created_anchor_not_changed_by_later_confirmation(self):
        self.insert_hosted_event(self.confirmed)
        policy=rules();policy['cancellation_tiers']=[{'min_hours':0,'fee_basis_points':10000}]
        self.assertEqual(self.hosted_terms(policy,self.created+timedelta(minutes=29))['fee_basis_points'],0)
        self.assertEqual(self.hosted_terms(policy,self.created+timedelta(minutes=30))['fee_basis_points'],10000)
    def test_confirmed_anchor_29_30_31_minutes(self):
        self.insert_hosted_event(self.confirmed)
        policy=rules();policy['cooling_off_anchor']='HOTEL_CONFIRMED';policy['cancellation_tiers']=[{'min_hours':0,'fee_basis_points':10000}]
        for minutes,fee in [(29,0),(30,10000),(31,10000)]:
            self.assertEqual(self.hosted_terms(policy,self.confirmed+timedelta(minutes=minutes))['fee_basis_points'],fee)
    def test_missing_confirmation_never_falls_back(self):
        policy=rules();policy['cooling_off_anchor']='HOTEL_CONFIRMED'
        with self.assertRaisesRegex(ValueError,'TIME_EVIDENCE_REQUIRED'):
            self.hosted_terms(policy,self.confirmed)
    def test_unrelated_and_nonconfirmation_events_do_not_count(self):
        self.insert_hosted_event(self.confirmed,kind='HOTEL_REJECT')
        self.insert_hosted_event(self.confirmed,rid='other',eid='other')
        policy=rules();policy['cooling_off_anchor']='HOTEL_CONFIRMED'
        with self.assertRaisesRegex(ValueError,'TIME_EVIDENCE_REQUIRED'):self.hosted_terms(policy,self.confirmed)
    def test_repeated_confirmation_does_not_extend_window(self):
        self.insert_hosted_event(self.confirmed)
        self.insert_hosted_event(self.confirmed+timedelta(minutes=20),eid='later')
        policy=rules();policy['cooling_off_anchor']='HOTEL_CONFIRMED';policy['cancellation_tiers']=[{'min_hours':0,'fee_basis_points':10000}]
        self.assertEqual(self.hosted_terms(policy,self.confirmed+timedelta(minutes=31))['fee_basis_points'],10000)
    def test_confirmation_before_creation_is_rejected(self):
        self.insert_hosted_event(self.created-timedelta(minutes=1))
        policy=rules();policy['cooling_off_anchor']='HOTEL_CONFIRMED'
        with self.assertRaisesRegex(ValueError,'INVALID_HOTEL_CONFIRMATION_TIME'):self.hosted_terms(policy,self.confirmed)
    def test_confirmation_in_future_is_rejected(self):
        self.insert_hosted_event(self.confirmed+timedelta(hours=1))
        policy=rules();policy['cooling_off_anchor']='HOTEL_CONFIRMED'
        with self.assertRaisesRegex(ValueError,'INVALID_HOTEL_CONFIRMATION_TIME'):self.hosted_terms(policy,self.confirmed)
    def exact_policy(self):
        policy=rules();policy['cooling_off_minutes']=0
        policy['cancellation_tiers']=[{'days_before_check_in':1,'local_time':'23:59','fee_basis_points':0},
            {'days_before_check_in':0,'local_time':'12:00','fee_basis_points':5000},
            {'after_last_deadline':True,'fee_basis_points':10000}]
        return hosted.validated(policy)
    def test_exact_local_deadline_second_boundary(self):
        policy=self.exact_policy()
        for value,fee in [('2026-09-19T23:58:59+08:00',0),('2026-09-19T23:59:00+08:00',5000),
            ('2026-09-20T00:00:00+08:00',5000),('2026-09-20T12:00:00+08:00',10000)]:
            self.assertEqual(self.hosted_terms(policy,moment(value))['fee_basis_points'],fee)
    def test_exact_cutoff_quote_expiry_is_not_ten_minutes_late(self):
        result=self.catalog_terms(self.exact_policy(),moment('2026-09-19T23:58:59+08:00'))
        self.assertEqual(result['expires_at'],moment('2026-09-19T23:59:00+08:00'))
    def test_original_wider_rule_stays_free_after_grace(self):
        self.insert_hosted_event(self.confirmed)
        policy=self.exact_policy();policy['cooling_off_minutes']=30;policy['cooling_off_anchor']='HOTEL_CONFIRMED'
        self.assertEqual(self.hosted_terms(policy,self.confirmed+timedelta(minutes=31))['fee_basis_points'],0)
    def test_dst_gap_and_overlap_rejected(self):
        for day,local in [('2026-03-08','02:30'),('2026-11-01','01:30')]:
            with self.assertRaisesRegex(ValueError,'AMBIGUOUS_OR_NONEXISTENT'):
                clock.local_deadline(day,{'days_before_check_in':0,'local_time':local},'America/New_York')
    def test_valid_dst_day_uses_actual_offset(self):
        result=clock.local_deadline('2026-03-09',{'days_before_check_in':1,'local_time':'03:30'},'America/New_York')
        self.assertEqual(result,moment('2026-03-08T07:30:00+00:00'))
    def test_bad_or_mixed_deadlines_rejected(self):
        for tiers in [[{'days_before_check_in':1,'local_time':'24:00','fee_basis_points':0},{'after_last_deadline':True,'fee_basis_points':10000}],
            [{'min_hours':24,'fee_basis_points':0},{'after_last_deadline':True,'fee_basis_points':10000}],
            [{'days_before_check_in':0,'local_time':'12:00','fee_basis_points':0},{'days_before_check_in':1,'local_time':'23:59','fee_basis_points':5000},{'after_last_deadline':True,'fee_basis_points':10000}]]:
            with self.assertRaises(ValueError):clock.validate_tiers(tiers)
    def test_catalog_uses_persisted_supplier_confirmation(self):
        self.insert_catalog_event(self.confirmed)
        policy=rules();policy['cooling_off_anchor']='HOTEL_CONFIRMED';policy['cancellation_tiers']=[{'min_hours':0,'fee_basis_points':10000}]
        self.assertEqual(self.catalog_terms(policy,self.confirmed+timedelta(minutes=29))['fee_basis_points'],0)
        self.assertEqual(self.catalog_terms(policy,self.confirmed+timedelta(minutes=31))['fee_basis_points'],10000)
    def test_catalog_missing_evidence_is_rejected(self):
        policy=rules();policy['cooling_off_anchor']='HOTEL_CONFIRMED'
        with self.assertRaisesRegex(ValueError,'TIME_EVIDENCE_REQUIRED'):self.catalog_terms(policy,self.confirmed)
    def test_catalog_other_supplier_evidence_rejected(self):
        self.insert_catalog_event(self.confirmed,supplier='different')
        policy=rules();policy['cooling_off_anchor']='HOTEL_CONFIRMED'
        with self.assertRaisesRegex(ValueError,'TIME_EVIDENCE_REQUIRED'):self.catalog_terms(policy,self.confirmed)


if __name__=='__main__':unittest.main()
