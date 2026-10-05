from copy import deepcopy
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import ConsumerProfileRow,OrderRow,CatalogCreditContractRow
from go_hotel.security.service import identity_service
from go_hotel.connectors.mock_hotel import connector
from test_depth13_catalog_fare import prebook,data
from test_depth11_catalog_supplier_remedy import supplier_headers
from test_sprint1m_fare_runtime import booked_order
from tests.test_sprint3a_flight import auth


def test_supplier_publishes_only_own_rule_with_explicit_version_confirmation(client):
    oid,pb=prebook(client);h=supplier_headers();v=pb['fare_rule'];path=f'/v1/supplier/catalog-fare/offers/{oid}/publish'
    rules={**deepcopy(v['rules']),'cooling_off_minutes':123}
    body={'rules':rules,'authority_reference':'simulation://supplier-published','expected_version_id':v['version_id'],'confirmed':True}
    assert client.post(path,json=body).status_code==401
    assert client.post(path,headers=h,json={**body,'confirmed':False}).status_code==409
    assert client.post(path,headers=h,json={**body,'confirmed':1}).status_code==422
    for role in ['READ_ONLY','FRONT_DESK']:
        name='fare13_'+role
        identity_service.create_user(name,'Test-Only-Role123!','SUPPLIER_USER','sup_mock',[role])
        limited={'Authorization':'Bearer '+identity_service.login(name,'Test-Only-Role123!')['access_token']}
        assert client.get('/v1/supplier/catalog-fare/offers',headers=limited).status_code==200
        assert client.post(path,headers=limited,json=body).status_code==403
    saved=data(client.post(path,headers=h,json=body))
    assert saved['version']==2 and saved['rules']['cooling_off_minutes']==123
    assert data(client.post(path,headers=h,json=body))['version_id']==saved['version_id']
    assert data(client.get('/v1/supplier/catalog-fare/offers',headers=h))['items'][0]['published_rule']['version_id']==saved['version_id']
    from tests.supplier_fixture import admit_trading_supplier
    fixture_owner = identity_service.create_user('fare_other_supplier','Test-Only-Other123!','SUPPLIER_USER','sup_other',['SUPPLIER_OWNER'])
    admit_trading_supplier('sup_other', fixture_owner)
    other={'Authorization':'Bearer '+identity_service.login('fare_other_supplier','Test-Only-Other123!')['access_token']}
    assert data(client.get('/v1/supplier/catalog-fare/offers',headers=other))['items']==[]
    assert client.post(path,headers=other,json=body).status_code==404


def test_mobile_conversion_uses_same_explicit_contract_and_idempotent_result(client):
    h=auth(client,'mobile-credit13@example.com');_,pb=prebook(client)
    order=data(client.post('/v1/consumer/orders',headers=h,json={'prebook_id':pb['prebook_id'],
        'expected_fare_rule_hash':pb['fare_rule']['offer_rule_hash'],'fare_confirmed':True}))
    with SessionLocal() as s:owner=s.scalar(select(ConsumerProfileRow).where(ConsumerProfileRow.email=='mobile-credit13@example.com')).user_id
    from go_hotel.services.booking import booking_service
    import asyncio
    asyncio.run(booking_service.pay(order['order_id'],order['total_amount_minor'],'CNY','pm_success'))
    asyncio.run(booking_service.confirm(order['order_id']))
    oid=order['order_id'];q=data(client.post(f'/v1/mobile/orders/{oid}/stay-credit-quote',headers=h))
    path=f'/v1/mobile/orders/{oid}/convert-to-stay-credit';body={'quote_id':q['quote_id'],'quote_hash':q['quote_hash'],'confirmed':True}
    assert client.post(path,headers=h).status_code==422
    assert client.post(path,headers=h,json={**body,'quote_hash':'0'*64}).status_code==409
    headers={**h,'Idempotency-Key':'same-mobile-credit'}
    first=data(client.post(path,headers=headers,json=body));again=data(client.post(path,headers=headers,json=body))
    assert first==again and first['status']=='ACTIVE' and connector.cancel_calls==1
    with SessionLocal() as s:assert s.get(CatalogCreditContractRow,first['stay_credit_id']).accepted_by==owner


def test_legacy_supplier_execution_cannot_bypass_customer_consent_or_fault_review(client):
    oid=booked_order(client);h=supplier_headers();before=connector.cancel_calls
    q=data(client.post(f'/v1/supplier/orders/{oid}/cancellation-quote',headers=h))
    denied=client.post(f'/v1/supplier/orders/{oid}/cancel',headers=h,json={'cancellation_quote_id':q['quote_id']})
    assert denied.status_code==409 and 'INDEPENDENT_REVIEW' in denied.text
    assert client.post(f'/v1/supplier/orders/{oid}/change',headers=h,json={'change_quote_id':'unapproved'}).status_code==409
    with SessionLocal() as s:assert s.get(OrderRow,oid).status=='CONFIRMED'
    assert connector.cancel_calls==before
    request=data(client.post(f'/v1/supplier/orders/{oid}/unable-to-fulfill',headers={**h,'Idempotency-Key':'proper-supplier-path'},json={'reason_code':'OVERBOOKING','evidence_ids':[]}))
    assert request['state']=='EVIDENCE_REQUIRED' and connector.cancel_calls==before
    assert data(client.get(f'/v1/supplier/orders/{oid}/workbench',headers=h))['order']['status']=='CONFIRMED'
