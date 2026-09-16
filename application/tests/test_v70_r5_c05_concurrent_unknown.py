"""V70-R5-C05-03: concurrent UNKNOWN episode opening is serialized atomically."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from tests.test_depth33_mobility_refund_consent import booked


def test_concurrent_unknown_open_has_exactly_one_committed_winner():
    svc, owner, oid = booked("RIDE")
    contenders = 10
    barrier = Barrier(contenders)

    def open_episode(index):
        reference = f"isolated://race-{index}"
        barrier.wait()
        try:
            result = svc.admin_external_state(
                oid, "UNKNOWN_EXTERNAL_STATE", reference, f"ops-{index}"
            )
            return ("PASS", reference, result["status"])
        except ValueError as error:
            return ("FAIL", reference, str(error))

    with ThreadPoolExecutor(max_workers=contenders) as pool:
        results = list(pool.map(open_episode, range(contenders)))

    winners = [result for result in results if result[0] == "PASS"]
    losers = [result for result in results if result[0] == "FAIL"]
    assert len(winners) == 1
    assert winners[0][2] == "UNKNOWN_EXTERNAL_STATE"
    assert len(losers) == contenders - 1
    assert {result[2] for result in losers} == {"RIDE_UNKNOWN_EPISODE_ALREADY_OPEN"}

    projection = svc.get(owner, oid)
    unknown_events = [
        event for event in projection["evidence"]
        if event["kind"] == "EXTERNAL_STATE_UNKNOWN"
    ]
    assert projection["status"] == "UNKNOWN_EXTERNAL_STATE"
    assert len(unknown_events) == 1
    assert unknown_events[0]["payload"]["evidence_reference"] == winners[0][1]


def test_open_loser_is_fail_closed_and_replay_does_not_append_evidence():
    svc, owner, oid = booked("RIDE")
    winner = "isolated://winner"
    svc.admin_external_state(oid, "UNKNOWN_EXTERNAL_STATE", winner, "ops-winner")
    before = svc.get(owner, oid)

    for reference in (winner, "isolated://competing"):
        try:
            svc.admin_external_state(
                oid, "UNKNOWN_EXTERNAL_STATE", reference, "ops-loser"
            )
        except ValueError as error:
            assert str(error) == "RIDE_UNKNOWN_EPISODE_ALREADY_OPEN"
        else:
            raise AssertionError("concurrent/replayed opener must lose")

    assert svc.get(owner, oid) == before
