"""Isolated functional evidence; all hotel pages and media here are synthetic.

These tests exercise real parsing, SQL transactions, cached image validation and
API authorization. They are not evidence of live multi-hotel capture or UX.
"""
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import random
import threading

import httpx
from PIL import Image
import pytest
from sqlalchemy import func, select

from go_hotel.db.models import HotelCanonicalProfileRow, HotelContentSourceSnapshotRow, HotelAutoPageVersionRow
from go_hotel.db.session import SessionLocal
from go_hotel.services import hotel_autopage_factory as factory_module
from go_hotel.services.hotel_autopage_factory import hotel_autopage_factory_service as factory
from go_hotel.services.hotel_catalog_quality import quality
from go_hotel.services.official_hotel_capture import capture_catalog
from go_hotel.services import regional_hotel_build as regional
from go_hotel.services.media_harvester import MediaHarvesterService


def html(node):
    return '<html><script type="application/ld+json">'+json.dumps(node)+'</script></html>'


def official_pages(number=1):
    root=f'https://official.example/hotels/{number}'
    hid=root+'#hotel'
    refs=[root+'/rooms/king#room',root+'/rooms/twin#room']
    hotel={'@context':'https://schema.org','@id':hid,'@type':'Hotel','name':f'Test Hotel {number}',
           'address':f'{number} Test Street','geo':{'latitude':45.0,'longitude':126.0},
           'amenityFeature':[{'name':'WiFi','value':True}], 'checkinTime':'14:00','checkoutTime':'12:00',
           'containsPlace':[{'@id':r} for r in refs], 'image':root+'/hero.png', 'numberOfRooms':250}
    pages={root:html(hotel)}
    for i,ref in enumerate(refs):
        room={'@type':'HotelRoom','@id':ref,'containedInPlace':{'@id':hid},'name':['King','Twin'][i],
              'floorSize':{'value':30+i*5,'unitCode':'MTK'},'bed':'King' if i==0 else 'Twin',
              'occupancy':{'maxValue':2}, 'image':[root+f'/photos/{i}-{j}.png' for j in range(3)]}
        pages[ref.split('#')[0]]=html(room)
    return root,hotel,pages


def fake_fetch(pages, calls=None):
    def fetch(url, **kwargs):
        if calls is not None: calls.append(url)
        body=pages[url]
        return url,body,len(body.encode()),{'fixture':True}
    return fetch


def capture(number=1, *, reviewed=False):
    root,hotel,pages=official_pages(number)
    payload,audit=capture_catalog(fake_fetch(pages),root,{'name':hotel['name']})
    if reviewed:
        m=payload['catalog_manifest']
        m['inventory_verification']={'kind':'OFFICIAL_ROOM_INDEX_REVIEW','source_url':root,
            'source_sha256':m['documents'][0]['sha256'],'reviewed_room_ids':sorted(m['declared_room_ids']),
            'reviewed_by':'isolated-fixture-reviewer'}
    return payload,audit


def source(payload, key='official:test', external='property-1'):
    return {'source_key':key,'source_type':'OFFICIAL_WEBSITE','external_hotel_id':external,
            'source_url':payload.get('website','https://official.example/hotel'),
            'rights_status':'PUBLIC_BUSINESS_FACT','confidence_bps':9500,'payload':payload}


@pytest.fixture
def media(tmp_path,monkeypatch):
    import go_hotel.services.media_harvester as module
    def response(request):
        rng=random.Random(str(request.url))
        buf=io.BytesIO()
        Image.frombytes('RGB',(80,80),rng.randbytes(80*80*3)).save(buf,format='PNG')
        return httpx.Response(200,content=buf.getvalue(),headers={'content-type':'image/png'})
    service=MediaHarvesterService(tmp_path/'media',transport=httpx.MockTransport(response))
    monkeypatch.setattr(module,'_is_public_ip',lambda _:True)
    monkeypatch.setattr(factory_module,'media_harvester_service',service)
    return service


def load_media(media,hotel_id,payload):
    for candidate in payload['media_candidates']:
        asset=media.harvest(source_url=candidate['source_url'],hotel_id=hotel_id,role=candidate['role'],
            room_type_id=candidate.get('room_type_id'),source_type='OFFICIAL_WEBSITE')
        media.decide_rights(asset['asset_id'],rights_state='HOTEL_SUBMITTED',actor='isolated-fixture',
                           rights_owner='Synthetic test hotel',evidence_reference='test-fixture-only')


