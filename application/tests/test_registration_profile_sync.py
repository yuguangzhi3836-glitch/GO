import importlib.util
import json
from pathlib import Path
import pytest
from go_hotel.services import registration_terms as terms

script=Path(__file__).resolve().parents[1]/'scripts/sync_registration_profile.py'
spec=importlib.util.spec_from_file_location('profile_sync',script)
sync=importlib.util.module_from_spec(spec);spec.loader.exec_module(sync)


def fictional_profile():
    first='0'*17
    check=sync.ALPHABET[(31-sum(sync.ALPHABET.index(c)*w for c,w in zip(first,sync.WEIGHTS))%31)%31]
    return {'legal_name':sync.COMPANY,'privacy_email':sync.EMAIL,'registration_address':'TEST ONLY 非真实企业地址','unified_social_credit_code':first+check,'source_reference':'SYNTHETIC TEST RECORD','delivery_evidence_ref':'TEST delivery'}


def test_existing_profile_sync_is_reviewable_not_auto_approval(tmp_path,monkeypatch):
    source=tmp_path/'profile.json';source.write_text(json.dumps(fictional_profile()))
    registry=terms._REGISTRY_ROOT/terms._DRAFT_VERSION/'registry.json'
    destination=tmp_path/'new-draft'
    result=sync.synchronize(source,registry,destination,'isolated-draft-test')
    assert not result['registration_enabled']
    value=json.loads((destination/'registry.json').read_text())
    assert value['operator']['registration_address']==fictional_profile()['registration_address']
    assert 'OPERATOR_REGISTRATION_DETAILS_MISSING' not in value['unresolved']
    assert 'CONTACT_DELIVERY_AND_HANDLING_UNVERIFIED' in value['unresolved']
    assert 'FORMAL_LEGAL_APPROVAL_MISSING' in value['unresolved']
    assert all(d['approval'] is None and d['status']=='DRAFT' for d in value['documents'])
    import hashlib
    for d in value['documents']:
        body=(destination/d['file']).read_bytes()
        assert hashlib.sha256(body).hexdigest()==d['sha256']
        assert fictional_profile()['registration_address'] in body.decode()
    with pytest.raises(ValueError,match='DESTINATION_ALREADY_EXISTS'):
        sync.synchronize(source,registry,destination,'isolated-draft-test')


@pytest.mark.parametrize('key,value', [('legal_name','other'),('privacy_email','other@example.test'),('registration_address',''),('unified_social_credit_code','wrong'),('password','must not be here')])
def test_bad_or_secret_source_never_writes(tmp_path,key,value):
    source=tmp_path/'profile.json';source.write_text(json.dumps(fictional_profile()|{key:value}))
    with pytest.raises(ValueError):sync.synchronize(source,terms._REGISTRY_ROOT/terms._DRAFT_VERSION/'registry.json',tmp_path/'out','new-draft')
    assert not (tmp_path/'out').exists()
