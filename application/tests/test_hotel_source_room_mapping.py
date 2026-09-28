import os
os.environ.setdefault('DATABASE_URL', 'sqlite:////tmp/go_room_mapping_test.db')

import pytest
from sqlalchemy import select, func
from go_hotel.db.models import Base, HotelPartnerImportJobRow
from go_hotel.db.session import engine, SessionLocal
from go_hotel.services.hotel_partner_core import hotel_partner_core_service as svc

SID='mapping-owner'
ACT='owner'


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def prop():
    return svc.create_property(SID,ACT,{'name_zh':'酒店','property_type':'HOTEL'})['property_id']


def room_data(source_id=None):
    result={'name_zh':'同名房型','physical_room_count':2,
            'occupancy':{'max_occupancy':2,'max_adults':2,'max_children':0}}
    if source_id is not None:result['source_room_id']=source_id
    return result


def local_room(pid):
    return svc.create_room_type(SID,ACT,pid,room_data()|{
        'name_en':'Keep English','sale_unit':'WHOLE_ROOM',
        'bed_configurations':[{'bed_type':'KING'}],
        'attributes':{'canonical_room_id':'canonical-17','area':48}})['room_type_id']


def request(source_id='ctrip-room-1',target=None):
    mapping={'source_room_id':source_id,'confirmed':True}
    mapping.update({'target_room_type_id':target} if target else {'action':'CREATE'})
    return {'provider':'CTRIP','method':'DATA_EXPORT',
            'hotel_package':{'room_types':[room_data(source_id)]},'room_mappings':[mapping]}


def test_confirmed_target_update_preserves_identity_optional_fields_and_other_rooms():
    pid=prop();target=local_room(pid);other=local_room(pid)
    body=request(target=target)
    body['hotel_package']['room_types'][0]['attributes']={'area':72}
    first=svc.one_click_import(SID,ACT,pid,body,'update-1')
    second=svc.one_click_import(SID,ACT,pid,body,'update-2')
    assert first['room_types_created']==second['room_types_created']==0
    assert second['room_types_updated']==1
    graph=svc.graph(SID,pid);rooms={x['room_type_id']:x for x in graph['room_types']}
    assert set(rooms)=={target,other}
    assert rooms[target]['name_en']=='Keep English'
    assert rooms[target]['bed_configurations_json']==[{'bed_type':'KING'}]
    assert rooms[target]['attributes_json']=={'canonical_room_id':'canonical-17','area':72}
    assert rooms[other]['attributes_json']['area']==48
    assert graph['property']['operations_json']['import_room_bindings']['CTRIP']=={'ctrip-room-1':target}


def test_explicit_create_same_key_replays_and_later_batch_requires_target():
    pid=prop();body=request()
    first=svc.one_click_import(SID,ACT,pid,body,'create')
    replay=svc.one_click_import(SID,ACT,pid,body,'create')
    assert replay['idempotent_replay'] is True
    assert first['import_job_id']==replay['import_job_id']
    target=first['mapping']['resolved_rooms'][0]['target_room_type_id']
    with pytest.raises(ValueError,match='ROOM_MAPPING_CONFLICT'):
        svc.one_click_import(SID,ACT,pid,body,'duplicate-create')
    body=request(target=target)
    body['hotel_package']['room_types'][0]['physical_room_count']=3
    result=svc.one_click_import(SID,ACT,pid,body,'confirmed-update')
    assert result['room_types_updated']==1 and result['room_types_created']==0
    assert len(svc.graph(SID,pid)['room_types'])==1
    assert svc.graph(SID,pid)['room_types'][0]['physical_room_count']==3


def test_source_provider_namespaces_same_external_room_id():
    pid=prop();body=request('shared-id')
    first=svc.one_click_import(SID,ACT,pid,body,'ctrip')
    body['provider']='BOOKING'
    second=svc.one_click_import(SID,ACT,pid,body,'booking')
    assert first['mapping']['resolved_rooms']!=second['mapping']['resolved_rooms']
    assert len(svc.graph(SID,pid)['room_types'])==2


@pytest.mark.parametrize('confirmed',[False,None,1,'true'])
def test_non_boolean_true_confirmation_rejected(confirmed):
    pid=prop();body=request();body['room_mappings'][0]['confirmed']=confirmed
    with pytest.raises(ValueError,match='ROOM_MAPPING_CONFIRMATION_REQUIRED'):
        svc.one_click_import(SID,ACT,pid,body)
    assert svc.graph(SID,pid)['room_types']==[]


def test_source_id_without_mapping_fails_without_name_guessing():
    pid=prop();local_room(pid);body=request();del body['room_mappings']
    with pytest.raises(ValueError,match='ROOM_MAPPING_CONFIRMATION_REQUIRED'):
        svc.one_click_import(SID,ACT,pid,body)
    assert len(svc.graph(SID,pid)['room_types'])==1


