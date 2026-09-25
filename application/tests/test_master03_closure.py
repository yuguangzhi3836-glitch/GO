from registration_terms_test_support import register_synthetic_consumer
from tests.attraction_fixtures import quoted_attraction
from datetime import date, timedelta
import json
import pytest
from sqlalchemy import select
from go_hotel.core.config import settings
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (ProfileFactRow, ProfileImportItemRow, ProfileConsentRow,
    OmnichannelMoneyMovementRow, PaymentOrderRootRow)
from go_hotel.services.personal_travel_vault import personal_travel_vault_service as vault

def profile(user='owner', relationship='SELF', name='TEST PERSON'):
    job=vault.create_import(user,{'source_type':'MANUAL','items':[
        {'entity_type':'TRAVELER','traveler_ref':'a','value':{'full_name':name,'relationship_type':relationship}},
        {'entity_type':'PROFILE_FACT','traveler_ref':'a','field_type':'MOBILE','value':'13800000000'},
        {'entity_type':'PROFILE_FACT','traveler_ref':'a','field_type':'DRIVER_LICENSE_NUMBER','value':'TEST-DL-12345678','sensitive':False}]})
    for item in job['items']:vault.review_item(user,job['import_job_id'],item['import_item_id'],'ACCEPT')
    result=vault.commit_import(user,job['import_job_id'])
    tid=next(x['resolution_traveler_id'] for x in result['items'] if x['entity_type']=='TRAVELER')
    return tid

def test_export_is_explicit_owner_scoped_and_companion_permission_bound():
    tid=profile();profile('another-owner',name='PRIVATE OTHER')
    companion=profile(relationship='FAMILY',name='COMPANION')
    with pytest.raises(ValueError,match='EXPORT_CONFIRMATION'):vault.export_owned('owner')
    exported=vault.export_owned('owner',True)
    assert [t['traveler_id'] for t in exported['travelers']]==[tid]
    assert 'PRIVATE OTHER' not in json.dumps(exported)
    vault.set_permission('owner',companion,'SHARE',True)
    exported=vault.export_owned('owner',True)
    assert len(exported['travelers'])==2
    c=next(t for t in exported['travelers'] if t['traveler_id']==companion)
    assert 'DRIVER_LICENSE_NUMBER' not in [f['field_type'] for f in c['facts']]

def test_traveler_delete_erases_reusable_sensitive_data_and_revokes_consent():
    tid=profile();c=vault.grant_consent('owner',{'traveler_id':tid,'scope':['DRIVER_LICENSE_NUMBER']})
    with pytest.raises(ValueError,match='TRAVELER_NOT_FOUND'):vault.delete_traveler('another-owner',tid)
    vault.delete_traveler('owner',tid)
    assert vault.delete_traveler('owner',tid)['replayed']
    assert vault.vault('owner')['travelers']==[]
    with pytest.raises(ValueError,match='TRAVELER_NOT_FOUND'):vault.release('owner',{'traveler_id':tid,'requested_fields':['LEGAL_NAME']})
    with SessionLocal() as s:
        assert s.get(ProfileConsentRow,c['consent_id']).status=='REVOKED'
        items=s.scalars(select(ProfileImportItemRow).where(ProfileImportItemRow.resolution_traveler_id==tid)).all()
        assert items and all(i.candidate_value_ciphertext is None for i in items)

def test_same_name_does_not_merge_distinct_people():
    first=profile()
    job=vault.create_import('owner',{'source_type':'MANUAL','source_reference':'different person','items':[{'entity_type':'TRAVELER','value':{'full_name':'TEST PERSON','relationship_type':'FAMILY'}}]})
    vault.review_item('owner',job['import_job_id'],job['items'][0]['import_item_id'],'ACCEPT')
    vault.commit_import('owner',job['import_job_id'])
    assert vault.vault('owner')['traveler_count']==2

@pytest.mark.parametrize('boundary',['past','future','malformed'])
def test_unusable_sensitive_fact_is_never_released(boundary):
    tid=profile();vault.grant_consent('owner',{'traveler_id':tid,'scope':['DRIVER_LICENSE_NUMBER']})
    with SessionLocal.begin() as s:
        fact=s.scalar(select(ProfileFactRow).where(ProfileFactRow.traveler_id==tid,ProfileFactRow.field_type=='DRIVER_LICENSE_NUMBER'))
        if boundary=='past':fact.valid_until='2000-01-01'
        elif boundary=='future':fact.valid_from='2099-01-01'
        else:fact.valid_until='broken-date'
    released=vault.release('owner',{'traveler_id':tid,'requested_fields':['DRIVER_LICENSE_NUMBER']})
    assert released['released_fields']=={}

