import pytest
from go_hotel.flight import coupon_authority as auth

KEY = b"test-only-authority-key"


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


def test_same_day_segments_and_negative_difference_are_frozen_without_netting():
    store = {}
    record = auth.persist(plan(), store, key_id="c02-test", authority_key=KEY)
    result = auth.authorize(store, "plan-1", consent(record),
                            [{"source_id": "capture-1", "amount_minor": 9000}],
                            authority_key=KEY)
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
        auth.authorize(store, "plan-1", approval, allocations, authority_key=KEY)


def test_persist_is_immutable_and_input_is_not_aliased():
    store = {}
    candidate = plan()
    first = auth.persist(candidate, store, key_id="c02-test", authority_key=KEY)
    candidate["changes"][0]["fare_difference_minor"] = 999
    assert store["plan-1"] == first
    with pytest.raises(ValueError, match="IMMUTABLE"):
        auth.persist(candidate, store, key_id="c02-test", authority_key=KEY)
