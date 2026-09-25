from registration_terms_test_support import register_synthetic_consumer
from concurrent.futures import ThreadPoolExecutor
import json
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import ProfileFactRow, ProfileImportItemRow, TravelerProfileRow
from go_hotel.security.crypto import decrypt_secret
from go_hotel.services.personal_travel_vault import personal_travel_vault_service as vault


def import_items(items, user='owner', **options):
    return vault.create_import(user, {'source_type':'MANUAL', 'items':items, **options})


def accept(job, user='owner'):
    for item in job['items']:
        vault.review_item(user,job['import_job_id'],item['import_item_id'],'ACCEPT')
    return vault.commit_import(user,job['import_job_id'])


def create_person(user='owner', relationship='SELF', name='TRAVELER ONE', field='DATE_OF_BIRTH', value='1990-01-01'):
    job=import_items([
        {'entity_type':'TRAVELER','traveler_ref':'person','value':{'full_name':name,'relationship_type':relationship}},
        {'traveler_ref':'person','field_type':field,'value':value}],user=user)
    result=accept(job,user)
    tid=result['items'][0]['resolution_traveler_id']
    person=next(t for t in vault.vault(user)['travelers'] if t['traveler_id']==tid)
    return person,job


def fact_edit(fact,value):
    return {'confirmed':True,'expected_revision':fact['revision'],'value':value}


def test_fact_edit_creates_user_revision_and_drops_prior_document_certification():
    person,_=create_person(field='PASSPORT_NUMBER',value='PASSPORT-OLD')
    fid=person['facts'][0]['fact_id']
    with SessionLocal.begin() as s:
        row=s.get(ProfileFactRow,fid);row.trust_level='L4_VERIFIED_DOCUMENT';row.verification_status='VERIFIED'
    person=vault.vault('owner')['travelers'][0];fact=person['facts'][0]
    with pytest.raises(ValueError,match='CONFIRMATION_REQUIRED'):
        vault.edit_fact('owner',fid,{**fact_edit(fact,'PASSPORT-NEW'),'confirmed':False})
    result=vault.edit_fact('owner',fid,fact_edit(fact,'PASSPORT-NEW'))
    assert result['trust_level']=='L1_USER_CONFIRMED'
    with SessionLocal() as s:
        old=s.get(ProfileFactRow,fid);new=s.get(ProfileFactRow,result['fact_id'])
        assert old.status=='SUPERSEDED' and old.superseded_by==new.fact_id
        assert new.source_type=='MANUAL' and new.verification_status=='USER_CONFIRMED'
    with pytest.raises(ValueError,match='CHANGED_RELOAD'):vault.edit_fact('owner',fid,fact_edit(fact,'LATE-WRITE'))


def test_two_concurrent_person_edits_cannot_silently_overwrite():
    person,_=create_person()
    def write(name):
        try:return vault.edit_traveler('owner',person['traveler_id'],{'confirmed':True,'expected_revision':person['revision'],'full_name':name})['status']
        except ValueError as e:return str(e)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(write,['DEVICE ONE','DEVICE TWO']))
    assert sorted(results)==['PROFILE_CHANGED_RELOAD_REQUIRED','UPDATED']
    assert vault.vault('owner')['travelers'][0]['full_name'] in {'DEVICE ONE','DEVICE TWO'}


@pytest.mark.parametrize('permission,field',[('USE_FOR_BOOKING','LEGAL_NAME'),('SENSITIVE_DATA','DATE_OF_BIRTH')])
def test_revoking_self_permission_blocks_real_data_release(permission,field):
    person,_=create_person();tid=person['traveler_id']
    vault.grant_consent('owner',{'traveler_id':tid,'scope':['DATE_OF_BIRTH']})
    assert field in vault.release('owner',{'traveler_id':tid,'requested_fields':[field]})['released_fields']
    vault.set_permission('owner',tid,permission,False)
    with pytest.raises(ValueError,match='PERMISSION_REQUIRED'):vault.release('owner',{'traveler_id':tid,'requested_fields':[field]})
    vault.set_permission('owner',tid,permission,True)
    assert field in vault.release('owner',{'traveler_id':tid,'requested_fields':[field]})['released_fields']


def test_companion_identity_match_cannot_bypass_edit_permission():
    person,_=create_person(relationship='FAMILY',field='PASSPORT_NUMBER',value='COMPANION-DOCUMENT')
    job=import_items([{'entity_type':'TRAVELER','traveler_ref':'match','value':{'full_name':person['full_name'],'document_number':'COMPANION-DOCUMENT'}},
        {'traveler_ref':'match','field_type':'MOBILE','value':'13900000000'}])
    for item in job['items']:vault.review_item('owner',job['import_job_id'],item['import_item_id'],'ACCEPT')
    with pytest.raises(ValueError,match='EDIT_PERMISSION'):vault.commit_import('owner',job['import_job_id'])
    assert [f['field_type'] for f in vault.vault('owner')['travelers'][0]['facts']]==['PASSPORT_NUMBER']


