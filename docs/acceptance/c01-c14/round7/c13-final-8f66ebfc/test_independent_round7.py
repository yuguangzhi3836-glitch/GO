"""Independent C13 assertions. Run only against a hash-verified frozen snapshot.
Fixtures provision synthetic engineering authority; no production rights implied.
"""
import hashlib,io,json,uuid
from datetime import datetime,timedelta,timezone
import pytest
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from go_hotel.db import models as m
from go_hotel.db.session import SessionLocal
from go_hotel.api.routes.hosted_direct_booking import router as hosted_router
from go_hotel.api.routes.rental_damage import router as damage_router
from go_hotel.api.routes.rental_deposit_money import router as deposit_router
from go_hotel.services import hosted_publication as publication
from go_hotel.services.hosted_operation_authority import ROOT_ROLE
from go_hotel.mobility.rental import deposit_authority as authority
from tests.hosted_review_support import hotel_fixture,identity,provision
from pathlib import Path
import sys
SOURCE_ROOT=Path(__file__).resolve().parent/'candidate-8f66ebfc'/'application'

def assert_candidate_imports():
 for name,module in list(sys.modules.items()):
  filename=getattr(module,'__file__',None)
  if (name=='go_hotel' or name.startswith('go_hotel.') or name.startswith('tests.')) and filename:
   assert Path(filename).resolve().is_relative_to(SOURCE_ROOT),(name,filename)

@pytest.fixture(autouse=True)
def bound_source_imports():
 assert_candidate_imports()
 yield
 assert_candidate_imports()

@pytest.fixture
def http():
 app=FastAPI();app.include_router(hosted_router);app.include_router(damage_router);app.include_router(deposit_router)
 assert not app.dependency_overrides
 with TestClient(app) as client:yield client

@pytest.fixture
def ready(monkeypatch,tmp_path):return hotel_fixture(monkeypatch,tmp_path,ready=True)

def book(client,h,key='independent'):
 r=client.post('/v1/direct/'+h['slug']+'/reservations',headers={**h['customer_headers'],'Idempotency-Key':key},json=h['body'])
 assert r.status_code==200,r.text
 return r.json()['data']['hosted_reservation_id']

def observations(rid):
 with SessionLocal() as s:
  reservation=s.get(m.HostedDirectReservationRow,rid);stay=s.get(m.HostedReservationStayRow,rid)
  return {'reservation_state':reservation.reservation_state,'operational_state':stay.operational_state,'amount':reservation.amount_minor,
   'dates':[reservation.check_in,reservation.check_out],
   'notifications':s.scalar(select(func.count()).select_from(m.HostedReservationNotificationRow).where(m.HostedReservationNotificationRow.hosted_reservation_id==rid)),
   'events':s.scalar(select(func.count()).select_from(m.HostedDirectReservationEventRow).where(m.HostedDirectReservationEventRow.hosted_reservation_id==rid)),
   'nights':[(x.stay_date,x.state) for x in s.scalars(select(m.HostedReservationNightRow).where(m.HostedReservationNightRow.hosted_reservation_id==rid))]}

def test_unfunded_confirmed_application_cancels_once_with_no_money(http,ready):
 h=ready;rid=book(http,h)
 r=http.post(f'/internal/v1/hosted-direct/reservations/{rid}/decision',headers=h['maker_headers'],json={'decision':'CONFIRM'});assert r.status_code==200,r.text
 with SessionLocal() as s:
  assert s.get(m.HostedOrderFareSnapshotRow,rid)
  assert s.scalar(select(func.count()).select_from(m.AlipayAuthorizationRow).where(m.AlipayAuthorizationRow.hosted_reservation_id==rid))==0
 first=http.post(f'/v1/direct/reservations/{rid}/cancel',headers=h['customer_headers']);assert first.status_code==200,first.text
 before=observations(rid)
 assert before['operational_state']=='CANCELLED' and all(state=='RELEASED' for _,state in before['nights'])
 replay=http.post(f'/v1/direct/reservations/{rid}/cancel',headers=h['customer_headers']);assert replay.status_code==200,replay.text
 assert observations(rid)==before
 with SessionLocal() as s:
  assert s.scalar(select(m.HostedInventoryDayRow.capacity_available).where(m.HostedInventoryDayRow.inventory_pool_id==h['pool'],m.HostedInventoryDayRow.stay_date==h['day'].isoformat()))==5


