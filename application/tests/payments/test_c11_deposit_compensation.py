from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OmnichannelMoneyMovementRow as Movement, OmnichannelLedgerEntryRow as Ledger
from go_hotel.mobility.rental import damage, deposit_authority as authority
from go_hotel.services import rental_deposit_money as service
from go_hotel.services.rental_deposit_review import review
from tests.payments.test_c11_rental_deposit_money import obligation,args,decide,settle,OWNER,CHECKER,principal,ev


def appeal(obligation,decision,amount,reviewer='appeal-checker'):
    case=damage.appeal(OWNER,'deposit-order',decision['case_id'],'appeal-'+str(decision['case_version']),decision['case_version'],'Review',ev('e'))
    damage.review_appeal(principal(reviewer),'deposit-order',case['case_id'],'review-'+str(case['version']),case['version'],amount,'Independent review',ev('f'))
    return authority.compensation_preview(CHECKER,'deposit-order',obligation['obligation_id'],case['case_id'])


def execute(obligation,decision,actor=CHECKER):
    return service.compensate(actor,*args(obligation),decision['case_id'],decision['case_version'],decision['decision_hash'])


@pytest.fixture
def settled(obligation):
    service.authorize(CHECKER,*args(obligation));original=decide(obligation,4000);settle(obligation,original)
    return original


@pytest.mark.parametrize('target',[0,1000])
def test_compensation_preserves_original_and_reverses_same_accounts(obligation,settled,target):
    with SessionLocal() as s:
        old=[(x.money_movement_id,x.movement_type,x.amount_minor,x.state) for x in s.scalars(select(Movement))]
    decision=appeal(obligation,settled,target)
    assert review(CHECKER,'deposit-order')['decisions'][0]['compensation']['amount_minor']==4000-target
    result=execute(obligation,decision)
    assert (result['captured_minor'],result['compensated_minor'],result['net_captured_minor'],result['remaining_minor'])==(4000,4000-target,target,0)
    assert execute(obligation,decision)==result
    with SessionLocal() as s:
        rows=list(s.scalars(select(Movement)));capture=next(x for x in rows if x.movement_type=='CAPTURE');comp=next(x for x in rows if x.movement_type=='COMPENSATION')
        assert comp.parent_movement_id==capture.money_movement_id
        assert all(item in [(x.money_movement_id,x.movement_type,x.amount_minor,x.state) for x in rows] for item in old)
        ledger=list(s.scalars(select(Ledger)))
        original={(x.account_code,x.direction) for x in ledger if x.transaction_id==capture.money_movement_id}
        reverse={(x.account_code,x.direction) for x in ledger if x.transaction_id==comp.money_movement_id}
        assert reverse=={(a,'CREDIT' if d=='DEBIT' else 'DEBIT') for a,d in original}
        assert len(rows)==4 and len(ledger)==4


def test_successive_reductions_are_differences(obligation,settled):
    first=appeal(obligation,settled,2500);execute(obligation,first)
    second=appeal(obligation,first,1000,'another-checker');result=execute(obligation,second)
    assert result['compensated_minor']==3000 and result['net_captured_minor']==1000
    with SessionLocal() as s:assert sorted(s.scalars(select(Movement.amount_minor).where(Movement.movement_type=='COMPENSATION')))==[1500,1500]
    with pytest.raises(ValueError,match='VERSION_CONFLICT'):execute(obligation,first)


@pytest.mark.parametrize('fault',['UNKNOWN','ledger','parent'])
def test_unknown_or_corrupt_money_stays_hold(obligation,settled,fault):
    decision=appeal(obligation,settled,1000)
    with SessionLocal.begin() as s:
        capture=s.scalar(select(Movement).where(Movement.movement_type=='CAPTURE'))
        if fault=='UNKNOWN':capture.state='UNKNOWN_EXTERNAL_STATE'
        if fault=='parent':capture.parent_movement_id='foreign-auth'
        if fault=='ledger':s.scalar(select(Ledger).where(Ledger.direction=='CREDIT')).amount_minor+=1
    with pytest.raises(ValueError):execute(obligation,decision)
    with SessionLocal() as s:assert not list(s.scalars(select(Movement).where(Movement.movement_type=='COMPENSATION')))


@pytest.mark.parametrize('actor',[OWNER,principal('supplier','SUPPLIER_USER'),principal('reader',permissions={'admin:read'})])
def test_compensation_roles(obligation,settled,actor):
    decision=appeal(obligation,settled,0)
    with pytest.raises(PermissionError):execute(obligation,decision,actor)


def test_atomic_rollback(obligation,settled,monkeypatch):
    decision=appeal(obligation,settled,1000);original=service.money._post
    def fail(s,i,m):
        original(s,i,m);raise RuntimeError('ledger interruption')
    monkeypatch.setattr(service.money,'_post',fail)
    with pytest.raises(RuntimeError):execute(obligation,decision)
    with SessionLocal() as s:assert len(list(s.scalars(select(Movement))))==3 and len(list(s.scalars(select(Ledger))))==2
    monkeypatch.setattr(service.money,'_post',original)
    assert execute(obligation,decision)['net_captured_minor']==1000


def test_parallel_single_booking(obligation,settled):
    decision=appeal(obligation,settled,1000)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:execute(obligation,decision),range(2)))
    assert results[0]==results[1]
    with SessionLocal() as s:assert len(list(s.scalars(select(Movement).where(Movement.movement_type=='COMPENSATION'))))==1