def ready_hotel(media,number=1):
    payload,_=capture(number,reviewed=True)
    result=factory.ingest(source(payload,external=f'property-{number}'),'test')
    hid=result['profile']['hotel_id']
    assert result['profile']['page_state']=='DRAFT'
    load_media(media,hid,payload)
    result=factory.compose(hid,'test')
    assert result['catalog_quality']['passed'],result['catalog_quality']
    return payload,hid,result['profile']['slug']


@pytest.mark.no_db
def test_declared_rooms_are_captured_with_exact_facts_and_image_bindings():
    root,hotel,pages=official_pages()
    calls=[]
    payload,audit=capture_catalog(fake_fetch(pages,calls),root,{'name':hotel['name']})
    assert len(payload['rooms'])==2 and audit['pages_fetched']==3
    assert len(calls)==len(set(calls))==3
    assert payload['rooms'][0]['floor_size']=={'value':30,'unitCode':'MTK'}
    assert payload['rooms'][1]['bed']=='Twin'
    assert payload['catalog_manifest']['declared_catalog_captured'] is True
    assert payload['catalog_manifest']['full_room_type_inventory_verified'] is False
    assert len(payload['catalog_manifest']['declared_room_ids'])==2 # 250 physical rooms is not 250 room types
    for room in payload['rooms']:
        bound=[m for m in payload['media_candidates'] if m.get('room_type_id')==room['room_type_id']]
        assert len(bound)==3 and {x['source_url'] for x in bound}==set(room['official_image_urls'])
    assert all(x['rights_state']=='RIGHTS_UNKNOWN' for x in payload['media_candidates'])


@pytest.mark.no_db
@pytest.mark.parametrize('fault',['wrong_hotel','cross_origin','foreign_parent','missing_page','budget','missing_id','duplicate_room'])
def test_official_capture_rejects_or_holds_ambiguous_and_incomplete_sources(fault):
    root,hotel,pages=official_pages()
    first=root+'/rooms/king'
    if fault=='wrong_hotel':
        hotel['name']='Another Hotel'
    elif fault=='cross_origin':
        hotel['containsPlace'][0]['@id']='https://elsewhere.example/room'
    elif fault=='foreign_parent':
        room=json.loads(pages[first].split('application/ld+json">')[1].split('</script>')[0])
        room['containedInPlace']['@id']=root+'/other#hotel';pages[first]=html(room)
    elif fault=='missing_page':
        pages[first]=html({'@type':'HotelRoom','@id':first+'#another','name':'Wrong Room'})
    elif fault=='missing_id':
        hotel['containsPlace']=[{'@type':'HotelRoom','name':'No ID'}]
    elif fault=='duplicate_room':
        room=json.loads(pages[first].split('application/ld+json">')[1].split('</script>')[0])
        pages[first]=html([room,{**room,'bed':'Conflicting bed'}])
    pages[root]=html(hotel)
    if fault=='wrong_hotel':
        with pytest.raises(ValueError,match='IDENTITY_NOT_UNIQUE'):
            capture_catalog(fake_fetch(pages),root,{'name':'Test Hotel 1'})
    else:
        p,_=capture_catalog(fake_fetch(pages),root,{'name':'Test Hotel 1'},max_pages=1 if fault=='budget' else 32)
        assert not p['catalog_manifest']['declared_catalog_captured']
        assert p['catalog_manifest']['failures']


@pytest.mark.no_db
def test_no_room_directory_and_arbitrary_images_do_not_become_complete_catalog():
    root,hotel,pages=official_pages()
    hotel.pop('containsPlace')
    pages[root]=html(hotel)+'<img src="/another-hotels-room.png"><h2>Presidential Suite</h2>'
    p,_=capture_catalog(fake_fetch(pages),root,{'name':hotel['name']})
    assert p['rooms']==[] and not p['catalog_manifest']['declared_catalog_captured']
    assert len(p['media_candidates'])==1


def test_name_address_alone_stays_draft_and_manual_publish_is_blocked(media):
    result=factory.ingest(source({'name':'Incomplete Hotel','address':'1 Test Street'}))
    hid=result['profile']['hotel_id']
    assert result['profile']['page_state']=='DRAFT'
    assert not result['catalog_quality']['passed']
    with pytest.raises(ValueError,match='QUALITY_HOLD'):
        factory.set_publication(hid,'PUBLISH')
    with pytest.raises(ValueError,match='NOT_PUBLISHED'):
        factory.public_page(result['profile']['slug'])


def test_name_only_match_does_not_merge_separate_properties(media):
    a=factory.ingest(source({'name':'Same Brand','address':'North Street'},external='north'))
    b=factory.ingest(source({'name':'Same Brand'},external='unknown'))
    c=factory.ingest(source({'name':'Same Brand','address':'South Street'},external='south'))
    assert len({r['profile']['hotel_id'] for r in (a,b,c)})==3