def test_autonomy_without_qualification_registry_is_denied():
    from go_hotel.autonomy import ALL_CELL_REGISTRY, AuthorityConstitutionGate, AIActionEnvelope, Environment, RiskFactors
    action=AIActionEnvelope(action_id='unqualified',cell_id='C02',capability='FLIGHT_SEARCH',target_domain='FLIGHT',environment=Environment.TEST,
        require_autonomous_execution=True,risk_factors=RiskFactors(**{k:0 for k in ['reversibility','blast_radius','money_exposure','pii_exposure','truth_mutation','customer_impact','supplier_impact','regulatory_impact','cross_domain_impact']}))
    result=AuthorityConstitutionGate(ALL_CELL_REGISTRY).check(action)
    assert not result.allowed and result.code=='AUTONOMY_QUALIFICATION_REGISTRY_REQUIRED'

def book_all(client):
    r=register_synthetic_consumer(client, json={'email':'master-03@example.test','password':'StrongPass123!','display_name':'ACCOUNT NICKNAME'})
    assert r.status_code==200,r.text
    uid=r.json()['data']['profile']['user_id']
    token=client.post('/v1/mobile/auth/login',json={'email':'master-03@example.test','password':'StrongPass123!'}).json()['data']['access_token']
    client.cookies.clear();headers={'Authorization':'Bearer '+token}
    tid=profile(uid);vault.grant_consent(uid,{'traveler_id':tid,'purpose':'RENTAL_BOOKING','scope':['DRIVER_LICENSE_NUMBER']})
    d=(date.today()+timedelta(days=10)).isoformat();end=(date.today()+timedelta(days=13)).isoformat()
    def post(path,body=None):
        r=client.post(path,headers=headers,json=body);assert r.status_code==200,r.text;return r.json()['data']
    out={}
    hotel=post('/v1/search/hotels',{'destination':{'city_code':'TYO'},'stay':{'check_in':d,'check_out':end},'occupancy':{'rooms':1,'adults':1,'children':0},'currency':'CNY'})['hotels'][0]
    pb=post(f"/v1/offers/{hotel['best_offer']['offer_id']}/prebook",{'currency':'CNY'})
    out['HOTEL']=post('/v1/consumer/orders',{'prebook_id':pb['prebook_id'],'traveler_id':tid,'expected_fare_rule_hash':pb['fare_rule']['offer_rule_hash'],'fare_confirmed':True})
    for vertical,base,body in [('FLIGHT','/v1/flights',{'origin':'PVG','destination':'NRT','departure_date':d}),('RAIL','/v1/rail',{'origin_station':'SHA','destination_station':'HZH','travel_date':d})]:
        offer=post(base+'/search',body)['items'][0];pb=post(f"{base}/offers/{offer['offer_id']}/prebook")
        out[vertical]=post(base+'/orders',{'prebook_id':pb['prebook_id'],'traveler_ids':[tid]})
    for vertical,base,body in [('RIDE','/v1/mobility/rides',{'pickup':'PVG','dropoff':'Bund','pickup_at':d+'T10:00:00','currency':'CNY'}),('RENTAL','/v1/mobility/rentals',{'pickup_location':'NRT','return_location':'NRT','pickup_at':d+'T10:00:00','return_at':end+'T10:00:00','currency':'CNY'})]:
        offer=post(base+'/search',body)['items'][0]
        out[vertical]=post(base+'/orders',{**body,'offer_id':offer['offer_id'],'traveler_ids':[tid]})
    offer=post('/v1/attractions/search',{'destination':'东京','visit_date':d})['items'][0]
    out['ATTRACTION']=post('/v1/attractions/orders',quoted_attraction(client,{'offer_id':offer['offer_id'],'visit_date':d,'quantity':1,'traveler_ids':[tid]}))
    return headers,out