def test_crosshotel_finance_reads_and_mandate_mutation_denied(http,ready,monkeypatch,tmp_path):
 h=ready;other=hotel_fixture(monkeypatch,tmp_path)
 with SessionLocal() as s:before=s.scalar(select(func.count()).select_from(m.HostedFaultDebitMandateRow))
 paths=[('GET',f"/internal/v1/hosted-direct/hotels/{other['hotel']}/fault-finance",None),('POST',f"/internal/v1/hosted-direct/hotels/{other['hotel']}/fault-mandates",{'currency':'CNY','maximum_per_case_minor':100000,'expires_at':(datetime.now(timezone.utc)+timedelta(days=30)).isoformat(),'authority_reference':'isolated://c13','authority_hash':'e'*64}),('POST',f"/internal/v1/hosted-direct/hotels/{other['hotel']}/fault-recoveries",{'amount_minor':1,'settlement_reference':'isolated://c13'})]
 for method,path,body in paths:
  r=http.request(method,path,headers={**h['maker_headers'],'Idempotency-Key':'c13-cross'},json=body);assert r.status_code==403,(path,r.text)
 with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(m.HostedFaultDebitMandateRow))==before


def test_media_self_review_rejected_and_server_submitter_cannot_be_spoofed(http,ready):
 h=ready
 buffer=io.BytesIO();Image.new('RGB',(1200,700),(18,91,207)).save(buffer,format='PNG');raw=buffer.getvalue();sha=hashlib.sha256(raw).hexdigest();(h['root']/(sha+'.png')).write_bytes(raw)
 body={'asset_role':'HERO','storage_reference':'isolated-media://'+sha+'.png','rights_owner':'哈尔滨敖麓谷雅酒店','rights_evidence_reference':'isolated://independent-media'}
 path=f"/internal/v1/hosted-direct/hotels/{h['hotel']}"
 spoof=http.post(path+'/media-assets',headers=h['checker_headers'],json={**body,'submitted_by':h['maker'].user_id});assert spoof.status_code in {403,409,422},spoof.text
 submitted=http.post(path+'/media-assets',headers=h['checker_headers'],json=body);assert submitted.status_code==200,submitted.text
 with SessionLocal() as s:
  asset=s.get(m.HostedMediaAssetRow,submitted.json()['data']['media_asset_id']);assert asset.submitted_by==h['checker'].user_id
  old=publication.latest(s,h['hotel']);previous_id=old.publication_review_id
 preview=http.get(path+'/publication-preview',headers=h['checker_headers']);assert preview.status_code==200,preview.text
 response=http.post(path+'/publication-review',headers=h['checker_headers'],json={'decision':'APPROVE','evidence_reference':'isolated://self','expected_manifest_hash':preview.json()['data']['manifest_hash'],'expected_review_id':previous_id})
 assert response.status_code==403,response.text
 assert http.get('/v1/direct/'+h['slug']).status_code in {403,409}
 third,third_headers=identity('independent-reviewer');provision(h['hotel'],third)
 response=http.post(path+'/publication-review',headers=third_headers,json={'decision':'APPROVE','evidence_reference':'isolated://independent-third','expected_manifest_hash':preview.json()['data']['manifest_hash'],'expected_review_id':previous_id})
 assert response.status_code==200,response.text
 assert http.get('/v1/direct/'+h['slug']).status_code==200


@pytest.mark.parametrize('fault',['root_revocation','user_permission_revocation','media_submitter_revocation'])
def test_revocations_are_effective_with_existing_valid_jwt(http,ready,fault):
 h=ready
 with SessionLocal.begin() as s:
  if fault=='root_revocation':s.scalar(select(m.HostedStaffRoleRow).where(m.HostedStaffRoleRow.staff_id==h['maker'].user_id,m.HostedStaffRoleRow.role==ROOT_ROLE)).state='REVOKED'
  elif fault=='user_permission_revocation':s.get(m.IdentityUserRow,h['maker'].user_id).roles=['GO_READ_ONLY']
  else:s.scalar(select(m.HostedStaffRoleRow).where(m.HostedStaffRoleRow.staff_id==h['maker'].user_id,m.HostedStaffRoleRow.role=='HOTEL_CONTENT_APPROVER')).state='REVOKED'
 if fault!='media_submitter_revocation':
  r=http.put(f"/internal/v1/hosted-direct/rate-variants/{h['variant']}/days/{h['day']}",headers=h['maker_headers'],json={'price_minor':1,'sale_state':'OPEN'});assert r.status_code==403,r.text
 else:
  assert http.get('/v1/direct/'+h['slug']).status_code in {403,409}
  r=http.post('/v1/direct/'+h['slug']+'/reservations',headers={**h['customer_headers'],'Idempotency-Key':'revoked-media'},json=h['body']);assert r.status_code==409,r.text


