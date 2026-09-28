import copy
from datetime import datetime, timezone
import pytest
from go_hotel.db.models import HotelRegistrationDirectRow, HotelCanonicalProfileRow, HotelPartnerRoomTypeRow, HotelPartnerPropertyRow, HotelPartnerChangeRequestRow, HotelPartnerAuditEventRow
from go_hotel.services import hotel_direct_submission_review as review
from test_hotel_direct_submission_verification import setup

@pytest.fixture
def ready(setup,monkeypatch):
    svc,client,app,pid,m,factory=setup
    monkeypatch.setattr(review,'SessionLocal',factory)
    stamp=datetime.now(timezone.utc)
    with factory() as s:
        s.add(HotelRegistrationDirectRow(hotel_registration_direct_id='reg',hotel_id='hotel',supplier_id='one',state='APPROVED',evidence_json=[],official_supplement_json={'property_id':pid},requested_by='owner',reviewed_by='admin-registration',created_at=stamp,reviewed_at=stamp))
        s.add(HotelCanonicalProfileRow(hotel_id='hotel',slug='test',canonical_json={'rooms':[{'room_type_id':'canonical-room','official_id':'official-room','name':'Room'}]},go_direct_state='GO_DIRECT_VERIFIED',created_at=stamp,updated_at=stamp))
        s.commit()
    for a in m['assets']:
        svc.media.cache.decide_rights(a['asset_id'],rights_state='HOTEL_SUBMITTED',actor='rights-admin',rights_owner='Hotel',evidence_reference='review',rights_scope='DISTRIBUTE_ON_GO',expires_at=None)
    yield review.HotelDirectSubmissionReviewService(svc),pid,m,factory,svc

def approved(ready):
    svc,pid,m,factory,v=ready
    row=svc.submit('one','owner',pid,m)
    svc.approve(row['review_id'],'binding-admin',row['manifest_sha256'])
    return row

def test_immutable_manifest_and_audit(ready):
    svc,pid,m,factory,v=ready
    original=copy.deepcopy(m)
    row=approved(ready)
    m['identity']['association_evidence_reference']='changed'
    result=svc.resolve(row['review_id'],'one',pid)
    assert result['manifest']['identity']==original['identity']
    assert result['reviewed_by']=='binding-admin'
    with factory() as s:
        assert s.query(HotelPartnerAuditEventRow).filter(HotelPartnerAuditEventRow.event_type.like('DIRECT_SUBMISSION_%')).count()==2
        assert s.get(HotelPartnerChangeRequestRow,row['review_id']).state=='APPROVED'
    with pytest.raises(ValueError,match='NOT_REVIEWABLE'):svc.approve(row['review_id'],'admin',row['manifest_sha256'])

@pytest.mark.parametrize('kind',['hash','missing_actor','missing_hash'])
def test_bad_approval_cannot_mutate(ready,kind):
    svc,pid,m,factory,v=ready
    row=svc.submit('one','owner',pid,m)
    with pytest.raises(ValueError):svc.approve(row['review_id'],'' if kind=='missing_actor' else 'admin','0'*64 if kind=='hash' else None if kind=='missing_hash' else row['manifest_sha256'])
    assert svc.get(row['review_id'])['state']=='SUBMITTED'

@pytest.mark.parametrize('kind',['revoked','room_added','room_changed','room_removed','canonical_changed','canonical_hotel_changed','owner','registration','registration_reviewer','rights','bytes'])
def test_live_changes_invalidate_review(ready,kind):
    svc,pid,m,factory,v=ready
    row=approved(ready)
    if kind=='revoked':svc.revoke(row['review_id'],'admin')
    elif kind=='rights':v.media.cache.decide_rights(m['assets'][0]['asset_id'],rights_state='REJECTED',actor='rights-admin')
    elif kind=='bytes':next(v.media.cache.files_dir.iterdir()).write_bytes(b'broken')
    else:
        with factory() as s:
            room=s.get(HotelPartnerRoomTypeRow,m['inventory']['partner_room_ids'][0])
            if kind=='room_added':
                clone={c.name:getattr(room,c.name) for c in room.__table__.columns};clone['room_type_id']='extra';s.add(HotelPartnerRoomTypeRow(**clone))
            elif kind=='room_changed':room.name_zh='Different room'
            elif kind=='room_removed':s.delete(room)
            elif kind=='canonical_changed':s.get(HotelCanonicalProfileRow,'hotel').canonical_json={'rooms':[{'room_type_id':'different'}]}
            elif kind=='canonical_hotel_changed':
                profile=s.get(HotelCanonicalProfileRow,'hotel');profile.canonical_json=dict(profile.canonical_json,name='Different Hotel')
            elif kind=='owner':s.get(HotelPartnerPropertyRow,pid).supplier_id='other'
            elif kind=='registration':s.get(HotelRegistrationDirectRow,'reg').state='REJECTED'
            elif kind=='registration_reviewer':s.get(HotelRegistrationDirectRow,'reg').reviewed_by=None
            s.commit()
    with pytest.raises(ValueError):svc.resolve(row['review_id'],'one',pid)


def test_metadata_cannot_approve_and_revoke_idempotent(ready):
    svc,pid,m,factory,v=ready
    row=svc.submit('one','owner',pid,m)
    with factory() as s:
        s.get(HotelPartnerPropertyRow,pid).operations_json={'direct_submission_binding':m,'approved':True}
        s.commit()
    with pytest.raises(ValueError,match='NOT_APPROVED'):svc.resolve(row['review_id'],'one',pid)
    svc.approve(row['review_id'],'admin',row['manifest_sha256'])
    svc.revoke(row['review_id'],'admin')
    assert svc.revoke(row['review_id'],'admin')['state']=='REVOKED'


def test_publish_metadata_does_not_invalidate_physical_identity(ready):
    svc,pid,m,factory,v=ready
    row=approved(ready)
    with factory() as s:
        p=s.get(HotelCanonicalProfileRow,'hotel');data=copy.deepcopy(p.canonical_json)
        data['rooms'][0]['images']=['/public/approved-image'];data['media_candidates']=[{'role':'HERO'}]
        p.canonical_json=data;p.version+=1;s.commit()
    assert svc.resolve(row['review_id'],'one',pid)['manifest_sha256']==row['manifest_sha256']
