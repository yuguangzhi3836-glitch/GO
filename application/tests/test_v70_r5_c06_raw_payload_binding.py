"""V70-R5-C06-02: internal imports are bound to supplied immutable raw bytes."""
from copy import deepcopy
from hashlib import sha256

import pytest

from go_hotel.attractions.policy_registry import Registry
from tests.test_c06_internal_policy_registry import policy


def bound_policy(raw=b'{"supplier":"fixture","version":"1.0"}', **changes):
    value = policy(raw_payload_sha256=sha256(raw).hexdigest())
    value.update(changes)
    return value, raw


def test_exact_raw_payload_digest_is_admitted_and_replay_is_idempotent():
    registry = Registry()
    item = bound_policy()
    assert registry.import_bound_batch([item]) == ["ACCEPTED"]
    before = deepcopy(registry.current("fixture-supplier", "p1", "o1"))
    assert registry.import_bound_batch([item]) == ["IDEMPOTENT_REPLAY"]
    assert registry.current("fixture-supplier", "p1", "o1") == before


def test_raw_payload_hash_mismatch_rejects_without_policy_or_audit_mutation():
    registry = Registry()
    claimed, _ = bound_policy()
    before_audit = deepcopy(registry.audit)
    with pytest.raises(ValueError, match="ATTRACTION_POLICY_RAW_HASH_MISMATCH"):
        registry.import_bound_batch([(claimed, b'{"tampered":true}')])
    assert registry.current("fixture-supplier", "p1", "o1") is None
    assert registry.audit == before_audit


@pytest.mark.parametrize("entry", [
    None,
    {},
    (policy(), "not-bytes"),
    (policy(), bytearray(b"mutable")),
    (policy(),),
])
def test_raw_import_requires_policy_and_immutable_bytes(entry):
    registry = Registry()
    with pytest.raises(ValueError, match="ATTRACTION_POLICY_RAW_PAYLOAD_BYTES_REQUIRED"):
        registry.import_bound_batch([entry])
    assert registry.current("fixture-supplier", "p1", "o1") is None
    assert registry.audit == []


def test_bound_batch_is_atomic_when_later_payload_mismatches():
    registry = Registry()
    first = bound_policy(b"first")
    second_policy, _ = bound_policy(b"second", product_id="p2")
    with pytest.raises(ValueError, match="ATTRACTION_POLICY_RAW_HASH_MISMATCH"):
        registry.import_bound_batch([first, (second_policy, b"changed")])
    assert registry.current("fixture-supplier", "p1", "o1") is None
    assert registry.current("fixture-supplier", "p2", "o1") is None
    assert registry.audit == []


def test_non_batch_container_fails_closed():
    with pytest.raises(ValueError, match="ATTRACTION_POLICY_RAW_BATCH_INVALID"):
        Registry().import_bound_batch(None)
