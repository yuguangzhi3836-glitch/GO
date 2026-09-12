import pytest
from go_hotel.services.personal_travel_vault import personal_travel_vault_service as svc

def import_body(source='SCREENSHOT_AI',fingerprint='src-1',seat='AISLE'):
    return {'source_type':source,'source_provider':'TRIP_COM','source_reference':'user_shared','source_fingerprint':fingerprint,'items':[
        {'entity_type':'TRAVELER','traveler_ref':'me','value':{'full_name':'Test Traveler','date_of_birth':'1990-01-01','nationality':'CHN','relationship_type':'SELF','is_primary':True},'confidence_bps':9800},
        {'entity_type':'PROFILE_FACT','traveler_ref':'me','field_type':'PASSPORT_NUMBER','value':'E12345678','sensitive':True,'confidence_bps':9900},
        {'entity_type':'PROFILE_FACT','traveler_ref':'me','field_type':'MOBILE','value':'13800000000','confidence_bps':9800},
        {'entity_type':'PROFILE_FACT','traveler_ref':'me','field_type':'PREFERENCE_FLIGHT_SEAT','value':seat,'confidence_bps':9700},
    ]}

def accept_all(user,job):
    cur=job
    for item in list(cur['items']):
        if item['status'] in {'NEEDS_REVIEW','EXTRACTED'}:
            cur=svc.review_item(user,cur['import_job_id'],item['import_item_id'],'ACCEPT')
    return cur

def test_screenshot_import_requires_review_and_masks_sensitive_fact():
    user='consumer_vault_1';job=svc.create_import(user,import_body())
    assert job['status']=='EXTRACTED'
    before=svc.commit_import(user,job['import_job_id'])
    assert before['status']=='NEEDS_REVIEW'
    accept_all(user,before);done=svc.commit_import(user,job['import_job_id'])
    assert done['status']=='COMMITTED'
    vault=svc.vault(user)
    assert vault['traveler_count']==1
    passport=next(f for f in vault['travelers'][0]['facts'] if f['field_type']=='PASSPORT_NUMBER')
    assert passport['value_masked'].endswith('5678') and passport['value_masked']!='E12345678'
    assert passport['verification_status']=='USER_CONFIRMED'
    assert passport['trust_level']=='L1_USER_CONFIRMED'
    assert vault['ai_full_vault_access'] is False

def test_sensitive_release_requires_consent_and_releases_only_requested_fields():
    user='consumer_vault_2';job=svc.create_import(user,import_body(fingerprint='src-2'));accept_all(user,job);svc.commit_import(user,job['import_job_id']);trav=svc.vault(user)['travelers'][0]
    with pytest.raises(ValueError,match='SENSITIVE_CONSENT_REQUIRED'):
        svc.release(user,{'traveler_id':trav['traveler_id'],'requested_fields':['PASSPORT_NUMBER'],'vertical':'FLIGHT','purpose':'INTERNATIONAL_FLIGHT_BOOKING','destination':'FLIGHT_ADAPTER'})
    c=svc.grant_consent(user,{'traveler_id':trav['traveler_id'],'consent_type':'SENSITIVE_DATA_RELEASE','purpose':'INTERNATIONAL_FLIGHT_BOOKING','scope':['PASSPORT_NUMBER']})
    r=svc.release(user,{'traveler_id':trav['traveler_id'],'requested_fields':['PASSPORT_NUMBER'],'vertical':'FLIGHT','purpose':'INTERNATIONAL_FLIGHT_BOOKING','destination':'FLIGHT_ADAPTER'})
    assert r['released_fields']=={'PASSPORT_NUMBER':'E12345678'}
    assert r['consent_id']==c['consent_id'] and r['minimum_necessary'] is True

def test_import_idempotency_and_conflict_no_silent_overwrite():
    user='consumer_vault_3';a=svc.create_import(user,import_body(fingerprint='same'));replay=svc.create_import(user,import_body(fingerprint='same'))
    assert replay['idempotent_replay'] is True and replay['import_job_id']==a['import_job_id']
    accept_all(user,a);svc.commit_import(user,a['import_job_id'])
    b=svc.create_import(user,import_body(fingerprint='new-source',seat='WINDOW'));accept_all(user,b);conf=svc.commit_import(user,b['import_job_id'])
    assert conf['status']=='CONFLICT' and conf['conflict_count']==1
    vault=svc.vault(user);seat=[f for f in vault['travelers'][0]['facts'] if f['field_type']=='PREFERENCE_FLIGHT_SEAT']
    assert len(seat)==1 and seat[0]['value_masked']=='AISLE'

def test_completeness_is_capability_based_not_percent_only():
    user='consumer_vault_4';job=svc.create_import(user,import_body(fingerprint='src-4'));accept_all(user,job);svc.commit_import(user,job['import_job_id'])
    c=svc.completeness(user)
    assert c['capabilities']['DOMESTIC_FLIGHT_READY'] is True
    assert c['capabilities']['INTERNATIONAL_FLIGHT_READY'] is True
    assert c['capabilities']['HOTEL_READY'] is True

def test_consumer_cannot_self_assert_official_or_verified_source():
    user='consumer_vault_5'
    body=import_body(source='OFFICIAL_API',fingerprint='forged-official')
    with pytest.raises(ValueError,match='TRUSTED_PROFILE_SOURCE_ADAPTER_REQUIRED'):
        svc.create_import(user,body)
    body=import_body(source='DOCUMENT_SCAN',fingerprint='forged-nfc')
    body['items'][1]['verification_method']='NFC'
    with pytest.raises(ValueError,match='TRUSTED_PROFILE_SOURCE_ADAPTER_REQUIRED'):
        svc.create_import(user,body)