def test_unknown_compensation_blocks_new_reduction(obligation,settled):
    first=appeal(obligation,settled,2500);execute(obligation,first)
    second=appeal(obligation,first,1000,'another-checker')
    with SessionLocal.begin() as s:s.scalar(select(Movement).where(Movement.movement_type=='COMPENSATION')).state='UNKNOWN_EXTERNAL_STATE'
    with pytest.raises(ValueError,match='RECONCILIATION_REQUIRED'):execute(obligation,second)
    result=service.status(OWNER,*args(obligation))
    assert result['compensated_minor'] is None and result['net_captured_minor'] is None
    with SessionLocal() as s:assert len(list(s.scalars(select(Movement).where(Movement.movement_type=='COMPENSATION'))))==1


def test_increase_after_compensation_is_hold(obligation,settled):
    first=appeal(obligation,settled,1000);execute(obligation,first)
    case=damage.appeal(OWNER,'deposit-order',first['case_id'],'new-appeal',first['case_version'],'Review',ev('e'))
    damage.review_appeal(principal('another-checker'),'deposit-order',case['case_id'],'upward',case['version'],2000,'New evidence',ev('f'))
    decision=authority.decision_preview(CHECKER,'deposit-order',obligation['obligation_id'],case['case_id'])
    with pytest.raises(ValueError,match='REDUCTION_REQUIRED'):execute(obligation,decision)
    assert service.status(OWNER,*args(obligation))['net_captured_minor']==1000


def test_legacy_capture_hold_without_rewriting_history():
    from types import SimpleNamespace
    entries=[SimpleNamespace(account_code='BUSINESS:RENTAL_DEPOSIT:rent_dep_'+'a'*40)]
    with pytest.raises(ValueError,match='LEGACY_ACCOUNT_COMPENSATION_HOLD'):
        service._assert_current_capture_accounts('rent_dep_'+'a'*40,entries)
    assert entries[0].account_code=='BUSINESS:RENTAL_DEPOSIT:rent_dep_'+'a'*40
    service._assert_current_capture_accounts('rent_dep_'+'a'*40,[SimpleNamespace(account_code='RD:rent_dep_'+'a'*40)])


def test_http_forbids_caller_amount_and_readonly_admin(obligation,settled):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from go_hotel.api.routes.rental_deposit_money import router
    from go_hotel.security.deps import current_principal
    decision=appeal(obligation,settled,1000)
    app=FastAPI();app.include_router(router);app.dependency_overrides[current_principal]=lambda:CHECKER
    path='/internal/v1/mobility/rentals/orders/deposit-order/deposit-money/'+obligation['obligation_id']+'/compensate'
    body=dict(expected_revision=obligation['revision'],expected_source_hash=obligation['source_hash'],case_id=decision['case_id'],expected_case_version=decision['case_version'],expected_decision_hash=decision['decision_hash'])
    with TestClient(app) as client:
        assert client.post(path,json={**body,'amount_minor':1}).status_code==422
        app.dependency_overrides[current_principal]=lambda:principal('reader',permissions={'admin:read'})
        assert client.post(path,json=body).status_code==403
        app.dependency_overrides[current_principal]=lambda:CHECKER
        assert client.post(path,json=body).status_code==200


@pytest.mark.parametrize('fault',['key','evidence','amount'])
def test_corrupt_compensation_is_unknown_to_readers(obligation,settled,fault):
    decision=appeal(obligation,settled,1000);execute(obligation,decision)
    with SessionLocal.begin() as s:
        comp=s.scalar(select(Movement).where(Movement.movement_type=='COMPENSATION'))
        if fault=='key':comp.idempotency_key='forged'
        if fault=='evidence':comp.evidence_json=['caller://fake']
        if fault=='amount':
            comp.amount_minor-=1
            for row in s.scalars(select(Ledger).where(Ledger.transaction_id==comp.money_movement_id)):row.amount_minor-=1
    result=service.status(OWNER,*args(obligation));assert result['state']=='RECONCILIATION_REQUIRED' and result['net_captured_minor'] is None
    assert review(CHECKER,'deposit-order')['money']['state']=='RECONCILIATION_REQUIRED'


def test_new_pending_appeal_does_not_erase_valid_historical_money(obligation,settled):
    first=appeal(obligation,settled,1000);execute(obligation,first)
    damage.appeal(OWNER,'deposit-order',first['case_id'],'new-appeal',first['case_version'],'More evidence',ev('e'))
    result=service.status(OWNER,*args(obligation));assert result['state']=='SETTLED' and result['net_captured_minor']==1000
    assert not review(CHECKER,'deposit-order')['decisions'][0].get('can_compensate')
    with pytest.raises(ValueError):execute(obligation,first)


def test_unknown_compensation_cannot_be_hidden_by_another_ledger_account(obligation,settled):
    decision=appeal(obligation,settled,1000);execute(obligation,decision)
    with SessionLocal.begin() as s:
        comp=s.scalar(select(Movement).where(Movement.movement_type=='COMPENSATION'))
        row=s.scalar(select(Ledger).where(Ledger.transaction_id==comp.money_movement_id,Ledger.direction=='DEBIT'))
        row.account_code='RD:foreign-obligation'
    assert service.status(OWNER,*args(obligation))['state']=='RECONCILIATION_REQUIRED'
    assert review(CHECKER,'deposit-order')['money']['state']=='RECONCILIATION_REQUIRED'


def test_generic_money_ingress_cannot_create_compensation(obligation,settled):
    with SessionLocal() as s:
        capture=s.scalar(select(Movement).where(Movement.movement_type=='CAPTURE'))
        iid,parent=capture.root_payment_intent_id,capture.money_movement_id
    with pytest.raises(ValueError,match='VERIFIED_SOURCE_SCOPE_REQUIRED'):
        service.money.create(iid,{'movement_type':'COMPENSATION','amount_minor':1,'parent_movement_id':parent,
                                 'mode':'CONTRACT_SIMULATOR','evidence':['caller://claim']},'foreign-comp','admin')
