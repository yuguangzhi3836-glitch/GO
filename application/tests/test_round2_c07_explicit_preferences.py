"""C07 preferences: owner intent, durable consent, purpose isolation and withdrawal."""
from datetime import datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import select

from go_hotel.core.config import settings
from go_hotel.db.models import ProfileAccessAuditRow, ProfileConsentRow, ProfileFactRow, TravelerProfileRow
from go_hotel.db.session import SessionLocal, engine
from go_hotel.services.personal_travel_vault import personal_travel_vault_service as vault
from go_hotel.travel_intelligence.service import travel_intelligence_service as svc

PURPOSE = "HOTEL_PLANNING"


def traveler(user="owner", tid="traveler", relationship="SELF"):
    t = datetime.now(timezone.utc)
    with SessionLocal.begin() as s:
        s.add(TravelerProfileRow(traveler_id=tid, user_id=user, full_name="EXPLICIT TEST",
            relationship_type=relationship, nationality="CHN", status="ACTIVE", created_at=t, updated_at=t))
    return tid


def consent(tid="traveler", user="owner", **overrides):
    return vault.grant_consent(user, {"traveler_id":tid, "consent_type":"EXPLICIT_TRAVEL_PREFERENCE",
        "purpose":PURPOSE, "scope":["TRAVEL_PREFERENCE:HOTEL_ROOM"],
        "expires_at":(datetime.now(timezone.utc)+timedelta(days=30)).isoformat(), **overrides})["consent_id"]


def context_consent(tid="traveler", user="owner", **overrides):
    return vault.grant_consent(user, {"traveler_id":tid, "consent_type":"TRAVELER_CONTEXT",
        "purpose":PURPOSE, "scope":["TRAVEL_INTENTS"],
        "expires_at":(datetime.now(timezone.utc)+timedelta(days=30)).isoformat(), **overrides})["consent_id"]


def save(cid, **overrides):
    return svc.save_preference("owner", "traveler", preference_key="HOTEL_ROOM",
        value={"quiet":True}, purpose=PURPOSE, consent_id=cid, confirmed=True, **overrides)


def read(purpose=PURPOSE):
    return svc.preferences("traveler", purpose=purpose, actor_id="review-admin")


def test_explicit_preference_survives_engine_reopen_and_is_encrypted():
    traveler(); cid=consent(); first=save(cid)
    engine.dispose()
    result=read()
    assert result["preferences"] == [first]
    assert result["projection"] == "EXPLICIT_PURPOSE_BOUND_V1"
    with SessionLocal() as s:
        f=s.get(ProfileFactRow, first["preference_id"])
        assert f.user_confirmed and f.source_type == "MANUAL"
        assert "quiet" not in f.value_ciphertext
        audits=list(s.scalars(select(ProfileAccessAuditRow)))
        assert {a.action for a in audits} >= {"TRAVEL_PREFERENCE_SAVED", "TRAVEL_PREFERENCES_READ"}
        assert "quiet" not in json.dumps([a.metadata_json for a in audits])


def test_wrong_purpose_never_releases_preference():
    traveler(); save(consent())
    assert read("ADVERTISING")["preferences"] == []
    graph=svc.traveler_graph("traveler", purpose="ADVERTISING")
    assert graph["durable_preferences"] == []
    assert graph["identity"] == {} and graph["recent_intents"] == []


@pytest.mark.parametrize("fault", ["revoked", "expired", "future", "wrong_scope", "wrong_type", "wrong_traveler", "wrong_owner", "revoked_at", "no_expiry", "wildcard_scope"])
def test_live_consent_invalidates_reads_and_rejects_writes(fault):
    traveler(); traveler(tid="other"); cid=consent(); save(cid)
    with SessionLocal.begin() as s:
        c=s.get(ProfileConsentRow,cid)
        if fault=="revoked": c.status="REVOKED"
        elif fault=="expired": c.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
        elif fault=="future": c.granted_at=datetime.now(timezone.utc)+timedelta(days=1)
        elif fault=="wrong_scope": c.scope_json=["TRAVELER_IDENTITY"]
        elif fault=="wrong_type": c.consent_type="SENSITIVE_DATA_RELEASE"
        elif fault=="wrong_traveler": c.traveler_id="other"
        elif fault=="wrong_owner": c.user_id="stranger"
        elif fault=="revoked_at": c.revoked_at=datetime.now(timezone.utc)
        elif fault=="no_expiry": c.expires_at=None
        elif fault=="wildcard_scope": c.scope_json=["*"]
    assert read()["preferences"] == []
    assert svc.traveler_graph("traveler",purpose=PURPOSE)["durable_preferences"] == []
    with pytest.raises(ValueError,match="TRAVEL_PREFERENCE_CONSENT_REQUIRED"):
        save(cid)


