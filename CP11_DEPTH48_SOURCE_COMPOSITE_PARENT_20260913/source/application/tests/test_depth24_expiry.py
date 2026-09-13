import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
import pytest
from sqlalchemy import select
from go_hotel.autonomy.durable import db_now_ms, digest
from go_hotel.db.session import SessionLocal, engine
from go_hotel.db.models import (
    VerticalPaymentDeadlineRow as Deadline, OmnichannelPaymentIntentRow as Intent,
    JourneyRecoveryEvidenceChainRow as Evidence, OmnichannelMoneyMovementRow as Movement,
    VerticalCapacityClaimRow as Claim,
)
from go_hotel.services import vertical_reservation_expiry as expiry
from go_hotel.services.omnichannel_payment import omnichannel_payment_service as payments
from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service as sources
from test_depth23_capacity import rail_quote, attr_quote, order, ledger, cancel, rail, attr, bridge


def pending(vertical, date='2026-09-15'):
    return order(vertical, rail_quote(date=date) if vertical == 'RAIL' else attr_quote(date=date))


def age(vertical, oid):
    with SessionLocal.begin() as s:
        row = s.get(Deadline, (vertical, oid))
        row.expires_ms = db_now_ms(s) - 1
        row.created_ms = row.expires_ms - expiry.HOLD_MS
        row.terms_hash = digest(expiry.terms(row))


def get(vertical, oid):
    return rail.order('owner', oid) if vertical == 'RAIL' else attr.get('owner', oid)


def intent(vertical, oid):
    if not sources.latest(vertical, oid):
        sources.decide(vertical, oid, [{'source_id': 'expiry-test', 'source_type': 'RAIL_OPERATOR_OFFICIAL',
            'authorized': True, 'available': True, 'evidence_reference': 'isolated://expiry'}])
    return payments.create_intent({'business_type': vertical + '_ORDER', 'business_id': oid,
        'channel_priority': ['LOCAL_MARKET']}, 'expiry-payment:' + oid, 'owner')


@pytest.mark.parametrize('vertical', ['RAIL', 'ATTRACTION'])
def test_new_deadline_is_frozen_and_legacy_has_none(vertical):
    o = pending(vertical); oid = o['order_id']
    with SessionLocal() as s:
        row = s.get(Deadline, (vertical, oid))
        assert row.expires_ms - row.created_ms == 900000
        assert row.terms_hash == digest(expiry.terms(row))
        assert o['payment_deadline_ms'] == row.expires_ms
    assert get(vertical, oid)['payment_deadline_ms'] == o['payment_deadline_ms']
    assert expiry.expire_one(vertical, oid) == 'NOT_DUE' and ledger() == 2
    with SessionLocal.begin() as s:s.delete(s.get(Deadline, (vertical, oid)))
    assert get(vertical, oid)['payment_deadline_ms'] is None
    assert expiry.expire_due()['scanned'] == 0 and ledger() == 2


@pytest.mark.parametrize('vertical', ['RAIL', 'ATTRACTION'])
def test_expiration_releases_once_with_native_evidence(vertical):
    oid = pending(vertical)['order_id']; age(vertical, oid)
    assert expiry.expire_due()['expired'] == 1
    o = get(vertical, oid)
    assert o['status'] == 'CANCELLED' and o['unpaid_reservation_state'] == 'EXPIRED'
    events = [e for e in o['evidence'] if e['kind'] == 'UNPAID_RESERVATION_EXPIRED']
    assert len(events) == 1 and events[0]['payload']['unpaid'] is True
    assert events[0]['payload']['payment_deadline_ms'] == o['payment_deadline_ms']
    assert expiry.expire_due()['scanned'] == 0 and ledger() == 0
    assert expiry.expire_one(vertical, oid) == 'UNCHANGED'
    with pytest.raises(ValueError, match='NOT_PAYABLE'):intent(vertical, oid)
    with SessionLocal() as s:
        assert not list(s.scalars(select(Intent))) and not list(s.scalars(select(Movement)))


