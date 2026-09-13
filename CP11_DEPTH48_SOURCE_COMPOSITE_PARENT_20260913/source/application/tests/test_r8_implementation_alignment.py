from go_hotel.core.r8_implementation_alignment import snapshot
from go_hotel.services.media_harvester import PUBLISHABLE_RIGHTS

def test_r8_day1_and_staging_truth():
    s=snapshot()
    assert s['release_train']=='R8.1'
    assert s['control_version']=='V6.1'
    assert s['day1_hotel_coverage_pipeline'][0]=='MULTI_OTA_OFFICIAL_DISCOVERY'
    assert 'HOTEL_REGISTRATION_AND_OFFICIAL_ASSOCIATION' in s['day1_hotel_coverage_pipeline']
    assert 'HOTEL_CLAIM' not in s['day1_hotel_coverage_pipeline']
    assert s['inventory_priority']==['GO_DIRECT','THIRD_PARTY_API_FALLBACK','DEEP_LINK_FALLBACK']
    assert s['after_sales_model']['call_center'] is False
    assert s['after_sales_model']['consumer_entry']=='GO_TRIPS_SELF_SERVICE'
    assert s['identity_truth']['admin_first_enrollment_ui_delivered'] is False
    assert s['staging_constraints']['alembic_revision_max_chars']==32
    assert s['staging_constraints']['postgres_object_name_max_chars']==63

def test_distribution_license_is_explicit_media_rights_basis():
    assert 'DISTRIBUTION_LICENSE' in PUBLISHABLE_RIGHTS


def test_distribution_license_requires_contract_metadata(tmp_path):
    from go_hotel.services.media_harvester import MediaHarvesterService
    svc=MediaHarvesterService(tmp_path/'cache')
    asset_id='media_test'
    svc._write_index({'version':1,'assets':{asset_id:{
        'asset_id':asset_id,'hotel_id':'h1','role':'GALLERY','room_type_id':None,
        'cache_state':'VALIDATED','rights_state':'RIGHTS_UNKNOWN','rights_history':[],
        'rights_owner':None,'rights_evidence_reference':None,'rights_decided_by':None,
        'rights_decided_at':None,'rights_expires_at':None,'rights_scope':None,'rights_regions':[],
        'publishable':False,'cache_file':'unused.jpg','sha256':'0'*64
    }}})
    import pytest
    with pytest.raises(ValueError,match='MEDIA_DISTRIBUTION_LICENSE_CONTRACT_REQUIRED'):
        svc.decide_rights(asset_id,rights_state='DISTRIBUTION_LICENSE',actor='admin',rights_owner='Hotel',evidence_reference='contract://x')
    rec=svc.decide_rights(asset_id,rights_state='DISTRIBUTION_LICENSE',actor='admin',rights_owner='Hotel',evidence_reference='contract://x',rights_basis='OTA_DISTRIBUTION',provider='CTRIP',contract_id='DIST-001',cache_allowed=True,modification_allowed=False)
    assert rec['rights_state']=='DISTRIBUTION_LICENSE'
    assert rec['provider']=='CTRIP'
    assert rec['cache_allowed'] is True