@pytest.mark.parametrize('count',[1,999])
def test_unpriced_extra_beds_cannot_create_orders(http,ready,count):
 h=ready
 with SessionLocal() as s:before=s.scalar(select(func.count()).select_from(m.HostedDirectReservationRow))
 r=http.post('/v1/direct/'+h['slug']+'/reservations',headers={**h['customer_headers'],'Idempotency-Key':'beds'},json={**h['body'],'extra_beds':count});assert r.status_code in {409,422},r.text
 with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(m.HostedDirectReservationRow))==before


def evidence(letter):return [{'reference':'isolated://c13-'+letter,'sha256':letter*64}]

@pytest.mark.parametrize('paid,target',[(False,5000),(True,5000),(False,4000),(True,4000),(True,7000)])
def test_rental_latest_award_real_http_money_truth(http,paid,target):
 owner,oh=identity('owner',consumer=True);maker,mh=identity('damage-maker');checker,ch=identity('damage-checker');second,sh=identity('appeal-checker');third,th=identity('maintained-checker')
 oid='c13-'+uuid.uuid4().hex;stamp=datetime.now(timezone.utc)
 with SessionLocal.begin() as s:
  s.add(m.MobilityRentalOrderRow(order_id=oid,account_id=owner.user_id,status='CONFIRMED',pickup_location='A',return_location='A',pickup_at='2026-09-26T10:00:00',return_at='2026-09-27T10:00:00',vehicle_class='COMPACT',insurance={'type':'BASIC','excess_minor':500000},mileage={},deposit_minor=200000,total_amount_minor=84000,currency='CNY',drivers=[],supplier_reference=None,created_at=stamp,updated_at=stamp))
 proposal=authority.propose(owner,oid,'proposal');obligation=authority.accept(owner,oid,proposal['obligation_id'],'accept',proposal['revision'],proposal['source_hash'],True)
 source={'expected_revision':obligation['revision'],'expected_source_hash':obligation['source_hash']};base=f"/internal/v1/mobility/rentals/orders/{oid}/deposit-money/{obligation['obligation_id']}"
 def post(path,headers,body,key):
  response=http.post(path,headers={**headers,'Idempotency-Key':key},json=body);assert response.status_code==200,(path,response.text);return response.json()['data']
 post(base+'/authorize',ch,source,'authorize')
 with SessionLocal.begin() as s:s.get(m.MobilityRentalOrderRow,oid).status='COMPLETED'
 claim=post(f'/internal/v1/admin/mobility/rentals/orders/{oid}/damage-cases',mh,{'amount_minor':10000,'currency':'CNY','pickup_evidence':evidence('a'),'return_evidence':evidence('b')},'open');cid=claim['case_id']
 public=f'/v1/mobility/rentals/orders/{oid}/damage-cases/{cid}';admin=f'/internal/v1/admin/mobility/rentals/orders/{oid}/damage-cases/{cid}'
 post(public+'/response',oh,{'expected_version':1,'response':'DISPUTE','evidence':evidence('c')},'response')
 post(admin+'/decision',ch,{'expected_version':2,'award_minor':10000,'reason':'Initial responsibility','evidence':evidence('d')},'decision')
 def decision_body():
  decision=authority.decision_preview(checker,oid,obligation['obligation_id'],cid)
  return {**source,'case_id':cid,'expected_case_version':decision['case_version'],'expected_decision_hash':decision['decision_hash']}
 post(base+'/settle',ch,decision_body(),'settle')
 post(public+'/appeal',oh,{'expected_version':3,'reason':'Reduce responsibility','evidence':evidence('e')},'appeal1')
 post(admin+'/appeal-decision',sh,{'expected_version':4,'award_minor':5000,'reason':'Confirmed reduction','evidence':evidence('f')},'review1');previous=decision_body()
 if paid:post(base+'/compensate',ch,previous,'compensate1')
 post(public+'/appeal',oh,{'expected_version':5,'reason':'Follow-up review','evidence':evidence('e')},'appeal2')
 post(admin+'/appeal-decision',th,{'expected_version':6,'award_minor':target,'reason':'Latest responsibility','evidence':evidence('f')},'review2');latest=decision_body()
 response=http.post(base+'/compensate',headers=ch,json=latest)
 expected_net=5000 if paid and target>5000 else target
 if paid and target>5000:assert response.status_code==409 and 'INCREASE_FORBIDDEN' in response.text,response.text
 else:assert response.status_code==200,response.text
 with SessionLocal() as s:
  initial_movements=[(x.money_movement_id,x.movement_type,x.amount_minor) for x in s.scalars(select(m.OmnichannelMoneyMovementRow))]
 replay=http.post(base+'/compensate',headers=ch,json=latest);assert replay.status_code==response.status_code,replay.text
 stale=http.post(base+'/compensate',headers=ch,json=previous);assert stale.status_code==409 and 'VERSION_CONFLICT' in stale.text,stale.text
 status=http.get(f"/v1/mobility/rentals/orders/{oid}/deposit-money/{obligation['obligation_id']}",headers=oh,params=source);assert status.status_code==200,status.text
 assert status.json()['data']['net_captured_minor']==expected_net
 with SessionLocal() as s:
  assert [(x.money_movement_id,x.movement_type,x.amount_minor) for x in s.scalars(select(m.OmnichannelMoneyMovementRow))]==initial_movements

