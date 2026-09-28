"""Real review endpoints; synthetic principals, no production login claim."""
import pytest
from datetime import datetime, timezone
from go_hotel.db.models import HotelPartnerChangeRequestRow, HotelPartnerRoomTypeRow
from test_hotel_direct_submission_api import api
from test_hotel_direct_submission_publication import publishing
from test_hotel_direct_submission_review import ready
from test_hotel_direct_submission_verification import setup
BASE='/internal/v1/hotel-autopage/direct-submission-reviews'

@pytest.mark.parametrize('suffix',['','/inspection','/media'])
def test_read_paths_require_admin_rules(api,suffix):
    client,login,data=api
    row=data[-1]; manifest=data[3]
    url=BASE if not suffix else BASE+'/'+row['review_id']+suffix
    if suffix=='/media':url+='/'+manifest['assets'][0]['asset_id']
    assert client.get(url).status_code==401
    login('SUPPLIER_USER',supplier='one');assert client.get(url).status_code==403
    login(permissions=set());assert client.get(url).status_code==403
    login();assert client.get(url).status_code==200


def test_queue_scoping_pagination_and_no_large_manifest(api):
    client,login,data=api
    pub,review,pid,manifest,factory,verifier,row=data
    for n in range(3):review.submit('one','owner',pid,manifest)
    with factory() as s:
        s.add(HotelPartnerChangeRequestRow(change_request_id='unrelated',property_id=pid,field_group='OTHER',proposed_value_json={},evidence_json=[],state='SUBMITTED',requested_by='owner',created_at=datetime.now(timezone.utc)))
        s.commit()
    login()
    first=client.get(BASE,params={'state':'SUBMITTED','property_id':pid,'limit':2}).json()['data']
    second=client.get(BASE,params={'state':'SUBMITTED','property_id':pid,'offset':2,'limit':2}).json()['data']
    assert first['total']==second['total']==3 and len(first['items'])==2 and len(second['items'])==1
    assert not set(r['review_id'] for r in first['items']) & set(r['review_id'] for r in second['items'])
    assert 'manifest' not in first['items'][0] and first['items'][0]['counts']['assets']==2
    assert client.get(BASE,params={'property_id':'other'}).json()['data']['total']==0
    assert client.get(BASE,params={'limit':101}).status_code==422
    assert client.get(BASE,params={'offset':-1}).status_code==422
    assert client.get(BASE,params={'state':'MADE_UP'}).status_code==409


def test_inspection_live_publication_then_stale_binding(api):
    client,login,data=api
    pub,review,pid,manifest,factory,verifier,row=data
    login();url=BASE+'/'+row['review_id']+'/inspection'
    before=client.get(url).json()['data']
    assert before['actions']=={'can_approve':False,'can_revoke':True,'can_publish':True}
    assert not before['publication']['publicly_available']
    assert before['room_mappings'][0]['canonical_name']=='Room'
    assert before['assets'][0]['verification']['original_verified']
    assert client.get(before['assets'][0]['preview_url']).headers['cache-control']=='no-store'
    pub.publish(row['review_id'],'one',pid,'admin')
    after=client.get(url).json()['data']
    assert after['publication']['publicly_available'] and after['publication']['live_read_verified']
    with factory() as s:
        s.get(HotelPartnerRoomTypeRow,manifest['inventory']['partner_room_ids'][0]).name_zh='Changed room'
        s.commit()
    stale=client.get(url).json()['data']
    assert not stale['actions']['can_publish'] and not stale['publication']['publicly_available']
    assert {'code':'DIRECT_SUBMISSION_REVIEW_STALE'} in stale['conflicts']
    assert stale['room_mappings'][0]['partner_name']=='Changed room'


def test_revocation_and_preview_unknown_asset(api):
    client,login,data=api
    pub,review,pid,manifest,factory,verifier,row=data
    login();url=BASE+'/'+row['review_id']
    assert client.get(url+'/media/unknown').status_code==404
    review.revoke(row['review_id'],'admin')
    result=client.get(url+'/inspection').json()['data']
    assert not any(result['actions'].values())


def test_current_rights_conflict_prevents_approval(api):
    client,login,data=api
    pub,review,pid,manifest,factory,verifier,row=data
    submitted=review.submit('one','owner',pid,manifest)
    verifier.media.cache.decide_rights(manifest['assets'][0]['asset_id'],rights_state='REJECTED',actor='rights-admin')
    login();result=client.get(BASE+'/'+submitted['review_id']+'/inspection').json()['data']
    assert not result['actions']['can_approve']
    assert any(b['code']=='CURRENT_RIGHTS_REVIEW_NOT_VERIFIED' for b in result['conflicts'])
    assert not next(a for a in result['assets'] if a['asset_id']==manifest['assets'][0]['asset_id'])['verification']['current_rights_verified']


def test_supplier_reads_are_property_scoped(api):
    client,login,data=api
    pub,review,pid,manifest,factory,verifier,row=data
    path=f'/v1/supplier/properties/{pid}/direct-submission-reviews'
    login('SUPPLIER_USER',supplier='other')
    assert client.get(path).status_code==409
    assert client.get(path+'/'+row['review_id']).status_code==409
    login('SUPPLIER_USER',supplier='one')
    assert client.get(path).json()['data']['total']==1
    assert client.get(path+'/'+row['review_id']).json()['data']['property_id']==pid
    assert client.get('/v1/supplier/properties/other/direct-submission-reviews/'+row['review_id']).status_code==409


def test_catalog_provenance_conflicts_visible_and_block_publish(api):
    from go_hotel.db.models import HotelCanonicalProfileRow
    client,login,data=api
    pub,review,pid,manifest,factory,verifier,row=data
    with factory() as s:
        s.get(HotelCanonicalProfileRow,'hotel').field_provenance_json={'address':{'conflict_state':'REVIEW_REQUIRED'}}
        s.commit()
    login();result=client.get(BASE+'/'+row['review_id']+'/inspection').json()['data']
    assert not result['actions']['can_publish']
    assert any(c['code']=='ADDRESS_CONFLICT' and c['field']=='address' for c in result['conflicts'])


def test_approval_binds_displayed_physical_facts(api):
    client,login,data=api
    pub,review,pid,manifest,factory,verifier,old=data
    row=review.submit('one','owner',pid,manifest)
    login();url=BASE+'/'+row['review_id']
    displayed=client.get(url+'/inspection').json()['data']
    assert displayed['actions']['can_approve'] and len(displayed['facts_sha256'])==64
    assert client.post(url+'/approve',json={'expected_sha256':row['manifest_sha256']}).status_code==422
    assert review.get(row['review_id'])['state']=='SUBMITTED'
    body={'expected_sha256':row['manifest_sha256'],'expected_facts_sha256':displayed['facts_sha256']}
    with factory() as s:
        s.get(HotelPartnerRoomTypeRow,manifest['inventory']['partner_room_ids'][0]).name_zh='Changed after inspection'
        s.commit()
    rejected=client.post(url+'/approve',json=body)
    assert rejected.status_code==409 and rejected.json()['detail']=='DIRECT_SUBMISSION_REVIEW_FACTS_MISMATCH'
    assert review.get(row['review_id'])['state']=='SUBMITTED'
    fresh=client.get(url+'/inspection').json()['data']
    assert fresh['facts_sha256']!=displayed['facts_sha256']
    body['expected_facts_sha256']=fresh['facts_sha256']
    assert client.post(url+'/approve',json=body).status_code==200