@pytest.mark.parametrize('ref',['missing','rejected'])
def test_unknown_or_rejected_reference_never_falls_back_to_account_owner(ref):
    person,_=create_person()
    items=[{'traveler_ref':ref,'field_type':'MOBILE','value':'13911111111'}]
    if ref=='rejected':items.insert(0,{'entity_type':'TRAVELER','traveler_ref':ref,'value':{'full_name':'DIFFERENT PERSON'}})
    job=import_items(items)
    for item in job['items']:vault.review_item('owner',job['import_job_id'],item['import_item_id'],'REJECT' if item['entity_type']=='TRAVELER' else 'ACCEPT')
    result=vault.commit_import('owner',job['import_job_id'])
    assert result['status']=='NEEDS_REVIEW'
    assert all(f['field_type']!='MOBILE' for f in vault.vault('owner')['travelers'][0]['facts'])
    item=next(i for i in result['items'] if i['entity_type']=='PROFILE_FACT')
    vault.assign_import_traveler('owner',job['import_job_id'],item['import_item_id'],{'traveler_id':person['traveler_id'],'confirmed':True,'expected_revision':item['revision']})
    vault.review_item('owner',job['import_job_id'],item['import_item_id'],'ACCEPT')
    assert vault.commit_import('owner',job['import_job_id'])['status']=='COMMITTED'


def test_source_disconnect_blocks_new_and_pending_imports_but_keeps_saved_facts():
    person,original=create_person()
    fingerprint=original['source_fingerprint']
    pending=import_items([{'field_type':'MOBILE','value':'13922222222'}],source_fingerprint=fingerprint)
    vault.set_source_connection('owner',fingerprint,False)
    with pytest.raises(ValueError,match='DISCONNECTED'):vault.commit_import('owner',pending['import_job_id'])
    with pytest.raises(ValueError,match='DISCONNECTED'):import_items([{'field_type':'EMAIL','value':'saved@example.test'}],source_fingerprint=fingerprint)
    assert vault.vault('owner')['travelers'][0]['facts']
    assert vault.source_list('owner')['items'][0]['status']=='DISCONNECTED'
    vault.set_source_connection('owner',fingerprint,True)
    assert accept(pending)['status']=='COMMITTED'


@pytest.mark.parametrize('change',['edit','delete'])
def test_conflict_choice_requires_review_again_when_existing_value_changes(change):
    person,_=create_person();old=person['facts'][0]
    pending=import_items([{'field_type':'DATE_OF_BIRTH','value':'1992-02-02'}]);result=accept(pending)
    assert result['status']=='CONFLICT'
    item=result['items'][0];vault.review_item('owner',pending['import_job_id'],item['import_item_id'],'REPLACE_EXISTING')
    if change=='edit':vault.edit_fact('owner',old['fact_id'],fact_edit(old,'1991-01-01'))
    else:vault.delete_fact('owner',old['fact_id'])
    result=vault.commit_import('owner',pending['import_job_id'])
    assert result['status'] in {'CONFLICT','NEEDS_REVIEW'}
    assert result['items'][0]['review_action'] is None
    exported=vault.export_owned('owner',True)
    assert '1992-02-02' not in json.dumps(exported)


def test_deleted_revision_chain_is_erased_from_export_core_and_import_copies():
    person,job=create_person();old=person['facts'][0]
    new=vault.edit_fact('owner',old['fact_id'],fact_edit(old,'1994-04-04'))
    result=vault.delete_fact('owner',new['fact_id'])
    assert result['erased_revision_count']==2
    exported=json.dumps(vault.export_owned('owner',True))
    assert '1990-01-01' not in exported and '1994-04-04' not in exported
    with SessionLocal() as s:
        assert s.get(TravelerProfileRow,person['traveler_id']).date_of_birth is None
        assert all(decrypt_secret(f.value_ciphertext)=='null' for f in s.scalars(select(ProfileFactRow)).all())
        item=s.get(ProfileImportItemRow,job['items'][1]['import_item_id'])
        assert item.candidate_value_ciphertext is None


def test_invalid_edit_is_atomic_and_cannot_change_relationship_or_certification():
    person,_=create_person()
    body={'confirmed':True,'expected_revision':person['revision'],'full_name':'SHOULD ROLLBACK','date_of_birth':'2999-01-01'}
    with pytest.raises(ValueError,match='BIRTH_DATE_INVALID'):vault.edit_traveler('owner',person['traveler_id'],body)
    assert vault.vault('owner')['travelers'][0]['full_name']==person['full_name']
    with pytest.raises(ValueError,match='FIELD_NOT_ALLOWED'):vault.edit_traveler('owner',person['traveler_id'],{'confirmed':True,'expected_revision':person['revision'],'relationship_type':'SELF'})