def test_same_name_and_address_resolves_identity_across_sources(media):
    payload={'name':'Same Property','address':'1 Same Street'}
    a=factory.ingest(source(payload,external='one'))
    b=factory.ingest(source(payload,key='official:second',external='two'))
    assert a['profile']['hotel_id']==b['profile']['hotel_id']


def test_concurrent_identical_import_has_one_profile_snapshot_and_version(media):
    barrier=threading.Barrier(6)
    body=source({'name':'Concurrent Hotel','address':'1 Race Street'})
    def run(_):
        barrier.wait()
        return factory.ingest(copy.deepcopy(body))
    with ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(run,range(6)))
    assert len({r['profile']['hotel_id'] for r in results})==1
    assert sum(not r['idempotent'] for r in results)==1
    with SessionLocal() as s:
        for model in (HotelCanonicalProfileRow,HotelContentSourceSnapshotRow,HotelAutoPageVersionRow):
            assert s.scalar(select(func.count()).select_from(model))==1


def test_concurrent_changed_snapshots_keep_stable_provider_identity(media):
    barrier=threading.Barrier(6)
    def run(i):
        barrier.wait()
        return factory.ingest(source({'name':'Concurrent Hotel','address':'1 Race Street','description':str(i)}))
    with ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(run,range(6)))
    assert len({r['profile']['hotel_id'] for r in results})==1
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(HotelContentSourceSnapshotRow))==6


def test_obsolete_source_fields_are_removed_without_historical_conflicts(media):
    a=factory.ingest(source({'name':'Change Hotel','address':'1 Test Street','rooms':[{'name':'Old'}]}))
    b=factory.ingest(source({'name':'Change Hotel','address':'1 Test Street','rooms':[]}))
    assert a['profile']['hotel_id']==b['profile']['hotel_id']
    assert not b['profile']['canonical_json'].get('rooms')
    assert not any(v.get('conflict_state') for v in b['profile']['field_provenance_json'].values())


def test_full_catalog_cache_can_publish_and_replay_without_growth(media):
    payload,hid,slug=ready_hotel(media)
    page=factory.public_page(slug)
    assert len(page['hotel_facts']['rooms'])==2
    assert '_catalog_evidence' not in page
    before=factory.factory_detail(hid)['factory']['latest_page_version']
    replay=factory.ingest(source(payload))
    assert replay['idempotent']
    assert factory.factory_detail(hid)['factory']['latest_page_version']==before


def test_bad_update_preserves_last_good_public_version(media):
    payload,hid,slug=ready_hotel(media)
    original=factory.public_page(slug)
    payload['rooms'][0]['bed']=None
    update=factory.ingest(source(payload))
    assert update['profile']['page_state']=='PUBLISHED'
    assert update['page_version']['publication_state']=='DRAFT'
    assert not update['catalog_quality']['passed']
    assert factory.public_page(slug)['hotel_facts']==original['hotel_facts']
    assert factory.factory_detail(hid)['factory']['primary_stage']=='NEEDS_ENRICHMENT'


def test_manual_unpublish_survives_recompose_and_updates(media):
    payload,hid,slug=ready_hotel(media)
    factory.set_publication(hid,'UNPUBLISH')
    payload['description']='Updated official description'
    factory.ingest(source(payload));factory.compose(hid)
    with pytest.raises(ValueError,match='NOT_PUBLISHED'):factory.public_page(slug)
    factory.set_publication(hid,'PUBLISH')
    assert factory.public_page(slug)['hotel_id']==hid


