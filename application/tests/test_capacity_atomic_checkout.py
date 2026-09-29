"""The local payment root is atomic; money transitions remain recoverable."""
import multiprocessing
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import event, select

from go_hotel.db.session import engine, SessionLocal
from go_hotel.db.models import (OmnichannelPaymentIntentRow as Intent,
    PaymentOrderRootRow as Root, VerticalPaymentDeadlineRow as Deadline,
    OmnichannelMoneyMovementRow as Movement, OmnichannelLedgerEntryRow as Ledger)
from go_hotel.mobility.ride.service import ride_service
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge as bridge
from go_hotel.services import vertical_reservation_expiry as expiry
from ride_cancellation_fixture import create_ride


def order():
    return create_ride(ride_service, 'atomic-checkout', {'offer_id': 'ride_standard',
        'pickup': 'ISOLATED_A', 'dropoff': 'ISOLATED_B',
        'pickup_at': (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
        'passengers': [{'full_name': 'SYNTHETIC'}]})['order_id']


def checkout(oid):
    return bridge.checkout_contract('RIDE', oid, 'atomic-checkout', 'ride-engineering-source', 'isolated://atomic-checkout')


def root_facts(oid):
    with SessionLocal() as s:
        roots = list(s.scalars(select(Root).where(Root.business_id == oid)))
        intents = list(s.scalars(select(Intent).where(Intent.business_id == oid)))
        deadline = s.get(Deadline, ('RIDE', oid))
        return len(roots), len(intents), deadline.state


def test_preparation_uses_one_commit_before_payment_execution(monkeypatch):
    oid = order()
    commits = []
    def observed(conn):
        commits.append(True)
    def stop(iid, owner):
        assert len(commits) == 1
        assert root_facts(oid) == (1, 1, 'PAYMENT_STARTED')
        raise RuntimeError('PAYMENT_BOUNDARY')
    event.listen(engine, 'commit', observed)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(bridge, '_confirm_contract_payment', stop)
            with pytest.raises(RuntimeError, match='PAYMENT_BOUNDARY'):
                checkout(oid)
    finally:
        event.remove(engine, 'commit', observed)
    result = checkout(oid)
    assert checkout(oid) == result


def test_final_guard_failure_rolls_back_entire_root(monkeypatch):
    oid = order()
    def failed(*args):
        raise ValueError('FINAL_GUARD_FAILURE')
    with monkeypatch.context() as patch:
        patch.setattr(expiry, 'confirm_payment_started_in', failed)
        with pytest.raises(ValueError, match='FINAL_GUARD_FAILURE'):
            checkout(oid)
    assert root_facts(oid) == (0, 0, 'OPEN')
    checkout(oid)
    assert root_facts(oid) == (1, 1, 'PAYMENT_STARTED')


def _crash_checkout(oid, committed):
    import os
    def crash(*args):
        os._exit(87)
    if committed:
        bridge._confirm_contract_payment = crash
    else:
        expiry.confirm_payment_started_in = crash
    checkout(oid)


@pytest.mark.parametrize('committed', [False, True])
def test_real_process_exit_before_and_after_root_commit(committed):
    oid = order()
    child = multiprocessing.get_context('spawn').Process(target=_crash_checkout, args=(oid, committed))
    child.start(); child.join(45)
    if child.is_alive():
        child.kill(); child.join()
        pytest.fail('checkout crash probe timed out')
    assert child.exitcode == 87
    assert root_facts(oid) == ((1, 1, 'PAYMENT_STARTED') if committed else (0, 0, 'OPEN'))
    result = checkout(oid)
    assert checkout(oid) == result
    with SessionLocal() as s:
        moves = list(s.scalars(select(Movement).where(Movement.root_payment_intent_id == result['payment_intent_id'])))
        ledger = list(s.scalars(select(Ledger).where(Ledger.payment_intent_id == result['payment_intent_id'])))
        assert len(moves) == 2 and len(ledger) == 2
        assert sum(x.amount_minor * (1 if x.direction == 'DEBIT' else -1) for x in ledger) == 0


def test_concurrent_checkout_has_one_root_and_capture():
    oid = order()
    barrier = Barrier(4)
    def run(_):
        barrier.wait(10)
        return checkout(oid)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, range(4)))
    assert all(result == results[0] for result in results)
    assert root_facts(oid) == (1, 1, 'PAYMENT_STARTED')
