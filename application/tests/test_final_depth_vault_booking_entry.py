from ride_cancellation_fixture import post_ride_order
from registration_terms_test_support import register_synthetic_consumer
from tests.attraction_fixtures import quoted_attraction
from sqlalchemy import select
from go_hotel.services.personal_travel_vault import personal_travel_vault_service as vault
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import ProfileDataReleaseAuditRow


def _auth_and_vault(client):
    email='final-vault-entry@example.com'
    r=register_synthetic_consumer(client, json={'email':email,'password':'StrongPass123!','display_name':'Vault Traveler'})
    assert r.status_code==200,r.text
    user_id=r.json()['data']['profile']['user_id']
    t=client.post('/v1/mobile/auth/login',json={'email':email,'password':'StrongPass123!'}).json()['data']
    client.cookies.clear(); h={'Authorization':'Bearer '+t['access_token']}
    body={'source_type':'SCREENSHOT_AI','source_provider':'USER','source_reference':'final-depth','source_fingerprint':'final-vault-entry-v1','items':[
        {'entity_type':'TRAVELER','traveler_ref':'me','value':{'full_name':'VAULT TESTER','relationship_type':'SELF','is_primary':True},'confidence_bps':9900},
        {'entity_type':'PROFILE_FACT','traveler_ref':'me','field_type':'MOBILE','value':'13800000000','sensitive':False,'confidence_bps':9900},
        {'entity_type':'PROFILE_FACT','traveler_ref':'me','field_type':'DRIVER_LICENSE_NUMBER','value':'DL-12345678','sensitive':True,'confidence_bps':9900},
    ]}
    job=vault.create_import(user_id,body)
    for item in list(job['items']):
        if item['status'] in {'NEEDS_REVIEW','EXTRACTED'}:
            job=vault.review_item(user_id,job['import_job_id'],item['import_item_id'],'ACCEPT')
    vault.commit_import(user_id,job['import_job_id'])
    traveler=vault.vault(user_id)['travelers'][0]
    vault.grant_consent(user_id,{'traveler_id':traveler['traveler_id'],'consent_type':'SENSITIVE_DATA_RELEASE','purpose':'TRAVEL_BOOKING','scope':['DRIVER_LICENSE_NUMBER']})
    return h,user_id,traveler['traveler_id']


def test_six_vertical_booking_entries_use_vault_minimum_release(client):
    h,user_id,tid=_auth_and_vault(client)
    # Hotel
    hs=client.post('/v1/search/hotels',json={'destination':{'city_code':'TYO'},'stay':{'check_in':'2026-09-02','check_out':'2026-09-04'},'occupancy':{'rooms':1,'adults':1,'children':0},'currency':'CNY'}).json()['data']['hotels'][0]
    hpb=client.post(f"/v1/offers/{hs['best_offer']['offer_id']}/prebook",json={'currency':'CNY'}).json()['data']
    ho=client.post('/v1/consumer/orders',headers=h,json={'prebook_id':hpb['prebook_id'],'traveler_id':tid,'expected_fare_rule_hash':hpb['fare_rule']['offer_rule_hash'],'fare_confirmed':True}); assert ho.status_code==200,ho.text
    assert ho.json()['data']['vault_release_ids']
    # Flight
    fs=client.post('/v1/flights/search',json={'origin':'PVG','destination':'NRT','departure_date':'2026-09-02','cabin':'ECONOMY','currency':'CNY'}).json()['data']['items'][0]
    fpb=client.post(f"/v1/flights/offers/{fs['offer_id']}/prebook").json()['data']
    fo=client.post('/v1/flights/orders',headers=h,json={'prebook_id':fpb['prebook_id'],'traveler_ids':[tid]}); assert fo.status_code==200,fo.text
    assert fo.json()['data']['passengers']==[{'full_name':'VAULT TESTER','type':'ADT'}]
    # Rail
    rs=client.post('/v1/rail/search',json={'origin_station':'SHA','destination_station':'HZH','travel_date':'2026-09-02','currency':'CNY'}).json()['data']['items'][0]
    rpb=client.post(f"/v1/rail/offers/{rs['offer_id']}/prebook").json()['data']
    ro=client.post('/v1/rail/orders',headers=h,json={'prebook_id':rpb['prebook_id'],'traveler_ids':[tid]}); assert ro.status_code==200,ro.text
    assert ro.json()['data']['passengers']==[{'full_name':'VAULT TESTER','type':'ADT'}]
    # Ride
    rides=client.post('/v1/mobility/rides/search',json={'pickup':'PVG','dropoff':'Bund','pickup_at':'2026-09-02T10:00:00','currency':'CNY'}).json()['data']['items'][0]
    ride=post_ride_order(client,headers=h,body={'offer_id':rides['offer_id'],'pickup':'PVG','dropoff':'Bund','pickup_at':'2026-09-02T10:00:00','currency':'CNY','traveler_ids':[tid]}); assert ride.status_code==200,ride.text
    assert ride.json()['data']['passengers']==[{'full_name':'VAULT TESTER','mobile':'13800000000'}]
    # Rental
    rentals=client.post('/v1/mobility/rentals/search',json={'pickup_location':'NRT','return_location':'NRT','pickup_at':'2026-09-02T09:00:00','return_at':'2026-09-05T09:00:00','currency':'CNY'}).json()['data']['items'][0]
    rental=client.post('/v1/mobility/rentals/orders',headers=h,json={'offer_id':rentals['offer_id'],'pickup_location':'NRT','return_location':'NRT','pickup_at':'2026-09-02T09:00:00','return_at':'2026-09-05T09:00:00','currency':'CNY','traveler_ids':[tid]}); assert rental.status_code==200,rental.text
    assert rental.json()['data']['drivers']==[{'full_name':'VAULT TESTER','driver_license_number':'DL-12345678'}]
    # Attraction
    attrs=client.post('/v1/attractions/search',json={'destination':'东京','visit_date':'2026-09-03'}).json()['data']['items'][0]
    attr=client.post('/v1/attractions/orders',headers=h,json=quoted_attraction(client,{'offer_id':attrs['offer_id'],'visit_date':'2026-09-03','quantity':1,'traveler_ids':[tid]})); assert attr.status_code==200,attr.text
    assert attr.json()['data']['attendees']==[{'full_name':'VAULT TESTER'}]

    with SessionLocal() as s:
        rows=s.scalars(select(ProfileDataReleaseAuditRow).where(ProfileDataReleaseAuditRow.user_id==user_id,ProfileDataReleaseAuditRow.decision=='ALLOW')).all()
        verticals={x.vertical for x in rows}
        assert {'HOTEL','FLIGHT','RAIL','RIDE','RENTAL','ATTRACTION'}.issubset(verticals)
        assert all(x.reason_code=='MINIMUM_NECESSARY_FIELDS_RELEASED' for x in rows if x.vertical in verticals)
