"""Direct room inventory, guest fulfillment and cash share one durable graph."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date,datetime,timedelta,timezone
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (OmnichannelMoneyMovementRow as Movement,OmnichannelLedgerEntryRow as Ledger,
    PaymentOrderRootRow as Root,PaymentOrderFactBindingRow as Binding,VerticalSourceDecisionRow as Source,
    OmnichannelPaymentIntentRow as Intent,StayDisputeRow as Mirror,RefundEligibilityRow as Refund,
    PostStayDecisionRow as Decision,PostStayDisputeCaseRow as Case,ConsumerUnifiedLifecycleRow as Trip)
from tests.test_depth06_direct_checkout import reservation,freeze,inventory,Reservation,Stay,Authorization,ops,payment
from go_hotel.services.guest_stay_fulfillment import guest_stay_fulfillment_service as guest
from go_hotel.services.post_stay_dispute import post_stay_dispute_service as dispute
from go_hotel.services.consumer_unified_lifecycle import consumer_unified_lifecycle_service as trips
from go_hotel.services import hosted_money as funds,hosted_after_sales as after
from go_hotel.services.unified_money_movement import unified_money_movement_service as money
from tests.test_sprint3a_flight import auth

PROOF={'hotel_fulfillment_evidence':'hotel-test://folio','guest_checkout_reference':'guest-test://checkout'}


def checked_out(client,amount=None):
    r,account,h=reservation(client);a=freeze(r,account)['authorization'];rid=r['hosted_reservation_id']
    ops.action(rid,{'action':'CONFIRM','hotel_confirmation_reference':'SIM-HOTEL'},'hotel')
    sid=guest.create(rid,'hotel')['stay_lifecycle_id']
    guest.identity(sid,{'identity_evidence_hash':'a'*64,'verification_method':'HOTEL_DESK_DOCUMENT_CHECK'},'hotel')
    guest.arrive(sid,'hotel');guest.assign_room(sid,{'room_reference':'SIM-101'},'hotel')
    guest.check_in(sid,{'registration_evidence_reference':'test://registration'},'hotel')
    assert trips.list(account)[0]['lifecycle_state']=='IN_PROGRESS'
    guest.checkout(sid,{**PROOF,'fulfilled_amount_minor':r['amount_minor'] if amount is None else amount},'hotel')
    return r,account,h,a,sid


def captured(client,amount=None):
    r,account,h,a,sid=checked_out(client,amount)
    payment.fulfill(a['authorization_id'],PROOF,'hotel')
    payment.capture(a['authorization_id'],{'mode':'CONTRACT_DRY_RUN'})
    return r,account,h,a,sid


def summary(r):
    with SessionLocal() as s:return funds.summary(s,s.get(Reservation,r['hosted_reservation_id']))


def new_case(sid,kind='SERVICE'):
    return dispute.open_case(sid,{'opened_by_party':'GUEST','dispute_type':kind,'assigned_to':'go-test','description':'测试服务争议'},'guest')['dispute_case_id']


def approve(sid,amount,case_id=None):
    cid=case_id or new_case(sid)
    d=dispute.request_decision(cid,{'outcome':'PARTIAL_REFUND' if amount else 'NO_REFUND','refund_amount_minor':amount},'maker')
    dispute.approve_decision(d['post_stay_decision_id'],{'evidence_reference':'test://independent-review'},'checker')
    return cid,dispute.refund_eligibility(d['post_stay_decision_id'])


def test_authorization_binds_selected_room_owner_hotel_and_has_no_cash_posting(client):
    r,account,h=reservation(client);freeze(r,account);freeze(r,account)
    x=summary(r)
    assert x['authorization_minor']==x['held_minor']==r['amount_minor'] and x['capture_minor']==0
    assert [m['type'] for m in x['movements']]==['AUTHORIZATION']
    with SessionLocal() as s:
        intent=s.get(Intent,x['payment_intent_id']);b=s.scalar(select(Binding));source=s.get(Source,b.source_decision_id)
        assert intent.payer_id==account and intent.payee_id==source.selected_source_id
        assert source.business_id==r['hosted_reservation_id'] and source.selected_source_type=='HOSTED_DIRECT_SIMULATION'
        assert source.candidate_snapshot_json[0]['hosted_offer_id']==r['hosted_offer_id']
        assert s.scalars(select(Ledger)).all()==[]
    assert client.get('/v1/direct/reservations/'+r['hosted_reservation_id'],headers=h).json()['data']['after_sales']['funds']==x


@pytest.mark.parametrize('action',['CANCEL','REJECT','EXPIRE'])
def test_cancel_reject_expiry_release_graph_and_nightly_inventory_without_cash_refund(client,action):
    r,account,_=reservation(client);freeze(r,account)
    if action=='EXPIRE':
        with SessionLocal.begin() as s:s.get(Stay,r['hosted_reservation_id']).confirmation_expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
        assert ops.expire_pending()['expired_count']==1
    else:ops.action(r['hosted_reservation_id'],{'action':action},account,account,True,True)
    x=summary(r);assert x['held_minor']==x['capture_minor']==x['refund_minor']==0 and x['release_minor']==r['amount_minor']
    assert inventory(r)==[('RELEASED',8),('RELEASED',8)]
    assert trips.list(account)[0]['payment_state']=='RELEASED'
    with SessionLocal() as s:assert not s.scalars(select(Ledger)).all()


def test_release_and_inventory_rollback_if_projection_fails_then_retry_once(client,monkeypatch):
    r,account,_=reservation(client);a=freeze(r,account)['authorization'];project=funds.project
    def fail(*args):raise RuntimeError('injected projection failure')
    monkeypatch.setattr(funds,'project',fail)
    with pytest.raises(RuntimeError):ops.action(r['hosted_reservation_id'],{'action':'CANCEL'},account,account,True,True)
    assert summary(r)['release_minor']==0 and inventory(r)==[('HELD',7),('HELD',7)]
    with SessionLocal() as s:assert s.get(Authorization,a['authorization_id']).state=='CONTRACT_FROZEN_NOT_ALIPAY'
    monkeypatch.setattr(funds,'project',project)
    ops.action(r['hosted_reservation_id'],{'action':'CANCEL'},account,account,True,True)
    assert summary(r)['release_minor']==r['amount_minor']


@pytest.mark.parametrize('amount',[162000,81001,0])
def test_capture_only_dual_confirmed_fulfillment_and_release_unused_amount(client,amount):
    r,account,h,a,sid=captured(client,amount)
    x=summary(r);assert x['capture_minor']==amount and x['release_minor']==r['amount_minor']-amount and x['held_minor']==0
    assert trips.list(account)[0]['lifecycle_state']=='COMPLETED'
    again=payment.capture(a['authorization_id'],{'mode':'CONTRACT_DRY_RUN'})
    assert summary(r)==x
    with SessionLocal() as s:
        ledger=s.scalars(select(Ledger)).all()
        assert len(ledger)==(2 if amount else 0)
        assert sum(v.amount_minor for v in ledger if v.direction=='DEBIT')==sum(v.amount_minor for v in ledger if v.direction=='CREDIT')==amount
    assert payment.reconcile(a['authorization_id'])['payment_amount_minor']==amount


def test_fulfillment_cannot_bypass_stay_or_change_proof_and_dispute_rechecks_at_capture(client):
    r,account,_,a,sid=checked_out(client)
    with pytest.raises(ValueError,match='FULFILLMENT_REFERENCE_MISMATCH'):payment.fulfill(a['authorization_id'],{**PROOF,'guest_checkout_reference':'other'},'hotel')
    payment.fulfill(a['authorization_id'],PROOF,'hotel')
    new_case(sid)
    with pytest.raises(ValueError,match='OPEN_FULFILLMENT_DISPUTE'):payment.capture(a['authorization_id'],{'mode':'CONTRACT_DRY_RUN'})
    assert summary(r)['held_minor']==r['amount_minor'] and summary(r)['capture_minor']==0


def test_capture_ledger_fault_rolls_back_cash_release_and_order_then_retries(client,monkeypatch):
    r,account,h,a,sid=checked_out(client,81000);payment.fulfill(a['authorization_id'],PROOF,'hotel')
    post=money._post
    def fail(s,i,m):post(s,i,m);raise RuntimeError('ledger unavailable')
    monkeypatch.setattr(money,'_post',fail)
    with pytest.raises(RuntimeError):payment.capture(a['authorization_id'],{'mode':'CONTRACT_DRY_RUN'})
    assert summary(r)['held_minor']==r['amount_minor'] and summary(r)['capture_minor']==summary(r)['release_minor']==0
    with SessionLocal() as s:assert not s.scalars(select(Ledger)).all()
    monkeypatch.setattr(money,'_post',post)
    payment.capture(a['authorization_id'],{'mode':'CONTRACT_DRY_RUN'})
    assert summary(r)['capture_minor']==summary(r)['release_minor']==81000


def test_simultaneous_capture_retries_post_once(client):
    r,_,_,a,sid=checked_out(client);payment.fulfill(a['authorization_id'],PROOF,'hotel')
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda _:payment.capture(a['authorization_id'],{'mode':'CONTRACT_DRY_RUN'}),range(3)))
    assert results[0]==results[1]==results[2]
    assert len([m for m in summary(r)['movements'] if m['type']=='CAPTURE'])==1


def test_partial_refund_is_durable_original_capture_and_only_closes_its_case(client,monkeypatch):
    r,account,h,a,sid=captured(client,81001);cid,elig=approve(sid,10001);other=new_case(sid,'AMOUNT')
    with pytest.raises(ValueError,match='REFUND_COMPLETION_REQUIRED'):dispute.close(cid,{'closure_evidence_reference':'test://close'},'manager')
    post=money._post
    def fail(s,i,m):post(s,i,m);raise RuntimeError('refund ledger interrupted')
    monkeypatch.setattr(money,'_post',fail)
    with pytest.raises(RuntimeError):dispute.execute_refund(elig['refund_eligibility_id'])
    assert summary(r)['refund_state']=='REFUND_PROCESSING' and summary(r)['refund_minor']==0
    with SessionLocal() as s:
        assert s.get(Refund,elig['refund_eligibility_id']).decision=='REFUND_PENDING_SIMULATION'
        assert len(s.scalars(select(Ledger)).all())==2
    monkeypatch.setattr(money,'_post',post)
    result=after.retry_refund(account,r['hosted_reservation_id'],elig['refund_eligibility_id'])
    assert dispute.execute_refund(elig['refund_eligibility_id'])==result
    assert result['original_capture_id']==elig['original_payment_reference']
    assert summary(r)['refund_minor']==10001 and trips.list(account)[0]['refund_state']=='REFUND_COMPLETED'
    dispute.close(cid,{'closure_evidence_reference':'test://close'},'manager')
    with SessionLocal() as s:
        assert s.get(Mirror,'sdp_'+cid).state=='CLOSED' and s.get(Mirror,'sdp_'+other).state=='OPEN_SETTLEMENT_FROZEN'
        ledger=s.scalars(select(Ledger)).all();assert len(ledger)==4
        assert sum(x.amount_minor for x in ledger if x.direction=='DEBIT')==sum(x.amount_minor for x in ledger if x.direction=='CREDIT')==91002
    assert payment.reconcile(a['authorization_id'])['refund_amount_minor']==10001
    assert dispute.reconcile(cid)['settlement_eligible_minor']==81001


def test_two_partial_refunds_start_distinct_cycles_without_resetting_trip_completion(client):
    r,account,_,a,sid=captured(client,81001)
    first,e1=approve(sid,30000);dispute.execute_refund(e1['refund_eligibility_id'])
    second,e2=approve(sid,51001)
    with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(lambda _:dispute.execute_refund(e2['refund_eligibility_id']),range(2)))
    assert result[0]==result[1]
    x=summary(r);assert x['refund_minor']==81001 and x['refund_cycle_count']==2 and x['refund_state']=='REFUND_COMPLETED'
    assert trips.list(account)[0]['lifecycle_state']=='COMPLETED'
    with pytest.raises(ValueError,match='REFUND_EXCEEDS'):approve(sid,1)


def test_parallel_refund_approvals_cannot_overcommit_actual_capture(client):
    r,_,_,a,sid=captured(client,80000)
    ds=[dispute.request_decision(new_case(sid),{'outcome':'PARTIAL_REFUND','refund_amount_minor':60000},'maker') for _ in range(2)]
    def attempt(d):
        try:dispute.approve_decision(d['post_stay_decision_id'],{'evidence_reference':'test://review'},'checker');return 'APPROVED'
        except ValueError as e:return str(e)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,ds))
    assert results.count('APPROVED')==1 and any('REFUND_EXCEEDS' in x for x in results)


def test_approval_checks_independent_actor_actual_cash_full_amount_and_closed_case(client):
    r,_,_,a,sid=captured(client,80000);cid=new_case(sid)
    d=dispute.request_decision(cid,{'outcome':'FULL_REFUND','refund_amount_minor':5000},'maker')
    with pytest.raises(ValueError,match='MAKER_CHECKER'):dispute.approve_decision(d['post_stay_decision_id'],{'evidence_reference':'proof'},'maker')
    with pytest.raises(ValueError,match='FULL_REFUND_MUST_EQUAL'):dispute.approve_decision(d['post_stay_decision_id'],{'evidence_reference':'proof'},'checker')
    _,e=approve(sid,0,cid);dispute.close(cid,{'closure_evidence_reference':'test://closed'},'manager')
    with pytest.raises(ValueError,match='DISPUTE_CASE_CLOSED'):dispute.approve_decision(d['post_stay_decision_id'],{'evidence_reference':'proof'},'checker')


def test_owner_after_sales_api_idempotency_and_refund_permissions(client):
    r,account,h,a,sid=captured(client,80000);rid=r['hosted_reservation_id'];path='/v1/direct/reservations/'+rid
    body={'dispute_type':'SERVICE','description':'入住服务未达约定'};headers={**h,'Idempotency-Key':'case-submit-1'}
    first=client.post(path+'/cases',headers=headers,json=body);assert first.status_code==200,first.text
    assert client.post(path+'/cases',headers=headers,json=body).json()==first.json()
    assert client.post(path+'/cases',headers=headers,json={**body,'description':'changed'}).status_code==409
    assert client.post(path+'/cases',headers=headers,json={**body,'refund_amount_minor':80000}).status_code==422
    cid=first.json()['data']['case_id'];_,e=approve(sid,12345,cid)
    other=auth(client,'another-stay-owner@example.com')
    assert client.post(path+'/refunds/'+e['refund_eligibility_id']+'/retry',headers=other).status_code==409
    assert client.get(path,headers=other).status_code==404
    assert summary(r)['refund_minor']==0
    result=client.post(path+'/refunds/'+e['refund_eligibility_id']+'/retry',headers=h)
    assert result.status_code==200,result.text
    status=client.get(path,headers=h).json()['data']['after_sales']
    assert status['funds']['refund_minor']==12345 and status['cases'][0]['retry_allowed'] is False
    assert 'requester_id' not in str(status) and 'evidence_reference' not in str(status)
    trip=trips.list(account)[0]
    assert trip['order_id']==rid and trip['facts_json']['detail_url']=='/go-app/direct.html?reservation='+rid
    assert trips.list('another-account')==[]


def test_terminal_refund_still_rejects_unproven_cycle_reset():
    body={'account_id':'owner','vertical':'HOTEL','order_id':'old','title':'Hotel','lifecycle_state':'COMPLETED',
        'payment_state':'PAID','refund_state':'REFUND_COMPLETED','source_updated_at':'2026-09-01T00:00:00Z','evidence_reference':'test://old','facts':{'refund_cycle_count':1}}
    trips.project(body)
    with pytest.raises(ValueError,match='REFUND_STATE_IMMUTABLE'):
        trips.project({**body,'refund_state':'REFUND_PROCESSING','source_updated_at':'2026-09-02T00:00:00Z','facts':{'refund_cycle_count':99}})


def test_released_authorization_retry_is_actionable_not_unique_constraint_failure(client):
    r,account,_=reservation(client);a=freeze(r,account)['authorization']
    payment.release(a['authorization_id'],{'reason':'FREE_CANCELLATION'},'hotel')
    with pytest.raises(ValueError,match='REBOOK_REQUIRED'):freeze(r,account)
    with pytest.raises(ValueError,match='REBOOK_REQUIRED'):payment.authorize(r['hosted_reservation_id'],{'mode':'CONTRACT_DRY_RUN'},'new-admin-key')


def test_pending_hotel_has_no_guest_stay_and_graph_extension_cannot_fake_inventory(client):
    r,account,_=reservation(client);freeze(r,account)
    with pytest.raises(ValueError,match='CONFIRMED_RESERVATION_REQUIRED'):guest.create(r['hosted_reservation_id'],'hotel')
    ops.action(r['hosted_reservation_id'],{'action':'CONFIRM','hotel_confirmation_reference':'SIM-HOTEL'},'hotel')
    sid=guest.create(r['hosted_reservation_id'],'hotel')['stay_lifecycle_id']
    guest.identity(sid,{'identity_evidence_hash':'a'*64,'verification_method':'HOTEL_DESK_DOCUMENT_CHECK'},'hotel')
    guest.arrive(sid,'hotel');guest.assign_room(sid,{'room_reference':'SIM-101'},'hotel');guest.check_in(sid,{'registration_evidence_reference':'test://reg'},'hotel')
    with pytest.raises(ValueError,match='EXTENSION_DATED_INVENTORY_AND_PRICE_CONFIRMATION_REQUIRED'):
        guest.extend(sid,{'new_check_out':(date.fromisoformat(r['check_out'])+timedelta(days=1)).isoformat(),'inventory_extension_reference':'unverified'},'hotel')
    assert inventory(r)==[('HELD',7),('HELD',7)]


def test_unknown_money_or_external_authorization_blocks_refund_before_claim(client):
    r,account,h,a,sid=captured(client);cid,e=approve(sid,10000)
    with SessionLocal.begin() as s:s.get(Authorization,a['authorization_id']).state='UNKNOWN_EXTERNAL_STATE'
    with pytest.raises(ValueError,match='PAYMENT_RECONCILIATION_REQUIRED'):dispute.execute_refund(e['refund_eligibility_id'])
    with SessionLocal() as s:assert s.get(Refund,e['refund_eligibility_id']).decision=='REFUND_ELIGIBLE_CONTRACT_ONLY'
    assert summary(r)['reconciliation_required'] and summary(r)['refund_minor']==0