def test_all_six_explicit_checkouts_bind_amount_and_capture_once(client,monkeypatch):
    headers,orders=book_all(client)
    for vertical,order in orders.items():
        path=f"/v1/consumer/checkout/{vertical}/{order['order_id']}"
        body={'mode':'CONTRACT_SIMULATOR','expected_amount_minor':order['total_amount_minor'],'currency':order['currency']}
        key={'Idempotency-Key':f'pay:{vertical}',**headers}
        assert client.post(path,headers=key,json={**body,'expected_amount_minor':1}).status_code==409
        assert client.post(path,headers={'Idempotency-Key':'unauthorized'},json=body).status_code==401
        first=client.post(path,headers=key,json=body);assert first.status_code==200,first.text
        assert first.json()['data']['external_live'] is False
        assert first.json()['data']['status'] in {'CONFIRMED','TICKETED'}
        for retry_key in [f'pay:{vertical}',f'new-device:{vertical}']:
            retry=client.post(path,headers={**headers,'Idempotency-Key':retry_key},json=body)
            assert retry.status_code==200,retry.text
        with SessionLocal() as s:
            root=s.scalar(select(PaymentOrderRootRow).where(PaymentOrderRootRow.business_type==f'{vertical}_ORDER',PaymentOrderRootRow.business_id==order['order_id']))
            captures=s.scalars(select(OmnichannelMoneyMovementRow).where(OmnichannelMoneyMovementRow.root_payment_intent_id==root.payment_intent_id,OmnichannelMoneyMovementRow.movement_type=='CAPTURE')).all()
            assert len(captures)==1 and captures[0].amount_minor==body['expected_amount_minor']
        if vertical=='HOTEL':
            q=client.post(f"/v1/orders/{order['order_id']}/cancellation-quote",headers=headers).json()['data']
            refunded=client.post(f"/v1/orders/{order['order_id']}/cancel",headers={**headers,'Idempotency-Key':f'refund:{vertical}'},json={'cancellation_quote_id':q['quote_id'],'quote_hash':q['quote_hash'],'confirmed':True})
        else:
            route={'FLIGHT':'flights','RAIL':'rail','RENTAL':'mobility','RIDE':'mobility','ATTRACTION':'attractions'}[vertical]
            action='cancel' if vertical in {'RENTAL','RIDE'} else 'refund'
            refunded=client.post(f"/v1/{route}/orders/{order['order_id']}/{action}",headers={**headers,'Idempotency-Key':f'refund:{vertical}'})
        assert refunded.status_code==200,refunded.text
        with SessionLocal() as s:
            refunds=s.scalars(select(OmnichannelMoneyMovementRow).where(OmnichannelMoneyMovementRow.root_payment_intent_id==root.payment_intent_id,OmnichannelMoneyMovementRow.movement_type=='REFUND')).all()
            assert len(refunds)==1 and refunds[0].state=='CONFIRMED'
            assert 0<refunds[0].amount_minor<=body['expected_amount_minor']
    monkeypatch.setattr(settings,'app_env','production')
    assert client.post(path,headers=key,json=body).status_code==403


@pytest.mark.parametrize('vertical', ['RIDE', 'RENTAL'])
def test_confirmed_mobility_replay_requires_durable_capture_evidence(client, vertical):
    headers, orders = book_all(client)
    order = orders[vertical]
    path = f"/v1/consumer/checkout/{vertical}/{order['order_id']}"
    body = {'mode': 'CONTRACT_SIMULATOR', 'expected_amount_minor': order['total_amount_minor'], 'currency': order['currency']}
    first = client.post(path, headers={**headers, 'Idempotency-Key': 'initial-capture'}, json=body)
    assert first.status_code == 200, first.text
    with SessionLocal.begin() as s:
        root = s.scalar(select(PaymentOrderRootRow).where(
            PaymentOrderRootRow.business_type == f'{vertical}_ORDER',
            PaymentOrderRootRow.business_id == order['order_id']))
        payment_intent_id = root.payment_intent_id
        captures = list(s.scalars(select(OmnichannelMoneyMovementRow).where(
            OmnichannelMoneyMovementRow.root_payment_intent_id == payment_intent_id,
            OmnichannelMoneyMovementRow.movement_type == 'CAPTURE')))
        assert len(captures) == 1
        capture_id = captures[0].money_movement_id
        captures[0].state = 'UNKNOWN_EXTERNAL_STATE'
    replay = client.post(path, headers={**headers, 'Idempotency-Key': 'another-device'}, json=body)
    assert replay.status_code == 409
    assert replay.json()['detail'] == 'PAYMENT_RECONCILIATION_REQUIRED'
    with SessionLocal() as s:
        captures = list(s.scalars(select(OmnichannelMoneyMovementRow).where(
            OmnichannelMoneyMovementRow.root_payment_intent_id == payment_intent_id,
            OmnichannelMoneyMovementRow.movement_type == 'CAPTURE')))
        assert [r.money_movement_id for r in captures] == [capture_id]
        assert captures[0].state == 'UNKNOWN_EXTERNAL_STATE'