def test_cross_hotel_target_rejected_even_same_supplier():
    pid=prop();other=prop();target=local_room(other)
    with pytest.raises(ValueError,match='ROOM_TYPE_NOT_FOUND'):
        svc.one_click_import(SID,ACT,pid,request(target=target))
    assert svc.graph(SID,pid)['room_types']==[]


def test_source_cannot_rebind_and_two_sources_cannot_alias_one_target():
    pid=prop();first=local_room(pid);second=local_room(pid)
    svc.one_click_import(SID,ACT,pid,request(target=first),'bind')
    with pytest.raises(ValueError,match='ROOM_MAPPING_CONFLICT'):
        svc.one_click_import(SID,ACT,pid,request(target=second),'rebind')
    with pytest.raises(ValueError,match='ROOM_MAPPING_TARGET_CONFLICT'):
        svc.one_click_import(SID,ACT,pid,request('different-id',first),'alias')


def test_last_mapping_failure_rolls_back_whole_batch_and_job():
    pid=prop();target=local_room(pid);before=svc.graph(SID,pid)
    body=request(target=target)
    body['hotel_package']['hotel']={'name_zh':'Must not change'}
    body['hotel_package']['room_types'][0]['name_zh']='Must not change either'
    body['hotel_package']['room_types'].append(room_data('bad-room'))
    body['room_mappings'].append({'source_room_id':'bad-room','confirmed':True,'target_room_type_id':'missing'})
    with pytest.raises(ValueError,match='ROOM_TYPE_NOT_FOUND'):
        svc.one_click_import(SID,ACT,pid,body,'atomic')
    assert svc.graph(SID,pid)==before
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(HotelPartnerImportJobRow))==0


def test_failure_after_room_updates_rolls_back_rooms_bindings_property_and_job(monkeypatch):
    pid=prop();target=local_room(pid);before=svc.graph(SID,pid)
    body=request(target=target)
    body['hotel_package']['hotel']={'name_zh':'Must rollback'}
    body['hotel_package']['room_types'][0]['name_zh']='Changed mapped room'
    body['hotel_package']['room_types'].append(room_data('new-room'))
    body['room_mappings'].append({'source_room_id':'new-room','confirmed':True,'action':'CREATE'})
    def fail_audit(*args,**kwargs):
        raise RuntimeError('audit unavailable')
    monkeypatch.setattr(svc,'_audit',fail_audit)
    with pytest.raises(RuntimeError,match='audit unavailable'):
        svc.one_click_import(SID,ACT,pid,body,'rollback-after-write')
    assert svc.graph(SID,pid)==before
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(HotelPartnerImportJobRow))==0


@pytest.mark.parametrize('variant,error',[
    ('duplicate','DUPLICATE_SOURCE_ROOM_ID'),
    ('different','ROOM_MAPPING_SOURCE_MISMATCH'),
    ('blank','INVALID_SOURCE_ROOM_ID'),
    ('mixed','INVALID_SOURCE_ROOM_ID'),
])
def test_invalid_source_identity_contract(variant,error):
    pid=prop();body=request()
    if variant=='duplicate':
        body['hotel_package']['room_types']*=2;body['room_mappings']*=2
    elif variant=='different':body['room_mappings'][0]['source_room_id']='wrong'
    elif variant=='blank':body['hotel_package']['room_types'][0]['source_room_id']=' '
    else:
        body['hotel_package']['room_types'].append(room_data())
        body['room_mappings'].append({'source_room_id':'second','action':'CREATE','confirmed':True})
    with pytest.raises(ValueError,match=error):svc.one_click_import(SID,ACT,pid,body)
    assert svc.graph(SID,pid)['room_types']==[]


def test_legacy_idless_import_stays_append_and_does_not_claim_deduplication():
    pid=prop();body={'provider':'CTRIP','method':'DATA_EXPORT','hotel_package':{'room_types':[room_data()]}}
    first=svc.one_click_import(SID,ACT,pid,body,'legacy-1')
    second=svc.one_click_import(SID,ACT,pid,body,'legacy-2')
    assert first['room_types_created']==second['room_types_created']==1
    assert second['mapping']['cross_batch_room_deduplication'] is False
    assert len(svc.graph(SID,pid)['room_types'])==2


def test_unselected_room_mappings_do_not_apply_or_change_bindings():
    pid=prop();body=request()
    body['selected_fields']=['hotel.name_zh'];body['hotel_package']['hotel']={'name_zh':'Only hotel'}
    result=svc.one_click_import(SID,ACT,pid,body)
    assert result['room_types_created']==result['room_types_updated']==0
    assert 'import_room_bindings' not in svc.graph(SID,pid)['property']['operations_json']
