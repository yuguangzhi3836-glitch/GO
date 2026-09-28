import base64
import copy
import io
from datetime import datetime, timezone
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from go_hotel.db.models import Base, HotelRegistrationDirectRow, HotelCanonicalProfileRow
from go_hotel.services import hotel_partner_core as coremod, hotel_partner_media_upload as mediamod
from go_hotel.services import hotel_direct_submission_verification as verification
from go_hotel.services.media_harvester import MediaHarvesterService
from go_hotel.api.routes import hotel_partner_core as api

@pytest.fixture
def setup(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path / 'isolated.db'), connect_args={'check_same_thread':False})
    factory = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    for module in (coremod, mediamod, verification): monkeypatch.setattr(module,'SessionLocal',factory)
    core=coremod.hotel_partner_core_service
    pid=core.create_property('one','owner',{'name_zh':'Test Hotel','property_type':'HOTEL'})['property_id']
    rid=core.create_room_type('one','owner',pid,{'name_zh':'Room','physical_room_count':1,'occupancy':{'max_occupancy':2,'max_adults':2,'max_children':0}})['room_type_id']
    media=mediamod.HotelPartnerMediaUploadService(MediaHarvesterService(tmp_path/'cache'))
    svc=verification.HotelDirectSubmissionVerificationService(media)
    monkeypatch.setattr(api,'submission_verifier',svc)
    rights={'rights_holder':'Hotel','evidence_reference':'declaration','usage_scope':['DISTRIBUTE_ON_GO'],'expires_at':None}
    image=io.BytesIO(); Image.new('RGB',(1600,900),'blue').save(image,format='JPEG')
    assets=[]
    for role,room in [('HERO',None),('ROOM',rid)]:
        rec=media.upload('one','owner',pid,{'content_base64':base64.b64encode(image.getvalue()).decode(),'role':role,'room_type_id':room,'rights':rights})
        assets.append(dict(asset_id=rec['asset_id'],supplier_id='one',property_id=pid,canonical_hotel_id='hotel',partner_room_id=room,canonical_room_id='canonical-room' if room else None,role=role,original_sha256=rec['sha256'],width=rec['width'],height=rec['height'],byte_size=rec['byte_size'],mime_type=rec['mime_type'],rights=rights|{'review_evidence_reference':'review'}))
    manifest={'schema':'HOTEL_DIRECT_SUBMISSION_V1','identity':dict(supplier_id='one',property_id=pid,registration_id='reg',canonical_hotel_id='hotel',association_evidence_reference='association'), 'inventory':dict(partner_room_ids=[rid],canonical_room_ids=['canonical-room'],complete_confirmed=True,confirmed_by='owner',confirmed_at='2026-01-01T00:00:00Z',evidence_reference='inventory'), 'room_mappings':[dict(partner_room_id=rid,canonical_room_id='canonical-room',confirmed=True,evidence_reference='mapping')], 'assets':assets}
    app=FastAPI(); app.include_router(api.router)
    app.dependency_overrides[api.supplier_principal]=lambda:SimpleNamespace(supplier_id='one',user_id='owner')
    yield svc,TestClient(app),app,pid,manifest,factory
    engine.dispose()

def codes(result): return {b['code'] for b in result['blockers']}

def test_reads_actual_bytes_no_publication_no_mutations(setup):
    svc,client,app,pid,m,factory=setup
    before=copy.deepcopy(svc.media.cache._index.snapshot())
    result=client.post(f'/v1/supplier/properties/{pid}/direct-submission-verification',json={'manifest':m})
    assert result.status_code==200,result.text
    data=result.json()['data']
    assert all(x['original_verified'] for x in data['assets'])
    assert 'CANONICAL_ROOM_MAPPING_AUTHORITY_UNAVAILABLE' in codes(data)
    assert 'CURRENT_RIGHTS_REVIEW_NOT_VERIFIED' in codes(data)
    assert not data['publishable'] and not data['published'] and not data['rights_granted']
    assert svc.media.cache._index.snapshot()==before
    assert coremod.hotel_partner_core_service.graph('one',pid)['property']['publication_state']=='DRAFT'

def test_foreign_property_and_declared_identity(setup):
    svc,client,app,pid,m,factory=setup
    m['identity']['supplier_id']='two'
    for a in m['assets']:a['supplier_id']='two'
    assert client.post(f'/v1/supplier/properties/{pid}/direct-submission-verification',json={'manifest':m}).status_code==422
    app.dependency_overrides[api.supplier_principal]=lambda:SimpleNamespace(supplier_id='two',user_id='other')
    assert client.post(f'/v1/supplier/properties/{pid}/direct-submission-verification',json={'manifest':m}).status_code==404

