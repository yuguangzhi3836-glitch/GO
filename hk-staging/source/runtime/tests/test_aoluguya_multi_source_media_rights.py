from io import BytesIO
from pathlib import Path
import httpx
from PIL import Image
from go_hotel.services.media_harvester import MediaHarvesterService


def _jpeg(rgb=(80,110,140), size=(800,600)):
    b=BytesIO(); Image.new('RGB',size,rgb).save(b,format='JPEG',quality=90); return b.getvalue()


def _transport():
    same=_jpeg(); other=_jpeg((120,80,60))
    def h(req):
        content=other if req.url.path.endswith('other.jpg') else same
        return httpx.Response(200,headers={'Content-Type':'image/jpeg'},content=content,request=req)
    return httpx.MockTransport(h)


def test_two_independent_sources_promote_hotel_origin_inference(tmp_path: Path):
    svc=MediaHarvesterService(tmp_path/'cache',transport=_transport())
    a=svc.harvest(source_url='https://hyatt.test/a.jpg',hotel_id='hotel_aoluguya',role='GALLERY',source_type='GROUP_OFFICIAL',source_group='HYATT_OFFICIAL',allow_private=True,title='AOLUGUYA Lobby')
    b=svc.harvest(source_url='https://ctrip.test/a.jpg',hotel_id='hotel_aoluguya',role='GALLERY',source_type='OTA_PUBLIC',source_group='CTRIP',allow_private=True,title='AOLUGUYA Lobby')
    out=svc.promote_multi_source_hotel_origin('hotel_aoluguya',rights_owner='AOLUGUYA Hotel',rights_regions=['CN'])
    assert out['promoted_cluster_count']==1
    assert out['promoted_asset_count']==2
    assert out['legal_adjudication'] is False
    for aid in (a['asset_id'],b['asset_id']):
        rec=svc.get(aid)
        assert rec['rights_state']=='HOTEL_SUBMITTED_INFERRED'
        assert rec['publishable'] is True
        assert rec['rights_basis']=='MULTI_SOURCE_IDENTICAL_HOTEL_ORIGIN_INFERENCE'
        assert rec['rights_evidence_reference'].startswith('go://hotel-media/multi-source-origin/')


def test_same_platform_mirrors_do_not_count_as_two_sources(tmp_path: Path):
    svc=MediaHarvesterService(tmp_path/'cache',transport=_transport())
    svc.harvest(source_url='https://ctrip-a.test/a.jpg',hotel_id='hotel_aoluguya',role='GALLERY',source_type='OTA_PUBLIC',source_group='CTRIP',allow_private=True)
    svc.harvest(source_url='https://ctrip-b.test/a.jpg',hotel_id='hotel_aoluguya',role='GALLERY',source_type='OTA_PUBLIC',source_group='CTRIP',allow_private=True)
    out=svc.promote_multi_source_hotel_origin('hotel_aoluguya',rights_owner='AOLUGUYA Hotel')
    assert out['promoted_cluster_count']==0
    assert out['held_cluster_count']==1
    assert svc.list_assets(hotel_id='hotel_aoluguya',publishable_only=True)==[]


def test_duplicate_cluster_keeps_highest_quality_publishable_asset(tmp_path: Path):
    small=_jpeg(size=(800,600)); large=_jpeg(size=(1600,1200))
    # Similar solid images have same dHash, intentionally testing near-duplicate quality choice.
    def h(req):
        return httpx.Response(200,headers={'Content-Type':'image/jpeg'},content=large if 'large' in req.url.path else small,request=req)
    svc=MediaHarvesterService(tmp_path/'cache',transport=httpx.MockTransport(h))
    a=svc.harvest(source_url='https://hyatt.test/small.jpg',hotel_id='hotel_aoluguya',role='GALLERY',source_group='HYATT_OFFICIAL',allow_private=True)
    b=svc.harvest(source_url='https://booking.test/large.jpg',hotel_id='hotel_aoluguya',role='GALLERY',source_group='BOOKING',allow_private=True)
    svc.promote_multi_source_hotel_origin('hotel_aoluguya',rights_owner='AOLUGUYA Hotel')
    unique=svc.unique_publishable_assets('hotel_aoluguya')
    assert len(unique)==1
    assert unique[0]['asset_id']==b['asset_id']
    assert unique[0]['width']==1600


def test_transitive_recompression_cluster_is_multi_source_evidence(tmp_path: Path):
    svc=MediaHarvesterService(tmp_path/'cache')
    assets={}
    for i,(group,ph) in enumerate((('HOTEL_OFFICIAL','0000000000000000'),('CTRIP','00000000000003ff'),('BOOKING','00000000000fffff')),1):
        rec={
            'asset_id':f'media_{i}','hotel_id':'hotel_aoluguya','role':'GALLERY',
            'source_type':'PUBLIC_WEB','source_group':group,'source_url':f'https://{group}.test/{i}.jpg',
            'cache_state':'VALIDATED','rights_state':'RIGHTS_UNKNOWN','perceptual_hash':ph,
            'sha256':f'{i:064x}','width':1600,'height':1000,'byte_size':100000+i,
            'rights_history':[],
        }
        assets[rec['asset_id']]=rec
    svc._write_index({'version':1,'assets':assets})
    clusters=svc.media_duplicate_clusters('hotel_aoluguya',max_phash_distance=10)
    assert len(clusters)==1
    assert clusters[0]['independent_source_group_count']==3


def test_embedded_third_party_mark_blocks_only_marked_asset(tmp_path: Path):
    svc=MediaHarvesterService(tmp_path/'cache',transport=_transport())
    a=svc.harvest(source_url='https://hyatt.test/a.jpg',hotel_id='hotel_aoluguya',role='GALLERY',source_group='HOTEL_OFFICIAL',allow_private=True)
    b=svc.harvest(source_url='https://ctrip.test/a.jpg',hotel_id='hotel_aoluguya',role='GALLERY',source_group='CTRIP',allow_private=True)
    idx=svc._read_index()
    idx['assets'][b['asset_id']]['third_party_content_mark_detected']=True
    idx['assets'][b['asset_id']]['platform_page_ui_detected']=True
    svc._write_index(idx)
    out=svc.promote_multi_source_hotel_origin('hotel_aoluguya',rights_owner='AOLUGUYA Hotel')
    assert out['promoted_asset_count']==1
    assert svc.get(a['asset_id'])['publishable'] is True
    assert svc.get(b['asset_id'])['publishable'] is False
