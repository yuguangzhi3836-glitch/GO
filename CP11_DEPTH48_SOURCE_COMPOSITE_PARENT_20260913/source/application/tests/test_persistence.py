from sqlalchemy import select, func
from go_hotel.db.models import EventRow, OutboxRow, IdempotencyRow, OrderRow, CatalogOrderFareSnapshotRow
from go_hotel.db.session import SessionLocal

def create_confirmed(client):
    search = client.post("/v1/search/hotels", json={"destination":{"city_code":"TYO"},"stay":{"check_in":"2026-09-01","check_out":"2026-09-05"},"occupancy":{"rooms":1,"adults":2,"children":0},"currency":"CNY"})
    offer = search.json()["data"]["hotels"][0]["best_offer"]
    pb = client.post(f"/v1/offers/{offer['offer_id']}/prebook", json={"currency":"CNY"}).json()["data"]
    order = client.post("/v1/orders", headers={"Idempotency-Key":"persist-order"}, json={"prebook_id":pb["prebook_id"],"account_id":"acct_demo"}).json()["data"]
    client.post(f"/v1/orders/{order['order_id']}/payments", headers={"Idempotency-Key":"persist-pay"}, json={"payment_method_token":"pm_success","amount_minor":order["total_amount_minor"],"currency":"CNY"})
    client.post(f"/internal/v1/orders/{order['order_id']}/confirm")
    return order["order_id"]

def test_state_event_and_outbox_are_persisted(client):
    oid = create_confirmed(client)
    with SessionLocal() as s:
        order = s.get(OrderRow, oid)
        assert order.status == "CONFIRMED"
        event_count = s.scalar(select(func.count()).select_from(EventRow).where(EventRow.aggregate_id == oid))
        outbox_count = s.scalar(select(func.count()).select_from(OutboxRow).where(OutboxRow.aggregate_id == oid))
        assert event_count == 7
        assert outbox_count == 7
        accepted=s.scalar(select(EventRow).where(EventRow.aggregate_id==oid,EventRow.event_type=='ORDER_FARE_RULE_ACCEPTED'))
        snapshot=s.get(CatalogOrderFareSnapshotRow,oid)
        emitted=s.scalar(select(OutboxRow).where(OutboxRow.event_id==accepted.event_id))
        assert accepted.payload['snapshot_hash']==snapshot.snapshot_hash
        assert emitted.payload['payload']==accepted.payload

def test_idempotency_is_durable(client):
    search = client.post("/v1/search/hotels", json={"destination":{"city_code":"TYO"},"stay":{"check_in":"2026-09-01","check_out":"2026-09-05"},"occupancy":{"rooms":1,"adults":2,"children":0},"currency":"CNY"})
    offer = search.json()["data"]["hotels"][0]["best_offer"]
    pb = client.post(f"/v1/offers/{offer['offer_id']}/prebook", json={"currency":"CNY"}).json()["data"]
    payload = {"prebook_id":pb["prebook_id"],"account_id":"acct_demo"}
    a = client.post("/v1/orders", headers={"Idempotency-Key":"durable-idem"}, json=payload)
    b = client.post("/v1/orders", headers={"Idempotency-Key":"durable-idem"}, json=payload)
    assert a.json() == b.json()
    with SessionLocal() as s:
        rec = s.get(IdempotencyRow, {"idempotency_key":"durable-idem","operation":"create_order"})
        assert rec is not None

def test_outbox_can_be_drained(client):
    oid = create_confirmed(client)
    res = client.post("/internal/v1/outbox/drain?limit=100")
    assert res.status_code == 200
    assert res.json()["data"]["published"] >= 6
    with SessionLocal() as s:
        pending = s.scalar(select(func.count()).select_from(OutboxRow).where(OutboxRow.aggregate_id == oid, OutboxRow.status == "PENDING"))
        assert pending == 0
