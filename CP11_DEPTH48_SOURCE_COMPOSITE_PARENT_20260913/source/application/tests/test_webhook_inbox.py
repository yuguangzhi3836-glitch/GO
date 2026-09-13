import hashlib, hmac, json
from go_hotel.core.config import settings
from go_hotel.db.models import WebhookInboxRow, ConnectorCursorRow
from go_hotel.db.session import SessionLocal
from sqlalchemy import select, func


def seed_paid_order(client):
    search = client.post("/v1/search/hotels", json={"destination":{"city_code":"TYO"},"stay":{"check_in":"2026-09-01","check_out":"2026-09-05"},"currency":"CNY"}).json()
    offer = search["data"]["hotels"][0]["best_offer"]
    pb = client.post(f"/v1/offers/{offer['offer_id']}/prebook", json={"currency":"CNY"}).json()["data"]
    order = client.post("/v1/orders", json={"prebook_id":pb["prebook_id"],"account_id":"acct_webhook"}).json()["data"]
    client.post(f"/v1/orders/{order['order_id']}/payments", json={"payment_method_token":"pm_success","amount_minor":order["total_amount_minor"],"currency":"CNY"})
    return order


def post_webhook(client, payload, valid=True):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    sig = hmac.new(settings.webhook_secret.encode(), raw, hashlib.sha256).hexdigest()
    if not valid: sig = "bad"
    return client.post("/internal/v1/connectors/conn_mock_hotel/webhooks", content=raw, headers={"Content-Type":"application/json","X-GO-Signature":sig})


def test_webhook_duplicate_and_out_of_order_are_safe(client):
    order = seed_paid_order(client)
    newest = {"external_event_id":"evt-supplier-2","order_id":order["order_id"],"event_type":"BOOKING_CONFIRMED","sequence":2,"confirmation_no":"WH-CONFIRM-2"}
    a = post_webhook(client, newest); assert a.status_code == 200; assert a.json()["data"]["status"] == "APPLIED"
    dup = post_webhook(client, newest); assert dup.status_code == 200; assert dup.json()["data"]["duplicate"] is True
    stale = {"external_event_id":"evt-supplier-1","order_id":order["order_id"],"event_type":"BOOKING_CONFIRMED","sequence":1,"confirmation_no":"OLD-CONFIRM"}
    b = post_webhook(client, stale); assert b.status_code == 200; assert b.json()["data"]["status"] == "IGNORED_STALE"
    current = client.get(f"/v1/orders/{order['order_id']}").json()["data"]
    assert current["supplier_confirmation_no"] == "WH-CONFIRM-2"
    assert current["status"] == "CONFIRMED"
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(WebhookInboxRow)) == 2
        cursor = s.get(ConnectorCursorRow, {"connector_id":"conn_mock_hotel","aggregate_id":order["order_id"]})
        assert cursor.last_sequence == 2


def test_invalid_webhook_signature_is_rejected_and_audited(client):
    order = seed_paid_order(client)
    payload = {"external_event_id":"evt-bad","order_id":order["order_id"],"event_type":"BOOKING_CONFIRMED","sequence":1,"confirmation_no":"NOPE"}
    r = post_webhook(client, payload, valid=False)
    assert r.status_code == 401
    with SessionLocal() as s:
        row = s.scalar(select(WebhookInboxRow).where(WebhookInboxRow.external_event_id == "evt-bad"))
        assert row.status == "REJECTED_SIGNATURE"
