"""Nationwide catalogue opens new work without resurrecting archived history."""
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient
from go_hotel.db.models import Base, HotelAutoPageEventRow as Event
from go_hotel.services import catalog_scope as scope
from go_hotel.security.deps import current_principal
from go_hotel.security.service import Principal

@pytest.fixture
def db(monkeypatch):
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory=sessionmaker(engine,expire_on_commit=False)
    monkeypatch.setattr(scope,'SessionLocal',factory)
    with factory.begin() as s:
        s.add(Event(hotel_auto_page_event_id='scope-old',hotel_id=None,event_type=scope.KINDS[0],actor='prior-admin',created_at=datetime.now(timezone.utc),evidence_json={'mode':'AOLUGUYA_ONLY','protected_ids':['keep'],'archived_ids':['archived'],'retired_job_ids':['old-job'],'retired_run_ids':['old-run'],'scope_sha256':'a'*64}))
    yield factory
    engine.dispose()

def activate():
    return scope.activate_nationwide(scope.nationwide_preview()['scope_sha256'],'admin','全国酒店自主建库')

def test_new_hotels_allowed_archives_and_work_remain_hidden(db):
    with db() as s:
        with pytest.raises(ValueError,match='AOLUGUYA_ONLY'):scope.require_seed(s,{'name':'成都酒店'})
    result=activate()
    assert result['mode']=='NATIONWIDE' and result['restores_archived_records'] is False
    with db() as s:
        scope.require_seed(s,{'name':'成都酒店'});scope.require_hotel(s,'new-hotel');scope.require_hotel(s,None)
        scope.require_run(s,{'run_id':'new-run','target_name':'北京酒店'})
        for call,args in [(scope.require_hotel,('archived',)),(scope.require_job,('old-job',)),(scope.require_run,({'run_id':'old-run'},))]:
            with pytest.raises(ValueError,match='ARCHIVED'):call(s,*args)
    assert scope.status()['nationwide_new_catalog_allowed'] is True
    assert scope.status()['activated_by']=='admin'

def test_scope_fingerprint_stale_and_reason_required(db):
    plan=scope.nationwide_preview()
    with pytest.raises(ValueError,match='REASON_REQUIRED'):scope.activate_nationwide(plan['scope_sha256'],'admin',' ')
    with db.begin() as s:
        s.add(Event(hotel_auto_page_event_id='new-scope',hotel_id=None,event_type=scope.KINDS[0],actor='other',created_at=datetime.now(timezone.utc),evidence_json={**scope.state(s),'archived_ids':['archived','newly-archived']}))
    with pytest.raises(ValueError,match='CHANGED_REVIEW'):scope.activate_nationwide(plan['scope_sha256'],'admin','nationwide')
    assert scope.status()['mode']=='AOLUGUYA_ONLY'

def test_idempotent_activation_retains_audit(db):
    result=activate()
    assert scope.activate_nationwide(result['scope_sha256'],'admin','retry')['idempotent']
    assert scope.activate_nationwide(scope.nationwide_preview()['scope_sha256'],'admin','already active')['idempotent']
    with db() as s:
        assert len(s.scalars(select(Event)).all())==2
        assert scope.state(s)['archived_ids']==['archived']

def test_sql_and_python_event_visibility_agree_before_limit(db):
    activate()
    with db.begin() as s:
        for key,hotel,evidence in [('new','new-hotel',{}),('arch','archived',{}),('job',None,{'job_id':'old-job'}),('run',None,{'run_id':'old-run'}),('keep','keep',{})]:
            s.add(Event(hotel_auto_page_event_id=key,hotel_id=hotel,event_type='TEST',actor='a',created_at=datetime.now(timezone.utc),evidence_json=evidence))
    with db() as s:
        rows=s.scalars(select(Event).where(Event.event_type=='TEST')).all();expected={'new','keep'}
        assert {r.hotel_auto_page_event_id for r in scope.visible_events(s,rows)}==expected
        assert {r.hotel_auto_page_event_id for r in s.scalars(select(Event).where(Event.event_type=='TEST',scope.event_filter(s)))}==expected
        assert len(s.scalars(select(Event).where(Event.event_type=='TEST',scope.event_filter(s)).limit(2)).all())==2

def test_api_permissions_activation_and_readback(db):
    from go_hotel.api.routes.hotel_autopage_factory import router
    app=FastAPI();app.include_router(router)
    base='/internal/v1/hotel-infrastructure/catalog-scope'
    with TestClient(app) as client:
        assert client.get(base+'/status').status_code==401
        def login(actor,permissions):
            app.dependency_overrides[current_principal]=lambda:Principal('u','u',actor,'supplier',[],'test',permissions)
        login('SUPPLIER_USER',{'admin:rules'})
        assert client.get(base+'/nationwide/preview').status_code==403
        login('GO_ADMIN',set())
        assert client.post(base+'/nationwide/activate',json={}).status_code==403
        login('GO_ADMIN',{'admin:rules'})
        plan=client.get(base+'/nationwide/preview').json()['data']
        assert client.post(base+'/nationwide/activate',json={'scope_sha256':'b'*64,'reason':'national'}).status_code==409
        result=client.post(base+'/nationwide/activate',json={'scope_sha256':plan['scope_sha256'],'reason':'national'})
        assert result.status_code==200,result.text
        current=client.get(base+'/status').json()['data']
        assert current['scope_sha256']==result.json()['data']['scope_sha256']
        assert current['archived_ids']==['archived']
