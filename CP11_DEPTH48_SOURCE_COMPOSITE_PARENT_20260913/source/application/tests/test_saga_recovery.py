from go_hotel.core.faults import faults
from go_hotel.db.models import ExternalOperationRow, PaymentRow, EventRow
from go_hotel.db.session import SessionLocal
from sqlalchemy import select, func


def seed_order(client):
    search = client.post("/v1/search/hotels", json={"destination":{"city_code":"TYO"},"stay":{"check_in":"2026-09-01","check_out":"2026-09-05"},"currency":"CNY"}).json()
    offer = search["data"]["hotels"][0]["best_offer"]
    pb = client.post(f"/v1/offers/{offer['offer_id']}/prebook", json={"currency":"CNY"}).json()["data"]
    return client.post("/v1/orders", json={"prebook_id":pb["prebook_id"],"account_id":"acct_recovery"}).json()["data"]


def test_payment_provider_success_local_failure_is_recovered(client):
    order = seed_order(client)
    faults.arm("authorization_after_external_success")
    res = client.post(f"/v1/orders/{order['order_id']}/payments", json={"payment_method_token":"pm_success","amount_minor":order["total_amount_minor"],"currency":"CNY"})
    assert res.status_code == 503
    assert client.get(f"/v1/orders/{order['order_id']}").json()["data"]["status"] == "PAYMENT_PENDING"
    recovery = client.post("/internal/v1/ops/saga-recovery/run-once").json()["data"]
    assert recovery["recovered"] == 1
    assert client.get(f"/v1/orders/{order['order_id']}").json()["data"]["status"] == "PAYMENT_AUTHORIZED"
    with SessionLocal() as s:
        op = s.scalar(select(ExternalOperationRow).where(ExternalOperationRow.aggregate_id == order["order_id"], ExternalOperationRow.operation_type == "PAYMENT_AUTHORIZE"))
        assert op.status == "COMPLETED"
        assert s.scalar(select(func.count()).select_from(PaymentRow).where(PaymentRow.order_id == order["order_id"])) == 1


def test_supplier_book_success_local_failure_is_recovered(client):
    order = seed_order(client)
    assert client.post(f"/v1/orders/{order['order_id']}/payments", json={"payment_method_token":"pm_success","amount_minor":order["total_amount_minor"],"currency":"CNY"}).status_code == 200
    faults.arm("confirm_after_external_success")
    res = client.post(f"/internal/v1/orders/{order['order_id']}/confirm")
    assert res.status_code == 503
    assert client.get(f"/v1/orders/{order['order_id']}").json()["data"]["status"] == "RECONCILIATION_REQUIRED"
    recovery = client.post("/internal/v1/ops/saga-recovery/run-once").json()["data"]
    assert recovery["recovered"] == 1
    current = client.get(f"/v1/orders/{order['order_id']}").json()["data"]
    assert current["status"] == "CONFIRMED"
    assert current["supplier_confirmation_no"].startswith("MOCK-")
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(EventRow).where(EventRow.aggregate_id == order["order_id"], EventRow.event_type == "ORDER_CONFIRMED")) == 1