@pytest.mark.parametrize('vertical', ['RAIL', 'ATTRACTION'])
def test_due_payment_rejected_before_worker_runs(vertical):
    oid = pending(vertical)['order_id']; age(vertical, oid)
    with pytest.raises(ValueError, match='EXPIRED_NOT_PAYABLE'):intent(vertical, oid)
    assert get(vertical, oid)['status'] == 'PAYMENT_PENDING' and ledger() == 2
    assert expiry.expire_due()['expired'] == 1 and ledger() == 0


def test_exact_deadline_uses_database_time(monkeypatch):
    o = pending('RAIL'); oid = o['order_id']
    monkeypatch.setattr(expiry, 'db_now_ms', lambda s: o['payment_deadline_ms'])
    with pytest.raises(ValueError, match='EXPIRED_NOT_PAYABLE'):intent('RAIL', oid)
    assert expiry.expire_one('RAIL', oid) == 'EXPIRED'


@pytest.mark.parametrize('vertical', ['RAIL', 'ATTRACTION'])
@pytest.mark.parametrize('state', ['REQUIRES_CHANNEL_SELECTION', 'UNKNOWN_EXTERNAL_STATE', 'FAILED'])
def test_any_started_payment_retains_capacity(vertical, state):
    oid = pending(vertical)['order_id']; i = intent(vertical, oid); age(vertical, oid)
    with SessionLocal.begin() as s:s.get(Intent, i['payment_intent_id']).state = state
    assert expiry.expire_due()['scanned'] == 0 and ledger() == 2
    assert get(vertical, oid)['unpaid_reservation_state'] == 'PAYMENT_STARTED'
    with pytest.raises(ValueError, match='PAYMENT_ALREADY_STARTED'):cancel(vertical, oid)
    assert intent(vertical, oid)['payment_intent_id'] == i['payment_intent_id']


@pytest.mark.parametrize('vertical', ['RAIL', 'ATTRACTION'])
def test_manual_cancel_finalizes_deadline(vertical):
    oid = pending(vertical)['order_id']; age(vertical, oid)
    first = cancel(vertical, oid)
    assert first['unpaid_reservation_state'] == 'CANCELLED'
    assert first == cancel(vertical, oid)
    assert expiry.expire_due()['scanned'] == 0 and ledger() == 0


@pytest.mark.parametrize('vertical', ['RAIL', 'ATTRACTION'])
def test_two_expiry_workers_release_once(vertical):
    oid = pending(vertical)['order_id']; age(vertical, oid)
    ready = Barrier(2)
    def expire():ready.wait(10); return expiry.expire_one(vertical, oid)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result() for f in [pool.submit(expire), pool.submit(expire)]]
    assert sorted(results) == ['EXPIRED', 'UNCHANGED'] and ledger() == 0


def test_payment_root_wins_before_sweep_and_capture_resumes(monkeypatch):
    oid = pending('RAIL')['order_id']; entered = Event(); finish = Event()
    original = payments.select_channel
    def pause(*a, **kw):entered.set(); assert finish.wait(10); return original(*a, **kw)
    monkeypatch.setattr(payments, 'select_channel', pause)
    with ThreadPoolExecutor(max_workers=2) as pool:
        f = pool.submit(bridge.checkout_contract, 'RAIL', oid, 'owner', 'isolated', 'isolated://expiry-race')
        try:
            assert entered.wait(10); age('RAIL', oid)
            assert expiry.expire_due()['scanned'] == 0 and ledger() == 2
        finally:finish.set()
        assert f.result()['capture_id']
    with SessionLocal() as s:
        assert len(list(s.scalars(select(Movement).where(Movement.movement_type == 'CAPTURE')))) == 1


