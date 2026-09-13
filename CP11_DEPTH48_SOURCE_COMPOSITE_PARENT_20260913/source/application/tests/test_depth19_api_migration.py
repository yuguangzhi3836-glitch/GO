from copy import deepcopy
import sqlite3
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from go_hotel.api.routes import mother_plan_p0 as routes
from go_hotel.security.deps import current_principal
from go_hotel.security.service import Principal
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import TravelFactAuthorityRow as Authority, RideFlightAdjustmentRow as Adjustment
from test_depth19_travel_facts import seed_flight, authority, checkin, signed
from test_depth19_ride_sync import seed_ride, proposal


@pytest.fixture
def http():
    app=FastAPI();app.include_router(routes.router)
    role={'value':Principal('u19','test','CONSUMER',None,[],'session',set())}
    app.dependency_overrides[current_principal]=lambda:role['value']
    with TestClient(app) as client:yield client,role


def principal(role,actor='GO_ADMIN',permissions=None,uid='admin19'):
    role['value']=Principal(uid,'test',actor,None,[],'session',set(permissions or []))


def test_http_read_no_store_and_owner_isolation(http):
    seed_flight();client,role=http
    response=client.get('/v1/flights/orders/flight19/check-in')
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    assert response.json()['data']['state']=='CHECK_IN_UNVERIFIED'
    principal(role,'CONSUMER',uid='other')
    assert client.get('/v1/flights/orders/flight19/check-in').status_code==409


def test_http_fact_write_requires_go_admin_and_rule_permission(http):
    seed_flight();auth=authority();client,role=http;path='/internal/v1/flights/orders/flight19/check-in/facts';body=checkin(auth)
    assert client.post(path,json=body).status_code==403
    principal(role)
    assert client.post(path,json=body).status_code==403
    principal(role,permissions=['admin:rules'])
    assert client.post(path,json=body).status_code==200
    bad=deepcopy(body);bad['fact']['subject']=[]
    assert client.post(path,json=bad).status_code==409
    assert client.post(path,json={'state':'CHECKED_IN'}).status_code==422


def test_http_binding_options_revision_and_customer_rules(http):
    auth=authority();ride,identity=seed_ride(auth);client,role=http
    path=f"/v1/mobility/rides/orders/{ride['order_id']}/flight-tracking"
    opts=client.get(path+'/options').json()['data']
    assert opts['available'] and opts['sources'][0]['authority_id']==auth[0]
    assert client.put(path,json={'expected_revision':1,'tracking_enabled':False,'max_free_wait_minutes':999}).status_code==422
    assert client.put(path,json={'expected_revision':1,'tracking_enabled':False}).status_code==200
    assert client.put(path,json={'expected_revision':1,'tracking_enabled':False}).status_code==409


def test_authority_api_two_reviewers_and_ops_hold_queue(http):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    client,role=http;principal(role,permissions=['admin:rules'],uid='maker')
    now=int(time.time()*1000)
    draft={'provider_id':'api19','environment':'ENGINEERING','source_type':'AIRLINE_OFFICIAL',
        'contract':{'reference':'isolated-api','kinds':['FLIGHT_ARRIVAL'],'carriers':['MU'],'link_hosts':[],'max_age_ms':60000},
        'public_key_hex':Ed25519PrivateKey.generate().public_key().public_bytes_raw().hex(),'valid_from_ms':now-1000,'valid_until_ms':now+100000}
    response=client.post('/internal/v1/travel-fact-authorities',json=draft)
    assert response.status_code==201
    aid=response.json()['data']['authority_id'];path=f'/internal/v1/travel-fact-authorities/{aid}/review'
    assert client.post(path,json={'expected_revision':1,'action':'APPROVE'}).status_code==409
    principal(role,permissions=['admin:rules'],uid='checker')
    assert client.post(path,json={'expected_revision':1,'action':'APPROVE'}).status_code==200
    auth=authority();ride,identity=seed_ride(auth);adjustment=proposal(auth,ride,identity)
    with SessionLocal.begin() as s:s.get(Adjustment,adjustment).status='HOLD'
    ops=client.get('/internal/v1/mobility/flight-adjustments').json()['data']
    assert ops['manual_reconciliation_required']==1 and ops['items'][0]['adjustment_id']==adjustment


@pytest.mark.no_db
def test_migration_roundtrip_preserves_legacy_and_refuses_fact_evidence_loss(tmp_path,monkeypatch):
    from alembic import command
    from alembic.config import Config
    from go_hotel.core.config import settings
    db=tmp_path/'migration.sqlite3'
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE original_booking (id text, amount integer)')
        c.execute("INSERT INTO original_booking VALUES ('paid',18800)")
    monkeypatch.setattr(settings,'database_url','sqlite+pysqlite:///'+str(db))
    config=Config('alembic.ini')
    command.stamp(config,'0125_regional_queue');command.upgrade(config,'0126_travel_operational_facts')
    command.downgrade(config,'0125_regional_queue');command.upgrade(config,'0126_travel_operational_facts')
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO ride_service_policy_snapshot VALUES ('ride','{}','hash',123)")
        assert c.execute('SELECT * FROM original_booking').fetchone()==('paid',18800)
    with pytest.raises(RuntimeError,match='TRAVEL_FACT_DATA_PRESENT'):
        command.downgrade(config,'0125_regional_queue')
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT version_num FROM alembic_version').fetchone()[0]=='0126_travel_operational_facts'
        assert c.execute('SELECT count(*) FROM ride_service_policy_snapshot').fetchone()[0]==1


@pytest.mark.parametrize('field,value',[('kind',[]),('subject',[]),('data',[]),('data',{'state':[]})])
def test_malformed_signed_fact_fields_return_controlled_errors(http,field,value):
    seed_flight();auth=authority();client,role=http
    principal(role,permissions=['admin:rules']);body=checkin(auth)
    body['fact'][field]=value
    from go_hotel.autonomy.durable import canonical
    body['signature_hex']=auth[1].sign(canonical(body['fact']).encode()).hex()
    assert client.post('/internal/v1/flights/orders/flight19/check-in/facts',json=body).status_code==409
