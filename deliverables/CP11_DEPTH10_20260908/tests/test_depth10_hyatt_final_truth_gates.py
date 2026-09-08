from go_hotel.services.hyatt_e2e_evidence import evaluate_hotel_evidence

def base():
    return {"build_state":"READY","identity_unique":True,"official_room_type_ids":["r1"],"go_room_type_ids":["r1"],"room_media_isolation":True,"room_media_cross_bind_count":0,"hotel_scene_categories":["EXTERIOR","LOBBY","DINING","WELLNESS","MEETING"],"durable_media_ledger":True,"missing_blob_count":0,"corrupt_blob_count":0,"published_without_rights_count":0,"blob_integrity_evidence_source":"MEDIA_BLOB_RECOVERY","lkg_protected":True,"lkg_evidence_source":"POSTGRES_PUBLICATION_EVENT_LEDGER","failed_candidate_count":1,"protected_failure_count":1,"authoritative_db_diffs":[{"zero_proliferation":True},{"zero_proliferation":True}],"rerun_count":2,"duplicate_hotel_count":0,"duplicate_room_count":0,"unintended_page_proliferation_count":0,"forced_kill_observed":True,"lease_reclaimed":True,"terminal_ack_count":1}

def test_blob_none_is_hold_not_zero():
    row=base();row["missing_blob_count"]=None;row["blob_integrity_evidence_source"]="UNAVAILABLE";result=evaluate_hotel_evidence(row);assert result["status"]=="HOLD";assert result["checks"]["blob_integrity_available"] is False

def test_blob_corruption_is_hold():
    row=base();row["corrupt_blob_count"]=1;assert evaluate_hotel_evidence(row)["status"]=="HOLD"

def test_producer_lkg_boolean_without_event_ledger_is_hold():
    row=base();row["lkg_evidence_source"]="PRODUCER_ASSERTION";assert evaluate_hotel_evidence(row)["status"]=="HOLD"

def test_lkg_requires_observed_failed_candidate():
    row=base();row["failed_candidate_count"]=0;row["protected_failure_count"]=0;assert evaluate_hotel_evidence(row)["status"]=="HOLD"

def test_lkg_requires_every_failure_protected():
    row=base();row["failed_candidate_count"]=2;row["protected_failure_count"]=1;assert evaluate_hotel_evidence(row)["status"]=="HOLD"

def test_complete_truth_record_can_pass():
    assert evaluate_hotel_evidence(base())["status"]=="PASS"
