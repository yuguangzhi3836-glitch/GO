"""Force both callback sessions to observe no receipt before processing."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import hmac
import json
from threading import Barrier, local

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError

from go_hotel.db.models import (
    OmnichannelPaymentAttemptRow as Attempt, OmnichannelPaymentIntentRow as Intent,
    OmnichannelWebhookReceiptRow as Receipt, OmnichannelLedgerEntryRow as Ledger,
)
from go_hotel.db.session import SessionLocal, engine
from go_hotel.services.omnichannel_payment import omnichannel_payment_service as svc, digest


def attempt(key):
    intent = svc.create_intent({"business_type": "SUBSCRIPTION_INVOICE", "business_id": key,
        "payee_id": "GO", "operation": "PAY", "amount_minor": 1200, "currency": "CNY",
        "channel_priority": ["ALIPAY"]}, key, "depth-payer")
    svc.select_channel(intent["payment_intent_id"], "ALIPAY", "depth-payer")
    return svc.execute(intent["payment_intent_id"])


def payload(attempt_id, **changes):
    return {"external_event_id": "depth-race-event", "payment_attempt_id": attempt_id,
            "external_operation_id": "depth-race-operation", "state": "SUCCEEDED",
            "occurred_at": datetime.now(timezone.utc).isoformat(), **changes}


def invoke(body):
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"))
    signature = hmac.new(b"isolated-callback-race", raw.encode(), hashlib.sha256).hexdigest()
    return svc.webhook("ALIPAY", body, signature)


def concurrent_callbacks(bodies):
    barrier = Barrier(2)
    thread = local()

    def first_receipt_read(conn, cursor, statement, parameters, context, executemany):
        if (statement.startswith("SELECT omnichannel_webhook_receipt.")
                and "external_event_id =" in statement and not getattr(thread, "observed", False)):
            thread.observed = True
            barrier.wait(timeout=10)

    def call(body):
        try:
            return invoke(body)
        except ValueError as error:
            return str(error)

    event.listen(engine, "after_cursor_execute", first_receipt_read)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(call, bodies))
    finally:
        event.remove(engine, "after_cursor_execute", first_receipt_read)


@pytest.mark.parametrize("state", ["SUCCEEDED", "FAILED", "PENDING"])
def test_simultaneous_identical_callbacks_have_one_transition_and_one_safe_duplicate(monkeypatch, state):
    monkeypatch.setenv("GO_PAYMENT_WEBHOOK_KEY_ALIPAY", "isolated-callback-race")
    a = attempt("depth-identical")
    body = payload(a["payment_attempt_id"], state=state)
    transitions = []
    original = svc._transition

    def record_transition(*args):
        transitions.append(args[1].payment_attempt_id)
        return original(*args)

    monkeypatch.setattr(svc, "_transition", record_transition)
    results = concurrent_callbacks([body, body])
    assert all(isinstance(result, dict) for result in results)
    assert sorted(result["duplicate"] for result in results) == [False, True]
    assert len({result["receipt"]["webhook_receipt_id"] for result in results}) == 1
    assert transitions == [a["payment_attempt_id"]]
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Receipt)) == 1
        expected = "UNKNOWN_EXTERNAL_STATE" if state == "PENDING" else state
        assert session.get(Intent, a["payment_intent_id"]).state == expected
        assert session.get(Attempt, a["payment_attempt_id"]).state == expected
        assert session.scalar(select(func.count()).select_from(Ledger)) == 0


@pytest.mark.parametrize("conflict", ["state", "operation", "other_attempt"])
def test_simultaneous_reused_event_with_different_payload_rejects_before_second_transition(monkeypatch, conflict):
    monkeypatch.setenv("GO_PAYMENT_WEBHOOK_KEY_ALIPAY", "isolated-callback-race")
    first = attempt("depth-first")
    second = attempt("depth-second")
    body = payload(first["payment_attempt_id"])
    changed = {**body, **{"state": {"state": "FAILED"},
        "operation": {"external_operation_id": "different-operation"},
        "other_attempt": {"payment_attempt_id": second["payment_attempt_id"]}}[conflict]}
    transitions = []
    original = svc._transition

    def record_transition(*args):
        transitions.append(args[1].payment_attempt_id)
        return original(*args)

    monkeypatch.setattr(svc, "_transition", record_transition)
    results = concurrent_callbacks([body, changed])
    assert results.count("PAYMENT_CALLBACK_REPLAY_PAYLOAD_MISMATCH") == 1
    winners = [(index, result) for index, result in enumerate(results) if isinstance(result, dict)]
    assert len(winners) == 1 and winners[0][1]["duplicate"] is False
    winner = [body, changed][winners[0][0]]
    assert transitions == [winner["payment_attempt_id"]]
    with SessionLocal() as session:
        receipt = session.scalar(select(Receipt))
        assert session.scalar(select(func.count()).select_from(Receipt)) == 1
        assert receipt.payload_hash == digest(winner)
        assert receipt.payment_attempt_id == winner["payment_attempt_id"]
        for a in [first, second]:
            expected = winner["state"] if a["payment_attempt_id"] == winner["payment_attempt_id"] else "CONTRACT_READY_NOT_EXTERNAL"
            assert session.get(Attempt, a["payment_attempt_id"]).state == expected
            assert session.get(Intent, a["payment_intent_id"]).state == expected
        assert session.scalar(select(func.count()).select_from(Ledger)) == 0


def test_unrelated_operation_uniqueness_error_is_not_reported_as_callback_duplicate(monkeypatch):
    monkeypatch.setenv("GO_PAYMENT_WEBHOOK_KEY_ALIPAY", "isolated-callback-race")
    first = attempt("depth-first")
    second = attempt("depth-second")
    original = payload(first["payment_attempt_id"])
    invoke(original)
    unrelated = {**original, "external_event_id": "another-event", "payment_attempt_id": second["payment_attempt_id"]}
    with pytest.raises(IntegrityError):
        invoke(unrelated)
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Receipt)) == 1
        assert session.get(Attempt, second["payment_attempt_id"]).state == "CONTRACT_READY_NOT_EXTERNAL"
        assert session.get(Intent, second["payment_intent_id"]).state == "CONTRACT_READY_NOT_EXTERNAL"
    # The rolled-back event claim can later be used with a valid unique operation.
    assert invoke({**unrelated, "external_operation_id": "valid-second-operation"})["duplicate"] is False


def test_different_events_competing_for_one_attempt_cannot_overwrite_terminal_state(monkeypatch):
    monkeypatch.setenv("GO_PAYMENT_WEBHOOK_KEY_ALIPAY", "isolated-callback-race")
    a = attempt("depth-terminal")
    original = payload(a["payment_attempt_id"])
    conflicting = {**original, "external_event_id": "second-terminal-event", "state": "FAILED"}
    results = concurrent_callbacks([original, conflicting])
    assert results.count("PAYMENT_TERMINAL_STATE_IMMUTABLE") == 1
    winner = next(result for result in results if isinstance(result, dict))
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Receipt)) == 1
        assert session.get(Intent, a["payment_intent_id"]).state == winner["intent"]["state"]
        assert session.get(Attempt, a["payment_attempt_id"]).state == winner["intent"]["state"]


def test_invalid_attempt_rolls_back_atomic_event_claim(monkeypatch):
    monkeypatch.setenv("GO_PAYMENT_WEBHOOK_KEY_ALIPAY", "isolated-callback-race")
    body = payload("missing-attempt")
    with pytest.raises(ValueError, match="PAYMENT_ATTEMPT_CHANNEL_MISMATCH"):
        invoke(body)
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Receipt)) == 0
    a = attempt("depth-valid-after-rollback")
    assert invoke({**body, "payment_attempt_id": a["payment_attempt_id"]})["duplicate"] is False
