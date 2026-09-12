from datetime import datetime,timezone
import pytest
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import FlightOrderRow,MobilityRideOrderRow,HotelPartnerGoOfferAuthorityRow,HotelPartnerPropertyRow
from go_hotel.services.mother_plan_p0 import mother_plan_p0_service as svc

def seed_flight(account='u1'):
 t=datetime.now(timezone.utc)
 with SessionLocal() as s:s.add(FlightOrderRow(order_id='f1',account_id=account,prebook_id='p1',status='TICKETED',total_amount_minor=100,currency='CNY',passengers=[],payment_method_id=None,pnr='P1',ticket_numbers=['T1'],current_itinerary=[{'flight_number':'MU523'}],created_at=t,updated_at=t));s.commit()
def seed_ride(account='u1'):
 t=datetime.now(timezone.utc)
 with SessionLocal() as s:s.add(MobilityRideOrderRow(order_id='r1',account_id=account,status='CONFIRMED',pickup='NRT',dropoff='Tokyo',pickup_at='2026-09-01T14:00:00+09:00',vehicle_class='COMFORT',total_amount_minor=100,currency='CNY',passengers=[],flight_no='MU523',supplier_reference='R1',created_at=t,updated_at=t));s.commit()

def test_checkin_four_states_require_authorized_fact_and_boarding_pass():
 from test_depth19_travel_facts import seed_flight as seed_current, authority, checkin
 seed_current();auth=authority()
 assert svc.checkin('u19','flight19')['state']=='CHECK_IN_UNVERIFIED'
 for seq,state in enumerate(['CHECK_IN_NOT_OPEN','CHECK_IN_OPEN','CHECKED_IN','BOARDING_PASS_AVAILABLE'],1):
  options={'boarding_pass_reference':'https://airline.example/pass'} if state=='BOARDING_PASS_AVAILABLE' else {}
  result=svc.ingest_checkin('flight19',checkin(auth,state=state,seq=seq,**options),'admin')
  assert result['state']==state
 with pytest.raises(ValueError,match='BOARDING_PASS_REFERENCE_REQUIRED'):
  svc.ingest_checkin('flight19',checkin(auth,state='BOARDING_PASS_AVAILABLE',seq=5),'admin')

def test_verified_flight_event_adjusts_go_pickup_with_bounded_free_wait_and_no_fake_fleet_confirmation():
 from test_depth19_travel_facts import authority
 from test_depth19_ride_sync import seed_ride as seed_current, arrival
 auth=authority();ride,identity=seed_current(auth,protection=True)
 result=svc.ingest_flight_event(arrival(auth,identity),'admin');e=result['events'][0]
 assert e['free_wait_minutes']==90 and e['status']=='PENDING'
 assert svc.ride_tracking('u19',ride['order_id'])['confirmed_pickup_at']==ride['pickup_at']
 assert svc.ingest_flight_event(arrival(auth,identity,seq=2),'admin')['matched_rides']==1

def test_requirement_builder_forbids_second_page_microphone_and_keeps_types_independent_of_quote_mode():
 with pytest.raises(ValueError,match='MICROPHONE_FORBIDDEN'):svc.create_requirement('u1',{'destination':'SHA','check_in':'2026-09-01','check_out':'2026-09-02','rooms':1,'adults':2,'voice':'hello'})
 r=svc.create_requirement('u1',{'destination':'SHA','check_in':'2026-09-01','check_out':'2026-09-02','rooms':1,'adults':2,'requirement_type':'MEETING_OR_EVENT'})
 assert r['requirement']['microphone_input_allowed'] is False and r['requirement']['requirement_type']=='MEETING_OR_EVENT' and r['requirement']['quote_mode'] is None

