"""Server waiting policy, exact-flight matching, and actual disk-backed fleet recovery."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import multiprocessing
import os
import signal
import sqlite3

import pytest
from sqlalchemy import select, func, create_engine
from sqlalchemy.orm import sessionmaker
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (MobilityRideOrderRow as Ride, RideFlightAdjustmentRow as Adjustment,
    RideFlightBindingV2Row as Binding, RideServicePolicyRow as Policy)
from go_hotel.mobility.ride.service import ride_service
from go_hotel.mobility.ride.flight_sync import FlightRideSync
from go_hotel.mobility.ride.isolated_fleet import IsolatedFleetAdapter
from go_hotel.services.travel_operational_facts import TravelFacts, instant
from test_depth19_travel_facts import authority, signed

svc=FlightRideSync()


def seed_ride(auth, account='u19', day_offset=0, airport='NRT', enabled=True, protection=False):
    time=datetime.now(timezone.utc).replace(microsecond=0)+timedelta(days=day_offset)
    ride=ride_service.create(account,{'offer_id':'ride_standard','pickup':airport,'dropoff':'City','pickup_at':time.isoformat(),'passengers':[{'full_name':'TEST RIDER'}]})
    with SessionLocal.begin() as s:
        row=s.get(Ride,ride['order_id']);row.status='CONFIRMED';row.supplier_reference='isolated:'+row.order_id
    identity={'carrier_code':'MU','flight_no':'MU523','departure_date':time.date().isoformat(),'arrival_airport':airport}
    if enabled:svc.bind(account,ride['order_id'],{'flight_identity':identity,'authority_id':auth[0],'expected_revision':0,'delay_protection_enabled':protection})
    return ride,identity


def arrival(auth, identity, seq=1):
    return signed(auth,identity,{'event_type':'DELAYED','verified_arrival_at':identity['departure_date']+'T20:30:00+00:00'},kind='FLIGHT_ARRIVAL',seq=seq)


def proposal(auth, ride, identity):
    result=svc.ingest(arrival(auth,identity),'admin')
    return next(x['adjustment_id'] for x in result['events'] if x['ride_order_id']==ride['order_id'])


def test_exact_date_airport_closed_and_disabled_rides_are_isolated():
    auth=authority();r,identity=seed_ride(auth)
    tomorrow,_=seed_ride(auth,day_offset=1);other,_=seed_ride(auth,airport='HND')
    closed,_=seed_ride(auth);disabled,_=seed_ride(auth)
    with SessionLocal.begin() as s:s.get(Ride,closed['order_id']).status='COMPLETED'
    svc.bind('u19',disabled['order_id'],{'tracking_enabled':False,'expected_revision':1})
    result=svc.ingest(arrival(auth,identity),'admin')
    assert result['matched_rides']==1 and result['events'][0]['ride_order_id']==r['order_id']
    with SessionLocal() as s:
        for x in [r,tomorrow,other,closed,disabled]:assert s.get(Ride,x['order_id']).pickup_at==x['pickup_at']


@pytest.mark.parametrize('field,value',[('included_wait_minutes',999),('delay_protection_free_wait_minutes',999),('max_free_wait_minutes',999),('supplier_rule_snapshot',{'max_wait':999})])
def test_customer_cannot_authorize_waiting_terms(field,value):
    auth=authority();ride,identity=seed_ride(auth)
    with pytest.raises(ValueError,match='OVERRIDE_FORBIDDEN'):
        svc.bind('u19',ride['order_id'],{'flight_identity':identity,'authority_id':auth[0],'expected_revision':1,field:value})
    with pytest.raises(ValueError,match='OVERRIDE_FORBIDDEN'):
        ride_service.create('u19',{'offer_id':'ride_standard','pickup':'NRT','dropoff':'City','pickup_at':ride['pickup_at'],field:value})
    with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(Ride))==1


def test_policy_opt_in_is_bounded_and_proposal_does_not_change_confirmed_time(tmp_path):
    auth=authority();ride,identity=seed_ride(auth,protection=True)
    aid=proposal(auth,ride,identity)
    before=svc.tracking('u19',ride['order_id'])
    assert before['binding']['included_wait_minutes']==60 and before['binding']['delay_protection_max_wait_minutes']==90
    assert before['confirmed_pickup_at']==ride['pickup_at'] and before['events'][0]['status']=='PENDING'
    result=svc.process(aid,IsolatedFleetAdapter(tmp_path/'fleet.db'))
    assert result['status']=='CONFIRMED'
    after=svc.tracking('u19',ride['order_id'])
    assert after['confirmed_pickup_at']==after['events'][0]['proposed_pickup_at']
    assert svc.process(aid,IsolatedFleetAdapter(tmp_path/'fleet.db'))['status']=='CONFIRMED'


def test_policy_missing_or_changed_cannot_become_authorized():
    auth=authority();ride,identity=seed_ride(auth,enabled=False)
    with SessionLocal.begin() as s:s.delete(s.get(Policy,ride['order_id']))
    with pytest.raises(ValueError,match='SERVER_RIDE_POLICY_REQUIRED'):
        svc.bind('u19',ride['order_id'],{'flight_identity':identity,'authority_id':auth[0],'expected_revision':0})


def test_unknown_after_fleet_acceptance_reopens_receipt_and_queries_only(tmp_path):
    auth=authority();ride,identity=seed_ride(auth);aid=proposal(auth,ride,identity)
    class LostReply(IsolatedFleetAdapter):
        def execute(self,*args):
            super().execute(*args)
            raise TimeoutError('reply lost')
    assert svc.process(aid,LostReply(tmp_path/'fleet.db'))['status']=='UNKNOWN'
    assert svc.tracking('u19',ride['order_id'])['confirmed_pickup_at']==ride['pickup_at']
    class QueryOnly(IsolatedFleetAdapter):
        def execute(self,*args):raise AssertionError('MUST NOT RESEND')
    assert svc.process(aid,QueryOnly(tmp_path/'fleet.db'))['status']=='CONFIRMED'
    with sqlite3.connect(tmp_path/'fleet.db') as c:assert c.execute('SELECT count(*) FROM requests').fetchone()[0]==1


def _kill_after_fleet_acceptance(url,aid,path):
    class Crash(IsolatedFleetAdapter):
        def execute(self,*args):
            super().execute(*args)
            os.kill(os.getpid(),signal.SIGKILL)
    engine=create_engine(url,connect_args={'timeout':30})
    local=FlightRideSync(sessionmaker(bind=engine,expire_on_commit=False))
    local.process(aid,Crash(path))


def test_sigkill_after_committed_provider_receipt_recovers_without_resend(tmp_path):
    auth=authority();ride,identity=seed_ride(auth);aid=proposal(auth,ride,identity)
    with SessionLocal() as s:url=str(s.bind.url)
    process=multiprocessing.get_context('fork').Process(target=_kill_after_fleet_acceptance,args=(url,aid,str(tmp_path/'crash.db')))
    process.start();process.join(15)
    assert process.exitcode==-signal.SIGKILL
    with SessionLocal() as s:assert s.get(Adjustment,aid).status=='DISPATCHED'
    class QueryOnly(IsolatedFleetAdapter):
        def execute(self,*a):raise AssertionError('RESEND')
    assert svc.process(aid,QueryOnly(tmp_path/'crash.db'))['status']=='CONFIRMED'


def test_crash_before_dispatch_keeps_unknown_without_blind_resend(tmp_path):
    auth=authority();ride,identity=seed_ride(auth);aid=proposal(auth,ride,identity)
    class Crash(IsolatedFleetAdapter):
        def execute(self,*args):raise SystemExit('process lost before outbound call')
    with pytest.raises(SystemExit):svc.process(aid,Crash(tmp_path/'fleet.db'))
    adapter=IsolatedFleetAdapter(tmp_path/'fleet.db')
    for _ in range(2):assert svc.process(aid,adapter)['status']=='UNKNOWN'
    with sqlite3.connect(tmp_path/'fleet.db') as c:assert c.execute('SELECT count(*) FROM requests').fetchone()[0]==0


def test_parallel_processors_never_send_same_intent_twice(tmp_path):
    auth=authority();ride,identity=seed_ride(auth);aid=proposal(auth,ride,identity)
    from threading import Lock
    class Count(IsolatedFleetAdapter):
        calls=0
        lock=Lock()
        def execute(self,*args):
            with self.lock:self.calls+=1
            return super().execute(*args)
    adapter=Count(tmp_path/'fleet.db')
    with ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(lambda _:svc.process(aid,adapter),range(12)))
    assert adapter.calls==1
    assert svc.process(aid,adapter)['status']=='CONFIRMED'


def test_fleet_rejection_and_wrong_confirmation_do_not_change_customer_time(tmp_path):
    auth=authority();ride,identity=seed_ride(auth);aid=proposal(auth,ride,identity)
    class Reject(IsolatedFleetAdapter):
        def execute(self,request,h):return {'status':'REJECTED','request_hash':h,'provider_reference':'isolated:rejected'}
    assert svc.process(aid,Reject(tmp_path/'fleet.db'))['status']=='REJECTED'
    assert svc.tracking('u19',ride['order_id'])['confirmed_pickup_at']==ride['pickup_at']


@pytest.mark.parametrize('change',['revoke','disable','manual_time','close','policy'])
def test_current_authority_binding_order_and_policy_rechecked_before_dispatch(tmp_path,change):
    auth=authority();ride,identity=seed_ride(auth);aid=proposal(auth,ride,identity)
    if change=='revoke':TravelFacts().review(auth[0],'checker19',2,'REVOKE')
    if change=='disable':svc.bind('u19',ride['order_id'],{'tracking_enabled':False,'expected_revision':1})
    with SessionLocal.begin() as s:
        if change=='manual_time':s.get(Ride,ride['order_id']).pickup_at='2026-01-01T00:00:00+00:00'
        if change=='close':s.get(Ride,ride['order_id']).status='REFUNDED'
        if change=='policy':s.get(Policy,ride['order_id']).policy_hash='0'*64
    class NeverSend(IsolatedFleetAdapter):
        def execute(self,*args):raise AssertionError('NO DISPATCH AUTHORIZED')
    assert svc.process(aid,NeverSend(tmp_path/'fleet.db'))['status']=='SUPERSEDED'


def test_revoked_during_external_call_records_hold_without_fabricated_local_success(tmp_path):
    auth=authority();ride,identity=seed_ride(auth);aid=proposal(auth,ride,identity)
    class Revoke(IsolatedFleetAdapter):
        def execute(self,*args):
            result=super().execute(*args)
            TravelFacts().review(auth[0],'checker19',2,'REVOKE')
            return result
    assert svc.process(aid,Revoke(tmp_path/'fleet.db'))['status']=='HOLD'
    assert svc.tracking('u19',ride['order_id'])['confirmed_pickup_at']==ride['pickup_at']


def test_new_fact_supersedes_pending_and_event_replay_cannot_match_later_bindings(tmp_path):
    auth=authority();ride,identity=seed_ride(auth);old=arrival(auth,identity)
    aid=svc.ingest(old,'admin')['events'][0]['adjustment_id']
    another,_=seed_ride(auth)
    assert svc.ingest(old,'admin')['matched_rides']==1
    newer=svc.ingest(arrival(auth,identity,seq=2),'admin')
    assert newer['matched_rides']==2
    assert svc.process(aid,IsolatedFleetAdapter(tmp_path/'fleet.db'))['status']=='SUPERSEDED'


def test_customer_binding_revision_and_ownership_isolation():
    auth=authority();ride,identity=seed_ride(auth)
    with pytest.raises(ValueError,match='NOT_FOUND'):svc.tracking('other',ride['order_id'])
    body={'flight_identity':identity,'authority_id':auth[0],'expected_revision':1}
    with pytest.raises(ValueError,match='NOT_FOUND'):svc.bind('other',ride['order_id'],body)
    svc.bind('u19',ride['order_id'],body)
    with pytest.raises(ValueError,match='REVISION_CONFLICT'):svc.bind('u19',ride['order_id'],body)


@pytest.mark.parametrize('fault',['hash','time','reference'])
def test_unbound_or_inconsistent_fleet_receipt_never_confirms(tmp_path,fault):
    auth=authority();ride,identity=seed_ride(auth);aid=proposal(auth,ride,identity)
    class Wrong(IsolatedFleetAdapter):
        def execute(self,request,h):
            result={'status':'CONFIRMED','request_hash':h,'provider_reference':'isolated:wrong','pickup_at':request['proposed_pickup_at']}
            if fault=='hash':result['request_hash']='0'*64
            if fault=='time':result['pickup_at']='2000-01-01T00:00:00+00:00'
            if fault=='reference':result['provider_reference']=''
            return result
    assert svc.process(aid,Wrong(tmp_path/'fleet.db'))['status']==('HOLD' if fault=='time' else 'UNKNOWN')
    assert svc.tracking('u19',ride['order_id'])['confirmed_pickup_at']==ride['pickup_at']


def test_booking_entry_saves_server_policy_and_tracking_together():
    auth=authority();now=datetime.now(timezone.utc).replace(microsecond=0)
    identity={'carrier_code':'MU','flight_no':'MU523','departure_date':now.date().isoformat(),'arrival_airport':'NRT'}
    body={'offer_id':'ride_premium','pickup':'NRT','dropoff':'City','pickup_at':now.isoformat(),
        'passengers':[{'full_name':'ISOLATED RIDER'}],'flight_tracking_enabled':True,
        'flight_identity':identity,'flight_authority_id':auth[0],'delay_protection_enabled':True}
    ride=ride_service.create('u19',body)
    with SessionLocal() as s:
        assert s.get(Ride,ride['order_id']).status=='PAYMENT_PENDING'
        assert s.get(Policy,ride['order_id']).policy_json['max_free_wait_minutes']==120
        assert s.get(Binding,ride['order_id']).delay_protection_enabled
    body['flight_identity']={}
    with pytest.raises(ValueError):ride_service.create('u19',body)
    with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(Ride))==1


def test_revoked_source_is_visible_as_unavailable_without_mutating_binding():
    auth=authority();ride,identity=seed_ride(auth)
    TravelFacts().review(auth[0],'checker19',2,'REVOKE')
    data=svc.tracking('u19',ride['order_id'])
    assert data['binding']['source_current'] is False and data['binding']['revision']==1
    assert svc.options('u19',ride['order_id'])['sources']==[]


def test_legacy_local_pickup_is_opaque_until_explicit_fleet_confirmation(tmp_path):
    auth=authority();ride,identity=seed_ride(auth,enabled=False)
    original=identity['departure_date']+'T08:00'
    with SessionLocal.begin() as s:s.get(Ride,ride['order_id']).pickup_at=original
    svc.bind('u19',ride['order_id'],{'flight_identity':identity,'authority_id':auth[0],'expected_revision':0})
    aid=proposal(auth,ride,identity)
    before=svc.tracking('u19',ride['order_id'])
    assert before['confirmed_pickup_at']==original
    assert before['events'][0]['expected_pickup_at']==original
    assert before['events'][0]['proposed_pickup_at'].endswith('+00:00')
    assert svc.process(aid,IsolatedFleetAdapter(tmp_path/'fleet.db'))['status']=='CONFIRMED'
    assert svc.tracking('u19',ride['order_id'])['confirmed_pickup_at'].endswith('+00:00')


@pytest.mark.parametrize('event_type',['EARLY','LANDED','CORRECTED'])
def test_delay_protection_does_not_grant_extra_wait_for_non_delay_facts(tmp_path,event_type):
    from go_hotel.autonomy.durable import canonical
    auth=authority();ride,identity=seed_ride(auth,protection=True)
    envelope=arrival(auth,identity);envelope['fact']['data']['event_type']=event_type
    envelope['signature_hex']=auth[1].sign(canonical(envelope['fact']).encode()).hex()
    proposal=svc.ingest(envelope,'admin')['events'][0]
    assert proposal['free_wait_minutes']==60
    assert svc.process(proposal['adjustment_id'],IsolatedFleetAdapter(tmp_path/'fleet.db'))['status']=='CONFIRMED'


def test_correction_withdraws_previous_delay_protection_before_dispatch(tmp_path):
    from go_hotel.autonomy.durable import canonical
    auth=authority();ride,identity=seed_ride(auth,protection=True)
    first=svc.ingest(arrival(auth,identity),'admin')['events'][0]
    assert first['free_wait_minutes']==90
    correction=arrival(auth,identity,seq=2);correction['fact']['data']['event_type']='CORRECTED'
    correction['signature_hex']=auth[1].sign(canonical(correction['fact']).encode()).hex()
    second=svc.ingest(correction,'admin')['events'][0]
    adapter=IsolatedFleetAdapter(tmp_path/'fleet.db')
    assert svc.process(first['adjustment_id'],adapter)['status']=='SUPERSEDED'
    assert svc.process(second['adjustment_id'],adapter)['free_wait_minutes']==60