def test_no_auth_is_rejected(setup):
    svc,client,app,pid,m,factory=setup
    app.dependency_overrides.clear()
    assert client.post(f'/v1/supplier/properties/{pid}/direct-submission-verification',json={'manifest':m}).status_code==401

@pytest.mark.parametrize('case',['tamper','dimensions','binding','missing','unknown_room'])
def test_actual_asset_failures(setup,case):
    svc,client,app,pid,m,factory=setup
    if case=='tamper': next(svc.media.cache.files_dir.iterdir()).write_bytes(b'broken')
    if case=='dimensions':m['assets'][0]['width']=1800
    if case=='binding':m['assets'][0]['role']='GALLERY';m['assets'][1]['role']='HERO';m['assets'][1]['partner_room_id']=None;m['assets'][1]['canonical_room_id']=None
    if case=='missing':m['assets'][0]['asset_id']='missing'
    if case=='unknown_room':
        from go_hotel.db.models import HotelPartnerRoomTypeRow
        with factory() as s:s.delete(s.get(HotelPartnerRoomTypeRow,m['inventory']['partner_room_ids'][0]));s.commit()
    if case=='binding':
        # Keep structurally complete coverage, but point hero at the room-bound record.
        m['assets'][0]['role']='HERO';m['assets'][1]['role']='ROOM'
        m['assets'][1]['partner_room_id']=m['inventory']['partner_room_ids'][0];m['assets'][1]['canonical_room_id']='canonical-room'
        m['assets'][0]['asset_id'],m['assets'][1]['asset_id']=m['assets'][1]['asset_id'],m['assets'][0]['asset_id']
    result=svc.verify('one',pid,m)
    expected={'tamper':'ORIGINAL_UNAVAILABLE_OR_INVALID','dimensions':'ORIGINAL_FACTS_MISMATCH','binding':'ASSET_BINDING_MISMATCH','missing':'ASSET_NOT_FOUND_IN_PROPERTY','unknown_room':'PARTNER_ROOM_INVENTORY_MISMATCH'}[case]
    assert expected in codes(result)

@pytest.mark.parametrize('case',['valid','expired','revoked','wrong_scope','wrong_reference','declaration_mismatch','declaration_expired'])
def test_current_rights_dynamic_and_mapping_still_blocked(setup,case):
    svc,client,app,pid,m,factory=setup
    for a in m['assets']:
        svc.media.cache.decide_rights(a['asset_id'],rights_state='HOTEL_SUBMITTED',actor='reviewer',rights_owner='Hotel',evidence_reference='review',rights_scope='DISTRIBUTE_ON_GO',expires_at=None)
    if case!='valid':
        for a in m['assets']:
            svc.media.cache.decide_rights(a['asset_id'],rights_state='REJECTED' if case=='revoked' else 'HOTEL_SUBMITTED',actor='reviewer',rights_owner='Hotel',evidence_reference='different' if case=='wrong_reference' else 'review',rights_scope='INTERNAL_ONLY' if case=='wrong_scope' else 'DISTRIBUTE_ON_GO',expires_at='2000-01-01T00:00:00Z' if case=='expired' else None)
    if case=='declaration_mismatch':
        for a in m['assets']: a['rights']['evidence_reference']='changed'
    if case=='declaration_expired':
        for a in m['assets']:
            a['rights']['expires_at']='2026-01-02T00:00:00Z'
            def expire_declaration(rec):
                rec['rights_declaration']['expires_at']='2026-01-02T00:00:00Z'
            svc.media.cache._index.update(a['asset_id'],expire_declaration)
    result=svc.verify('one',pid,m)
    assert all(a['current_rights_verified']==(case=='valid') for a in result['assets'])
    assert result['verification_state']=='BLOCKED' and not result['publishable']


def test_rejected_registration_and_supplier_metadata_cannot_clear_review(setup):
    svc,client,app,pid,m,factory=setup
    stamp=datetime.now(timezone.utc)
    with factory() as s:
        s.add(HotelRegistrationDirectRow(hotel_registration_direct_id='reg',hotel_id='hotel',supplier_id='one',state='REJECTED',evidence_json=[],official_supplement_json={'property_id':pid,'room_mappings':m['room_mappings'],'direct_submission_binding':m},requested_by='owner',reviewed_by='reviewer',created_at=stamp,reviewed_at=stamp))
        s.add(HotelCanonicalProfileRow(hotel_id='hotel',slug='test-hotel',canonical_json={},created_at=stamp,updated_at=stamp))
        s.commit()
    result=svc.verify('one',pid,m)
    assert 'REGISTRATION_REVIEW_NOT_VERIFIED' in codes(result)
    assert 'CANONICAL_ROOM_MAPPING_AUTHORITY_UNAVAILABLE' in codes(result)
    assert not result['published']
