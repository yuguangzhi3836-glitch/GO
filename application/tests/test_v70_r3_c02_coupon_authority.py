import pytest
from go_hotel.flight import coupon_authority as auth

KEY = b"test-only-authority-key"
KEYS = {"c02-test": KEY}


def plan():
    return {"plan_hash": "plan-1", "order": {"currency": "CNY"}, "changes": [
        {"leg_index": 0, "passenger_index": 0,
         "new_departure_at": "2026-10-01T08:00:00+08:00",
         "fare_difference_minor": -3000, "change_fee_minor": 500},
        {"leg_index": 1, "passenger_index": 0,
         "new_departure_at": "2026-10-01T18:00:00+08:00",
         "fare_difference_minor": 8000, "change_fee_minor": 500}]}


def consent(record):
    return {"plan_id": record["plan_id"], "authority_mac": record["authority_mac"],
            "charge_minor": 9000, "credit_minor": 3000, "currency": "CNY",
            "negative_fare_treatment": "CREDIT_NOT_NETTED", "confirmed": True}


def authorize(store, record, allocations=None, **kwargs):
    return auth.authorize(
        store, record["plan_id"], consent(record),
        allocations or [{"source_id": "capture-1", "amount_minor": 9000}],
        authority_keys=kwargs.pop("authority_keys", KEYS), **kwargs)


def test_same_day_segments_and_negative_difference_are_frozen_without_netting():
    store = {}
    record = auth.persist(plan(), store, key_id="c02-test", authority_key=KEY)
    result = authorize(store, record)
    assert result["payment_intent"]["amount_minor"] == 9000
    assert result["credit_instruction"] == {"amount_minor": 3000,
                                             "mode": "CREDIT_NOT_NETTED"}


@pytest.mark.parametrize("fault", ["stored", "consent", "allocation", "order"])
def test_tampering_wrong_consent_allocation_or_same_day_order_is_rejected(fault):
    store = {}
    candidate = plan()
    if fault == "order":
        candidate["changes"][1]["new_departure_at"] = "2026-10-01T07:59:00+08:00"
        with pytest.raises(ValueError, match="ITINERARY_ORDER_INVALID"):
            auth.persist(candidate, store, key_id="c02-test", authority_key=KEY)
        return
    record = auth.persist(candidate, store, key_id="c02-test", authority_key=KEY)
    approval = consent(record)
    allocations = [{"source_id": "capture-1", "amount_minor": 9000}]
    if fault == "stored":
        store["plan-1"]["charge_minor"] += 1
    elif fault == "consent":
        approval["credit_minor"] = 0
    else:
        allocations[0]["amount_minor"] -= 1
    with pytest.raises(ValueError):
        auth.authorize(store, "plan-1", approval, allocations, authority_keys=KEYS)


def test_persist_is_immutable_and_input_is_not_aliased():
    store = {}
    candidate = plan()
    first = auth.persist(candidate, store, key_id="c02-test", authority_key=KEY)
    candidate["changes"][0]["fare_difference_minor"] = 999
    assert store["plan-1"] == first
    with pytest.raises(ValueError, match="IMMUTABLE"):
        auth.persist(candidate, store, key_id="c02-test", authority_key=KEY)


def test_key_rotation_resolves_the_immutable_record_key_id():
    store = {}
    old = auth.persist(plan(), store, key_id="c02-test", authority_key=KEY)
    rotated = {"c02-test": KEY, "c02-next": b"next-test-only-authority-key"}
    assert authorize(store, old, authority_keys=rotated)["plan_id"] == "plan-1"

    with pytest.raises(ValueError, match="KEY_UNKNOWN"):
        authorize(store, old, authority_keys={"c02-next": rotated["c02-next"]})
    with pytest.raises(ValueError, match="KEY_RETIRED"):
        authorize(store, old, authority_keys=rotated, retired_key_ids={"c02-test"})


def test_wrong_key_for_record_key_id_fails_mac_instead_of_falling_through():
    store = {}
    record = auth.persist(plan(), store, key_id="c02-test", authority_key=KEY)
    with pytest.raises(ValueError, match="MAC_INVALID"):
        authorize(store, record, authority_keys={"c02-test": b"wrong-key"})


@pytest.mark.parametrize("currency", [None, "", "cny", "CN", "CNY1", "人民币"])
def test_missing_or_noncanonical_currency_is_rejected(currency):
    candidate = plan()
    candidate["order"]["currency"] = currency
    with pytest.raises(ValueError, match="CURRENCY_INVALID"):
        auth.persist(candidate, {}, key_id="c02-test", authority_key=KEY)