@pytest.mark.parametrize('fault',['file_deleted','file_corrupted','rights_revoked','wrong_room','wrong_hotel','wrong_source_url','duplicates','unreviewed_inventory','missing_core_fact','room_set_mismatch'])
def test_publication_checks_real_media_and_exact_catalog_evidence(media,fault):
    payload,hid,slug=ready_hotel(media)
    if fault in {'unreviewed_inventory','missing_core_fact','room_set_mismatch'}:
        if fault=='unreviewed_inventory':payload['catalog_manifest'].pop('inventory_verification')
        elif fault=='missing_core_fact':payload['rooms'][1]['occupancy']=None
        else:payload['catalog_manifest']['declared_room_ids'].append('https://official.example/missing')
        result=factory.ingest(source(payload))
        assert not result['catalog_quality']['passed']
        return
    asset=next(x for x in media.list_assets(hotel_id=hid) if x['role']=='ROOM')
    if fault=='file_deleted':media.content_path(asset['asset_id']).unlink()
    elif fault=='file_corrupted':media.content_path(asset['asset_id']).write_bytes(b'corruption')
    elif fault=='rights_revoked':media.decide_rights(asset['asset_id'],rights_state='REJECTED',actor='test')
    else:
        index=media._read_index();record=index['assets'][asset['asset_id']]
        if fault=='wrong_room':record['room_type_id']='other-room'
        elif fault=='wrong_hotel':record['hotel_id']='other-hotel'
        elif fault=='wrong_source_url':record['source_url']='https://official.example/unrelated.png'
        else:
            other=next(x for x in media.list_assets(hotel_id=hid) if x['role']=='ROOM' and x['room_type_id']==asset['room_type_id'] and x['asset_id']!=asset['asset_id'])
            for key in ('sha256','cache_file'):record[key]=other[key]
        media._write_index(index)
    with pytest.raises(ValueError,match='QUALITY_HOLD'):factory.public_page(slug)


def test_regional_finished_work_with_incomplete_catalog_is_not_completed(media):
    rid='quality-run'
    regional.event('REGIONAL_BUILD_CREATED',{'run_id':rid,'mode':'REGION','city':'Test City'})
    regional.event('REGIONAL_BUILD_CITY_ENQUEUED',{'run_id':rid,'city':'Test City'})
    regional.event('REGIONAL_BUILD_CITY_DISCOVERY_FINISHED',{'run_id':rid,'city':'Test City','discovered':1,'deduped':1})
    regional.event('REGIONAL_BUILD_HOTEL_ENQUEUED',{'run_id':rid,'city':'Test City','candidate_key':'one'})
    regional.event('REGIONAL_BUILD_HOTEL_FINISHED',{'run_id':rid,'city':'Test City','candidate_key':'one','hotel_id':'test',
        'page':True,'state':'NEEDS_ENRICHMENT','completeness_gate':{'passed':False}})
    status=regional.regional_hotel_build_service.status(rid)['runs'][0]
    assert status['state']=='NEEDS_ENRICHMENT' and status['pages']==0 and status['needs_enrichment']==1


@pytest.mark.parametrize('path',['/sources/ingest','/media/harvest','/factory/hotels/test/publication'])
def test_read_only_admin_cannot_change_catalog_or_publish(client,media,path):
    from go_hotel.security.service import identity_service
    identity_service.ensure_user('catalog-reader','ReaderPassword123!','GO_ADMIN',None,['GO_READ_ONLY'])
    reply=client.post('/v1/auth/login',json={'username':'catalog-reader','password':'ReaderPassword123!'})
    token=reply.json()['data']['access_token'];client.cookies.clear()
    response=client.post('/internal/v1/hotel-autopage'+path,json={},headers={'Authorization':'Bearer '+token})
    assert response.status_code==403,response.text


def test_discovery_api_reports_collection_separately_from_ready_catalog(client,media,monkeypatch):
    from go_hotel.services.hotel_discovery_orchestrator import hotel_discovery_orchestrator_service as discovery
    root,hotel,pages=official_pages()
    monkeypatch.setattr(discovery,'_fetch_html',fake_fetch(pages))
    auth=client.post('/v1/auth/login',json={'username':'go_admin','password':'change-me-admin'})
    headers={'Authorization':'Bearer '+auth.json()['data']['access_token']};client.cookies.clear()
    response=client.post('/internal/v1/hotel-discovery/seeds',headers=headers,
        json={'name':hotel['name'],'source_hints':[{'kind':'OFFICIAL_WEBSITE','url':root}]})
    assert response.status_code==200,response.text
    jid=response.json()['data']['job_id']
    result=client.post('/internal/v1/hotel-discovery/jobs/'+jid+'/run',headers=headers,json={'max_retries':0})
    assert result.status_code==200,result.text
    data=result.json()['data']
    assert data['state']=='COMPLETED' and data['stage']=='SOURCE_COLLECTION'
    assert data['build_state']=='NEEDS_ENRICHMENT'
    assert data['catalog_quality']['room_count']==2


def test_two_official_photos_are_copied_without_inventing_a_third(media):
    payload,_=capture(reviewed=True)
    room=payload['rooms'][0]
    removed=room['official_image_urls'].pop()
    payload['media_candidates']=[x for x in payload['media_candidates'] if x['source_url']!=removed]
    r=factory.ingest(source(payload));hid=r['profile']['hotel_id']
    load_media(media,hid,payload)
    result=factory.compose(hid)
    assert result['catalog_quality']['passed']
    assert result['catalog_quality']['room_photo_counts'][room['room_type_id']]==2


