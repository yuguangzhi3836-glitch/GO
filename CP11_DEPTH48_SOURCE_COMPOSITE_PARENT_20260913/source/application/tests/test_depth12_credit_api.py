from datetime import datetime,timezone,timedelta
import json
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import ConsumerProfileRow,CatalogCreditAllocationRow,ProfileDataReleaseAuditRow
from go_hotel.services import catalog_stay_credit as svc
from go_hotel.security.crypto import decrypt_secret
from tests.test_sprint3a_flight import auth
from tests.test_sprint1n_supplier_compensation import booked_order
from tests.test_depth04_vault_management import create_person,vault
from tests.test_depth12_catalog_credit import dates


def data(r):assert r.status_code==200,r.text;return r.json()['data']
def owned(client,email):
    h=auth(client,email)
    with SessionLocal() as s:account=s.scalar(select(ConsumerProfileRow).where(ConsumerProfileRow.email==email)).user_id
    oid,_=booked_order(client,email,account_id=account)
    q=data(client.post(f'/v1/orders/{oid}/stay-credit-quote',headers=h))
    path=f'/v1/orders/{oid}/convert-to-stay-credit';b={'quote_id':q['quote_id'],'quote_hash':q['quote_hash'],'confirmed':True}
    assert client.post(path,headers=h,json=b|{'credit_value_minor':99999999}).status_code==422
    c=data(client.post(path,headers=h|{'Idempotency-Key':'convert-'+email},json=b))
    return h,account,oid,c


def test_signed_customer_credit_requires_selected_owned_guest_and_full_current_consent(client):
    h,account,oid,c=owned(client,'credit12-owner@example.com');cid=c['stay_credit_id'];ci,co=dates()
    q=data(client.post(f'/v1/stay-credits/{cid}/redemption-quote',headers=h,json={'check_in':ci,'check_out':co}))
    b={'redemption_quote_id':q['quote_id'],'quote_hash':q['quote_hash'],'confirmed':True,'payment_method_token':'pm_success'}
    path=f'/v1/stay-credits/{cid}/redeem'
    assert client.post(path,headers=h,json=b).status_code==409
    person,_=create_person(account,name='ACTUAL CREDIT GUEST',field='MOBILE',value='13900000000');b['traveler_id']=person['traveler_id']
    # Mobile contact release requires a current purpose-specific permission.
    assert client.post(path,headers=h,json=b).status_code==409
    consent=vault.grant_consent(account,{'traveler_id':person['traveler_id'],'consent_type':'SENSITIVE_DATA_RELEASE','purpose':'HOTEL_BOOKING','scope':['LEGAL_NAME','MOBILE'],'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat()})
    b['consent_id']=consent['consent_id']
    assert client.post(path,headers=h,json=b|{'guest_name':'FORGED NICKNAME'}).status_code==422
    completed=data(client.post(path,headers=h|{'Idempotency-Key':'redeem-owned'},json=b));assert completed['status']=='REDEEMED'
    with SessionLocal() as s:
        a=s.get(CatalogCreditAllocationRow,completed['order_id']);profile=a.request_json['profile_release'];guest=json.loads(decrypt_secret(profile['guest_ciphertext']))
        assert guest=={'full_name':'ACTUAL CREDIT GUEST','mobile':'13900000000'}
        assert 'ACTUAL CREDIT GUEST' not in json.dumps(a.request_json)
        release=s.get(ProfileDataReleaseAuditRow,profile['release_id']);assert release.user_id==account and release.traveler_id==person['traveler_id']
    d=data(client.get(f'/v1/consumer/orders/{completed["order_id"]}/detail',headers=h))
    assert d['credit_redemption']['stay_credit_id']==cid and 'guest_ciphertext' not in json.dumps(d)
    other=auth(client,'credit12-other@example.com')
    assert client.get(f'/v1/stay-credits/{cid}',headers=other).status_code==404
    assert client.post(f'/v1/stay-credits/{cid}/redemptions/{completed["order_id"]}/cancellation-quote',headers=other).status_code==404
    other_person,_=create_person('different-account',field='MOBILE',value='13911111111')
    assert client.post(path,headers=h,json=b|{'traveler_id':other_person['traveler_id']}).status_code==409


def test_withdrawn_traveler_permission_keeps_credit_unchanged_and_cross_credit_actions_fail(client):
    h,account,oid,c=owned(client,'credit12-revoke@example.com');cid=c['stay_credit_id']
    person,_=create_person(account,field='MOBILE',value='13900000000')
    consent=vault.grant_consent(account,{'traveler_id':person['traveler_id'],'purpose':'HOTEL_BOOKING','scope':['LEGAL_NAME','MOBILE'],'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat()})
    vault.set_permission(account,person['traveler_id'],'USE_FOR_BOOKING',False)
    ci,co=dates();q=data(client.post(f'/v1/stay-credits/{cid}/redemption-quote',headers=h,json={'check_in':ci,'check_out':co}))
    b={'redemption_quote_id':q['quote_id'],'quote_hash':q['quote_hash'],'confirmed':True,'traveler_id':person['traveler_id'],'consent_id':consent['consent_id'],'payment_method_token':'pm_success'}
    response=client.post(f'/v1/stay-credits/{cid}/redeem',headers=h,json=b)
    assert response.status_code==409 and 'PERMISSION' in response.text
    assert data(client.get(f'/v1/stay-credits/{cid}',headers=h))['available_minor']==c['available_minor']
    assert client.post(f'/v1/stay-credits/{cid}/redemptions/non-owned/reconcile',headers=h).status_code==404
