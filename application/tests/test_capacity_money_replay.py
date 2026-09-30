"""Committed RIDE replay has no write effects; misses keep money locking."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event

import pytest
from sqlalchemy import event, select

from go_hotel.db.session import engine, SessionLocal
from go_hotel.db.models import OmnichannelMoneyMovementRow as Movement, OmnichannelLedgerEntryRow as Ledger, OmnichannelPaymentIntentRow as Intent
from go_hotel.mobility.ride.service import ride_service
from go_hotel.services.omnichannel_payment import omnichannel_payment_service as pay
from go_hotel.services.unified_money_movement import unified_money_movement_service as money
from ride_cancellation_fixture import create_ride


def prepared():
    oid = create_ride(ride_service, 'replay-owner', {'offer_id': 'ride_standard',
        'pickup': 'ISOLATED_A', 'dropoff': 'ISOLATED_B',
        'pickup_at': (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()})['order_id']
    intent = pay.create_intent({'business_type': 'RIDE_ORDER', 'business_id': oid,
        'channel_priority': ['LOCAL_MARKET']}, 'intent:' + oid, 'replay-owner')
    iid = intent['payment_intent_id']
    pay.select_channel(iid, 'LOCAL_MARKET', 'replay-owner')
    attempt = pay.execute(iid)
    pay.simulate_result(attempt['payment_attempt_id'], 'SUCCEEDED')
    auth = money.create(iid, {'movement_type': 'AUTHORIZATION', 'mode': 'CONTRACT_SIMULATOR',
        'evidence': ['isolated://replay']}, 'auth:' + oid, 'test')
    body = {'movement_type': 'CAPTURE', 'parent_movement_id': auth['money_movement_id'],
        'mode': 'CONTRACT_SIMULATOR', 'evidence': ['isolated://replay']}
    return iid, body, 'capture:' + oid


def assert_balanced(iid):
    with SessionLocal() as s:
        moves = list(s.scalars(select(Movement).where(Movement.root_payment_intent_id == iid)))
        entries = list(s.scalars(select(Ledger).where(Ledger.payment_intent_id == iid)))
        assert len(moves) == 2 and len(entries) == 2
        assert sum(e.amount_minor * (1 if e.direction == 'DEBIT' else -1) for e in entries) == 0


def original_replay(iid, body, key):
    # Compare with the original persisted replay representation. SQLite drops
    # timezone offsets on storage; a just-created Python row retains them.
    with SessionLocal() as s:
        return money.create_in_session(s, iid, body, key, 'test')


def test_confirmed_replay_one_select_zero_row_locks_no_new_effects(monkeypatch):
    iid, body, key = prepared()
    money.create(iid, body, key, 'test')
    result = original_replay(iid, body, key)
    queries = []
    def observed(conn, cursor, statement, params, context, many):
        if statement.lstrip().upper().startswith('SELECT'):
            queries.append(statement)
    def forbidden(*args):
        pytest.fail('confirmed RIDE replay entered mutation path')
    event.listen(engine, 'before_cursor_execute', observed)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(money, 'create_in_session', forbidden)
            assert money.create(iid, body, key, 'test') == result
    finally:
        event.remove(engine, 'before_cursor_execute', observed)
    assert len(queries) == 1 and 'FOR UPDATE' not in queries[0].upper()
    assert_balanced(iid)


@pytest.mark.parametrize('changes,code', [
    ({'amount_minor': 16801}, 'MONEY_MOVEMENT_IDEMPOTENCY_CONFLICT'),
    ({'amount_minor': True}, 'INTEGER_MOVEMENT_AMOUNT_REQUIRED'),
    ({'parent_movement_id': 'another-parent'}, 'MONEY_MOVEMENT_IDEMPOTENCY_CONFLICT'),
    ({'movement_type': 'AUTHORIZATION'}, 'MONEY_MOVEMENT_IDEMPOTENCY_CONFLICT'),
    ({'mode': 'EXTERNAL_CERTIFIED_FACT'}, 'EXTERNAL_CERTIFIED_FACT_TRUSTED_INGRESS_REQUIRED'),
])
def test_replay_preserves_conflict_and_trusted_ingress_rules(changes, code):
    iid, body, key = prepared()
    money.create(iid, body, key, 'test')
    with pytest.raises(ValueError, match=code):
        money.create(iid, body | changes, key, 'test')
    assert_balanced(iid)


def test_concurrent_replay_and_other_intent_conflict():
    iid, body, key = prepared()
    money.create(iid, body, key, 'test')
    result = original_replay(iid, body, key)
    barrier = Barrier(8)
    def replay(_):
        barrier.wait(10)
        return money.create(iid, body, key, 'test')
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(x == result for x in pool.map(replay, range(8)))
    other, _, _ = prepared()
    with pytest.raises(ValueError, match='MONEY_MOVEMENT_IDEMPOTENCY_CONFLICT'):
        money.create(other, body, key, 'test')
    assert_balanced(iid)


def test_nonconfirmed_replay_retains_original_path(monkeypatch):
    iid, body, key = prepared()
    money.create(iid, body | {'mode': 'EXTERNAL_SANDBOX'}, key, 'test')
    pending = original_replay(iid, body, key)
    calls = []
    original = money.create_in_session
    def tracked(*args):
        calls.append(True)
        return original(*args)
    with monkeypatch.context() as patch:
        patch.setattr(money, 'create_in_session', tracked)
        assert money.create(iid, body, key, 'test') == pending
    assert calls == [True]


def test_rental_scope_cannot_be_bypassed_by_existing_receipt():
    iid, body, key = prepared()
    money.create(iid, body, key, 'test')
    # Deliberately corrupt the business discriminator to test fail-closed scope.
    with SessionLocal.begin() as s:
        s.get(Intent, iid).business_type = 'RENTAL_DEPOSIT'
    with pytest.raises(ValueError, match='RENTAL_DEPOSIT_'):
        money.create(iid, body, key, 'test')


@pytest.mark.skipif(engine.dialect.name != 'postgresql', reason='PostgreSQL MVCC and real row locks required')
def test_uncommitted_capture_miss_rechecks_after_original_intent_lock(monkeypatch):
    iid, body, key = prepared()
    pending, missed, release = Event(), Event(), Event()
    original = money._confirmed_ride_replay
    def tracked(*args):
        result = original(*args)
        if result is None:
            missed.set()
        return result
    def writer():
        with SessionLocal() as s:
            result = money.create_in_session(s, iid, body, key, 'test')
            pending.set()
            assert release.wait(15)
            s.commit()
            return result
    with monkeypatch.context() as patch:
        patch.setattr(money, '_confirmed_ride_replay', tracked)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(writer)
            assert pending.wait(15)
            second = pool.submit(money.create, iid, body, key, 'test')
            try:
                assert missed.wait(10)
                assert not second.done(), 'replay did not wait for the writer transaction'
            finally:
                release.set()
            assert first.result(15) == second.result(15)
    assert_balanced(iid)
