from pathlib import Path
import json
from go_hotel.services.media_harvester import MediaHarvesterService, classify_scene


def test_scene_classifier_covers_aoluguya_six_scenes():
    assert classify_scene(source_url='https://x/hotel-exterior-night.jpg') == 'EXTERIOR'
    assert classify_scene(title='酒店大堂接待区') == 'LOBBY'
    assert classify_scene(alt='卧云套房 bedroom') == 'ROOM'
    assert classify_scene(context='早餐餐厅 restaurant') == 'DINING'
    assert classify_scene(title='泳池与健身中心') == 'WELLNESS'
    assert classify_scene(context='鄂温克森林文化与驯鹿体验') == 'SIGNATURE_SPACE'


def _rec(i, scene, ph, *, w=1600,h=1000):
    return {
        'asset_id':f'media_{i}','hotel_id':'hotel_aoluguya','role':'GALLERY','scene_role':scene,
        'room_type_id':None,'source_type':'PUBLIC_SOURCE','source_url':f'https://img/{i}.jpg',
        'resolved_url':f'https://img/{i}.jpg','observed_at':'2026-09-04T00:00:00+00:00',
        'downloaded_at':f'2026-09-04T00:00:{i:02d}+00:00','sha256':f'{i:064x}',
        'perceptual_hash':ph,'byte_size':100000+i,'mime_type':'image/jpeg','width':w,'height':h,
        'cache_file':f'{i}.jpg','cache_state':'VALIDATED','rights_state':'AUTHORIZED',
        'rights_owner':'hotel','rights_evidence_reference':'evidence','rights_decided_by':'qa',
        'rights_decided_at':'2026-09-04T00:00:00+00:00','rights_expires_at':None,
        'rights_scope':'hotel-page','rights_regions':['CN'],'rights_basis':'MULTI_SOURCE_MATCH',
        'provider':None,'contract_id':None,'cache_allowed':True,'modification_allowed':True,
        'publishable':True,'rights_history':[],
    }


def test_golden_media_gate_30_unique_and_six_scene(tmp_path):
    svc=MediaHarvesterService(cache_dir=tmp_path/'media')
    scenes=['EXTERIOR','LOBBY','ROOM','DINING','WELLNESS','SIGNATURE_SPACE']
    assets={}
    for i in range(30):
        scene=scenes[i%6]
        # spaced hashes avoid near-duplicate grouping
        rec=_rec(i,scene,'')
        assets[rec['asset_id']]=rec
    (tmp_path/'media'/'index.json').write_text(json.dumps({'version':1,'assets':assets}),encoding='utf-8')
    gate=svc.six_scene_coverage('hotel_aoluguya')
    assert gate['unique_publishable_media'] == 30
    assert gate['six_scene_complete'] is True
    assert gate['golden_media_gate_pass'] is True
    assert all(v >= 5 for v in gate['scene_counts'].values())


def test_near_duplicate_does_not_count_twice(tmp_path):
    svc=MediaHarvesterService(cache_dir=tmp_path/'media')
    a=_rec(1,'EXTERIOR','0000000000000000',w=1200,h=800)
    b=_rec(2,'EXTERIOR','0000000000000001',w=2400,h=1600)
    (tmp_path/'media'/'index.json').write_text(json.dumps({'version':1,'assets':{a['asset_id']:a,b['asset_id']:b}}),encoding='utf-8')
    unique=svc.unique_publishable_assets('hotel_aoluguya')
    assert len(unique)==1
    assert unique[0]['asset_id']=='media_2'


def test_public_media_projection_hides_internal_provenance(tmp_path):
    svc=MediaHarvesterService(cache_dir=tmp_path/'media')
    a=_rec(1,'LOBBY','1111111111111111')
    (tmp_path/'media'/'index.json').write_text(json.dumps({'version':1,'assets':{a['asset_id']:a}}),encoding='utf-8')
    page=svc.page_media('hotel_aoluguya')
    item=page['lobby'][0]
    assert set(item)=={'asset_id','url','width','height','mime_type'}
    assert 'source_type' not in item and 'rights_state' not in item and 'evidence_reference' not in item
