"""Persistent JWT rejection matrix for four executable hotel/money operations."""
from datetime import timedelta
import json
import pytest
from sqlalchemy import select
from tests.test_c01_aoluguya_business_day import http,business,purchase,post,window
from tests.hosted_review_support import identity,provision
from go_hotel.db import models as m
from go_hotel.db.session import SessionLocal
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service as booking,out
from go_hotel.services.hosted_frontdesk_uat import hosted_frontdesk_uat_service as desk
from go_hotel.services.hosted_operation_authority import ROOT_ROLE,scoped


MODELS=[m.HostedDirectReservationRow,m.HostedReservationStayRow,m.HostedReservationNightRow,
 m.HostedInventoryDayRow,m.HostedReservationNotificationRow,m.HostedDirectReservationEventRow,
 m.GuestStayLifecycleRow,m.GuestStayEventRow,m.StayFulfillmentEvidenceRow,
 m.SettlementEligibilityDecisionRow,m.AlipayAuthorizationRow,m.AlipaySafeguardedEventRow,
 m.OmnichannelPaymentIntentRow,m.PaymentOrderRootRow,m.PaymentOrderFactBindingRow,
 m.OmnichannelMoneyMovementRow,m.OmnichannelLedgerEntryRow,m.PostStayDisputeCaseRow,
 m.PostStayDecisionRow,m.RefundEligibilityRow,m.PostStayReconciliationRow,m.HostedDailyCloseRow]


def facts():
    with SessionLocal() as s:
        return {model.__name__:sorted(json.dumps(out(row),sort_keys=True,default=str)
            for row in s.scalars(select(model))) for model in MODELS}


def prepared_operation(http,h,action):
    if action=='daily_close':
        purchase(http,h,'authorized-close');h['clock']['at']=window(h['day'].isoformat())[1]
        return f"/internal/v1/hosted-direct/hotels/{h['hotel']}/daily-closes",{'business_date':h['day'].isoformat()},h['manager_headers']
    rid,aid=purchase(http,h,'authorized-'+action)
    sid=post(http,f'/internal/v1/stays/reservations/{rid}',h['maker_headers'])['stay_lifecycle_id']
    base=f'/internal/v1/stays/{sid}'
    post(http,base+'/arrive',h['maker_headers'])
    post(http,base+'/identity-evidence',h['maker_headers'],{'identity_evidence_hash':'e'*64,'verification_method':'HOTEL_DESK_DOCUMENT_CHECK'})
    post(http,base+'/room-assignment',h['maker_headers'],{'room_reference':'ISOLATED-ROUND-DREAM-101'})
    h['clock']['at']+=timedelta(hours=6)
    if action=='check_in':
        staff,headers=identity('positive-frontdesk',['GO_ORDER_OPS'])
        desk.assign_role(h['hotel'],{'staff_id':staff.user_id,'role':'FRONT_DESK','evidence_reference':'isolated://frontdesk'},h['maker'])
        return base+'/check-in',{'registration_evidence_reference':'isolated://valid-registration'},headers
    post(http,base+'/check-in',h['maker_headers'],{'registration_evidence_reference':'isolated://valid-registration'})
    h['clock']['at']+=timedelta(hours=4)
    proof={'hotel_fulfillment_evidence':'isolated://authority-folio','guest_checkout_reference':'isolated://authority-checkout','fulfilled_amount_minor':69800}
    post(http,base+'/check-out',h['maker_headers'],proof)
    post(http,base+'/settlement-eligibility',h['maker_headers'])
    post(http,f'/internal/v1/alipay/authorizations/{aid}/fulfill',h['maker_headers'],proof)
    finance,headers=identity('positive-finance',['GO_ORDER_OPS','GO_FINANCE'])
    desk.assign_role(h['hotel'],{'staff_id':finance.user_id,'role':'DUTY_MANAGER','evidence_reference':'isolated://finance'},h['maker'])
    capture_path=f'/internal/v1/alipay/authorizations/{aid}/capture'
    if action=='capture':return capture_path,{'mode':'CONTRACT_DRY_RUN'},headers
    post(http,capture_path,h['maker_headers'],{'mode':'CONTRACT_DRY_RUN'})
    case=post(http,f'/internal/v1/post-stay/stays/{sid}/cases',h['maker_headers'],{'opened_by_party':'GUEST','dispute_type':'SERVICE','assigned_to':'isolated-owner','initial_evidence_reference':'isolated://case'})['dispute_case_id']
    decision=post(http,f'/internal/v1/post-stay/cases/{case}/decisions',h['maker_headers'],{'outcome':'PARTIAL_REFUND','refund_amount_minor':9800})['post_stay_decision_id']
    post(http,f'/internal/v1/post-stay/decisions/{decision}/approve',h['checker_headers'],{'evidence_reference':'isolated://independent-decision'})
    eligibility=post(http,f'/internal/v1/post-stay/decisions/{decision}/refund-eligibility',h['checker_headers'])['refund_eligibility_id']
    return f'/internal/v1/post-stay/refund-eligibilities/{eligibility}/execute',None,headers


@pytest.mark.parametrize('action',['check_in','capture','refund','daily_close'])
@pytest.mark.parametrize('fault',['readonly','other_hotel','revoked_grant','revoked_session'])
def test_executable_operation_rejects_invalid_authority_without_business_writes(http,business,action,fault):
    h=business;path,body,valid_headers=prepared_operation(http,h,action)
    principal,headers=identity('denied-'+fault,['GO_READ_ONLY'] if fault=='readonly' else None)
    if fault=='other_hotel':
        other=booking.create_hotel({'supplier_name':'哈尔滨敖麓谷雅酒店','page_slug':'isolated-other-authority','contact':{'inventory_data_mode':'SIMULATION'}},'fixture')['hosted_hotel_id']
        provision(other,principal)
        with SessionLocal() as s:scoped(s,principal,other,'admin:rules',root_only=True)
    else:
        provision(h['hotel'],principal)
        with SessionLocal.begin() as s:
            if fault=='revoked_grant':s.scalar(select(m.HostedStaffRoleRow).where(m.HostedStaffRoleRow.hosted_hotel_id==h['hotel'],m.HostedStaffRoleRow.staff_id==principal.user_id,m.HostedStaffRoleRow.role==ROOT_ROLE)).state='REVOKED'
            if fault=='revoked_session':s.get(m.AuthSessionRow,principal.session_id).status='REVOKED'
    before=facts()
    denied=http.post(path,headers=headers,**({'json':body} if body is not None else {}))
    assert denied.status_code in {401,403},denied.text
    assert facts()==before
    result=post(http,path,valid_headers,body)
    assert facts()!=before
    if action=='check_in':assert result['state']=='IN_HOUSE'
    elif action=='capture':
        with SessionLocal() as s:assert s.query(m.OmnichannelMoneyMovementRow).filter_by(movement_type='CAPTURE',state='CONFIRMED').count()==1
    elif action=='refund':
        assert result['state']=='REFUND_COMPLETED'
        with SessionLocal() as s:
            assert s.query(m.RefundEligibilityRow).filter_by(decision='REFUND_CONFIRMED_SIMULATION').count()==1
            assert s.query(m.OmnichannelMoneyMovementRow).filter_by(movement_type='REFUND',state='CONFIRMED').count()==1
    else:assert result['daily_close_id'] and result['exception_summary_json']['blockers']==[]
