from copy import deepcopy
from datetime import datetime, timezone
import pytest
from go_hotel.attractions.policy_registry import Registry, validate

def policy(**overrides):
    p={"supplier_id":"fixture-supplier","product_id":"p1","go_offer_id":"o1","version":"1.0",
       "state":"ACTIVE","destination_timezone":"Asia/Shanghai",
       "effective_from":"2026-01-01T00:00:00+08:00","effective_until":"2027-01-01T00:00:00+08:00",
       "allow_open_ended":False,"opens_minutes_before_session":60,"closes_minutes_after_session":30,
       "amendment_allowed":True,"cancellation_allowed":False,
       "raw_payload_ref":"fixtures/c06/p1-v1.json","raw_payload_sha256":"a"*64,
       "source_uri":"fixture://c06/p1","observed_at":"2026-09-16T08:25:00Z"}
    p.update(overrides); return p

@pytest.mark.parametrize("field",["supplier_id","product_id","go_offer_id","version","state","destination_timezone",
"effective_from","opens_minutes_before_session","closes_minutes_after_session","allow_open_ended",
"amendment_allowed","cancellation_allowed","raw_payload_ref","raw_payload_sha256","source_uri","observed_at"])
def test_missing_required_rejected(field):
    p=policy(); del p[field]
    with pytest.raises(ValueError,match="SCHEMA_INVALID"): validate(p)

@pytest.mark.parametrize("bad",[
 {"state":"BOGUS"},{"destination_timezone":"Mars/Olympus"},{"version":"v1"},
 {"effective_from":"2027-01-01T00:00:00+08:00"},{"raw_payload_sha256":"no"},
 {"opens_minutes_before_session":-1},{"closes_minutes_after_session":10081},
 {"amendment_allowed":"yes"},{"observed_at":"2026-01-01"}])
def test_malformed_rejected(bad):
    with pytest.raises((ValueError,TypeError)): validate(policy(**bad))

def test_open_ended_requires_flag():
    with pytest.raises(ValueError,match="OPEN_ENDED_NOT_ALLOWED"): validate(policy(effective_until=None))
    assert validate(policy(effective_until=None,allow_open_ended=True))["effective_until"] is None

def test_import_replay_and_conflict():
    r=Registry(); assert r.import_batch([policy()])==["ACCEPTED"]
    assert r.import_batch([policy()])==["IDEMPOTENT_REPLAY"]
    with pytest.raises(ValueError,match="VERSION_HASH_CONFLICT"):
        r.import_batch([policy(source_uri="fixture://changed")])

def test_version_order_and_supersedes_chain():
    r=Registry(); r.import_batch([policy()])
    r.import_batch([policy(version="2.0",supersedes="1.0",state="WITHDRAWN")])
    assert r.current("fixture-supplier","p1","o1")["state"]=="WITHDRAWN"
    with pytest.raises(ValueError,match="STALE_VERSION"): r.import_batch([policy(version="1.5",supersedes="2.0")])
    with pytest.raises(ValueError,match="SUPERSEDES_MISMATCH"): r.import_batch([policy(version="3.0",supersedes="1.0")])

def test_batch_is_atomic_on_partial_failure():
    r=Registry()
    with pytest.raises(ValueError): r.import_batch([policy(),policy(product_id="p2",destination_timezone="bad")])
    assert r.current("fixture-supplier","p1","o1") is None

@pytest.mark.parametrize("at,decision",[
 ("2026-06-01T08:59:59+08:00","TOO_EARLY"),
 ("2026-06-01T09:00:00+08:00","ELIGIBLE"),
 ("2026-06-01T10:30:00+08:00","ELIGIBLE"),
 ("2026-06-01T10:30:01+08:00","TOO_LATE")])
def test_redemption_boundaries(at,decision):
    r=Registry(); r.import_batch([policy()])
    assert r.decide("fixture-supplier","p1","o1","2026-06-01T10:00:00+08:00",at)["decision"]==decision

@pytest.mark.parametrize("state,decision",[
 ("EXPIRED","EXPIRED"),("WITHDRAWN","WITHDRAWN")])
def test_state_precedence(state,decision):
    r=Registry(); r.import_batch([policy(state=state)])
    assert r.decide("fixture-supplier","p1","o1","2026-06-01T10:00:00+08:00","2026-06-01T10:00:00+08:00")["decision"]==decision

def test_unknown_fails_safe():
    assert Registry().decide("x","y","z","2026-06-01T10:00:00Z","2026-06-01T10:00:00Z")["decision"]=="LEGACY_UNVERIFIED"

def test_expiry_and_not_yet_effective():
    r=Registry(); r.import_batch([policy()])
    assert r.decide("fixture-supplier","p1","o1","2028-01-01T10:00:00+08:00","2028-01-01T10:00:00+08:00")["decision"]=="EXPIRED"
    assert r.decide("fixture-supplier","p1","o1","2025-01-01T10:00:00+08:00","2025-01-01T10:00:00+08:00")["decision"]=="LEGACY_UNVERIFIED"

def test_dst_destination_timezone_is_absolute_and_deterministic():
    r=Registry(); r.import_batch([policy(destination_timezone="America/New_York",
      effective_from="2026-01-01T00:00:00-05:00",effective_until="2027-01-01T00:00:00-05:00")])
    result=r.decide("fixture-supplier","p1","o1","2026-11-01T01:30:00-05:00","2026-11-01T05:45:00Z")
    assert result["decision"]=="ELIGIBLE"

def test_change_refund_flags_and_audit_reason():
    r=Registry(); r.import_batch([policy()])
    out=r.decide("fixture-supplier","p1","o1","2026-06-01T10:00:00+08:00","2026-06-01T10:00:00+08:00")
    assert out["amendment_allowed"] is True and out["cancellation_allowed"] is False
    assert r.audit[-1]["reason"]=="IN_REDEMPTION_WINDOW"
    assert out["synthetic_only"] is True
