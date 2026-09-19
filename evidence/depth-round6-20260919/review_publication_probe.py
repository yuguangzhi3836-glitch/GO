import copy
import pytest
from test_hotel_direct_submission_publication import publishing
from test_hotel_direct_submission_review import ready
from test_hotel_direct_submission_verification import setup
from go_hotel.db.models import HotelCanonicalProfileRow, HotelContentSourceSnapshotRow

def test_missing_source_snapshot_does_not_erase_approved_profile(publishing):
    pub,review,pid,m,factory,v,row=publishing
    with factory() as s:
        before=copy.deepcopy(s.get(HotelCanonicalProfileRow,'hotel').canonical_json)
        s.query(HotelContentSourceSnapshotRow).delete();s.commit()
    with pytest.raises(ValueError):pub.publish(row['review_id'],'one',pid,'admin')
    with factory() as s:
        assert s.get(HotelCanonicalProfileRow,'hotel').canonical_json == before

def test_stale_physical_source_snapshot_does_not_mutate_approved_profile(publishing):
    pub,review,pid,m,factory,v,row=publishing
    with factory() as s:
        before=copy.deepcopy(s.get(HotelCanonicalProfileRow,'hotel').canonical_json)
        source=s.get(HotelContentSourceSnapshotRow,'facts')
        changed=copy.deepcopy(source.payload_json);changed['rooms'][0]['bed']='Twin';source.payload_json=changed;s.commit()
    with pytest.raises(ValueError):pub.publish(row['review_id'],'one',pid,'admin')
    with factory() as s:
        assert s.get(HotelCanonicalProfileRow,'hotel').canonical_json == before
