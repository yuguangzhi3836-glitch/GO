from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, func
import pytest
from go_hotel.api.routes.rental_operations import router
from go_hotel.security.deps import current_principal
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoveryEvidenceChainRow as EvidenceRow, OmnichannelMoneyMovementRow as Movement
from go_hotel.mobility.rental import damage, deposit_authority
from tests.test_rental_damage_disputes import order, OWNER, MAKER, CHECKER, principal, claim, Order

@pytest.fixture
def http():
    app=FastAPI();app.include_router(router)
    actor={'p':OWNER};app.dependency_overrides[current_principal]=lambda:actor['p']
    with TestClient(app) as client: yield client,actor

def base(oid):return f'/v1/mobility/rentals/orders/{oid}/operations'
def admin(oid):return '/internal/v1/admin'+base(oid)[3:]
def count():
    with SessionLocal() as s:return s.scalar(select(func.count()).select_from(EvidenceRow))

def test_owner_response_statement_persists_atomically_and_exact_retry(order,http):
    client,actor=http;c=claim(order)
    body={'expected_version':1,'response':'DISPUTE','statement':'I disagree with the recorded return damage.'}
    path=base(order)+f'/cases/{c["case_id"]}/response'
    result=client.post(path,json=body,headers={'Idempotency-Key':'response'})
    assert result.status_code==200,result.text
    evidence=result.json()['data']['customer_evidence'][0]
    assert evidence['statement']['actor_id']==OWNER.user_id and evidence['statement']['order_id']==order
    assert evidence['statement']['kind']=='ACTOR_STATEMENT_UNVERIFIED'
    assert evidence['statement']['text']==body['statement']
    before=count()
    assert client.post(path,json=body,headers={'Idempotency-Key':'response'}).json()==result.json()
    assert client.post(path,json={**body,'statement':'different'},headers={'Idempotency-Key':'response'}).status_code==409
    assert count()==before
    workspace=client.get(base(order)).json()['data']
    assert workspace['receipts'][0]['key']=='response'
    assert workspace['cases'][0]['case']['status']=='REVIEW_REQUIRED'


def test_denied_role_stale_and_spoofed_actor_leave_no_statement(order,http):
    client,actor=http;c=claim(order);before=count()
    body={'expected_version':1,'response':'DISPUTE','statement':'My observation'}
    path=base(order)+f'/cases/{c["case_id"]}/response'
    assert client.post(path,json={**body,'actor_id':'another'},headers={'Idempotency-Key':'x'}).status_code==422
    assert client.post(path,json={**body,'expected_version':99},headers={'Idempotency-Key':'x'}).status_code==409
    actor['p']=principal('other','CONSUMER')
    assert client.get(base(order)).status_code==404
    assert client.post(path,json=body,headers={'Idempotency-Key':'x'}).status_code==404
    actor['p']=MAKER
    assert client.post(path,json=body,headers={'Idempotency-Key':'x'}).status_code==403
    assert count()==before


def test_admin_open_independent_decision_and_appeal_ui_journey(order,http):
    client,actor=http;actor['p']=MAKER
    body={'amount_minor':10000,'currency':'CNY','pickup_statement':'No mark at pickup.','return_statement':'Door mark observed on return.'}
    r=client.post(admin(order)+'/cases',json=body,headers={'Idempotency-Key':'open'})
    assert r.status_code==200,r.text
    cid=r.json()['data']['case_id'];actor['p']=OWNER
    r=client.post(base(order)+f'/cases/{cid}/response',json={'expected_version':1,'response':'DISPUTE','statement':'Mark existed before rental.'},headers={'Idempotency-Key':'response'})
    assert r.status_code==200
    decision={'expected_version':2,'award_minor':5000,'statement':'Partial responsibility in isolated review.'}
    path=admin(order)+f'/cases/{cid}/decision';actor['p']=MAKER;before=count()
    assert client.post(path,json=decision,headers={'Idempotency-Key':'decision'}).status_code==403
    assert count()==before
    actor['p']=CHECKER
    assert client.get(base(order)).json()['data']['cases'][0]['actions']==['DECISION']
    assert client.post(path,json=decision,headers={'Idempotency-Key':'decision'}).status_code==200
    actor['p']=OWNER
    assert client.get(base(order)).json()['data']['cases'][0]['actions']==['APPEAL']
    assert client.post(base(order)+f'/cases/{cid}/appeal',json={'expected_version':3,'statement':'Please review additional account.'},headers={'Idempotency-Key':'appeal'}).status_code==200
    actor['p']=CHECKER;body={'expected_version':4,'award_minor':0,'statement':'No attributable damage.'}
    path=admin(order)+f'/cases/{cid}/appeal-decision'
    assert client.get(base(order)).json()['data']['cases'][0]['actions']==[]
    assert client.post(path,json=body,headers={'Idempotency-Key':'appeal-decision'}).status_code==403
    actor['p']=principal('third-reviewer')
    assert client.post(path,json=body,headers={'Idempotency-Key':'appeal-decision'}).status_code==200
    with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(Movement))==0


def test_admin_return_statement_creates_source_not_financial_release(order,http):
    client,actor=http
    with SessionLocal.begin() as s:s.get(Order,order).status='CONFIRMED'
    p=deposit_authority.propose(OWNER,order,'propose')
    a=deposit_authority.accept(OWNER,order,p['obligation_id'],'accept',1,p['source_hash'],True)
    with SessionLocal.begin() as s:s.get(Order,order).status='COMPLETED'
    body={'expected_revision':2,'expected_source_hash':a['source_hash'],'statement':'I explicitly checked the final return; no damage claim in this fixture.'}
    path=admin(order)+f'/obligations/{a["obligation_id"]}/return-review'
    before=count();assert client.post(path,json=body,headers={'Idempotency-Key':'return'}).status_code==403
    assert count()==before
    actor['p']=MAKER
    r=client.post(path,json=body,headers={'Idempotency-Key':'return'})
    assert r.status_code==200,r.text
    assert r.json()['data']['financial_state']=='NO_FINANCIAL_FACT_ASSERTED'
    assert r.json()['data']['evidence'][0]['statement']['actor_id']==MAKER.user_id
    w=client.get(base(order)).json()['data'];assert w['actions']==[] and w['receipts'][0]['key']=='return'


def test_statement_action_audit_failure_rolls_back(order,http,monkeypatch):
    client,actor=http;c=claim(order);before=count();original=damage.append_vertical_evidence
    def fail(*args,**kwargs):original(*args,**kwargs);raise RuntimeError('CRASH')
    monkeypatch.setattr(damage,'append_vertical_evidence',fail)
    with pytest.raises(RuntimeError):client.post(base(order)+f'/cases/{c["case_id"]}/response',json={'expected_version':1,'response':'DISPUTE','statement':'my statement'},headers={'Idempotency-Key':'response'})
    assert count()==before


def test_statement_blank_and_raw_evidence_injection_rejected(order,http):
    client,actor=http;c=claim(order);before=count()
    body={'expected_version':1,'response':'DISPUTE','statement':'   '}
    assert client.post(base(order)+f'/cases/{c["case_id"]}/response',json=body,headers={'Idempotency-Key':'x'}).status_code==409
    assert count()==before
    from go_hotel.api.routes.rental_damage import Evidence
    from pydantic import ValidationError
    with pytest.raises(ValidationError):Evidence(reference='r',sha256='a'*64,statement={'actor_id':'fake'})
