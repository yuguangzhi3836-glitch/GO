from go_hotel.services.hyatt_db_authority_snapshot import diff
from go_hotel.services.hyatt_e2e_evidence import evaluate_hotel_evidence


def snap(*, audits=1, hotels=("h1",), rooms=("r1",), media=None, versions=("v1",), active=("v1",)):
    return {"hotel_ids":list(hotels),"room_ids":list(rooms),"media_assets":media or [{"asset_id":"a1","room_type_id":"r1","sha256":"s1","publication_state":"PUBLISHED","rights_state":"AUTHORIZED"}],"page_state":{"audit_event_count":audits,"page_versions":list(versions),"active_page_versions":list(active)}}


def test_audit_growth_is_allowed_when_authoritative_state_is_stable():
    result=diff(snap(audits=1),snap(audits=9))
    assert result["audit_event_growth"]==8
    assert result["audit_growth_allowed"] is True
    assert result["forbidden_state_proliferation"] is False
    assert result["zero_proliferation"] is True


def test_new_room_fails_authoritative_idempotency():
    result=diff(snap(),snap(rooms=("r1","r2")))
    assert result["room_entity_added"]==["r2"]
    assert result["zero_proliferation"] is False


def test_media_state_drift_fails_authoritative_idempotency():
    changed=[{"asset_id":"a1","room_type_id":"r1","sha256":"s1","publication_state":"HOLD","rights_state":"AUTHORIZED"}]
    result=diff(snap(),snap(media=changed))
    assert result["media_asset_changed"]==["a1"]
    assert result["zero_proliferation"] is False


def test_new_page_version_fails_but_audit_only_does_not():
    assert diff(snap(audits=1),snap(audits=2))["zero_proliferation"] is True
    result=diff(snap(),snap(versions=("v1","v2"),active=("v2",)))
    assert result["page_version_added"]==["v2"]
    assert result["active_page_version_added"]==["v2"]
    assert result["zero_proliferation"] is False


def passing_record():
    return {"build_state":"READY","identity_unique":True,"official_room_type_ids":["r1"],"go_room_type_ids":["r1"],"room_media_isolation":True,"room_media_cross_bind_count":0,"hotel_scene_categories":["EXTERIOR","LOBBY","DINING","WELLNESS","MEETING"],"durable_media_ledger":True,"missing_blob_count":0,"corrupt_blob_count":0,"published_without_rights_count":0,"lkg_protected":True,"rerun_count":2,"duplicate_hotel_count":0,"duplicate_room_count":0,"unintended_page_proliferation_count":0,"authoritative_db_idempotency":True,"forced_kill_observed":True,"lease_reclaimed":True,"terminal_ack_count":1}


def test_matrix_requires_authoritative_db_idempotency():
    record=passing_record();assert evaluate_hotel_evidence(record)["status"]=="PASS"
    record["authoritative_db_idempotency"]=False
    result=evaluate_hotel_evidence(record)
    assert result["status"]=="HOLD"
    assert result["checks"]["authoritative_db_idempotency"] is False
