"""V70-R4-C05-02: UNKNOWN episode references are single-use per ride order."""
import pytest
from tests.test_depth33_mobility_refund_consent import booked


def test_completed_unknown_reference_cannot_be_reopened_on_same_order():
    svc, owner, oid = booked('RIDE')
    ref='isolated://stable-episode-id'
    svc.admin_external_state(oid,'UNKNOWN_EXTERNAL_STATE',ref,'ops')
    svc.admin_external_state(oid,'CONFIRMED','isolated://confirm-1','ops',ref)
    before=svc.get(owner,oid)
    with pytest.raises(ValueError,match='RIDE_UNKNOWN_EPISODE_REFERENCE_REUSED'):
        svc.admin_external_state(oid,'UNKNOWN_EXTERNAL_STATE',ref,'ops')
    assert svc.get(owner,oid)==before


def test_reference_is_scoped_per_order_not_globally():
    svc1, _, oid1 = booked('RIDE')
    svc2, _, oid2 = booked('RIDE')
    ref='isolated://supplier-correlation'
    assert svc1.admin_external_state(oid1,'UNKNOWN_EXTERNAL_STATE',ref,'ops')['status']=='UNKNOWN_EXTERNAL_STATE'
    assert svc2.admin_external_state(oid2,'UNKNOWN_EXTERNAL_STATE',ref,'ops')['status']=='UNKNOWN_EXTERNAL_STATE'


def test_missing_unknown_reference_rejected_without_mutation():
    svc, owner, oid = booked('RIDE')
    before=svc.get(owner,oid)
    with pytest.raises(ValueError,match='EXTERNAL_STATE_ACTOR_AND_EVIDENCE_REQUIRED'):
        svc.admin_external_state(oid,'UNKNOWN_EXTERNAL_STATE','  ','ops')
    assert svc.get(owner,oid)==before
