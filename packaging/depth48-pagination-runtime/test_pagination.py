"""Real SQL/HTTP tests with private, synthetic rows; no shared database access."""
import os
os.environ['DATABASE_URL'] = 'sqlite+pysqlite:///:memory:'
os.environ['APP_ENV'] = 'test'
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, Integer, DateTime, Boolean, JSON, select
from sqlalchemy.orm import sessionmaker
from go_hotel.api.routes import operations_console as ops
from go_hotel.security.deps import current_principal

VERTICALS = ['HOTEL', 'FLIGHT', 'RAIL', 'RIDE', 'RENTAL', 'ATTRACTION']
ORDER_MODELS = [ops.OrderRow, ops.FlightOrderRow, ops.RailOrderRow, ops.MobilityRideOrderRow, ops.MobilityRentalOrderRow, ops.AttractionOrderRow]
REFUND_MODELS = [ops.RefundRow, ops.FlightRefundRow, ops.RailRefundRow, ops.MobilityRefundRow, ops.MobilityRefundRow, ops.AttractionRefundRow]
T0 = datetime(2026, 9, 13, tzinfo=timezone.utc)

def synthetic(model, identity, **values):
    row = {}
    for c in model.__table__.columns:
        if c.nullable or c.default is not None or c.server_default is not None:
            continue
        if isinstance(c.type, Boolean): value = False
        elif isinstance(c.type, Integer): value = 100
        elif isinstance(c.type, DateTime): value = T0
        elif isinstance(c.type, JSON): value = []
        else: value = 'TEST'
        row[c.name] = identity if c.primary_key else value
    row.update(values)
    return model(**row)

@pytest.fixture
def setup(tmp_path, monkeypatch):
    engine=create_engine('sqlite+pysqlite:///'+str(tmp_path/'private.db'),connect_args={'check_same_thread':False})
    models=set(ORDER_MODELS+REFUND_MODELS+[ops.HotelPartnerPropertyRow])
    for model in models:model.__table__.create(engine)
    sessions=sessionmaker(bind=engine)
    monkeypatch.setattr(ops,'SessionLocal',sessions)
    with sessions() as s:
        for v,om,rm in zip(VERTICALS,ORDER_MODELS,REFUND_MODELS):
            for i in reversed(range(125)):
                oid=f'{v.lower()}-test-{i:03d}'
                created=T0+timedelta(seconds=i//7)
                s.add(synthetic(om,oid,currency='CNY',created_at=created,updated_at=T0))
                extra={'vertical':v} if v in {'RIDE','RENTAL'} else {}
                s.add(synthetic(rm,f'{v.lower()}-refund-{i:03d}',order_id=oid,currency='CNY',created_at=created,**extra))
        s.commit()
    app=FastAPI();app.include_router(ops.router)
    app.dependency_overrides[current_principal]=lambda:SimpleNamespace(actor_type='GO_ADMIN')
    with TestClient(app) as client:yield client,app,sessions
    engine.dispose()

def get(client,v,**params):
    r=client.get('/internal/v1/admin/operations/verticals/'+v,params=params)
    assert r.status_code==200,r.text
    return r.json()['data']

@pytest.mark.parametrize('v',VERTICALS)
def test_all_pages_and_ties(setup,v):
    client,_,sessions=setup
    seen=[];refunds=[]
    for page in [1,2,3]:
        d=get(client,v,page=page,refund_page=page)
        assert d['metrics']['orders']==125 and d['metrics']['refunds']==125
        assert d['pagination']['orders']['total']==125
        assert d['pagination']['refunds']['total']==125
        assert len(d['orders'])==(50 if page<3 else 25)
        assert d['pagination']['orders']['has_next']==(page<3)
        assert d['pagination']['orders']['has_previous']==(page>1)
        seen.extend(x['order_id'] for x in d['orders']);refunds.extend(x['order_id'] for x in d['refunds'])
    expected=[f'{v.lower()}-test-{i:03d}' for i in reversed(range(125))]
    assert seen==refunds==expected
    assert get(client,v,page=999)['pagination']['orders']['page']==3
    first=get(client,v)
    model=ORDER_MODELS[VERTICALS.index(v)]
    with sessions() as s:
        row=s.get(model,expected[-1]);row.updated_at=T0+timedelta(days=1);s.commit()
    assert get(client,v)['orders']==first['orders'],'status updates must not reshuffle page 1'

@pytest.mark.parametrize('v',VERTICALS)
def test_exact_lookup_and_empty_results(setup,v):
    client,_,sessions=setup
    oid=f'{v.lower()}-test-001' # beyond the first 100 rows
    d=get(client,v,order_id=' '+oid+' ',page=3,refund_page=3)
    assert [x['order_id'] for x in d['orders']]==[oid]
    assert [x['order_id'] for x in d['refunds']]==[oid]
    assert d['pagination']['orders']['page']==1
    assert d['metrics']['orders']==d['metrics']['refunds']==125
    for query in [oid[:-1],'%','test-001',"' OR 1=1 --",'missing-order']:
        d=get(client,v,order_id=query)
        assert d['orders']==d['refunds']==[]
        assert d['pagination']['orders']['total']==0
        assert not d['pagination']['orders']['has_next']
    foreign='rental-test-001' if v=='RIDE' else 'ride-test-001'
    if v!='RIDE' and v!='RENTAL':foreign='rental-test-001'
    assert get(client,v,order_id=foreign)['orders']==[]
    assert get(client,v,order_id=foreign)['refunds']==[]

@pytest.mark.parametrize('v',VERTICALS)
def test_independent_refund_pagination_and_page_sizes(setup,v):
    client,_,_=setup
    d=get(client,v,page=1,refund_page=3)
    assert len(d['orders'])==50 and len(d['refunds'])==25
    assert d['orders'][0]['order_id']!=d['refunds'][0]['order_id']
    assert len(get(client,v,page_size=100)['orders'])==100
    assert len(get(client,v,page_size=1)['orders'])==1
    assert get(client,v,order_id='   ')['pagination']['orders']['total']==125

@pytest.mark.parametrize('params',[{'page':0},{'page':-1},{'page':'x'},{'refund_page':0},{'page_size':0},{'page_size':101},{'page':1000001},{'order_id':'x'*65}])
def test_invalid_parameters_rejected(setup,params):
    client,_,_=setup
    assert client.get('/internal/v1/admin/operations/verticals/HOTEL',params=params).status_code==422

def test_authentication_and_roles_remain_required(setup):
    client,app,_=setup
    app.dependency_overrides.clear()
    assert client.get('/internal/v1/admin/operations/verticals/HOTEL').status_code==401
    for role in ['CONSUMER','SUPPLIER_USER']:
        app.dependency_overrides[current_principal]=lambda:SimpleNamespace(actor_type=role)
        assert client.get('/internal/v1/admin/operations/verticals/HOTEL',params={'order_id':'hotel-test-001'}).status_code==403

def test_invalid_vertical_rejected(setup):
    client,_,_=setup
    assert client.get('/internal/v1/admin/operations/verticals/UNKNOWN').status_code==404
