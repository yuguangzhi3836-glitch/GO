import copy
import pytest
from go_hotel.flight import coupon_authority as auth

KEY = b"r6-test-only"
KEYS = {"r6": KEY}


def plan():
    return {"plan_hash": "partial-1", "order": {"currency": "CNY"}, "changes": [
        {"passenger_index": 0, "leg_index": 0, "fare_difference_minor": 1000, "change_fee_minor": 0},
        {"passenger_index": 1, "leg_index": 0, "fare_difference_minor": 2000, "change_fee_minor": 0},
        {"passenger_index": 1, "leg_index": 1, "fare_difference_minor": -500, "change_fee_minor": 0},
    ]}


def setup():
    store = {}
    record = auth.persist(plan(), store, key_id="r6", authority_key=KEY)
    consent = {"plan_id": record["plan_id"], "authority_mac": record["authority_mac"],
               "charge_minor": 3000, "credit_minor": 500, "currency": "CNY",
               "negative_fare_treatment": "CREDIT_NOT_NETTED", "confirmed": True}
    allocations = [{"source_id": "cash-1", "amount_minor": 3000}]
    return store, record, consent, allocations


def call(store, record, consent, allocations, execution, selection, key="idem-1"):
    return auth.authorize_partial_party(
        store, record["plan_id"], consent, allocations, selection,
        idempotency_key=key, execution_store=execution, authority_keys=KEYS)


def test_exact_traveler_segment_subset_is_frozen_and_replay_is_identical():
    store, record, consent, allocations = setup()
    execution = {}
    selection = [{"passenger_index": 1, "leg_index": 1},
                 {"passenger_index": 1, "leg_index": 0}]
    first = call(store, record, consent, allocations, execution, selection)
    second = call(store, record, consent, allocations, execution, list(reversed(selection)))
    assert first == second == execution["idem-1"]
    assert first["selection"] == [{"passenger_index": 1, "leg_index": 0},
                                  {"passenger_index": 1, "leg_index": 1}]


@pytest.mark.parametrize("selection", [
    [{"passenger_index": 2, "leg_index": 0}],
    [{"passenger_index": 1, "leg_index": 0}, {"passenger_index": 1, "leg_index": 0}],
    [{"passenger_index": True, "leg_index": 0}],
    [{"passenger_index": 1}],
])
def test_invalid_or_unbound_selection_fails_with_zero_execution_write(selection):
    store, record, consent, allocations = setup()
    execution = {}
    with pytest.raises(ValueError, match="PARTIAL_SELECTION_INVALID"):
        call(store, record, consent, allocations, execution, selection)
    assert execution == {}


def test_consent_or_allocation_mismatch_fails_before_execution_write():
    store, record, consent, allocations = setup()
    execution = {}
    wrong = copy.deepcopy(consent)
    wrong["credit_minor"] = 0
    with pytest.raises(ValueError, match="CONSENT_INVALID"):
        call(store, record, wrong, allocations, execution,
             [{"passenger_index": 1, "leg_index": 0}])
    assert execution == {}


def test_idempotency_key_cannot_authorize_a_different_traveler_subset():
    store, record, consent, allocations = setup()
    execution = {}
    call(store, record, consent, allocations, execution,
         [{"passenger_index": 0, "leg_index": 0}])
    before = copy.deepcopy(execution)
    with pytest.raises(ValueError, match="IDEMPOTENCY_CONFLICT"):
        call(store, record, consent, allocations, execution,
             [{"passenger_index": 1, "leg_index": 0}])
    assert execution == before