def test_expiry_wins_order_lock_against_payment(monkeypatch):
    oid = pending('RAIL')['order_id']; age('RAIL', oid)
    from go_hotel.services import vertical_capacity as cap
    entered = Event(); finish = Event(); original = cap.release_all_in
    def pause(*a, **kw):entered.set(); assert finish.wait(10); return original(*a, **kw)
    monkeypatch.setattr(cap, 'release_all_in', pause)
    with ThreadPoolExecutor(max_workers=2) as pool:
        expired = pool.submit(expiry.expire_one, 'RAIL', oid)
        assert entered.wait(10)
        payment = pool.submit(intent, 'RAIL', oid)
        finish.set()
        assert expired.result() == 'EXPIRED'
        with pytest.raises(ValueError, match='NOT_PAYABLE'):payment.result()
    assert ledger() == 0


@pytest.mark.parametrize('commit_first', [False, True])
def test_expiry_recovers_from_actual_process_exit(commit_first):
    oid = pending('RAIL')['order_id']; age('RAIL', oid)
    code = '''import os
from go_hotel.services import vertical_reservation_expiry as expiry
if os.environ['COMMIT_FIRST']=='False':
 from go_hotel.services import rc20_vertical_evidence as evidence
 evidence.append_vertical_evidence=lambda *a,**kw:os._exit(74)
expiry.expire_one('RAIL',os.environ['ORDER_ID'])
os._exit(74)
'''
    env = {**os.environ, 'DATABASE_URL': str(engine.url), 'PYTHONPATH': os.path.abspath('src'),
        'ORDER_ID': oid, 'COMMIT_FIRST': str(commit_first)}
    p = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, timeout=30)
    assert p.returncode == 74, p.stderr.decode()
    assert ledger() == (0 if commit_first else 2)
    assert expiry.expire_one('RAIL', oid) == ('UNCHANGED' if commit_first else 'EXPIRED')
    assert ledger() == 0
    assert len([e for e in get('RAIL', oid)['evidence'] if e['kind']=='UNPAID_RESERVATION_EXPIRED']) == 1


def test_broken_deadline_is_quarantined_without_starving_good_order():
    bad = pending('RAIL')['order_id']; good = pending('ATTRACTION')['order_id']
    age('RAIL', bad); age('ATTRACTION', good)
    with SessionLocal.begin() as s:s.get(Deadline, ('RAIL', bad)).expires_ms -= 1
    result = expiry.expire_due()
    assert result['review'] == 1 and result['expired'] == 1 and not result['errors']
    assert ledger() == 2 and expiry.expire_due()['scanned'] == 0
    with pytest.raises(ValueError, match='INTEGRITY_INVALID'):intent('RAIL', bad)


def test_missing_claim_is_not_reported_as_successful_release():
    oid = pending('RAIL')['order_id']; age('RAIL', oid)
    with SessionLocal.begin() as s:s.delete(s.get(Claim, ('RAIL', oid, 'ORIGINAL')))
    assert expiry.expire_one('RAIL', oid) == 'REVIEW'
    assert get('RAIL', oid)['status'] == 'PAYMENT_PENDING'


def test_rail_checkout_does_not_fabricate_authorized_state_on_pre_root_failure(monkeypatch):
    oid = pending('RAIL')['order_id']
    def fail(*a, **kw):raise RuntimeError('before_payment_root')
    monkeypatch.setattr(bridge, 'checkout_contract', fail)
    with pytest.raises(RuntimeError):rail.checkout('owner', oid, 'isolated')
    assert get('RAIL', oid)['status'] == 'PAYMENT_PENDING'
    age('RAIL', oid)
    assert expiry.expire_due()['expired'] == 1 and ledger() == 0


def test_one_shot_worker_runs_against_durable_database():
    oid = pending('ATTRACTION')['order_id']; age('ATTRACTION', oid)
    env = {**os.environ, 'DATABASE_URL': str(engine.url), 'PYTHONPATH': os.path.abspath('src')}
    p = subprocess.run([sys.executable, '-m', 'go_hotel.workers.vertical_expiry_worker', '--once'],
        env=env, capture_output=True, timeout=30)
    assert p.returncode == 0, p.stderr.decode()
    assert json.loads(p.stdout)['expired'] == 1 and ledger() == 0


