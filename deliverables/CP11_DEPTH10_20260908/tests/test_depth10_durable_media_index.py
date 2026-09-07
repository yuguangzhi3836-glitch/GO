from go_hotel.services.durable_media_index import _fold, _is_publishable, PUBLISHABLE_RIGHTS, PREFIX


class Row:
    def __init__(self, state, evidence):
        self.event_type = PREFIX + state
        self.evidence_json = evidence


def record(asset_id="media_1"):
    return {
        "asset_id": asset_id,
        "hotel_id": "hotel_1",
        "role": "ROOM",
        "room_type_id": "room_1",
        "sha256": "a" * 64,
        "cache_file": "a.jpg",
        "cache_state": "VALIDATED",
        "rights_state": "RIGHTS_UNKNOWN",
        "publication_state": "HOLD",
    }


def test_fold_registration_rights_and_publish_state():
    r = record()
    rows = [
        Row("REGISTERED", {"asset_id": "media_1", "hotel_id": "hotel_1", "record": r}),
        Row("RIGHTS_DECIDED", {
            "asset_id": "media_1", "hotel_id": "hotel_1",
            "rights": {"rights_state": "AUTHORIZED", "rights_owner": "hotel", "rights_evidence_reference": "official:1"},
        }),
        Row("PUBLICATION_CHANGED", {"asset_id": "media_1", "hotel_id": "hotel_1", "publication_state": "PUBLISHED"}),
    ]
    got = _fold(rows)["media_1"]
    assert got["rights_state"] == "AUTHORIZED"
    assert got["publication_state"] == "PUBLISHED"
    assert got["publishable"] is True


def test_revoke_wins_and_is_not_publishable():
    r = record()
    r.update({"rights_state": "HOTEL_SUBMITTED", "rights_owner": "hotel", "rights_evidence_reference": "upload:1"})
    rows = [
        Row("REGISTERED", {"asset_id": "media_1", "hotel_id": "hotel_1", "record": r}),
        Row("REVOKED", {"asset_id": "media_1", "hotel_id": "hotel_1", "reason": "withdrawn"}),
    ]
    got = _fold(rows)["media_1"]
    assert got["publication_state"] == "REVOKED"
    assert got["publishable"] is False


def test_publishable_requires_validated_cache_and_evidence():
    for state in PUBLISHABLE_RIGHTS:
        r = record()
        r.update({"rights_state": state, "rights_owner": "hotel", "rights_evidence_reference": "evidence"})
        assert _is_publishable(r) is True
    r = record()
    r.update({"rights_state": "AUTHORIZED", "rights_owner": "hotel"})
    assert _is_publishable(r) is False


def test_unrelated_rights_event_does_not_create_asset():
    rows = [Row("RIGHTS_DECIDED", {"asset_id": "ghost", "rights": {"rights_state": "AUTHORIZED"}})]
    assert _fold(rows) == {}
