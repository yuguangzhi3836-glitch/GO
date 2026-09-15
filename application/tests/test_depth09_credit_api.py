from datetime import datetime,timedelta,timezone
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HostedDirectReservationEventRow as Event
from tests.test_depth09_stay_credit import issued,redemption,credit,summary,Reservation,Allocation
from tests.test_depth04_vault_management import create_person,vault


def test_redemption_requires_current_owned_traveler_release_and_rejects_raw_pii(client,monkeypatch):
    r,account,h,a,q,c=issued(client,monkeypatch);q=redemption(r,account,c)
    person,_=create_person(account,field='MOBILE',value='13900000000',name='ACTUAL NEW GUEST')
    path='/v1/consumer/stay-credits/'+c['credit_id']+'/redeem'
    body={'quote_id':q['quote_id'],'expected_due_minor':0,'currency':'CNY','traveler_id':person['traveler_id'],'consent_id':'missing-consent'}
    for wrong in [{**body,'guest_name':'FORGED'},{**body,'expected_due_minor':True},{**body,'traveler_id':''}]:
        assert client.post(path,headers=h,json=wrong).status_code in {409,422}
    # Selecting a stored traveler does not confirm a new credit booking.
    assert client.post(path,headers=h,json=body).status_code==409
    with SessionLocal() as s:assert not s.scalars(select(Allocation)).all()
    consent={'traveler_id':person['traveler_id'],'consent_type':'SENSITIVE_DATA_RELEASE','purpose':'HOTEL_BOOKING',
        'scope':['LEGAL_NAME','MOBILE'],'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat()}
    response=client.post('/v1/consumer/profile/consents',headers=h,json=consent);assert response.status_code==201,response.text
    body['consent_id']=response.json()['data']['consent_id']
    first=client.post(path,headers=h,json=body);assert first.status_code==200,first.text
    assert client.post(path,headers=h,json=body).json()==first.json()
    rid=first.json()['data']['reservation_id']
    with SessionLocal() as s:
        new=s.get(Reservation,rid);assert (new.guest_name,new.guest_contact)==('ACTUAL NEW GUEST','13900000000')
        event=s.scalar(select(Event).where(Event.hosted_reservation_id==rid,Event.event_type=='STAY_CREDIT_REDEEMED'))
        assert event.payload_json['profile_release']['traveler_id']==person['traveler_id'] and event.payload_json['profile_release']['release_ids']
    other,_=create_person('different-owner',field='MOBILE',value='13911111111')
    assert client.post(path,headers=h,json={**body,'traveler_id':other['traveler_id']}).status_code==409


def test_credit_list_and_order_expose_distinct_value_cash_and_terminal_state(client,monkeypatch):
    r,account,h,a,q,c=issued(client,monkeypatch)
    rows=client.get('/v1/consumer/stay-credits',headers=h).json()['data']['items']
    assert len(rows)==1 and rows[0]['can_redeem'] and rows[0]['hotel_slug']=='aoluguya-harbin'
    result=client.get('/v1/direct/reservations/'+r['hosted_reservation_id'],headers=h).json()['data']['after_sales']
    assert result['stay_state']=='CONVERTED_TO_CREDIT' and result['can_open_case']
    assert result['funds']['credit']['issued_credit']['credit_id']==c['credit_id']
    assert not any(o['available'] for o in result['fare']['options'])


def test_redemption_quote_carries_authoritative_new_rule_after_search_policy_changes(client,monkeypatch):
    from tests.test_depth09_stay_credit import fare,RULES,value
    r,account,h,a,q,c=issued(client,monkeypatch);old=redemption(r,account,c)
    new=fare.publish(r['hosted_offer_id'],{**RULES,'cooling_off_minutes':2000,'credit_terms':value.TERMS},'test://new-redemption-policy','hotel')
    response=client.post('/v1/consumer/stay-credits/'+c['credit_id']+'/quote',headers=h,json={k:old[k] for k in ['hosted_offer_id','check_in','check_out','adults','children']})
    assert response.status_code==200,response.text
    q=response.json()['data'];assert q['fare_rule']['rule_hash']==new['rule_hash'] and q['fare_rule']['rules']['cooling_off_minutes']==2000


def test_withdrawn_booking_permission_prevents_credit_redemption_without_value_change(client,monkeypatch):
    r,account,h,a,q,c=issued(client,monkeypatch);q=redemption(r,account,c)
    person,_=create_person(account,field='MOBILE',value='13900000000')
    consent=vault.grant_consent(account,{'traveler_id':person['traveler_id'],'scope':['LEGAL_NAME','MOBILE'],'purpose':'HOTEL_BOOKING','expires_at':(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat()})
    vault.set_permission(account,person['traveler_id'],'USE_FOR_BOOKING',False)
    response=client.post('/v1/consumer/stay-credits/'+c['credit_id']+'/redeem',headers=h,
        json={'quote_id':q['quote_id'],'expected_due_minor':0,'currency':'CNY','traveler_id':person['traveler_id'],'consent_id':consent['consent_id']})
    assert response.status_code==409 and 'PERMISSION' in response.text
    assert credit.list_credits(account)[0]['available_minor']==162000 and summary(r)['refund_minor']==0