def test_no_implicit_promotion_and_graph_scopes_are_independent():
    traveler()
    svc.create_intent(traveler_id="traveler",session_id="session-1",raw_input="quiet room budget 500",
        consent_scope=[PURPOSE],correlation_id="c07-session")
    cid=consent()
    graph=svc.traveler_graph("traveler",purpose=PURPOSE)
    assert graph["durable_preferences"] == [] and graph["recent_intents"] == []
    assert graph["identity"] == {}
    with SessionLocal() as s:
        assert not list(s.scalars(select(ProfileFactRow)))
    context_consent(scope=["TRAVELER_IDENTITY","TRAVEL_INTENTS"])
    graph=svc.traveler_graph("traveler",purpose=PURPOSE)
    assert graph["identity"]["nationality"] == "CHN"
    assert graph["recent_intents"] == []
    assert graph["durable_preferences"] == []
    svc.create_intent(traveler_id="traveler",session_id="session-2",raw_input="suite budget 700",
        consent_scope=[PURPOSE],correlation_id="c07-session-2")
    graph=svc.traveler_graph("traveler",purpose=PURPOSE)
    assert graph["recent_intents"] == [{"raw_normalized":"suite budget 700","budget_max":700.0}]
    saved=save(cid)
    assert svc.traveler_graph("traveler",purpose=PURPOSE)["durable_preferences"] == [saved]


def test_save_retry_revision_conflict_and_withdrawal_are_durable():
    traveler(); cid=consent(); first=save(cid)
    assert save(cid) == first
    with pytest.raises(ValueError,match="TRAVEL_PREFERENCE_REVISION_CONFLICT"):
        svc.save_preference("owner","traveler",preference_key="HOTEL_ROOM",value={"quiet":False},
            purpose=PURPOSE,consent_id=cid,confirmed=True)
    changed=svc.save_preference("owner","traveler",preference_key="HOTEL_ROOM",value={"quiet":False},
        purpose=PURPOSE,consent_id=cid,confirmed=True,expected_preference_id=first["preference_id"])
    assert changed["preference_id"] != first["preference_id"]
    assert read()["preferences"] == [changed]
    with pytest.raises(ValueError,match="TRAVEL_PREFERENCE_REVISION_CONFLICT"):
        svc.revoke_preference("owner","traveler",first["preference_id"])
    assert read()["preferences"] == [changed]
    result=svc.revoke_preference("owner","traveler",changed["preference_id"])
    assert result["status"] == "REVOKED"
    assert svc.revoke_preference("owner","traveler",changed["preference_id"]) == result
    engine.dispose()
    assert read()["preferences"] == []
    with SessionLocal() as s:
        f=s.get(ProfileFactRow,changed["preference_id"])
        assert f.status == "REVOKED" and f.value_ciphertext != json.dumps({"quiet":False})


def test_existing_vault_consent_withdrawal_takes_effect_immediately():
    traveler(); cid=consent(); save(cid)
    vault.revoke_consent("owner",cid)
    assert read()["preferences"] == []
    assert svc.traveler_graph("traveler",purpose=PURPOSE)["durable_preferences"] == []
    # Granting a different consent cannot revive a fact bound to the withdrawn one.
    consent()
    assert read()["preferences"] == []


