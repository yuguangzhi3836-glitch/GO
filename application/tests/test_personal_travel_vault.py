import pytest
from datetime import timedelta
from urllib.parse import parse_qs,urlparse
from go_hotel.db.models import ProfileImportJobRow
from go_hotel.db.session import SessionLocal
from go_hotel.services.personal_travel_vault import now
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

def test_account_holder_connection_never_accepts_ota_password_and_has_upload_fallback(monkeypatch):
    user='consumer_provider_1'
    monkeypatch.delenv('GO_CTRIP_PROFILE_AUTHORIZATION_URL',raising=False)
    with pytest.raises(ValueError,match='OTA_CREDENTIALS_NOT_ACCEPTED'):
        svc.create_provider_connection(user,{'provider':'CTRIP','password':'secret'})
    connection=svc.create_provider_connection(user,{'provider':'CTRIP','method':'OFFICIAL_AUTHORIZATION','account_holder_confirmed':True})
    assert connection['status']=='AWAITING_USER_UPLOAD'
    assert connection['authorization_url'] is None
    assert connection['credentials_received_by_go'] is False

def test_account_holder_connection_returns_provider_hosted_authorization(monkeypatch):
    monkeypatch.setenv('GO_MEITUAN_PROFILE_AUTHORIZATION_URL','https://open.meituan.example/oauth/authorize?client_id=go')
    connection=svc.create_provider_connection('consumer_provider_2',{'provider':'MEITUAN','method':'OFFICIAL_AUTHORIZATION','account_holder_confirmed':True})
    assert connection['status']=='AWAITING_PROVIDER_AUTHORIZATION'
    assert connection['authorization_url'].startswith('https://open.meituan.example/')
    assert 'state=' in connection['authorization_url']
    assert connection['login_surface']=='PROVIDER_HOSTED'

def test_provider_connection_requires_explicit_holder_confirmation_and_rejects_nested_credentials(monkeypatch):
    monkeypatch.delenv('GO_FLIGGY_PROFILE_AUTHORIZATION_URL',raising=False)
    with pytest.raises(ValueError,match='ACCOUNT_HOLDER_CONFIRMATION_REQUIRED'):
        svc.create_provider_connection('consumer_provider_3',{'provider':'FLIGGY','method':'FILE_UPLOAD'})
    with pytest.raises(ValueError,match='OTA_CREDENTIALS_NOT_ACCEPTED'):
        svc.create_provider_connection('consumer_provider_3',{'provider':'FLIGGY','account_holder_confirmed':True,'payload':{'cookie':'private'}})

def test_official_authorization_is_bound_to_holder_and_state_is_one_time(monkeypatch):
    monkeypatch.setenv('GO_CTRIP_PROFILE_AUTHORIZATION_URL','https://accounts.ctrip.example/authorize')
    user='consumer_provider_4'
    connection=svc.create_provider_connection(user,{'provider':'CTRIP','account_holder_confirmed':True})
    state=parse_qs(urlparse(connection['authorization_url']).query)['state'][0]
    body={'state':state,'account_holder_verified':True,'provider_account_subject':'ctrip-user-42',
        'authorization_evidence_reference':'adapter-evidence://ctrip/42','items':import_body()['items']}
    result=svc.complete_provider_connection(connection['connection_id'],body)
    assert result['status']=='PREVIEW_READY'
    assert result['preview']['status']=='EXTRACTED'
    assert result['credentials_received_by_go'] is False
    with pytest.raises(ValueError,match='PROFILE_PROVIDER_STATE_ALREADY_USED'):
        svc.complete_provider_connection(connection['connection_id'],body)
    assert svc.provider_connections(user)['items'][0]['import_job_id']==result['preview']['import_job_id']
    assert svc.provider_connections('another-consumer')['items']==[]

def test_official_authorization_rejects_unverified_holder_and_expired_state(monkeypatch):
    monkeypatch.setenv('GO_BOOKING_PROFILE_AUTHORIZATION_URL','https://account.booking.example/authorize')
    connection=svc.create_provider_connection('consumer_provider_5',{'provider':'BOOKING','account_holder_confirmed':True})
    state=parse_qs(urlparse(connection['authorization_url']).query)['state'][0]
    with pytest.raises(ValueError,match='PROVIDER_ACCOUNT_HOLDER_NOT_VERIFIED'):
        svc.complete_provider_connection(connection['connection_id'],{'state':state})
    with SessionLocal.begin() as s:
        row=s.get(ProfileImportJobRow,connection['connection_id'])
        row.metadata_json={**row.metadata_json,'expires_at':(now()-timedelta(seconds=1)).isoformat()}
    with pytest.raises(ValueError,match='PROFILE_PROVIDER_STATE_EXPIRED'):
        svc.complete_provider_connection(connection['connection_id'],{'state':state,'account_holder_verified':True,
            'provider_account_subject':'booking-user','authorization_evidence_reference':'adapter-evidence://booking/1'})

def test_fallback_upload_previews_then_delete_removes_imported_values(monkeypatch):
    monkeypatch.delenv('GO_MEITUAN_PROFILE_AUTHORIZATION_URL',raising=False)
    user='consumer_provider_6'
    connection=svc.create_provider_connection(user,{'provider':'MEITUAN','account_holder_confirmed':True})
    result=svc.upload_provider_export(user,connection['connection_id'],{'account_holder_confirmed':True,
        'upload_kind':'DATA_EXPORT','items':import_body()['items']})
    assert result['status']=='PREVIEW_READY' and result['preview']['item_count']==4
    preview=accept_all(user,result['preview']);committed=svc.commit_import(user,preview['import_job_id'])
    assert committed['status']=='COMMITTED' and svc.vault(user)['traveler_count']==1
    removed=svc.disconnect_provider_connection(user,connection['connection_id'],True)
    assert removed['status']=='DELETED' and removed['imported_values']['deleted_facts']>=1
    with pytest.raises(ValueError,match='PROFILE_PROVIDER_CONNECTION_NOT_FOUND'):
        svc.disconnect_provider_connection('different-owner',connection['connection_id'],True)

def test_provider_upload_is_one_time_and_requires_owner_confirmation(monkeypatch):
    monkeypatch.delenv('GO_CTRIP_PROFILE_AUTHORIZATION_URL',raising=False)
    connection=svc.create_provider_connection('consumer_provider_7',{'provider':'CTRIP','account_holder_confirmed':True})
    with pytest.raises(ValueError,match='ACCOUNT_HOLDER_CONFIRMATION_REQUIRED'):
        svc.upload_provider_export('consumer_provider_7',connection['connection_id'],{'items':[]})
    svc.upload_provider_export('consumer_provider_7',connection['connection_id'],{'account_holder_confirmed':True,'items':[]})
    with pytest.raises(ValueError,match='PROFILE_PROVIDER_UPLOAD_ALREADY_RECEIVED'):
        svc.upload_provider_export('consumer_provider_7',connection['connection_id'],{'account_holder_confirmed':True,'items':[]})
