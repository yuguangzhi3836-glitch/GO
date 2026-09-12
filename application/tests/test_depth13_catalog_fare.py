from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import asyncio
import pytest
from sqlalchemy import select, func

from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (OrderRow, OfferRow, PrebookRow, EventRow, ProfileDataReleaseAuditRow,
    CatalogFareFamilyRow as Family, CatalogFareRuleVersionRow as Version,
    CatalogOrderFareSnapshotRow as Snapshot, CatalogOfferFareSnapshotRow as OfferSnapshot)
from go_hotel.services import catalog_fare_snapshot as fare, catalog_stay_credit as credit
from go_hotel.fare.service import fare_service
from go_hotel.repositories.sql import repo
from go_hotel.connectors.mock_hotel import connector
from test_sprint1m_fare_runtime import booked_order
from catalog_fare_helpers import publish_for_order


def data(response):
    assert response.status_code==200,response.text
    return response.json()['data']


def prebook(client,currency='CNY'):
    today=datetime.now(timezone.utc).date()
    offers=data(client.post('/v1/search/hotels',json={'destination':{'city_code':'TYO'},
        'stay':{'check_in':(today+timedelta(days=20)).isoformat(),'check_out':(today+timedelta(days=24)).isoformat()},
        'occupancy':{'rooms':1,'adults':2,'children':0},'currency':currency}))
    oid=offers['hotels'][0]['best_offer']['offer_id']
    return oid,data(client.post(f'/v1/offers/{oid}/prebook',json={'currency':currency}))


def test_prebook_terms_survive_publication_and_next_offer_gets_new_version(client):
    oid,pb=prebook(client);first=pb['fare_rule']
    changed={**first['rules'],'cooling_off_minutes':555,'stay_credit_days':80}
    second=fare.publish(oid,changed,'simulation://new-terms','supplier','sup_mock',first['version_id'])
    order=data(client.post('/v1/orders',json={'prebook_id':pb['prebook_id'],'expected_fare_rule_hash':first['offer_rule_hash'],'fare_confirmed':True}))
    rules=fare.order_rule(order['order_id'])
    assert rules['change_fee_minor']==0 and rules['stay_credit_validity_days']==365
    _,new_pb=prebook(client)
    assert new_pb['fare_rule']['version_id']==second['version_id'] and new_pb['fare_rule']['rules']['cooling_off_minutes']==555


def test_original_order_rules_drive_cancellation_and_credit_after_supplier_update(client):
    oid=booked_order(client)
    original=fare.order_rule(oid)
    publish_for_order(oid,cancellation_tiers=[{'min_hours':0,'fee_basis_points':10000}],stay_credit_days=10,cooling_off_minutes=999)
    assert fare_service.cancellation_quote(oid)['cancellation_fee_minor']==0
    assert credit.conversion_quote(oid)['validity_days']==365
    assert fare.order_rule(oid)['rule_hash']==original['rule_hash']


def test_current_quote_consent_is_required_before_authenticated_profile_release(client):
    from tests.test_sprint3a_flight import auth
    headers=auth(client,'snapshot13-owner@example.com');_,pb=prebook(client)
    for body in [ {'prebook_id':pb['prebook_id']},
        {'prebook_id':pb['prebook_id'],'expected_fare_rule_hash':'0'*64,'fare_confirmed':True},
        {'prebook_id':pb['prebook_id'],'expected_fare_rule_hash':pb['fare_rule']['offer_rule_hash'],'fare_confirmed':False}]:
        assert client.post('/v1/consumer/orders',headers=headers,json=body).status_code==409
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(OrderRow))==0
        assert s.scalar(select(func.count()).select_from(ProfileDataReleaseAuditRow))==0
    good={'prebook_id':pb['prebook_id'],'expected_fare_rule_hash':pb['fare_rule']['offer_rule_hash'],'fare_confirmed':True}
    assert client.post('/v1/consumer/orders',headers=headers,json={**good,'fare_confirmed':1}).status_code==422
    order=data(client.post('/v1/consumer/orders',headers=headers,json=good))
    with SessionLocal() as s:assert s.get(Snapshot,order['order_id']).acceptance_kind=='CUSTOMER_EXPLICIT'
    detail=data(client.get(f'/v1/consumer/orders/{order["order_id"]}/detail',headers=headers))
    assert detail['fare_rule']['rule_hash']==pb['fare_rule']['rule_hash']


def test_order_and_rule_snapshot_roll_back_together_if_event_persistence_fails(client,monkeypatch):
    _,pb=prebook(client);original=repo._append_event_and_outbox
    def fail(s,event):
        if event.event_type=='ORDER_CREATED':raise RuntimeError('order evidence interrupted')
        return original(s,event)
    monkeypatch.setattr(repo,'_append_event_and_outbox',fail)
    from go_hotel.services.booking import booking_service
    with pytest.raises(RuntimeError,match='evidence interrupted'):
        asyncio.run(booking_service.create_order(pb['prebook_id'],'owner',pb['fare_rule']['offer_rule_hash'],True))
    with SessionLocal() as s:
        assert not s.scalars(select(OrderRow)).all() and not s.scalars(select(Snapshot)).all()
        assert not s.scalars(select(EventRow).where(EventRow.event_type=='ORDER_FARE_RULE_ACCEPTED')).all()