def test_worker_rechecks_existing_intent_even_if_deadline_is_open():
    oid = pending('RAIL')['order_id']; intent('RAIL', oid); age('RAIL', oid)
    with SessionLocal.begin() as s:s.get(Deadline, ('RAIL', oid)).state = 'OPEN'
    result = expiry.expire_due()
    assert result['payment_started'] == 1 and not result['expired'] and ledger() == 2


def test_failed_expiry_rolls_back_and_does_not_block_next_candidate(monkeypatch):
    bad = pending('RAIL')['order_id']; good = pending('ATTRACTION')['order_id']
    age('RAIL', bad); age('ATTRACTION', good)
    from go_hotel.services import rc20_vertical_evidence as evidence
    original = evidence.append_vertical_evidence
    def fail_one(s, vertical, *args, **kwargs):
        if vertical == 'RAIL':raise RuntimeError('temporary_write_failure')
        return original(s, vertical, *args, **kwargs)
    monkeypatch.setattr(evidence, 'append_vertical_evidence', fail_one)
    result = expiry.expire_due()
    assert result['expired'] == 1 and len(result['errors']) == 1 and ledger() == 2
    assert get('RAIL', bad)['unpaid_reservation_state'] == 'OPEN'
    monkeypatch.setattr(evidence, 'append_vertical_evidence', original)
    assert expiry.expire_due()['expired'] == 1 and ledger() == 0


def test_worker_batch_is_bounded_and_restarts_from_unfinished_orders():
    for vertical in ('RAIL', 'ATTRACTION'):age(vertical, pending(vertical)['order_id'])
    assert expiry.expire_due(limit=1)['expired'] == 1 and ledger() == 2
    assert expiry.expire_due(limit=1)['expired'] == 1 and ledger() == 0
    for invalid in (0, -1, 1001, True):
        with pytest.raises(ValueError, match='BATCH_LIMIT_INVALID'):expiry.expire_due(invalid)


def test_application_lifespan_starts_expiry_worker():
    import time
    from fastapi.testclient import TestClient
    from go_hotel.main import app
    oid = pending('RAIL')['order_id']; age('RAIL', oid)
    with TestClient(app):
        deadline = time.monotonic() + 5
        while get('RAIL', oid)['status'] != 'CANCELLED' and time.monotonic() < deadline:
            time.sleep(0.02)
        assert get('RAIL', oid)['unpaid_reservation_state'] == 'EXPIRED' and ledger() == 0


@pytest.mark.no_db
def test_migration_preserves_all_deadline_history(tmp_path, monkeypatch):
    import sqlite3
    from alembic import command
    from alembic.config import Config
    from go_hotel.core.config import settings
    db = tmp_path / 'deadline.db'; url = 'sqlite+pysqlite:///' + str(db)
    monkeypatch.setattr(settings, 'database_url', url)
    cfg = Config('alembic.ini'); cfg.set_main_option('sqlalchemy.url', url)
    command.stamp(cfg, '0130_vertical_capacity'); command.upgrade(cfg, '0131_vertical_payment_deadline')
    command.downgrade(cfg, '0130_vertical_capacity'); command.upgrade(cfg, '0131_vertical_payment_deadline')
    with sqlite3.connect(db) as s:
        s.execute("INSERT INTO vertical_payment_deadline VALUES ('RAIL','o','a',0,900000,'hash','EXPIRED',900000,'expired')")
    with pytest.raises(RuntimeError, match='DATA_PRESENT'):command.downgrade(cfg, '0130_vertical_capacity')
    with sqlite3.connect(db) as s:assert s.execute('SELECT state FROM vertical_payment_deadline').fetchone()[0] == 'EXPIRED'
