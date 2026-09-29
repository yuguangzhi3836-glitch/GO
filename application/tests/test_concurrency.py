import asyncio
import pytest
from fastapi import HTTPException
from go_hotel.services.booking import booking_service
from go_hotel.payments.mock import payment_provider
from go_hotel.connectors.mock_hotel import connector
from go_hotel.db.models import PaymentRow, EventRow
from go_hotel.db.session import SessionLocal
from sqlalchemy import select, func


def seed_order(client):
    search = client.post("/v1/search/hotels", json={"destination":{"city_code":"TYO"},"stay":{"check_in":"2026-09-01","check_out":"2026-09-05"},"currency":"CNY"}).json()
    offer = search["data"]["hotels"][0]["best_offer"]
    pb = client.post(f"/v1/offers/{offer['offer_id']}/prebook", json={"currency":"CNY"}).json()["data"]
    return client.post("/v1/orders", json={"prebook_id":pb["prebook_id"],"account_id":"acct_concurrency"}).json()["data"]

@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_concurrent_payment_has_one_external_authorization(client):
    order = seed_order(client)
    payment_provider.delay_seconds = 0.05
    async def pay():
        try:
            return await booking_service.pay(order["order_id"], order["total_amount_minor"], "CNY", "pm_success")
        except HTTPException as exc:
            return exc
    a, b = await asyncio.gather(pay(), pay())
    assert payment_provider.authorize_calls == 1
    assert any(getattr(x, "status_code", None) == 409 for x in (a,b))
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(PaymentRow).where(PaymentRow.order_id == order["order_id"])) == 1
        assert s.scalar(select(func.count()).select_from(EventRow).where(EventRow.aggregate_id == order["order_id"], EventRow.event_type == "PAYMENT_AUTHORIZED")) == 1

@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_concurrent_confirmation_has_one_connector_book(client):
    order = seed_order(client)
    pay = client.post(f"/v1/orders/{order['order_id']}/payments", json={"payment_method_token":"pm_success","amount_minor":order["total_amount_minor"],"currency":"CNY"})
    assert pay.status_code == 200
    connector.delay_seconds = 0.05
    async def confirm():
        try:
            return await booking_service.confirm(order["order_id"])
        except HTTPException as exc:
            return exc
    a, b = await asyncio.gather(confirm(), confirm())
    assert connector.book_calls == 1
    assert any(getattr(x, "status_code", None) == 409 for x in (a,b))
    current = client.get(f"/v1/orders/{order['order_id']}").json()["data"]
    # One caller may still be finishing when the other receives 409; after gather it is final.
    assert current["status"] == "CONFIRMED"
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(EventRow).where(EventRow.aggregate_id == order["order_id"], EventRow.event_type == "ORDER_CONFIRMED")) == 1


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_cancel_after_provider_success_commits_once_and_replays(client, monkeypatch):
    """Offloading must not drop the durable receipt at its new await boundary."""
    from go_hotel.db.models import OrderRow, ExternalOperationRow
    order = seed_order(client)
    authorize = payment_provider.authorize
    async def cancel_after_success(*args, **kwargs):
        payment = await authorize(*args, **kwargs)
        asyncio.current_task().cancel()
        return payment
    monkeypatch.setattr(payment_provider, 'authorize', cancel_after_success)
    task = asyncio.create_task(booking_service.pay(order['order_id'], order['total_amount_minor'], 'CNY', 'pm_success'))
    with pytest.raises(asyncio.CancelledError):
        await task
    with SessionLocal() as s:
        payments = list(s.scalars(select(PaymentRow).where(PaymentRow.order_id == order['order_id'])))
        operations = list(s.scalars(select(ExternalOperationRow).where(
            ExternalOperationRow.aggregate_id == order['order_id'],
            ExternalOperationRow.operation_type == 'PAYMENT_AUTHORIZE')))
        assert len(payments) == len(operations) == 1
        assert payments[0].status == 'AUTHORIZED' and operations[0].status == 'COMPLETED'
        assert s.get(OrderRow, order['order_id']).status == 'PAYMENT_AUTHORIZED'
        assert s.scalar(select(func.count()).select_from(EventRow).where(
            EventRow.aggregate_id == order['order_id'], EventRow.event_type == 'PAYMENT_AUTHORIZED')) == 1
        payment_id = payments[0].payment_id
    replay = await booking_service.pay(order['order_id'], order['total_amount_minor'], 'CNY', 'pm_success')
    assert replay.payment_id == payment_id
    assert payment_provider.authorize_calls == 1 and payment_provider.capture_calls == 0
