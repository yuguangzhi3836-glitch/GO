"""Real service/HTTP persistence tests; no canonical publication is granted here."""
from types import SimpleNamespace
import pytest
from test_hotel_partner_media_upload import setup, payload
from go_hotel.api.routes import hotel_partner_core as api
from go_hotel.services.hotel_partner_core import hotel_partner_core_service as core


def bound(setup):
    svc, client, app, pid, other = setup
    url = f'/v1/supplier/properties/{pid}'
    asset = client.post(url + '/media-uploads', json=payload()[0]).json()['data']
    response = client.post(url + f'/media-uploads/{asset["asset_id"]}/binding',
        json={'expected_revision': asset['revision'], 'role': 'HERO'})
    assert response.status_code == 200, response.text
    return url, response.json()['data']


def test_binding_persisted_request_dedup_private_readback(setup):
    svc, client, app, pid, other = setup
    url, item = bound(setup)
    assert item['bound'] and not item['publishable'] and not item['rights_approved']
    assert client.get(url + '/media-uploads').json()['data'][0]['bound']
    body = {'asset_ids': [item['asset_id']], 'confirmed': True}
    response = client.post(url + '/media-publication-requests', json=body)
    assert response.status_code == 200, response.text
    request = response.json()['data']
    assert request['state'] == 'SUBMITTED' and request['publication_state'] == 'PUBLISH_REQUESTED'
    assert not request['published'] and not request['supplier_can_publish']
    assert {x['code'] for x in request['blockers']} == {'RIGHTS_REVIEW_REQUIRED','CANONICAL_PUBLICATION_REVIEW_REQUIRED'}
    again = client.post(url + '/media-publication-requests', json=body).json()['data']
    assert again['deduplicated'] and again['change_request_id'] == request['change_request_id']
    assert len(client.get(url + '/media-publication-requests').json()['data']) == 1
    assert core.graph('one', pid)['property']['publication_state'] == 'DRAFT'
    with pytest.raises(ValueError, match='MEDIA_ASSET_NOT_PUBLISHABLE'):
        svc.cache.content_path(item['asset_id'])


def test_room_binding_reuses_original_resets_rights_not_other_property(setup):
    svc, client, app, pid, other = setup
    url, item = bound(setup)
    svc.cache.decide_rights(asset_id=item['asset_id'], rights_state='AUTHORIZED', actor='catalog-reviewer',
        rights_owner='hotel', evidence_reference='approved-contract', expected_revision=item['revision'])
    approved = svc.cache.get(item['asset_id'])
    room = core.create_room_type('one','owner',pid,{'name_zh':'room','physical_room_count':1,
        'occupancy':{'max_occupancy':2,'max_adults':2,'max_children':0}})['room_type_id']
    response = client.post(url + f'/media-uploads/{item["asset_id"]}/binding', json={
        'expected_revision': approved['revision'], 'role':'ROOM','room_type_id':room})
    assert response.status_code == 200, response.text
    derived = response.json()['data']
    assert derived['asset_id'] != item['asset_id'] and derived['sha256'] == item['sha256']
    assert derived['room_type_id'] == room and not derived['rights_approved']
    assert len(list(svc.cache.files_dir.iterdir())) == 1
    graph = core.graph('one',pid)
    assert graph['room_types'][0]['media_json'][0]['asset_id'] == derived['asset_id']
    repeat = client.post(url + f'/media-uploads/{item["asset_id"]}/binding', json={
        'expected_revision': approved['revision'], 'role':'ROOM','room_type_id':room}).json()['data']
    assert repeat['asset_id'] == derived['asset_id']
    assert len(core.graph('one',pid)['room_types'][0]['media_json']) == 1
    app.dependency_overrides[api.supplier_principal] = lambda: SimpleNamespace(supplier_id='two',user_id='other')
    assert client.post(url + '/media-publication-requests',json={'asset_ids':[derived['asset_id']], 'confirmed':True}).status_code == 404
    assert client.get(url + '/media-publication-requests').status_code == 404