def test_revoked_traveler_context_grant_does_not_revive_old_intent_after_regrant():
    traveler()
    traveler(user="other-owner", tid="other-traveler")
    first_grant=context_consent()
    svc.create_intent(traveler_id="traveler",session_id="session-1",raw_input="quiet room budget 500",
        consent_scope=[PURPOSE],correlation_id="c07-intent-1")
    assert svc.traveler_graph("traveler",purpose=PURPOSE)["recent_intents"] == [
        {"raw_normalized":"quiet room budget 500","budget_max":500.0}
    ]
    vault.revoke_consent("owner",first_grant)
    assert svc.traveler_graph("traveler",purpose=PURPOSE)["recent_intents"] == []
    context_consent()
    assert svc.traveler_graph("traveler",purpose=PURPOSE)["recent_intents"] == []
    svc.create_intent(traveler_id="traveler",session_id="session-2",raw_input="suite budget 900",
        consent_scope=[PURPOSE],correlation_id="c07-intent-2")
    graph=svc.traveler_graph("traveler",purpose=PURPOSE)
    assert graph["recent_intents"] == [{"raw_normalized":"suite budget 900","budget_max":900.0}]
    context_consent(tid="other-traveler", user="other-owner")
    svc.create_intent(traveler_id="other-traveler",session_id="other-session",raw_input="late arrival budget 300",
        consent_scope=[PURPOSE],correlation_id="c07-other-intent")
    assert svc.traveler_graph("traveler",purpose=PURPOSE)["recent_intents"] == graph["recent_intents"]


@pytest.mark.parametrize("confirmed", [False, None, 1, "true"])
def test_explicit_confirmation_required(confirmed):
    traveler(); cid=consent()
    with pytest.raises(ValueError,match="TRAVEL_PREFERENCE_CONFIRMATION_REQUIRED"):
        svc.save_preference("owner","traveler",preference_key="HOTEL_ROOM",value={"quiet":True},
            purpose=PURPOSE,consent_id=cid,confirmed=confirmed)


def test_owner_and_companion_edit_permission_enforced():
    traveler(); cid=consent()
    with pytest.raises(ValueError,match="TRAVELER_NOT_FOUND"):
        svc.save_preference("other-owner","traveler",preference_key="HOTEL_ROOM",value={"quiet":True},
            purpose=PURPOSE,consent_id=cid,confirmed=True)
    saved=save(cid)
    with pytest.raises(ValueError,match="TRAVELER_NOT_FOUND"):
        svc.revoke_preference("other-owner","traveler",saved["preference_id"])
    vault.set_permission("owner","traveler","EDIT",False)
    with pytest.raises(ValueError,match="TRAVELER_EDIT_PERMISSION_REQUIRED"):
        save(cid)


def test_companion_cannot_be_treated_as_self_even_with_edit_permission():
    traveler(relationship="FAMILY")
    vault.set_permission("owner","traveler","EDIT",True)
    cid=consent()
    with pytest.raises(ValueError,match="TRAVEL_PREFERENCE_SELF_REQUIRED"):
        save(cid)
    with pytest.raises(ValueError,match="TRAVEL_PREFERENCE_SELF_REQUIRED"):
        read()


def test_parallel_first_writes_produce_one_revision_and_one_conflict():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    traveler(); cid=consent(); ready=Barrier(2)
    def attempt(quiet):
        ready.wait(timeout=10)
        try:
            return svc.save_preference("owner","traveler",preference_key="HOTEL_ROOM",value={"quiet":quiet},
                purpose=PURPOSE,consent_id=cid,confirmed=True)
        except ValueError as e:
            return str(e)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(attempt,[True,False]))
    assert sum(isinstance(r,dict) for r in results)==1
    assert "TRAVEL_PREFERENCE_REVISION_CONFLICT" in results
    assert len(read()["preferences"])==1


@pytest.mark.parametrize("key", ["GO_SCORE","JUDGMENT_VERDICT","COMMISSION_BOOST","UNKNOWN"])
def test_c09_truth_and_unregistered_keys_cannot_be_saved(key):
    traveler(); cid=consent(scope=["TRAVEL_PREFERENCE:"+key])
    with pytest.raises(ValueError,match="TRAVEL_PREFERENCE_KEY_INVALID"):
        svc.save_preference("owner","traveler",preference_key=key,value={"score":1},
            purpose=PURPOSE,consent_id=cid,confirmed=True)
    with SessionLocal() as s:
        assert not list(s.scalars(select(ProfileFactRow)))


