"""C11: immutable payment requests and signed callback replay boundaries."""
from datetime import datetime, timezone
import hashlib
import hmac
import json

import pytest
from sqlalchemy import func, select

from go_hotel.db.models import OmnichannelPaymentIntentRow as Intent, OmnichannelWebhookReceiptRow as Receipt
from go_hotel.db.session import SessionLocal
from go_hotel.security.service import identity_service
from go_hotel.services.omnichannel_payment import omnichannel_payment_service as svc


def obligation(**changes):
    return {**dict(business_type="SUBSCRIPTION_INVOICE", business_id="invoice-depth",
                payee_id="GO", operation="PAY", amount_minor=69900, currency="CNY",
                channel_priority=["ALIPAY", "VISA"], automatic_fallback_allowed=False), **changes}


@pytest.mark.parametrize("changes", [
    {"business_type": "OTHER_OBLIGATION"}, {"business_id": "another-invoice"},
    {"payee_id": "other-payee"}, {"operation": "REFUND"}, {"amount_minor": 1},
    {"currency": "USD"}, {"channel_priority": ["VISA", "ALIPAY"]},
    {"automatic_fallback_allowed": True},
])
def test_obligation_idempotency_rejects_changed_request_without_mutation(changes):
    svc.create_intent(obligation(), "depth-c11", "payer-a")
    before = svc.status("payer-a")["intents"]
    with pytest.raises(ValueError, match="IDEMPOTENCY_KEY_REQUEST_FINGERPRINT_MISMATCH"):
        svc.create_intent(obligation(**changes), "depth-c11", "payer-a")
    assert svc.status("payer-a")["intents"] == before


def test_global_key_cannot_disclose_another_payers_payment():
    svc.create_intent(obligation(), "shared-depth-c11", "payer-a")
    before = svc.status("payer-a")["intents"]
    with pytest.raises(ValueError, match="IDEMPOTENCY_KEY_REQUEST_FINGERPRINT_MISMATCH"):
        svc.create_intent(obligation(), "shared-depth-c11", "payer-b")
    assert svc.status("payer-a")["intents"] == before
    assert svc.status("payer-b")["intents"] == []


def test_legitimate_server_obligation_replay_retains_selected_channel():
    original = svc.create_intent(obligation(), "depth-c11", "payer-a")
    selected = svc.select_channel(original["payment_intent_id"], "ALIPAY", "payer-a")
    replay = svc.create_intent(obligation(), "depth-c11", "payer-a")
    assert replay["payment_intent_id"] == selected["payment_intent_id"]
    assert replay["state"] == "READY" and replay["selected_channel"] == "ALIPAY"


@pytest.mark.parametrize("business_type", ["SUBSCRIPTION_INVOICE", "UNKNOWN", None])
def test_consumer_http_cannot_create_unbound_money_obligations(client, business_type):
    identity_service.create_user("depth-consumer", "depth-passphrase", "CONSUMER", None, ["CONSUMER"])
    tokens = identity_service.login("depth-consumer", "depth-passphrase")
    body = obligation(business_type=business_type)
    response = client.post("/v1/payments/intents", json=body, headers={
        "Authorization": "Bearer " + tokens["access_token"], "Idempotency-Key": "depth-http"})
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "CONSUMER_AUTHORITATIVE_ORDER_REQUIRED"
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Intent)) == 0


def callback(monkeypatch):
    intent = svc.create_intent(obligation(), "depth-callback", "payer-a")
    svc.select_channel(intent["payment_intent_id"], "ALIPAY", "payer-a")
    attempt = svc.execute(intent["payment_intent_id"])
    monkeypatch.setenv("GO_PAYMENT_WEBHOOK_KEY_ALIPAY", "isolated-depth-key")
    body = {"external_event_id": "depth-event", "payment_attempt_id": attempt["payment_attempt_id"],
            "external_operation_id": "depth-operation", "state": "SUCCEEDED",
            "occurred_at": datetime.now(timezone.utc).isoformat()}
    return body


def signed(body):
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hmac.new(b"isolated-depth-key", raw.encode(), hashlib.sha256).hexdigest()


@pytest.mark.parametrize("changes", [{"state": "FAILED"}, {"payment_attempt_id": "other-attempt"},
                                      {"external_operation_id": "other-operation"}])
def test_signed_event_identity_cannot_be_reused_for_different_payload(monkeypatch, changes):
    body = callback(monkeypatch)
    first = svc.webhook("ALIPAY", body, signed(body))
    conflicting = {**body, **changes}
    with pytest.raises(ValueError, match="PAYMENT_CALLBACK_REPLAY_PAYLOAD_MISMATCH"):
        svc.webhook("ALIPAY", conflicting, signed(conflicting))
    replay = svc.webhook("ALIPAY", body, signed(body))
    assert replay["duplicate"]
    assert replay["receipt"]["webhook_receipt_id"] == first["receipt"]["webhook_receipt_id"]
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Receipt)) == 1


def test_signed_naive_timestamp_is_rejected_without_callback_state(monkeypatch):
    body = callback(monkeypatch)
    body["occurred_at"] = datetime.now().isoformat()
    with pytest.raises(ValueError, match="PAYMENT_CALLBACK_TIMEZONE_REQUIRED"):
        svc.webhook("ALIPAY", body, signed(body))
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Receipt)) == 0
