import base64
import io
import os
from types import SimpleNamespace
os.environ.setdefault('DATABASE_URL', 'sqlite:////tmp/go_partner_media_upload_test.db')
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from go_hotel.db.session import engine
from go_hotel.db.models import Base
from go_hotel.services.hotel_partner_core import hotel_partner_core_service as core
from go_hotel.services.hotel_partner_media_upload import HotelPartnerMediaUploadService
from go_hotel.services.media_harvester import MediaHarvesterService
from go_hotel.api.routes import hotel_partner_core as api

@pytest.fixture
def setup(tmp_path, monkeypatch):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    svc = HotelPartnerMediaUploadService(MediaHarvesterService(tmp_path / 'cache'))
    monkeypatch.setattr(api, 'media_svc', svc)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.supplier_principal] = lambda: SimpleNamespace(supplier_id='one', user_id='owner')
    client = TestClient(app)
    pid = core.create_property('one', 'owner', {'name_zh': 'hotel', 'property_type': 'HOTEL'})['property_id']
    other = core.create_property('two', 'other', {'name_zh': 'other', 'property_type': 'HOTEL'})['property_id']
    return svc, client, app, pid, other

def payload(size=(1600, 900), fmt='JPEG'):
    f = io.BytesIO()
    Image.new('RGB', size, 'blue').save(f, format=fmt)
    return {'content_base64': base64.b64encode(f.getvalue()).decode(), 'role': 'HERO',
            'rights': {'rights_holder': 'hotel', 'evidence_reference': 'owner declaration', 'usage_scope': ['DISTRIBUTE_ON_GO']}}, f.getvalue()

def test_http_original_roundtrip_dedup_stays_private(setup):
    svc, client, app, pid, other = setup
    body, raw = payload()
    url = f'/v1/supplier/properties/{pid}/media-uploads'
    response = client.post(url, json=body)
    assert response.status_code == 201, response.text
    item = response.json()['data']
    assert (item['width'], item['height'], item['state'], item['publishable']) == (1600, 900, 'DRAFT', False)
    assert client.get(item['original_url']).content == raw
    assert client.get(item['original_url']).headers['cache-control'] == 'private, no-store'
    repeat = client.post(url, json=body).json()['data']
    assert repeat['asset_id'] == item['asset_id'] and repeat['deduplicated']
    assert len(client.get(url).json()['data']) == 1
    with pytest.raises(ValueError, match='MEDIA_ASSET_NOT_PUBLISHABLE'):
        svc.cache.content_path(item['asset_id'])
    assert core.graph('one', pid)['property']['publication_state'] == 'DRAFT'
    assert len(list(svc.cache.files_dir.iterdir())) == 1
    app.dependency_overrides[api.supplier_principal] = lambda: SimpleNamespace(supplier_id='two', user_id='other')
    assert client.get(item['original_url']).status_code == 404
    assert client.post(url, json=body).status_code == 404
    assert client.get(url).status_code == 404
    second = client.post(f'/v1/supplier/properties/{other}/media-uploads', json=body).json()['data']
    assert second['asset_id'] != item['asset_id'] and not second['deduplicated']
    assert client.get(f'/v1/supplier/properties/{other}/media-uploads/{item["asset_id"]}/original').status_code == 404
    assert len(list(svc.cache.files_dir.iterdir())) == 1

@pytest.mark.parametrize('size,fmt,error', [((640,480),'JPEG','MEDIA_IMAGE_TOO_SMALL'), ((1600,900),'GIF','MEDIA_IMAGE_FORMAT_NOT_ALLOWED')])
def test_size_format_rejected(setup,size,fmt,error):
    svc,client,app,pid,_ = setup
    response = client.post(f'/v1/supplier/properties/{pid}/media-uploads', json=payload(size,fmt)[0])
    assert response.status_code == 422 and response.json()['detail'] == error
    assert svc.list_uploads('one',pid) == []
    assert list(svc.cache.files_dir.iterdir()) == []

@pytest.mark.parametrize('kind', ['url','fake','truncated','rights','scope','expired','extra'])
def test_invalid_input_does_not_admit_bytes(setup,kind):
    svc,client,app,pid,_ = setup
    body, raw = payload()
    if kind == 'url': body['content_base64'] = 'https://example.test/a.jpg'
    if kind == 'fake': body['content_base64'] = base64.b64encode(b'<html>not a photo</html>').decode()
    if kind == 'truncated': body['content_base64'] = base64.b64encode(raw[:len(raw)//2]).decode()
    if kind == 'rights': body['rights'] = {}
    if kind == 'scope': body['rights']['usage_scope'] = ['ANYTHING']
    if kind == 'expired': body['rights']['expires_at'] = '2000-01-01T00:00:00Z'
    if kind == 'extra': body['path'] = '../../etc/passwd'
    response = client.post(f'/v1/supplier/properties/{pid}/media-uploads', json=body)
    assert response.status_code == 422
    assert svc.list_uploads('one',pid) == []
    assert list(svc.cache.files_dir.iterdir()) == []

def test_room_binding_and_integrity(setup):
    svc, client, app, pid, other = setup
    room = core.create_room_type('two','actor',other,{'name_zh':'room','physical_room_count':1,'occupancy':{'max_occupancy':2,'max_adults':2,'max_children':0}})['room_type_id']
    body, raw = payload()
    body.update(role='ROOM',room_type_id=room)
    with pytest.raises(ValueError,match='ROOM_TYPE_NOT_FOUND'):
        svc.upload('one','owner',pid,body)
    room = core.create_room_type('one','actor',pid,{'name_zh':'room','physical_room_count':1,'occupancy':{'max_occupancy':2,'max_adults':2,'max_children':0}})['room_type_id']
    body['room_type_id'] = room
    asset = svc.upload('one','owner',pid,body)
    assert asset['room_type_id'] == room
    path = next(svc.cache.files_dir.iterdir())
    path.write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='MEDIA_CACHE_INTEGRITY_FAILED'):
        svc.original('one',pid,asset['asset_id'])
    with pytest.raises(ValueError,match='MEDIA_CACHE_INTEGRITY_FAILED'):
        svc.upload('one','owner',pid,body)

def test_symlink_rejected(setup,tmp_path):
    svc,client,app,pid,_ = setup
    asset = svc.upload('one','owner',pid,payload()[0])
    path = next(svc.cache.files_dir.iterdir())
    outside = tmp_path/'outside.jpg'
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ValueError,match='MEDIA_CACHE_PATH_INVALID'):
        svc.original('one',pid,asset['asset_id'])

@pytest.mark.parametrize("field,value", [("role", []), ("room_type_id", {}), ("room_type_id", " ")])
def test_malformed_identity_rejected(setup, field, value):
    svc, client, app, pid, _ = setup
    body, _ = payload()
    body[field] = value
    with pytest.raises(ValueError):
        svc.upload('one', 'owner', pid, body)
    assert svc.list_uploads('one', pid) == []