def test_api_requires_owner_strict_permission_and_explicit_uncached_inspection(client):
    r=register_synthetic_consumer(client, json={'email':'depth04@example.test','password':'StrongPass123!','display_name':'NICKNAME'})
    uid=r.json()['data']['profile']['user_id']
    token=client.post('/v1/mobile/auth/login',json={'email':'depth04@example.test','password':'StrongPass123!'}).json()['data']['access_token']
    client.cookies.clear();headers={'Authorization':'Bearer '+token}
    person,job=create_person(uid);path=f"/v1/consumer/profile/travelers/{person['traveler_id']}/permissions/USE_FOR_BOOKING"
    assert client.put(path,headers=headers,json={'allowed':'false'}).status_code==422
    assert client.put(path,json={'allowed':False}).status_code==401
    assert client.get('/v1/consumer/profile/imports',headers=headers).json()['data']['items'][0]['import_job_id']==job['import_job_id']
    item=job['items'][1];path=f"/v1/consumer/profile/imports/{job['import_job_id']}/items/{item['import_item_id']}/inspect"
    assert client.post(path,headers=headers,json={'confirmed':False}).status_code==409
    inspected=client.post(path,headers=headers,json={'confirmed':True})
    assert inspected.status_code==200 and inspected.json()['data']['value']=='1990-01-01'
    assert 'no-store' in inspected.headers['Cache-Control']
    other,other_job=create_person('different-owner')
    other_path=f"/v1/consumer/profile/imports/{other_job['import_job_id']}/items/{other_job['items'][1]['import_item_id']}/inspect"
    assert client.post(other_path,headers=headers,json={'confirmed':True}).status_code==404
    assert client.patch(f"/v1/consumer/profile/facts/{other['facts'][0]['fact_id']}",headers=headers,json=fact_edit(other['facts'][0],'2000-01-01')).status_code==404


def test_completed_import_review_is_immutable_and_replay_does_not_duplicate():
    person,job=create_person();count=len(vault.export_owned('owner',True)['travelers'][0]['facts'])
    with pytest.raises(ValueError,match='FINALIZED'):vault.review_item('owner',job['import_job_id'],job['items'][0]['import_item_id'],'REJECT')
    assert vault.commit_import('owner',job['import_job_id'])['idempotent_replay']
    assert len(vault.export_owned('owner',True)['travelers'][0]['facts'])==count


def test_duplicate_traveler_reference_is_rejected_atomically():
    with pytest.raises(ValueError,match='REFERENCE_AMBIGUOUS'):
        import_items([{'entity_type':'TRAVELER','traveler_ref':'a','value':{'full_name':name}} for name in ['PERSON A','PERSON B']])
    assert vault.import_list('owner')['items']==[]


def test_source_delete_erases_core_values_and_reconnect_requires_fresh_import():
    data=[{'entity_type':'TRAVELER','traveler_ref':'self','value':{'full_name':'IMPORTED PERSON',
        'date_of_birth':'1988-08-08','nationality':'CHN','document_number':'OLD-DOC'}}]
    job=import_items(data);accept(job)
    vault.delete_source('owner',job['source_fingerprint'])
    exported=json.dumps(vault.export_owned('owner',True))
    assert all(value not in exported for value in ['IMPORTED PERSON','1988-08-08','OLD-DOC'])
    with SessionLocal() as s:assert s.scalar(select(TravelerProfileRow)).document_ciphertext is None
    vault.set_source_connection('owner',job['source_fingerprint'],True)
    with pytest.raises(ValueError,match='VALUE_REMOVED'):vault.commit_import('owner',job['import_job_id'])
    fresh=import_items(data)
    assert fresh['import_job_id']!=job['import_job_id']


def test_clearing_birth_date_also_erases_original_traveler_declaration():
    job=import_items([{'entity_type':'TRAVELER','value':{'full_name':'PERSON','date_of_birth':'1988-08-08'}}]);accept(job)
    person=vault.vault('owner')['travelers'][0]
    vault.edit_traveler('owner',person['traveler_id'],{'confirmed':True,'expected_revision':person['revision'],'date_of_birth':None})
    with SessionLocal() as s:
        item=s.get(ProfileImportItemRow,job['items'][0]['import_item_id'])
        assert '1988-08-08' not in decrypt_secret(item.candidate_value_ciphertext)


def test_source_deletion_retains_independent_manual_revision():
    person,job=create_person()
    vault.edit_fact('owner',person['facts'][0]['fact_id'],fact_edit(person['facts'][0],'1995-05-05'))
    vault.delete_source('owner',job['source_fingerprint'])
    exported=json.dumps(vault.export_owned('owner',True))
    assert '1995-05-05' in exported and '1990-01-01' not in exported


def test_self_export_respects_revoked_share_and_sensitive_permissions():
    person,_=create_person()
    vault.set_permission('owner',person['traveler_id'],'SENSITIVE_DATA',False)
    assert '1990-01-01' not in json.dumps(vault.export_owned('owner',True))
    vault.set_permission('owner',person['traveler_id'],'SHARE',False)
    assert vault.export_owned('owner',True)['travelers']==[]
