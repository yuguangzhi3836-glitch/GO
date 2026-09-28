"""Real JWT/DB sessions through actual routes; positive, refusal and recovery."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from go_hotel.api.routes.hosted_direct_booking import router
from go_hotel.db import models as m
from go_hotel.db.session import SessionLocal
from go_hotel.services.hosted_content_acceptance import hosted_content_acceptance_service as content
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service as booking
from go_hotel.services.hosted_frontdesk_uat import hosted_frontdesk_uat_service as frontdesk
from go_hotel.services.hosted_reservation_operations import hosted_reservation_operations_service as ops
from go_hotel.services import hosted_publication as publication
from go_hotel.services.hosted_operation_authority import ROOT_ROLE
from go_hotel.core.faults import faults
from tests.hosted_review_support import hotel_fixture,identity,prepare_publication,provision


@pytest.fixture
def http():
    app=FastAPI();app.include_router(router)
    assert not app.dependency_overrides
    with TestClient(app) as client:yield client


@pytest.fixture
def ready(monkeypatch,tmp_path):return hotel_fixture(monkeypatch,tmp_path,ready=True)


def reserve(http,h,key='journey'):
    result=http.post(f"/v1/direct/{h['slug']}/reservations",headers={**h['customer_headers'],'Idempotency-Key':key},json=h['body'])
    assert result.status_code==200,result.text
    return result.json()['data']


def counts():
    with SessionLocal() as s:
        return tuple(s.scalar(select(func.count()).select_from(cls)) for cls in
            [m.HostedDirectReservationRow,m.HostedStaffRoleRow,m.HostedGuestAccessAuditRow,m.HostedReservationNotificationRow,m.HostedDirectReservationEventRow])


def test_gate_blocks_every_sale_entry_then_independent_review_opens_full_journey(http,monkeypatch,tmp_path):
    h=hotel_fixture(monkeypatch,tmp_path)
    assert content.gate(h['hotel'])['state']=='BLOCKED_PENDING_CONTENT_AND_MEDIA'
    assert http.post(f"/internal/v1/hosted-direct/hotels/{h['hotel']}/publish",headers=h['maker_headers']).status_code==409
    for suffix in ['reservations','managed-reservations']:
        assert http.post(f"/v1/direct/{h['slug']}/{suffix}",headers={**h['customer_headers'],'Idempotency-Key':suffix},json=h['body']).status_code==409
    assert not http.post(f"/v1/direct/{h['slug']}/availability",json=h['body']).json()['data']['items'][0]['bookable']
    prepare_publication(h['hotel'],h['maker'],h['checker'],tmp_path)
    published=http.post(f"/internal/v1/hosted-direct/hotels/{h['hotel']}/publish",headers=h['maker_headers'])
    assert published.status_code==200,published.text
    page=http.get(f"/v1/direct/{h['slug']}");assert page.status_code==200
    assert http.get(page.json()['data']['media'][0]['url']).status_code==200
    availability=http.post(f"/v1/direct/{h['slug']}/availability",json=h['body']).json()['data']['items'][0]
    assert availability['bookable'];h['body']['expected_fare_rule_hash']=availability['fare_rule']['rule_hash']
    r=reserve(http,h);rid=r['hosted_reservation_id']
    checkout=http.post(f'/v1/direct/reservations/{rid}/checkout',headers=h['customer_headers'],json={'expected_amount_minor':r['amount_minor'],'currency':r['currency'],'mode':'CONTRACT_SIMULATOR'})
    assert checkout.status_code==200,checkout.text
    response=http.post(f'/internal/v1/hosted-direct/reservations/{rid}/decision',headers=h['maker_headers'],json={'decision':'CONFIRM'})
    assert response.status_code==200,response.text
    assert response.json()['data']['guest_contact']=='***'
    q=http.post(f'/v1/direct/reservations/{rid}/fare/cancellation-quote',headers=h['customer_headers'])
    assert q.status_code==200,q.text
    quote=q.json()['data']
    done=http.post(f'/v1/direct/reservations/{rid}/fare/cancel',headers=h['customer_headers'],json={'quote_id':quote['quote_id'],'expected_fee_minor':0,'currency':'CNY'})
    assert done.status_code==200,done.text
    with SessionLocal() as s:
        assert s.get(m.HostedReservationStayRow,rid).operational_state=='CANCELLED'
        assert s.scalar(select(m.HostedInventoryDayRow.capacity_available).where(m.HostedInventoryDayRow.stay_date==h['day'].isoformat()))==5
        assert s.scalar(select(func.count()).select_from(m.HostedReservationNotificationRow).where(m.HostedReservationNotificationRow.hosted_reservation_id==rid))>=3
    assert content.gate(h['hotel'])['real_hotel_authority_state']=='HOLD_UNVERIFIED'


@pytest.mark.parametrize('fault',['readonly','unscoped','revoked_role','revoked_session'])
def test_unauthorized_equivalent_entries_have_no_writes_or_pii(http,ready,fault):
    h=ready;r=reserve(http,h);rid=r['hosted_reservation_id']
    p,headers=identity('denied',['GO_READ_ONLY'] if fault=='readonly' else None)
    if fault.startswith('revoked'):
        provision(h['hotel'],p)
        with SessionLocal.begin() as s:
            if fault=='revoked_role':s.scalar(select(m.HostedStaffRoleRow).where(m.HostedStaffRoleRow.staff_id==p.user_id,m.HostedStaffRoleRow.role==ROOT_ROLE)).state='REVOKED'
            else:s.get(m.AuthSessionRow,p.session_id).status='REVOKED'
    before=counts()
    cases=[('POST',f"hotels/{h['hotel']}/staff-roles",{'staff_id':p.user_id,'role':'DUTY_MANAGER','evidence_reference':'self'}),
      ('PUT',f"rate-variants/{h['variant']}/days/{h['day']}",{'price_minor':1,'sale_state':'OPEN'}),
      ('PUT',f"inventory-pools/{h['pool']}/days/{h['day']}",{'capacity_available':0,'sale_state':'STOP_SELL'}),
      ('POST',f'reservations/{rid}/guest-access',{'reason':'probe','unmask':True}),
      ('POST',f'reservations/{rid}/decision',{'decision':'REJECT'}),
      ('POST',f'reservations/{rid}/cancel',{}),
      ('POST',f'managed-reservations/{rid}/actions',{'action':'CANCEL'}),
      ('POST',f'managed-reservations/{rid}/reschedule',{'check_in':h['body']['check_in'],'check_out':h['body']['check_out']}),
      ('POST',f"{h['slug']}/phone-reservations",h['body']),('POST',f"{h['slug']}/governed-phone-reservations",h['body']),
      ('POST','managed-reservations/expire-pending',{})]
    for method,path,body in cases:
        response=http.request(method,'/internal/v1/hosted-direct/'+path,headers={**headers,'Idempotency-Key':'denied'},json=body)
        assert response.status_code in {401,403},(path,response.text)
        assert 'synthetic@example.invalid' not in response.text
    assert counts()==before
    with SessionLocal() as s:
        assert s.get(m.HostedReservationStayRow,rid).operational_state=='PENDING_HOTEL_CONFIRMATION'
        assert s.scalar(select(m.HostedRateCalendarDayRow.price_minor).where(m.HostedRateCalendarDayRow.rate_variant_id==h['variant']))==50000


@pytest.mark.parametrize('fault',['reject','content','bytes','reviewer_revoked','fare_changed'])
def test_approved_version_invalidates_across_public_page_availability_and_reservation(http,ready,fault):
    h=ready
    with SessionLocal() as s:review=publication.latest(s,h['hotel']);review_id,manifest_hash=review.publication_review_id,review.manifest_hash
    if fault=='reject':publication.review(h['hotel'],{'decision':'REJECT','evidence_reference':'revoked','expected_manifest_hash':manifest_hash,'expected_review_id':review_id},h['checker'])
    elif fault=='bytes':next(h['root'].glob('*.png')).write_bytes(b'corrupt')
    else:
        with SessionLocal.begin() as s:
            if fault=='content':s.get(m.HostedDirectHotelRow,h['hotel']).contact_json={'changed':True}
            elif fault=='reviewer_revoked':s.get(m.IdentityUserRow,h['checker'].user_id).status='DISABLED'
            else:s.scalar(select(m.HostedFareRuleVersionRow).where(m.HostedFareRuleVersionRow.hosted_offer_id==h['offer'])).rule_hash='changed'
    before=counts()
    assert http.get(f"/v1/direct/{h['slug']}").status_code in {403,409}
    assert not http.post(f"/v1/direct/{h['slug']}/availability",json=h['body']).json()['data']['items'][0]['bookable']
    for suffix in ['reservations','managed-reservations']:
        response=http.post(f"/v1/direct/{h['slug']}/{suffix}",headers={**h['customer_headers'],'Idempotency-Key':'stale-'+suffix},json=h['body'])
        assert response.status_code==409,response.text
    assert counts()==before


def delegated(h):
    maker,mh=identity('frontdesk',['GO_ORDER_OPS']);checker,ch=identity('manager')
    for p,role in [(maker,'FRONT_DESK'),(checker,'DUTY_MANAGER')]:
        frontdesk.assign_role(h['hotel'],{'staff_id':p.user_id,'role':role,'evidence_reference':'isolated://staff'},h['maker'])
    return maker,mh,checker,ch


@pytest.mark.parametrize('failure',['missing_ari','after_approval','before_commit'])
def test_approval_failure_and_retry_are_truthful_atomic_and_idempotent(http,ready,failure):
    h=ready;r=reserve(http,h);rid=r['hosted_reservation_id'];maker,mh,checker,ch=delegated(h)
    start=(h['day']+timedelta(days=4)).isoformat();end=(h['day']+timedelta(days=5)).isoformat()
    if failure!='missing_ari':ops.bootstrap_calendar(h['hotel'],{'start_date':start,'end_date':end})
    request=http.post(f'/internal/v1/hosted-direct/reservations/{rid}/action-approvals',headers=mh,json={'action_type':'RESCHEDULE','payload':{'check_in':start,'check_out':end}})
    assert request.status_code==200,request.text
    aid=request.json()['data']['action_approval_id'];path=f'/internal/v1/hosted-direct/action-approvals/{aid}/approve';body={'evidence_reference':'isolated://approval'}
    before=counts()
    if failure=='missing_ari':assert http.post(path,headers=ch,json=body).status_code==409
    else:
        faults.arm('hosted_action_after_approval_commit' if failure=='after_approval' else 'hosted_action_before_execution_commit')
        with pytest.raises(RuntimeError):http.post(path,headers=ch,json=body)
    with SessionLocal() as s:
        assert s.get(m.HostedActionApprovalRow,aid).state in {'APPROVED_RETRY_REQUIRED','APPROVED_PENDING_EXECUTION'}
        assert s.get(m.HostedDirectReservationRow,rid).check_in==h['day'].isoformat()
    assert counts()==before
    if failure=='missing_ari':ops.bootstrap_calendar(h['hotel'],{'start_date':start,'end_date':end})
    done=http.post(path,headers=ch,json=body);assert done.status_code==200,done.text
    after=counts();replay=http.post(path,headers=ch,json=body);assert replay.status_code==200
    assert counts()==after
    with SessionLocal() as s:
        assert s.get(m.HostedDirectReservationRow,rid).check_in==start
        assert s.get(m.HostedActionApprovalRow,aid).state=='APPROVED_EXECUTED'
        assert s.scalar(select(m.HostedInventoryDayRow.capacity_available).where(m.HostedInventoryDayRow.stay_date==h['day'].isoformat()))==5
        assert s.scalar(select(m.HostedInventoryDayRow.capacity_available).where(m.HostedInventoryDayRow.stay_date==start))==4


def test_staff_grant_requires_real_target_and_cannot_self_grant(http,ready):
    h=ready
    for target in [h['maker'].user_id,'missing']:
        response=http.post(f"/internal/v1/hosted-direct/hotels/{h['hotel']}/staff-roles",headers=h['maker_headers'],json={'staff_id':target,'role':'DUTY_MANAGER','evidence_reference':'claim'})
        assert response.status_code==403,response.text


def test_scope_checks_other_hotel_even_for_legitimate_operator(http,ready,monkeypatch,tmp_path):
    other=hotel_fixture(monkeypatch,tmp_path)
    assert http.put(f"/internal/v1/hosted-direct/rate-variants/{other['variant']}/days/{other['day']}",headers=ready['maker_headers'],json={'price_minor':1,'sale_state':'OPEN'}).status_code==403


def test_confirmed_uncharged_request_can_withdraw_and_updates_trips(http,ready):
    h=ready;rid=reserve(http,h)['hosted_reservation_id']
    confirm=http.post(f'/internal/v1/hosted-direct/reservations/{rid}/decision',headers=h['maker_headers'],json={'decision':'CONFIRM'})
    assert confirm.status_code==200,confirm.text
    with SessionLocal() as s:
        trip=s.scalar(select(m.ConsumerUnifiedLifecycleRow).where(m.ConsumerUnifiedLifecycleRow.order_id==rid))
        assert trip.lifecycle_state=='CONFIRMED' and trip.cancel_allowed
        assert s.get(m.HostedOrderFareSnapshotRow,rid)
        assert not s.scalar(select(m.AlipayAuthorizationRow).where(m.AlipayAuthorizationRow.hosted_reservation_id==rid))
    path=f'/v1/direct/reservations/{rid}/cancel'
    done=http.post(path,headers=h['customer_headers'])
    assert done.status_code==200,done.text
    before=counts();assert http.post(path,headers=h['customer_headers']).status_code==200
    assert counts()==before
    with SessionLocal() as s:
        trip=s.scalar(select(m.ConsumerUnifiedLifecycleRow).where(m.ConsumerUnifiedLifecycleRow.order_id==rid))
        assert trip.lifecycle_state=='CANCELLED' and not trip.cancel_allowed
        assert s.scalar(select(m.HostedInventoryDayRow.capacity_available).where(m.HostedInventoryDayRow.inventory_pool_id==h['pool'],m.HostedInventoryDayRow.stay_date==h['day'].isoformat()))==5
        assert s.get(m.HostedDirectReservationRow,rid).payment_state=='NO_PAYMENT_NO_REFUND_REQUIRED'


@pytest.mark.parametrize('boundary',['UNKNOWN_EXTERNAL_STATE','IN_HOUSE'])
def test_uncharged_exit_does_not_bypass_unknown_or_fulfilled_stay(http,ready,boundary):
    h=ready;rid=reserve(http,h)['hosted_reservation_id']
    assert http.post(f'/internal/v1/hosted-direct/reservations/{rid}/decision',headers=h['maker_headers'],json={'decision':'CONFIRM'}).status_code==200
    with SessionLocal.begin() as s:
        if boundary=='UNKNOWN_EXTERNAL_STATE':s.get(m.HostedDirectReservationRow,rid).payment_state=boundary
        else:
            from go_hotel.services.hosted_direct_booking import now
            s.add(m.GuestStayLifecycleRow(stay_lifecycle_id='synthetic-stay',hosted_reservation_id=rid,state='IN_HOUSE',planned_check_out=h['body']['check_out'],updated_at=now()))
    before=counts()
    response=http.post(f'/v1/direct/reservations/{rid}/cancel',headers=h['customer_headers'])
    assert response.status_code==409,response.text
    assert counts()==before


def test_finance_scope_covers_cross_hotel_mandate_and_global_lists(http,ready,monkeypatch,tmp_path):
    h=ready;other=hotel_fixture(monkeypatch,tmp_path)
    before=counts()
    for path in [f"hotels/{other['hotel']}/fault-finance",'disruptions','disruption-candidates']:
        response=http.get('/internal/v1/hosted-direct/'+path,headers=h['maker_headers'])
        assert response.status_code==403,response.text
    body={'currency':'CNY','maximum_per_case_minor':100,'expires_at':'2099-01-01T00:00:00Z','authority_reference':'isolated://scope-probe','authority_hash':'a'*64}
    response=http.post(f"/internal/v1/hosted-direct/hotels/{other['hotel']}/fault-mandates",headers=h['maker_headers'],json=body)
    assert response.status_code==403,response.text
    with SessionLocal() as s:assert not s.scalar(select(m.HostedFaultDebitMandateRow))
    assert counts()==before


def test_media_submitter_cannot_self_review_or_claim_another_identity(http,ready):
    h=ready
    with SessionLocal() as s:
        asset=s.scalar(select(m.HostedMediaAssetRow));storage=asset.storage_reference
        previous=publication.latest(s,h['hotel']);prior=previous.publication_review_id
    body={'asset_role':'HERO','storage_reference':storage,'rights_owner':'哈尔滨敖麓谷雅酒店','rights_evidence_reference':'isolated://new-media'}
    path=f"/internal/v1/hosted-direct/hotels/{h['hotel']}/media-assets"
    spoof=http.post(path,headers=h['checker_headers'],json={**body,'submitted_by':h['maker'].user_id})
    assert spoof.status_code==409,spoof.text
    added=http.post(path,headers=h['checker_headers'],json=body);assert added.status_code==200,added.text
    with SessionLocal() as s:
        asset=s.get(m.HostedMediaAssetRow,added.json()['data']['media_asset_id'])
        assert asset.submitted_by==h['checker'].user_id and asset.submitter_binding_hash
    preview=publication.preview(h['hotel'],h['maker'])
    review=http.post(f"/internal/v1/hosted-direct/hotels/{h['hotel']}/publication-review",headers=h['checker_headers'],json={'decision':'APPROVE','evidence_reference':'self','expected_manifest_hash':preview['manifest_hash'],'expected_review_id':prior})
    assert review.status_code==403,review.text
    assert http.get(f"/v1/direct/{h['slug']}").status_code==409


@pytest.mark.parametrize('extra',[1,999,True,'999',-1])
def test_extra_beds_without_structured_quantity_price_are_not_sold(http,ready,extra):
    h=ready;before=counts()
    response=http.post(f"/v1/direct/{h['slug']}/reservations",headers={**h['customer_headers'],'Idempotency-Key':'extra'},json={**h['body'],'extra_beds':extra})
    assert response.status_code==409,response.text
    assert counts()==before