def test_unrelated_approved_images_never_enter_the_public_page(media):
    payload,hid,slug=ready_hotel(media)
    extra=media.harvest(source_url='https://official.example/unrelated.png',hotel_id=hid,role='HERO',source_type='OFFICIAL_WEBSITE')
    media.decide_rights(extra['asset_id'],rights_state='HOTEL_SUBMITTED',actor='test',rights_owner='Fixture',evidence_reference='fixture')
    assert extra['asset_id'] not in json.dumps(factory.public_page(slug))


def test_ten_hotel_replication_replay_keeps_identity_and_room_media_separate(media):
    all_hotels=[]
    for i in range(10,20):
        payload,hid,slug=ready_hotel(media,i)
        all_hotels.append((payload,hid,slug))
    before=None
    with SessionLocal() as s:
        before=tuple(s.scalar(select(func.count()).select_from(m)) for m in
                     (HotelCanonicalProfileRow,HotelContentSourceSnapshotRow,HotelAutoPageVersionRow))
    for payload,hid,slug in all_hotels:
        number=payload['name'].split()[-1]
        assert factory.ingest(source(payload,external='property-'+number))['idempotent']
        page=factory.public_page(slug)
        expected={r['room_type_id'] for r in payload['rooms']}
        assert set(page['media']['rooms'])==expected
        assert all(len(images)==3 for images in page['media']['rooms'].values())
        assert page['hotel_id']==hid
    with SessionLocal() as s:
        after=tuple(s.scalar(select(func.count()).select_from(m)) for m in
                    (HotelCanonicalProfileRow,HotelContentSourceSnapshotRow,HotelAutoPageVersionRow))
    assert before==after==(10,10,20)


@pytest.mark.no_db
@pytest.mark.parametrize('bad',[{'rooms':[None]},{'rooms':[{'official_id':{}}]},
    {'catalog_manifest':{'documents':None}},{'catalog_manifest':{'declared_room_ids':[{}]}}])
def test_malformed_catalog_is_incomplete_and_cannot_crash_the_gate(bad):
    assert quality(bad,{},[],hotel_id='test',verify_asset=lambda _:None)['passed'] is False


def test_explicit_target_cannot_reassign_an_existing_source_identity(media):
    one=factory.ingest(source({'name':'One','address':'One'},external='one'))
    two=factory.ingest(source({'name':'Two','address':'Two'},external='two'))
    b=source({'name':'Changed','address':'One'},external='one')
    b['canonical_hotel_id']=two['profile']['hotel_id']
    with pytest.raises(ValueError,match='IDENTITY_CONFLICT'):factory.ingest(b)


def test_failed_composition_rolls_back_source_and_profile_together(media,monkeypatch):
    def fail(*args,**kwargs):raise RuntimeError('injected before publication commit')
    monkeypatch.setattr(factory,'_publish_version',fail)
    with pytest.raises(RuntimeError):factory.ingest(source({'name':'Rollback','address':'One'}))
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(HotelCanonicalProfileRow))==0
        assert s.scalar(select(func.count()).select_from(HotelContentSourceSnapshotRow))==0


def test_bounded_parallel_batch_preserves_order_and_isolates_failed_hotel(media,monkeypatch):
    import time
    from go_hotel.services.hotel_discovery_orchestrator import hotel_discovery_orchestrator_service as discovery
    pages={};seeds=[];lock=threading.Lock();state={'active':0,'peak':0}
    for number in range(40,48):
        root,hotel,site=official_pages(number);pages.update(site)
        seeds.append({'name':hotel['name'],'source_hints':[{'kind':'OFFICIAL_WEBSITE','url':root}]})
    seeds[3]['name']='Wrong hotel identity'
    fetch=fake_fetch(pages)
    def delayed(*args,**kwargs):
        with lock:
            state['active']+=1;state['peak']=max(state['peak'],state['active'])
        try:
            time.sleep(0.02)
            return fetch(*args,**kwargs)
        finally:
            with lock:state['active']-=1
    monkeypatch.setattr(discovery,'_fetch_html',delayed)
    result=discovery.run_batch(seeds,'test',max_retries=0)
    assert result['job_count']==8 and result['max_parallel_hotels']==4
    assert 2<=state['peak']<=4
    assert [x['run']['state'] for x in result['jobs']]==['COMPLETED']*3+['FAILED']+['COMPLETED']*4
    assert result['ready_hotels']==0 and result['needs_enrichment']==8
    with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(HotelCanonicalProfileRow))==7