@pytest.mark.parametrize('failure',['missing_ari','sold_out','after_approval','before_commit'])
def test_approval_recovery_keeps_order_nights_trips_notifications_atomic(http,ready,failure):
 from go_hotel.core.faults import faults
 h=ready;rid=book(http,h);requester,rh=identity('recovery-front',['GO_ORDER_OPS']);checker,ch=identity('recovery-checker')
 for p,role in [(requester,'FRONT_DESK'),(checker,'DUTY_MANAGER')]:
  response=http.post(f"/internal/v1/hosted-direct/hotels/{h['hotel']}/staff-roles",headers=h['maker_headers'],json={'staff_id':p.user_id,'role':role,'evidence_reference':'isolated://c13-delegation'});assert response.status_code==200,response.text
 start=(h['day']+timedelta(days=4)).isoformat();end=(h['day']+timedelta(days=5)).isoformat()
 def configure_target():
  response=http.post(f"/internal/v1/hosted-direct/hotels/{h['hotel']}/calendar/bootstrap",headers=h['maker_headers'],json={'start_date':start,'end_date':end});assert response.status_code==200,response.text
 if failure!='missing_ari':configure_target()
 if failure=='sold_out':
  response=http.put(f"/internal/v1/hosted-direct/inventory-pools/{h['pool']}/days/{start}",headers=h['maker_headers'],json={'sale_state':'SOLD_OUT','capacity_available':0});assert response.status_code==200,response.text
 response=http.post(f'/internal/v1/hosted-direct/reservations/{rid}/action-approvals',headers=rh,json={'action_type':'RESCHEDULE','payload':{'check_in':start,'check_out':end}});assert response.status_code==200,response.text
 aid=response.json()['data']['action_approval_id'];path=f'/internal/v1/hosted-direct/action-approvals/{aid}/approve';body={'evidence_reference':'isolated://c13-independent-recovery'}
 before=observations(rid)
 if failure in {'after_approval','before_commit'}:
  faults.arm('hosted_action_after_approval_commit' if failure=='after_approval' else 'hosted_action_before_execution_commit')
  with pytest.raises(RuntimeError):http.post(path,headers=ch,json=body)
 else:
  response=http.post(path,headers=ch,json=body);assert response.status_code==409,response.text
 assert observations(rid)==before
 with SessionLocal() as s:
  a=s.get(m.HostedActionApprovalRow,aid);assert a.state in {'APPROVED_PENDING_EXECUTION','APPROVED_RETRY_REQUIRED'}
  trip=s.scalar(select(m.ConsumerUnifiedLifecycleRow).where(m.ConsumerUnifiedLifecycleRow.order_id==rid));assert trip.facts_json['check_in']==h['body']['check_in']
 if failure=='missing_ari':configure_target()
 if failure=='sold_out':
  response=http.put(f"/internal/v1/hosted-direct/inventory-pools/{h['pool']}/days/{start}",headers=h['maker_headers'],json={'sale_state':'OPEN','capacity_available':5});assert response.status_code==200,response.text
 response=http.post(path,headers=ch,json=body);assert response.status_code==200,response.text
 after=observations(rid);assert after['dates']==[start,end] and after['notifications']==before['notifications']+1 and after['events']==before['events']+1
 with SessionLocal() as s:
  assert s.get(m.HostedActionApprovalRow,aid).state=='APPROVED_EXECUTED'
  trip=s.scalar(select(m.ConsumerUnifiedLifecycleRow).where(m.ConsumerUnifiedLifecycleRow.order_id==rid));assert trip.facts_json['check_in']==start and trip.facts_json['check_out']==end and trip.lifecycle_state=='PENDING'
  assert s.scalar(select(m.HostedInventoryDayRow.capacity_available).where(m.HostedInventoryDayRow.inventory_pool_id==h['pool'],m.HostedInventoryDayRow.stay_date==start))==4
  assert s.scalar(select(m.HostedInventoryDayRow.capacity_available).where(m.HostedInventoryDayRow.inventory_pool_id==h['pool'],m.HostedInventoryDayRow.stay_date==h['day'].isoformat()))==5
 response=http.post(path,headers=ch,json=body);assert response.status_code==200 and response.json()['data']['replayed'],response.text
 assert observations(rid)==after
 changed=http.post(path,headers=ch,json={'evidence_reference':'different'});assert changed.status_code==409,changed.text
 assert observations(rid)==after


