from datetime import timedelta

import pytest

from go_hotel.services import chain_task_lease as lease


def test_task_view_claimable_rules():
    now = lease._now()
    queued = lease.TaskView("a", "QUEUED", {}, 0, None, None, None, None)
    future_retry = lease.TaskView("b", "RETRY_WAIT", {}, 1, "w", None, now + timedelta(seconds=5), "x")
    expired_retry = lease.TaskView("c", "RETRY_WAIT", {}, 1, "w", None, now - timedelta(seconds=1), "x")
    live = lease.TaskView("d", "LEASED", {}, 1, "w", now + timedelta(seconds=5), None, None)
    expired = lease.TaskView("e", "LEASED", {}, 1, "w", now - timedelta(seconds=1), None, None)
    acked = lease.TaskView("f", "ACKED", {}, 1, "w", None, None, None)
    assert queued.claimable(now)
    assert not future_retry.claimable(now)
    assert expired_retry.claimable(now)
    assert not live.claimable(now)
    assert expired.claimable(now)
    assert not acked.claimable(now)


def test_fold_preserves_payload_across_retry_and_ack():
    class Row:
        def __init__(self, state, evidence):
            self.event_type = lease.EVENT_PREFIX + state
            self.evidence_json = evidence

    rows = [
        Row("QUEUED", {"task_id": "t", "payload": {"hotel": "H"}, "attempt": 0}),
        Row("LEASED", {"task_id": "t", "payload": {"hotel": "H"}, "attempt": 1, "worker_id": "w", "lease_until": "2026-09-08T00:01:00+00:00"}),
        Row("RETRY_WAIT", {"task_id": "t", "payload": {"hotel": "H"}, "attempt": 1, "worker_id": "w", "retry_at": "2026-09-08T00:02:00+00:00", "error": "timeout"}),
    ]
    task = lease._fold(rows)["t"]
    assert task.payload == {"hotel": "H"}
    assert task.attempt == 1
    assert task.state == "RETRY_WAIT"
    assert task.last_error == "timeout"


def test_lock_key_is_stable_signed_bigint():
    a = lease._lock_key("chain_property_abc")
    b = lease._lock_key("chain_property_abc")
    assert a == b
    assert -(2**63) <= a < 2**63
