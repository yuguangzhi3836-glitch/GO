"""Supplier snapshots, time boundaries and real money/inventory atomicity."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (HostedOrderFareSnapshotRow as Snapshot,HostedFareRuleVersionRow as Rule,
    HostedFareQuoteRow as Quote,GuestStayLifecycleRow as Guest,AlipayAdjustmentApprovalRow as Approval,
    HostedDirectRoomOfferRow as Offer)
from go_hotel.services import hosted_fare_rules as fare
from tests.test_depth07_hosted_money import reservation,freeze,inventory,summary,ops,payment,guest,dispute,after,approve,funds,money,Reservation,Stay,Authorization,Ledger,trips

RULES={'fare_family':'ISOLATED TEST','timezone':'Asia/Shanghai','check_in_hour':14,'cooling_off_minutes':30,
    'cancellation_tiers':[{'min_hours':24,'fee_basis_points':0},{'min_hours':0,'fee_basis_points':5000}],
    'change_allowed':True,'change_fee_minor':0,'stay_credit_enabled':True,'stay_credit_days':365,
    'stay_credit_scope':'PROPERTY_ONLY','no_show_grace_hours':10,'no_show_fee_basis_points':8000}


def booked(client,monkeypatch,*,rules=None,cooling=False):
    old,account,h=reservation(client)
    rules=deepcopy(rules or RULES);published=fare.publish(old['hosted_offer_id'],rules,'test://hotel-explicit-authority','hotel')
    # Keep old orders historical; only a new booking receives the selected version.
    ops.action(old['hosted_reservation_id'],{'action':'CANCEL'},account,account,True,True)
    body={k:old[k] for k in ['hosted_offer_id','check_in','check_out','guest_name','guest_contact']}
    body['expected_fare_rule_hash']=published['rule_hash']
    r=ops.reserve('aoluguya-harbin',body,'fare-reserve','GO_PAGE',account)
    a=freeze(r,account)['authorization'];rid=r['hosted_reservation_id']
    ops.action(rid,{'action':'CONFIRM'},'hotel')
    t=datetime.fromisoformat(r['created_at'])+timedelta(minutes=1) if cooling else datetime.fromisoformat(r['check_in']).replace(hour=5,tzinfo=timezone.utc)
    monkeypatch.setattr(fare,'now',lambda:t)
    return r,account,h,a,published


def quote(r,account):return fare.create_quote(r['hosted_reservation_id'],'CANCEL_FOR_REFUND',account)


def execute(r,account,q):return fare.execute(r['hosted_reservation_id'],q['quote_id'],q['fee_minor'],r['currency'],account)


@pytest.mark.parametrize('field,value,error',[('stay_credit_days',366,'365'),('stay_credit_scope','GO_WALLET','PROPERTY_ONLY'),('change_allowed','yes','BOOLEAN'),('check_in_hour',True,'CHECK_IN'),('no_show_fee_basis_points',10001,'NO_SHOW'),('cancellation_tiers',[{'min_hours':24,'fee_basis_points':0}],'COMPLETE')])
def test_supplier_rules_reject_ambiguous_or_forbidden_terms(field,value,error):
    with pytest.raises(ValueError,match=error):fare.validated({**RULES,field:value})


def test_rule_publication_is_versioned_order_snapshot_is_not_retroactive(client,monkeypatch):
    r,account,h,a,p=booked(client,monkeypatch)
    q=quote(r,account);assert q['fee_minor']==81000
    newer=fare.publish(r['hosted_offer_id'],{**RULES,'cancellation_tiers':[{'min_hours':0,'fee_basis_points':10000}]},'test://new-policy','hotel')
    assert newer['version']==2 and quote(r,account)['fee_minor']==81000
    assert fare.publish(r['hosted_offer_id'],{**RULES,'cancellation_tiers':[{'min_hours':0,'fee_basis_points':10000}]},'test://new-policy','hotel')['version']==2
    with SessionLocal() as s:assert s.get(Snapshot,r['hosted_reservation_id']).rule_version_id==p['rule_version_id']
    body={k:r[k] for k in ['hosted_offer_id','check_in','check_out','guest_name','guest_contact']}
    with pytest.raises(ValueError,match='FARE_RULE_CHANGED'):ops.reserve('aoluguya-harbin',{**body,'expected_fare_rule_hash':p['rule_hash']},'old-policy','GO_PAGE',account)


@pytest.mark.parametrize('cooling,fee',[(True,0),(False,81000)])
def test_cancellation_quote_consent_atomic_inventory_money_and_idempotent_replay(client,monkeypatch,cooling,fee):
    r,account,h,a,p=booked(client,monkeypatch,cooling=cooling);q=quote(r,account)
    assert q['fee_minor']==fee and q['cash_refund_minor']==0
    path='/v1/direct/reservations/'+r['hosted_reservation_id']+'/fare/cancel'
    body={'quote_id':q['quote_id'],'expected_fee_minor':fee,'currency':'CNY'}
    for wrong in [{**body,'expected_fee_minor':True},{**body,'expected_fee_minor':fee+1},{**body,'currency':'USD'},{**body,'refund_amount_minor':r['amount_minor']}]:
        assert client.post(path,headers=h,json=wrong).status_code in {409,422}
    first=client.post(path,headers=h,json=body);assert first.status_code==200,first.text
    assert client.post(path,headers=h,json=body).json()==first.json()
    x=summary(r);assert (x['capture_minor'],x['held_minor'],x['release_minor'])==(fee,0,r['amount_minor']-fee)
    assert inventory(r)==[('RELEASED',8),('RELEASED',8)]
    assert trips.list(account)[0]['lifecycle_state']=='CANCELLED'
    with SessionLocal() as s:
        ledger=list(s.scalars(select(Ledger)));assert len(ledger)==(2 if fee else 0)
        assert sum(x.amount_minor for x in ledger if x.direction=='DEBIT')==sum(x.amount_minor for x in ledger if x.direction=='CREDIT')==fee


def test_fare_quote_owner_expiry_stale_state_and_hash_are_enforced(client,monkeypatch):
    r,account,h,a,p=booked(client,monkeypatch);q=quote(r,account)
    with pytest.raises(ValueError,match='RESERVATION_NOT_FOUND'):execute(r,'other',q)
    with SessionLocal.begin() as s:s.get(Quote,q['quote_id']).expires_at=fare.now()-timedelta(seconds=1)
    with pytest.raises(ValueError,match='EXPIRED'):execute(r,account,q)
    q=quote(r,account)
    guest.create(r['hosted_reservation_id'],'hotel')
    with pytest.raises(ValueError,match='ORDER_CHANGED'):execute(r,account,q)
    q=quote(r,account)
    with SessionLocal.begin() as s:s.get(Quote,q['quote_id']).quote_json={**q,'fee_minor':1}
    with pytest.raises(ValueError,match='HASH_MISMATCH'):execute(r,account,q)
    assert summary(r)['held_minor']==r['amount_minor']


def test_cooling_and_tier_boundaries_force_fresh_quote(client,monkeypatch):
    r,account,h,a,p=booked(client,monkeypatch,cooling=True);q=quote(r,account)
    assert q['cooling_off_applied']
    monkeypatch.setattr(fare,'now',lambda:datetime.fromisoformat(q['expires_at']))
    with pytest.raises(ValueError,match='EXPIRED'):execute(r,account,q)
    boundary=datetime.fromisoformat(r['check_in']).replace(hour=6,tzinfo=timezone.utc)
    with SessionLocal.begin() as s:s.get(Reservation,r['hosted_reservation_id']).created_at=boundary-timedelta(days=3)
    monkeypatch.setattr(fare,'now',lambda:boundary-timedelta(hours=24,seconds=1))
    q=quote(r,account);assert q['fee_minor']==0 and datetime.fromisoformat(q['expires_at'])==boundary-timedelta(hours=24)
    monkeypatch.setattr(fare,'now',lambda:boundary-timedelta(hours=24)+timedelta(microseconds=1))
    assert quote(r,account)['fee_minor']==81000


def test_unconfigured_old_order_never_inherits_new_fee_rule(client,monkeypatch):
    r,account,h=reservation(client);fare.publish(r['hosted_offer_id'],RULES,'test://policy','hotel');freeze(r,account);ops.action(r['hosted_reservation_id'],{'action':'CONFIRM'},'hotel')
    with pytest.raises(ValueError,match='SNAPSHOT_REQUIRED'):quote(r,account)
    with SessionLocal() as s:assert fare.options(s,s.get(Reservation,r['hosted_reservation_id']),s.get(Stay,r['hosted_reservation_id']))['configured'] is False


def test_confirmed_free_release_and_old_cancel_routes_cannot_bypass_fare(client,monkeypatch):
    r,account,h,a,p=booked(client,monkeypatch)
    with pytest.raises(ValueError,match='FARE_QUOTE_REQUIRED'):payment.release(a['authorization_id'],{'reason':'FREE_CANCELLATION'},'hotel')
    with pytest.raises(ValueError,match='FARE_QUOTE_REQUIRED'):ops.action(r['hosted_reservation_id'],{'action':'CANCEL'},'hotel')
    assert summary(r)['held_minor']==r['amount_minor']


def test_money_or_projection_fault_rolls_back_quote_fee_release_and_inventory(client,monkeypatch):
    r,account,h,a,p=booked(client,monkeypatch);q=quote(r,account);post=money._post
    def fail(s,i,m):post(s,i,m);raise RuntimeError('injected ledger outage')
    monkeypatch.setattr(money,'_post',fail)
    with pytest.raises(RuntimeError):execute(r,account,q)
    assert summary(r)['held_minor']==r['amount_minor'] and inventory(r)==[('HELD',7),('HELD',7)]
    with SessionLocal() as s:assert s.get(Quote,q['quote_id']).state=='QUOTED' and list(s.scalars(select(Ledger)))==[]
    monkeypatch.setattr(money,'_post',post);project=funds.project
    monkeypatch.setattr(funds,'project',lambda *args:(_ for _ in ()).throw(RuntimeError('projection offline')))
    with pytest.raises(RuntimeError):execute(r,account,q)
    assert summary(r)['held_minor']==r['amount_minor']
    monkeypatch.setattr(funds,'project',project);execute(r,account,q)
    assert summary(r)['capture_minor']==81000


def test_parallel_cancel_quotes_settle_exactly_once(client,monkeypatch):
    r,account,h,a,p=booked(client,monkeypatch);qs=[quote(r,account) for _ in range(3)]
    def attempt(q):
        try:return execute(r,account,q)['state']
        except ValueError as e:return str(e)
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(attempt,qs))
    assert results.count('CANCELLED')==1 and summary(r)['capture_minor']==81000 and inventory(r)==[('RELEASED',8),('RELEASED',8)]


def no_show_ready(client,monkeypatch,fee_bps=8000):
    r,account,h,a,p=booked(client,monkeypatch,rules={**RULES,'no_show_fee_basis_points':fee_bps})
    sid=guest.create(r['hosted_reservation_id'],'hotel')['stay_lifecycle_id']
    with pytest.raises(ValueError,match='DEADLINE'):fare.create_quote(r['hosted_reservation_id'],'NO_SHOW')
    deadline=datetime.fromisoformat(r['check_in']).replace(hour=16,tzinfo=timezone.utc)
    monkeypatch.setattr(fare,'now',lambda:deadline)
    q=fare.create_quote(r['hosted_reservation_id'],'NO_SHOW')
    approval=fare.request_no_show(r['hosted_reservation_id'],q['quote_id'],'hotel')
    assert fare.request_no_show(r['hosted_reservation_id'],q['quote_id'],'hotel')==approval
    with pytest.raises(ValueError,match='MAKER_CHECKER'):payment.approve_adjustment(approval['adjustment_approval_id'],{'evidence_reference':'test://review'},'hotel')
    payment.approve_adjustment(approval['adjustment_approval_id'],{'evidence_reference':'test://independent-review'},'checker')
    body={'fare_quote_id':q['quote_id'],'expected_fee_minor':q['fee_minor'],'currency':'CNY','approval_id':approval['adjustment_approval_id'],'hotel_no_show_evidence':'test://desk-confirmation'}
    return r,account,h,a,sid,q,body


@pytest.mark.parametrize('fee_bps',[0,8000,10000])
def test_no_show_deadline_rule_approval_inventory_and_original_fee_refund(client,monkeypatch,fee_bps):
    r,account,h,a,sid,q,body=no_show_ready(client,monkeypatch,fee_bps)
    with pytest.raises(ValueError,match='CANCELLATION_WINDOW'):quote(r,account)
    with pytest.raises(ValueError,match='APPROVAL'):guest.no_show(sid,{**body,'approval_id':'other'},'hotel')
    result=guest.no_show(sid,body,'hotel');assert guest.no_show(sid,body,'hotel')==result
    assert summary(r)['capture_minor']==q['fee_minor'] and summary(r)['held_minor']==0
    assert inventory(r)==[('RELEASED',8),('RELEASED',8)] and trips.list(account)[0]['lifecycle_state']=='COMPLETED'
    with pytest.raises(ValueError,match='PRE_ARRIVAL'):ops.reschedule(r['hosted_reservation_id'],{'check_in':r['check_in'],'check_out':r['check_out']},'hotel')
    status=client.get('/v1/direct/reservations/'+r['hosted_reservation_id'],headers=h).json()['data']['after_sales']
    assert status['can_open_case']
    if q['fee_minor']:
        case=after.open_case(account,r['hosted_reservation_id'],'NO_SHOW','客人对未到店认定有异议','no-show-case')
        _,e=approve(sid,q['fee_minor'],case['case_id']);after.retry_refund(account,r['hosted_reservation_id'],e['refund_eligibility_id'])
        assert summary(r)['refund_minor']==q['fee_minor']


def test_cancelled_fee_can_be_disputed_without_reopening_or_fabricating_a_stay(client,monkeypatch):
    r,account,h,a,p=booked(client,monkeypatch);execute(r,account,quote(r,account))
    case=after.open_case(account,r['hosted_reservation_id'],'CANCELLATION','取消费复核','cancel-fee-case')
    with SessionLocal() as s:
        x=s.scalar(select(Guest).where(Guest.hosted_reservation_id==r['hosted_reservation_id']));sid=x.stay_lifecycle_id
        assert x.state=='CANCELLED' and x.actual_check_in_at is None and x.actual_check_out_at is None
    _,e=approve(sid,81000,case['case_id']);after.retry_refund(account,r['hosted_reservation_id'],e['refund_eligibility_id'])
    dispute.close(case['case_id'],{'closure_evidence_reference':'test://closed'},'manager')
    assert summary(r)['refund_minor']==81000 and trips.list(account)[0]['lifecycle_state']=='CANCELLED'