def test_stale_revision_foreign_room_and_unknown_fields_rejected(setup):
    svc, client, app, pid, other = setup
    url, item = bound(setup)
    endpoint = url + f'/media-uploads/{item["asset_id"]}/binding'
    assert client.post(endpoint,json={'expected_revision':999,'role':'HERO'}).status_code == 409
    assert client.post(endpoint,json={'expected_revision':True,'role':'HERO'}).status_code == 422
    assert client.post(endpoint,json={'expected_revision':item['revision'],'role':'HERO','rights_state':'AUTHORIZED'}).status_code == 422
    room = core.create_room_type('two','other',other,{'name_zh':'room','physical_room_count':1,
        'occupancy':{'max_occupancy':2,'max_adults':2,'max_children':0}})['room_type_id']
    assert client.post(endpoint,json={'expected_revision':item['revision'],'role':'ROOM','room_type_id':room}).status_code == 404
    assert len(svc.list_uploads('one',pid)) == 1


@pytest.mark.parametrize('kind',['unbound','foreign','missing','unconfirmed','duplicate','publication_override','corrupt'])
def test_invalid_publication_batch_no_partial_request(setup,kind):
    svc, client, app, pid, other = setup
    url,item = bound(setup)
    body={'asset_ids':[item['asset_id']],'confirmed':True}
    if kind=='unbound':
        b,_=payload();b['role']='GALLERY';body['asset_ids'].append(svc.upload('one','owner',pid,b)['asset_id'])
    if kind=='foreign':body['asset_ids'].append(svc.upload('two','other',other,payload()[0])['asset_id'])
    if kind=='missing':body['asset_ids'].append('missing')
    if kind=='unconfirmed':body['confirmed']=False
    if kind=='duplicate':body['asset_ids']*=2
    if kind=='publication_override':body['published']=True
    if kind=='corrupt':next(svc.cache.files_dir.iterdir()).write_bytes(b'broken')
    assert client.post(url+'/media-publication-requests',json=body).status_code in {404,422}
    assert client.get(url+'/media-publication-requests').json()['data']==[]


def test_approved_then_revoked_rights_readback_is_dynamic(setup):
    svc, client, app, pid, other = setup
    url,item = bound(setup)
    endpoint=url+'/media-publication-requests'
    client.post(endpoint,json={'asset_ids':[item['asset_id']],'confirmed':True})
    approved=svc.cache.decide_rights(asset_id=item['asset_id'],rights_state='AUTHORIZED',actor='reviewer',
        rights_owner='hotel',evidence_reference='contract',expected_revision=item['revision'])
    assert client.get(url+'/media-uploads').json()['data'][0]['rights_approved']
    assert [x['code'] for x in client.get(endpoint).json()['data'][0]['blockers']]==['CANONICAL_PUBLICATION_REVIEW_REQUIRED']
    svc.cache.decide_rights(asset_id=item['asset_id'],rights_state='REJECTED',actor='reviewer',expected_revision=approved['revision'])
    assert not client.get(url+'/media-uploads').json()['data'][0]['rights_approved']
    assert client.get(endpoint).json()['data'][0]['blockers'][0]['code']=='RIGHTS_REVIEW_REQUIRED'


def test_rejected_request_history_is_not_reported_pending(setup):
    from go_hotel.db.session import SessionLocal
    from go_hotel.db.models import HotelPartnerChangeRequestRow
    svc, client, app, pid, other = setup
    url, item = bound(setup)
    endpoint = url + '/media-publication-requests'
    request = client.post(endpoint,json={'asset_ids':[item['asset_id']],'confirmed':True}).json()['data']
    with SessionLocal() as s:
        row = s.get(HotelPartnerChangeRequestRow, request['change_request_id'])
        row.state = 'REJECTED'
        s.commit()
    latest = client.get(endpoint).json()['data'][0]
    assert latest['publication_state'] == 'REVIEW_REJECTED'
    assert latest['state'] == 'REJECTED' and not latest['published']