def test_view_withdrawal_blocks_both_preferences_and_graph():
    traveler(); save(consent())
    vault.set_permission("owner","traveler","VIEW",False)
    with pytest.raises(ValueError,match="TRAVELER_VIEW_PERMISSION_REQUIRED"):
        read()
    with pytest.raises(ValueError,match="TRAVELER_VIEW_PERMISSION_REQUIRED"):
        svc.traveler_graph("traveler",purpose=PURPOSE)


@pytest.mark.parametrize("value", [None,"",{},[],{"x":float("nan")},{"x":"y"*4096}])
def test_invalid_payload_does_not_persist_or_enter_audit(value):
    traveler(); cid=consent()
    with pytest.raises(ValueError,match="TRAVEL_PREFERENCE_VALUE_INVALID"):
        svc.save_preference("owner","traveler",preference_key="HOTEL_ROOM",value=value,
            purpose=PURPOSE,consent_id=cid,confirmed=True)
    with SessionLocal() as s:
        assert not list(s.scalars(select(ProfileFactRow)))
        assert not list(s.scalars(select(ProfileAccessAuditRow).where(ProfileAccessAuditRow.action=="TRAVEL_PREFERENCE_SAVED")))


def test_preferences_http_authenticated_owner_internal_read_and_no_cache(client, monkeypatch):
    monkeypatch.setattr(settings,"travel_intelligence_enabled",True)
    reg=client.post("/v1/consumer/auth/register",json={"email":"c07@example.test","password":"StrongPass123!","display_name":"C07"})
    assert reg.status_code==200,reg.text
    user=reg.json()["data"]["profile"]["user_id"]
    token=client.post("/v1/mobile/auth/login",json={"email":"c07@example.test","password":"StrongPass123!"}).json()["data"]["access_token"]
    client.cookies.clear(); headers={"Authorization":"Bearer "+token}
    traveler(user=user)
    grant=client.post("/v1/consumer/profile/consents",headers=headers,json={
        "traveler_id":"traveler","consent_type":"EXPLICIT_TRAVEL_PREFERENCE","purpose":PURPOSE,
        "scope":["TRAVEL_PREFERENCE:HOTEL_ROOM"],"expires_at":(datetime.now(timezone.utc)+timedelta(days=30)).isoformat()})
    assert grant.status_code==201,grant.text
    cid=grant.json()["data"]["consent_id"]
    base="/v1/consumer/travelers/traveler/preferences"
    body={"value":{"quiet":True},"purpose":PURPOSE,"consent_id":cid,"confirmed":True}
    assert client.put(base+"/HOTEL_ROOM",json=body).status_code==401
    rejected=client.put(base+"/HOTEL_ROOM",headers=headers,json={**body,"confirmed":"true"})
    assert rejected.status_code==422
    saved=client.put(base+"/HOTEL_ROOM",headers=headers,json=body)
    assert saved.status_code==200,saved.text
    got=client.get(base,headers=headers,params={"purpose":PURPOSE})
    assert got.status_code==200,got.text
    assert got.json()["data"]["preferences"] == [saved.json()["data"]]
    assert "no-store" in got.headers["cache-control"]
    assert client.get("/internal/v1/travelers/traveler/preferences",headers=headers,params={"purpose":PURPOSE}).status_code==403
    # Internal reads require an actual GO_ADMIN principal; an administrator
    # cannot reuse this public write endpoint as the owner of a consumer record.
    from go_hotel.security.service import identity_service
    admin=identity_service.login(settings.bootstrap_admin_username,settings.bootstrap_admin_password)
    admin_headers={"Authorization":"Bearer "+admin["access_token"]}
    internal=client.get("/internal/v1/travelers/traveler/preferences",headers=admin_headers,params={"purpose":PURPOSE})
    assert internal.status_code==200,internal.text
    assert internal.json()["data"]["preferences"] == [saved.json()["data"]]
    assert "no-store" in internal.headers["cache-control"]
    assert client.put(base+"/HOTEL_ROOM",headers=admin_headers,json=body).status_code==403
    assert client.put(base+"/HOTEL_ROOM",headers=headers,json={**body,"user_id":"other-owner"}).status_code==422
    revoked=client.delete(base+"/"+saved.json()["data"]["preference_id"],headers=headers)
    assert revoked.status_code==200,revoked.text
    assert client.get(base,headers=headers,params={"purpose":PURPOSE}).json()["data"]["preferences"] == []