def test_funded_confirmation_uses_quote_and_projects_one_cancellation(http,ready):
 h=ready;rid=book(http,h)
 with SessionLocal() as s:r=s.get(m.HostedDirectReservationRow,rid);amount=r.amount_minor
 checkout=http.post(f'/v1/direct/reservations/{rid}/checkout',headers=h['customer_headers'],json={'expected_amount_minor':amount,'currency':'CNY','mode':'CONTRACT_SIMULATOR'});assert checkout.status_code==200,checkout.text
 confirm=http.post(f'/internal/v1/hosted-direct/reservations/{rid}/decision',headers=h['maker_headers'],json={'decision':'CONFIRM'});assert confirm.status_code==200,confirm.text
 before=observations(rid)
 refused=http.post(f'/v1/direct/reservations/{rid}/cancel',headers=h['customer_headers']);assert refused.status_code==409,refused.text
 assert observations(rid)==before
 quote=http.post(f'/v1/direct/reservations/{rid}/fare/cancellation-quote',headers=h['customer_headers']);assert quote.status_code==200,quote.text
 q=quote.json()['data'];body={'quote_id':q['quote_id'],'expected_fee_minor':q['fee_minor'],'currency':'CNY'}
 done=http.post(f'/v1/direct/reservations/{rid}/fare/cancel',headers=h['customer_headers'],json=body);assert done.status_code==200,done.text
 after=observations(rid);assert after['operational_state']=='CANCELLED' and after['notifications']==before['notifications']+1
 with SessionLocal() as s:
  trip=s.scalar(select(m.ConsumerUnifiedLifecycleRow).where(m.ConsumerUnifiedLifecycleRow.order_id==rid));assert trip.lifecycle_state=='CANCELLED' and not trip.cancel_allowed
  assert s.scalar(select(m.HostedInventoryDayRow.capacity_available).where(m.HostedInventoryDayRow.inventory_pool_id==h['pool'],m.HostedInventoryDayRow.stay_date==h['day'].isoformat()))==5
 replay=http.post(f'/v1/direct/reservations/{rid}/fare/cancel',headers=h['customer_headers'],json=body);assert replay.status_code==200,replay.text
 assert observations(rid)==after
