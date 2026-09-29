"""Facts and successful receipts share one commit; ambiguous outcomes fail closed."""
from datetime import datetime, timedelta, timezone
import multiprocessing
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from go_hotel.api.routes.mobility import rb, RideBook
from go_hotel.db.models import MobilityRideOrderRow as Ride, IdempotencyRow
from go_hotel.db.session import engine, SessionLocal
from go_hotel.mobility.ride.service import ride_service
from go_hotel.repositories.sql import repo
from ride_cancellation_fixture import synthetic_policy, accepted_body


def request():
    body = {'offer_id': 'ride_standard', 'pickup': 'ISOLATED_A', 'dropoff': 'ISOLATED_B',
            'pickup_at': (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
            'passengers': [{'full_name': 'SYNTHETIC'}]}
    return RideBook(**accepted_body(ride_service, body))


def facts(key):
    with SessionLocal() as s:
        orders = list(s.scalars(select(Ride).where(Ride.account_id == key)))
        receipt = s.get(IdempotencyRow, {'operation': 'RIDE_CREATE_ORDER', 'idempotency_key': key})
        return len(orders), None if receipt is None else receipt.response_code


def test_order_receipt_two_commits_replay_and_conflict():
    commits = []
    with synthetic_policy():
        body = request()
        def committed(conn):
            commits.append(True)
        event.listen(engine, 'commit', committed)
        try:
            result = rb(body, SimpleNamespace(user_id='atomic'), 'atomic')
        finally:
            event.remove(engine, 'commit', committed)
        assert len(commits) == 2
        assert facts('atomic') == (1, 200)
        assert rb(body, SimpleNamespace(user_id='atomic'), 'atomic') == result
        with pytest.raises(HTTPException) as caught:
            rb(body.model_copy(update={'dropoff': 'CHANGED'}), SimpleNamespace(user_id='atomic'), 'atomic')
        assert caught.value.status_code == 409
        assert facts('atomic') == (1, 200)


def test_receipt_failure_rolls_back_order_and_releases_claim(monkeypatch):
    def failed(*args, **kwargs):
        raise RuntimeError('RECEIPT_WRITE_FAILURE')
    with synthetic_policy():
        body = request()
        with monkeypatch.context() as patch:
            patch.setattr(repo, 'complete_idempotency_in_session', failed)
            with pytest.raises(RuntimeError, match='RECEIPT_WRITE_FAILURE'):
                rb(body, SimpleNamespace(user_id='atomic'), 'atomic')
        assert facts('atomic') == (0, None)
        rb(body, SimpleNamespace(user_id='atomic'), 'atomic')
        assert facts('atomic') == (1, 200)


@pytest.mark.parametrize('committed', [False, True])
def test_commit_ack_failure_never_releases_claim(monkeypatch, committed):
    original = Session.commit
    def fail(session):
        if committed:
            original(session)
        raise ConnectionError('COMMIT_ACK_LOST')
    with synthetic_policy():
        body = request()
        with monkeypatch.context() as patch:
            patch.setattr(Session, 'commit', fail)
            with pytest.raises(ConnectionError, match='COMMIT_ACK_LOST'):
                rb(body, SimpleNamespace(user_id='atomic'), 'atomic')
        assert facts('atomic') == ((1, 200) if committed else (0, 102))
        if committed:
            assert rb(body, SimpleNamespace(user_id='atomic'), 'atomic')['data']['order_id']
        else:
            with pytest.raises(HTTPException) as caught:
                rb(body, SimpleNamespace(user_id='atomic'), 'atomic')
            assert caught.value.detail['code'] == 'IDEMPOTENCY_IN_PROGRESS'


def _exit_at_commit(body, key, committed):
    import os
    original = Session.commit
    def crash(session):
        session.flush()
        if committed:
            original(session)
        os._exit(86)
    Session.commit = crash
    with synthetic_policy():
        rb(RideBook(**body), SimpleNamespace(user_id=key), key)


@pytest.mark.parametrize('committed', [False, True])
def test_real_process_exit_on_both_sides_of_commit(committed):
    with synthetic_policy():
        body = request()
        child = multiprocessing.get_context('spawn').Process(
            target=_exit_at_commit, args=(body.model_dump(), 'atomic-exit', committed))
        child.start()
        child.join(45)
        if child.is_alive():
            child.kill(); child.join()
            pytest.fail('crash probe timed out')
        assert child.exitcode == 86
        assert facts('atomic-exit') == ((1, 200) if committed else (0, 102))
        if committed:
            rb(body, SimpleNamespace(user_id='atomic-exit'), 'atomic-exit')
            assert facts('atomic-exit') == (1, 200)
        else:
            with pytest.raises(HTTPException) as caught:
                rb(body, SimpleNamespace(user_id='atomic-exit'), 'atomic-exit')
            assert caught.value.status_code == 409
