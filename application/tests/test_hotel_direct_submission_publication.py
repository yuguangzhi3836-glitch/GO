import copy
from datetime import datetime, timezone
import pytest
from go_hotel.db.models import HotelCanonicalProfileRow, HotelContentSourceSnapshotRow, HotelAutoPageVersionRow, HotelPartnerRoomTypeRow
from go_hotel.services import hotel_direct_submission_publication as publication
from go_hotel.services import hotel_autopage_factory as factorymod
from go_hotel.services import hotel_partner_media_upload as mediamod
from go_hotel.services.hotel_catalog_quality import quality
from test_hotel_direct_submission_review import ready
from test_hotel_direct_submission_verification import setup


@pytest.fixture
def publishing(ready, monkeypatch):
    review,pid,m,factory,verifier=ready
    monkeypatch.setattr(publication,'SessionLocal',factory)
    monkeypatch.setattr(factorymod,'SessionLocal',factory)
    monkeypatch.setattr(publication,'_reviews',lambda:review)
    monkeypatch.setattr(factorymod,'media_harvester_service',verifier.media.cache)
    monkeypatch.setattr(mediamod,'hotel_partner_media_upload_service',verifier.media)
    stamp=datetime.now(timezone.utc)
    with factory() as s:
        profile=s.get(HotelCanonicalProfileRow,'hotel')
        data=copy.deepcopy(profile.canonical_json)
        data.update(name='Test Hotel',address={'formatted':'Test street'},facilities=['WiFi'],policies=['Check in 14:00'])
        data['rooms'][0].update(floor_size={'unitCode':'MTK','value':30},occupancy={'maxValue':2},bed='Double')
        profile.canonical_json=data
        s.add(HotelContentSourceSnapshotRow(content_source_snapshot_id='facts',source_key='existing-facts',source_type='HOTEL_OFFICIAL_SUBMISSION',external_hotel_id='hotel',source_url=None,rights_status='HOTEL_SUBMITTED',confidence_bps=10000,payload_json=data,payload_hash=factorymod.sha(data),canonical_hotel_id='hotel',observed_at=stamp,created_at=stamp))
        s.commit()
    row=review.submit('one','owner',pid,m)
    review.approve(row['review_id'],'admin',row['manifest_sha256'])
    yield publication.hotel_direct_submission_publication_service,review,pid,m,factory,verifier,row


def test_existing_page_history_public_original_and_retry(publishing):
    pub,review,pid,m,factory,v,row=publishing
    result=pub.publish(row['review_id'],'one',pid,'admin')
    assert result['published'] and not result['idempotent']
    page=factorymod.hotel_autopage_factory_service.public_page('test')
    assert '_catalog_evidence' not in page
    assert page['media']['rooms']['canonical-room'][0]['asset_id']==m['assets'][1]['asset_id']
    original,mime=pub.public_content(row['review_id'],m['assets'][0]['asset_id'])
    assert original.startswith(b'\xff\xd8') and mime=='image/jpeg'
    assert pub.publish(row['review_id'],'one',pid,'admin')['idempotent']
    with factory() as s:
        assert s.query(HotelAutoPageVersionRow).count()==1
        p=s.get(HotelCanonicalProfileRow,'hotel')
        assert p.field_provenance_json['name']['snapshot_id']=='facts'


@pytest.mark.parametrize('kind',['review','rights','bytes','inventory','mapping','unpublish'])
def test_public_reads_fail_closed_after_change(publishing,kind):
    pub,review,pid,m,factory,v,row=publishing
    pub.publish(row['review_id'],'one',pid,'admin')
    if kind=='review':review.revoke(row['review_id'],'admin')
    elif kind=='rights':v.media.cache.decide_rights(m['assets'][0]['asset_id'],rights_state='REJECTED',actor='rights-admin')
    elif kind=='bytes':next(v.media.cache.files_dir.iterdir()).write_bytes(b'corrupt')
    elif kind=='unpublish':factorymod.hotel_autopage_factory_service.set_publication('hotel','UNPUBLISH','admin')
    else:
        with factory() as s:
            if kind=='inventory':s.delete(s.get(HotelPartnerRoomTypeRow,m['inventory']['partner_room_ids'][0]))
            else:
                p=s.get(HotelCanonicalProfileRow,'hotel');c=copy.deepcopy(p.canonical_json);c['rooms'][0]['room_type_id']='different';p.canonical_json=c
            s.commit()
    with pytest.raises(ValueError):factorymod.hotel_autopage_factory_service.public_page('test')
    with pytest.raises(ValueError):pub.public_content(row['review_id'],m['assets'][0]['asset_id'])