def test_system_quote_uses_only_dedicated_authority_and_selection_requires_revalidation():
 t=datetime.now(timezone.utc)
 with SessionLocal() as s:s.add(HotelPartnerGoOfferAuthorityRow(go_offer_authority_id='a1',property_id='hotel1',requirement_type='ROOM_ONLY',quote_mode='SYSTEM_GENERATED',authorized_inventory_json={'rooms':2},authorized_rules_json={'min_rooms':1},packages_json=[{'name':'Breakfast'}],price_floor_json={'amount_minor':88800},validity_json={'minutes':20},conditions_json={'refundable':True},source_scope='GO_OFFER_DEDICATED',state='ACTIVE',updated_at=t));s.commit()
 r=svc.create_requirement('u1',{'property_id':'hotel1','destination':'SHA','check_in':'2026-09-01','check_out':'2026-09-02','rooms':1,'adults':2,'requirement_type':'ROOM_ONLY'});assert r['quote']['amount_minor']==88800 and r['ordinary_bar_member_inventory_used'] is False
 selected=svc.accept_quote('u1',r['requirement']['go_offer_requirement_id'],r['quote']['go_offer_quote_id']);assert selected['booking_created'] is False and selected['revalidation_required'] is True
 pb=svc.start_prebook('u1',r['requirement']['go_offer_requirement_id'],r['quote']['go_offer_quote_id'],{'idempotency_key':'system-pb-1'});assert pb['state']=='REVALIDATED'
 h=svc.order_handoff('u1',pb['go_offer_prebook_id'],{'idempotency_key':'system-handoff-1','traveler_ids':['trav1']});assert h['state']=='READY_FOR_CHECKOUT' and h['booking_confirmed'] is False and h['payment_captured'] is False
 assert svc.order_handoff('u1',pb['go_offer_prebook_id'],{'idempotency_key':'system-handoff-1'})['go_offer_order_handoff_id']==h['go_offer_order_handoff_id']

def test_manual_quote_requires_supplier_revalidation_before_order_handoff():
 t=datetime.now(timezone.utc)
 with SessionLocal() as s:
  s.add(HotelPartnerPropertyRow(property_id='manual_hotel',supplier_id='supplier_1',name_zh='Manual Hotel',name_en=None,property_type='HOTEL',group_name=None,brand_name=None,address_json={},latitude=None,longitude=None,contacts_json={},legal_json={},operations_json={},poi_json=[],publication_state='PUBLISHED',version=1,created_at=t,updated_at=t))
  s.add(HotelPartnerGoOfferAuthorityRow(go_offer_authority_id='manual_a1',property_id='manual_hotel',requirement_type='MEETING_OR_EVENT',quote_mode='MANUAL_QUOTE',authorized_inventory_json={},authorized_rules_json={},packages_json=[],price_floor_json={},validity_json={'minutes':30},conditions_json={},source_scope='GO_OFFER_DEDICATED',state='ACTIVE',updated_at=t));s.commit()
 r=svc.create_requirement('u2',{'property_id':'manual_hotel','destination':'SHA','check_in':'2026-10-01','check_out':'2026-10-02','rooms':5,'adults':10,'requirement_type':'MEETING_OR_EVENT'})
 q=svc.manual_quote('supplier_1',r['requirement']['go_offer_requirement_id'],{'amount_minor':200000,'currency':'CNY','validity_minutes':30})
 svc.accept_quote('u2',r['requirement']['go_offer_requirement_id'],q['go_offer_quote_id'])
 pb=svc.start_prebook('u2',r['requirement']['go_offer_requirement_id'],q['go_offer_quote_id'],{'idempotency_key':'manual-pb-1'});assert pb['state']=='PENDING_SUPPLIER_REVALIDATION'
 with pytest.raises(ValueError,match='REVALIDATION_REQUIRED'):svc.order_handoff('u2',pb['go_offer_prebook_id'],{'idempotency_key':'manual-handoff-before'})
 pb=svc.supplier_revalidate('supplier_1',pb['go_offer_prebook_id'],{'available':True,'amount_minor':200000,'currency':'CNY','supplier_confirmation_reference':'supplier://availability/123','conditions_changed':False},'supplier_user')
 assert pb['state']=='REVALIDATED'
 assert svc.order_handoff('u2',pb['go_offer_prebook_id'],{'idempotency_key':'manual-handoff-after'})['state']=='READY_FOR_CHECKOUT'
