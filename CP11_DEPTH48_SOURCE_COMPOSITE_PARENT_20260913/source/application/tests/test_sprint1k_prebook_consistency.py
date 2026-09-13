from datetime import datetime, timezone, timedelta
from go_hotel.connectors.mock_hotel import connector
from go_hotel.repositories.sql import repo

def search_offer(client):
    r=client.post("/v1/search/hotels",json={"destination":{"city_code":"TYO"},"stay":{"check_in":"2026-09-01","check_out":"2026-09-05"},"occupancy":{"rooms":1,"adults":2,"children":0},"currency":"CNY"})
    assert r.status_code==200
    return r.json()["data"]["hotels"][0]["best_offer"]["offer_id"]

def test_prebook_revalidation_unchanged(client):
    offer_id=search_offer(client)
    r=client.post(f"/v1/offers/{offer_id}/prebook",json={"currency":"CNY"})
    assert r.status_code==200, r.text
    pb=r.json()["data"]
    saved=repo.get_prebook(pb["prebook_id"])
    rv=repo.get_latest_revalidation_for_prebook(saved.prebook_id)
    assert rv["price_status"]=="UNCHANGED"
    assert rv["inventory_status"] in ("AVAILABLE_NOT_HELD","HELD")

def test_price_change_blocks_checkout(client):
    offer_id=search_offer(client)
    connector.prebook_price_delta_minor=12000
    r=client.post(f"/v1/offers/{offer_id}/prebook",json={"currency":"CNY"})
    assert r.status_code==422
    assert r.json()["detail"]["code"]=="HOTEL_RATE_CHANGED"

def test_inventory_loss_blocks_checkout(client):
    offer_id=search_offer(client)
    connector.inventory_available=False
    r=client.post(f"/v1/offers/{offer_id}/prebook",json={"currency":"CNY"})
    assert r.status_code==422
    assert r.json()["detail"]["code"]=="HOTEL_INVENTORY_CHANGED"

def test_quote_expiry_blocks_payment(client):
    offer_id=search_offer(client)
    pb=client.post(f"/v1/offers/{offer_id}/prebook",json={"currency":"CNY"}).json()["data"]
    order=client.post("/v1/orders",json={"prebook_id":pb["prebook_id"],"account_id":"acct_1"}).json()["data"]
    # force expiry in DB via ORM model
    from go_hotel.db.session import SessionLocal
    from go_hotel.db.models import PrebookRow
    with SessionLocal.begin() as s:
        row=s.get(PrebookRow,pb["prebook_id"]); row.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
    r=client.post(f"/v1/orders/{order['order_id']}/payments",json={"amount_minor":order["total_amount_minor"],"currency":"CNY","payment_method_token":"pm_ok"},headers={"Idempotency-Key":"pay-expired"})
    assert r.status_code==422
    assert r.json()["detail"]["code"]=="BOOKING_CONSISTENCY_FAILED"
