from tests.test_depth10_hosted_disruption import (datetime,timedelta,timezone,ThreadPoolExecutor,pytest,select,SessionLocal,Disruption,Account,Liability,Compensation,Intent,Mandate,Offer,fault,funding,legacy_finance,booked,credited,approved,start,EVIDENCE,summary,inventory,Reservation,Ledger,Authorization,money)
from fastapi import HTTPException
from go_hotel.db.models import HostedDirectReservationEventRow as Event,HostedFaultRecoveryRow as Recovery


def test_guest_liability_hold_cannot_pay_and_only_new_evidence_reopens_with_history(client,monkeypatch):
    r,account,h,a,p=booked(client,monkeypatch);hotel,c=approved(r,account,'GUEST_FRAUD')
    assert c['state']=='GUEST_LIABILITY_POLICY_REQUIRED' and not c['financial_decision_approved']
    assert c['refund_due_minor'] is None and c['compensation_due_minor'] is None and c['refund_state']=='NOT_APPROVED'
    with pytest.raises(ValueError,match='APPROVED_SUPPLIER'):fault.execute(c['case_id'])
    assert fault.add_evidence(c['case_id'],EVIDENCE,'someone-else')['state']=='GUEST_LIABILITY_POLICY_REQUIRED'
    reopened=fault.add_evidence(c['case_id'],{**EVIDENCE,'reference':'test://corrected-proof','sha256':'c'*64},'hotel-maker')
    assert reopened['state']=='INDEPENDENT_REVIEW_REQUIRED' and reopened['decision_hash'] is None
    revised=fault.review(c['case_id'],'NO_ROOM',reopened['evidence_ids'],'test://independent-correction','checker-2',reopened['evidence_hash'])
    assert revised['state']=='APPROVED' and revised['decision_hash']!=c['decision_hash']
    with SessionLocal() as s:
        events=s.scalars(select(Event).where(Event.hosted_reservation_id==r['hosted_reservation_id'])).all()
        prior=next(e for e in events if e.event_type=='SUPPLIER_FAULT_REVIEW_REOPENED').payload_json
        assert prior['prior_decision_hash']==c['decision_hash'] and prior['prior_decision']['confirmed_cause']=='GUEST_FRAUD'
        assert any(e.event_type=='SUPPLIER_FAULT_GUEST_POLICY_REQUIRED' for e in events)
    assert summary(r)['held_minor']==162000


def test_expired_mandate_does_not_debit_bank(client,monkeypatch):
    original,r,account,credit=credited(client,monkeypatch);hotel,c=approved(r,account)
    legacy_finance.configure_supplier_finance(hotel,0,0,200000,True)
    mandate=funding.register_mandate(hotel,'CNY',200000,(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),'test://expires','b'*64,'finance')
    monkeypatch.setattr(funding,'now',lambda:datetime.now(timezone.utc)+timedelta(days=2))
    assert fault.execute(c['case_id'])['state']=='COMPENSATION_PENDING'
    with SessionLocal() as s:assert s.get(Account,hotel).bank_available_minor==200000


def test_refund_interruption_cannot_start_compensation_and_retry_is_exact(client,monkeypatch):
    original,r,account,credit=credited(client,monkeypatch);hotel,c=approved(r,account)
    legacy_finance.configure_supplier_finance(hotel,162000,0,0,False);post=money._post
    def fail(s,i,m):
        post(s,i,m)
        if m.movement_type=='REFUND':raise RuntimeError('refund ledger interrupted')
    monkeypatch.setattr(money,'_post',fail)
    with pytest.raises(RuntimeError,match='interrupted'):fault.execute(c['case_id'])
    assert fault.status(c['case_id'])['state']=='CANCELLED_REFUND_PENDING'
    assert summary(original)['refund_minor']==0 and inventory(r)==[('RELEASED',8),('RELEASED',8)]
    with SessionLocal() as s:assert not s.scalars(select(Compensation)).all() and s.get(Account,hotel).settlement_available_minor==162000
    monkeypatch.setattr(money,'_post',post);assert fault.execute(c['case_id'])['state']=='COMPLETED'
    assert summary(original)['refund_minor']==162000


def test_concurrent_recovery_and_legacy_guard_preserve_finite_fund(client,monkeypatch):
    original,r,account,credit=credited(client,monkeypatch);hotel,c=approved(r,account)
    legacy_finance.configure_supplier_finance(hotel,0,0,0,False)
    legacy_finance.configure_supplier_finance(funding.PROTECTION_ACCOUNT,0,200000,0,False);fault.execute(c['case_id'])
    with pytest.raises(HTTPException) as rejected:legacy_finance.apply_future_settlement(hotel,162000)
    assert rejected.value.detail['code']=='SCOPED_FAULT_RECOVERY_REQUIRED'
    with ThreadPoolExecutor(max_workers=4) as pool:
        result=list(pool.map(lambda n:funding.recover(hotel,170000,'test://one-settlement','key-'+str(n),'finance'),range(4)))
    assert all(x==result[0] for x in result) and result[0]['new_available_minor']==8000
    with SessionLocal() as s:
        assert len(s.scalars(select(Recovery)).all())==1
        assert s.get(Account,funding.PROTECTION_ACCOUNT).reserve_available_minor==200000
        assert s.get(Account,hotel).negative_balance_minor==0 and s.get(Account,hotel).settlement_available_minor==8000


def test_repeated_mandate_document_cannot_change_limit_or_resurrect_revoked_authority(client,monkeypatch):
    r,account,h,a,p=booked(client,monkeypatch)
    with SessionLocal() as s:hotel=s.get(Offer,r['hosted_offer_id']).hosted_hotel_id
    expiry=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    first=funding.register_mandate(hotel,'CNY',10000,expiry,'test://one-signed-document','a'*64,'maker')
    again=funding.register_mandate(hotel,'CNY',10000,expiry,'test://one-signed-document','a'*64,'maker')
    assert again['mandate_id']==first['mandate_id']
    with pytest.raises(ValueError,match='DOCUMENT_CONFLICT'):funding.register_mandate(hotel,'CNY',20000,expiry,'test://one-signed-document','a'*64,'maker')
    revoked=funding.revoke_mandate(first['mandate_id'],'revoker')
    assert funding.revoke_mandate(first['mandate_id'],'someone-else')==revoked
    with pytest.raises(ValueError,match='NEW_SIGNED'):funding.register_mandate(hotel,'CNY',10000,expiry,'test://one-signed-document','a'*64,'maker')
    with SessionLocal() as s:assert len(s.scalars(select(Mandate)).all())==1