def test_historical_order_without_snapshot_never_uses_todays_rules(client):
    oid=booked_order(client)
    with SessionLocal.begin() as s:s.delete(s.get(Snapshot,oid))
    with pytest.raises(ValueError,match='HISTORICAL_ORDER'):fare.order_rule(oid)
    response=client.post(f'/v1/orders/{oid}/cancellation-quote')
    assert response.status_code==409 and 'HISTORICAL_ORDER' in response.text
    assert data(client.get(f'/v1/consumer/orders/{oid}/detail?account_id=acct_demo'))['fare_rule']['reconciliation_required']
    assert connector.cancel_calls==0


@pytest.mark.parametrize('target',['order_snapshot','source_version','offer_date'])
def test_changed_rule_evidence_is_rejected_before_any_cancellation(client,target):
    oid=booked_order(client)
    with SessionLocal.begin() as s:
        snap=s.get(Snapshot,oid)
        if target=='order_snapshot':
            body=deepcopy(snap.snapshot_json);body['version']['rules']['change_fee_minor']=1;snap.snapshot_json=body
        elif target=='source_version':
            version=s.get(Version,snap.version_id);body=deepcopy(version.contract_json);body['rules']['change_fee_minor']=1;version.contract_json=body
        else:s.get(OfferRow,snap.snapshot_json['offer']['offer_id']).check_in='2099-01-01'
    assert client.post(f'/v1/orders/{oid}/cancellation-quote').status_code==409
    assert connector.cancel_calls==0


def test_publishing_is_owned_version_checked_and_currency_scoped(client):
    oid,pb=prebook(client);v=pb['fare_rule']
    with pytest.raises(ValueError,match='OWN_SUPPLIER'):fare.publish(oid,v['rules'],'doc://wrong','intruder','another_supplier',v['version_id'])
    next_rule={**v['rules'],'cooling_off_minutes':101}
    second=fare.publish(oid,next_rule,'simulation://new','supplier','sup_mock',v['version_id'])
    assert fare.publish(oid,next_rule,'simulation://new','supplier','sup_mock',v['version_id'])['version_id']==second['version_id']
    with pytest.raises(ValueError,match='VERSION_CONFLICT'):fare.publish(oid,{**next_rule,'cooling_off_minutes':202},'simulation://stale','supplier','sup_mock',v['version_id'])
    _,usd=prebook(client,'USD')
    assert usd['fare_rule']['rules']['change_fee_minor']==0 and usd['fare_rule']['currency']=='USD'
    assert usd['fare_rule']['version_id']!=second['version_id']


def test_concurrent_distinct_publications_cannot_overwrite_the_same_version(client):
    oid,pb=prebook(client);v=pb['fare_rule']
    def attempt(i):
        try:return fare.publish(oid,{**v['rules'],'cooling_off_minutes':200+i},'simulation://competing','supplier','sup_mock',v['version_id'])['version_id']
        except ValueError as e:return str(e)
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(attempt,range(4)))
    assert results.count('CATALOG_FARE_PUBLISH_VERSION_CONFLICT')==3
    with SessionLocal() as s:assert len(s.scalars(select(Version)).all())==2


def test_cooling_window_uses_original_order_time_and_hotel_timezone(client,monkeypatch):
    import go_hotel.services.catalog_cash_fare as cash_service
    original=fare.demo_rules
    monkeypatch.setattr(fare,'demo_rules',lambda:{**original(),'timezone':'Asia/Tokyo','check_in_hour':15,
        'cooling_off_minutes':30,'cancellation_tiers':[{'min_hours':0,'fee_basis_points':125}]})
    oid=booked_order(client)
    start=datetime.fromisoformat(fare.order_rule(oid)['order_created_at'])
    monkeypatch.setattr(cash_service,'now',lambda:start+timedelta(minutes=5))
    q=fare_service.cancellation_quote(oid)
    assert q['cancellation_fee_minor']==0 and q['cooling_off_applied']
    assert datetime.fromisoformat(q['check_in_at']).hour==6
    assert datetime.fromisoformat(q['expires_at'])==start+timedelta(minutes=15)
    monkeypatch.setattr(cash_service,'now',lambda:start+timedelta(minutes=31))
    charged=fare_service.cancellation_quote(oid)
    assert charged['cancellation_fee_minor']==18040 and type(charged['cancellation_fee_minor']) is int
    assert not charged['cooling_off_applied']
    assert client.post(f'/v1/orders/{oid}/cancel',json={'cancellation_quote_id':q['quote_id']}).status_code==422
    assert connector.cancel_calls==0


def test_credit_cancellation_supports_exact_basis_points_without_float_money(client,monkeypatch):
    from test_depth12_catalog_credit import convert,redeem,run
    from go_hotel.services import catalog_credit_after_sales as after
    original=fare.demo_rules
    monkeypatch.setattr(fare,'demo_rules',lambda:{**original(),'cancellation_tiers':[{'min_hours':0,'fee_basis_points':125}]})
    _,cid,_=convert(client);_,redeemed=redeem(cid,156800)
    q=after.cancellation_quote(redeemed['order_id'])
    assert q['fee_minor']==20000 and type(q['fee_minor']) is int
    finished=run(after.cancel(redeemed['order_id'],q['quote_id'],q['quote_hash'],True,'owner'))
    assert finished['restored_credit_minor']==1423200 and finished['cash_refund_minor']==156800