def test_approval_alone_is_not_public_and_unknown_asset_denied(publishing):
    pub,review,pid,m,factory,v,row=publishing
    with pytest.raises(ValueError):pub.public_content(row['review_id'],m['assets'][0]['asset_id'])
    pub.publish(row['review_id'],'one',pid,'admin')
    with pytest.raises(ValueError):pub.public_content(row['review_id'],'not-reviewed')


def test_forged_marker_and_legacy_contract_remain_blocked(publishing):
    pub,review,pid,m,factory,v,row=publishing
    with factory() as s:c=copy.deepcopy(s.get(HotelCanonicalProfileRow,'hotel').canonical_json)
    legacy=quality(c,{},[],hotel_id='hotel',verify_asset=lambda _:None)
    assert legacy['rule_version']=='OFFICIAL_CATALOG_REPLICATION_V1' and not legacy['passed']
    c['direct_submission']={'schema':'HOTEL_DIRECT_SUBMISSION_V1','review_id':'forged','supplier_id':'one','property_id':pid,'manifest_sha256':row['manifest_sha256']}
    assert not quality(c,{},[],hotel_id='hotel',verify_asset=None)['passed']


def test_revoked_page_can_still_be_unpublished(publishing):
    pub,review,pid,m,factory,v,row=publishing
    pub.publish(row['review_id'],'one',pid,'admin')
    review.revoke(row['review_id'],'admin')
    result=factorymod.hotel_autopage_factory_service.set_publication('hotel','UNPUBLISH','admin')
    assert result['profile']['page_state']=='DRAFT'


def test_missing_fact_snapshots_rolls_back_without_erasing_profile(publishing):
    pub,review,pid,m,factory,v,row=publishing
    with factory() as s:
        before=copy.deepcopy(s.get(HotelCanonicalProfileRow,'hotel').canonical_json)
        s.delete(s.get(HotelContentSourceSnapshotRow,'facts'));s.commit()
    with pytest.raises(ValueError):pub.publish(row['review_id'],'one',pid,'admin')
    with factory() as s:
        assert s.get(HotelCanonicalProfileRow,'hotel').canonical_json==before
        assert s.query(HotelAutoPageVersionRow).count()==0
        assert s.query(HotelContentSourceSnapshotRow).count()==0


def test_media_review_cannot_clear_fact_conflicts(publishing):
    pub,review,pid,m,factory,v,row=publishing
    with factory() as s:
        p=s.get(HotelCanonicalProfileRow,'hotel')
        p.field_provenance_json={'address':{'conflict_state':'REVIEW_REQUIRED'}}
        s.commit()
    with pytest.raises(ValueError,match='QUALITY_HOLD'):pub.publish(row['review_id'],'one',pid,'admin')


def test_stale_snapshot_same_room_id_rolls_back_physical_changes(publishing):
    pub,review,pid,m,factory,v,row=publishing
    with factory() as s:
        before=copy.deepcopy(s.get(HotelCanonicalProfileRow,'hotel').canonical_json)
        snapshot=s.get(HotelContentSourceSnapshotRow,'facts');data=copy.deepcopy(snapshot.payload_json)
        data['rooms'][0]['bed']='Different bed';snapshot.payload_json=data;s.commit()
    with pytest.raises(ValueError,match='CANONICAL_FACTS_CHANGED'):pub.publish(row['review_id'],'one',pid,'admin')
    with factory() as s:
        assert s.get(HotelCanonicalProfileRow,'hotel').canonical_json==before
        assert s.query(HotelAutoPageVersionRow).count()==0
