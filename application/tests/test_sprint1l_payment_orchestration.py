from sqlalchemy import select
from go_hotel.db.models import PaymentRow, PaymentOrchestrationRow, EventRow
from go_hotel.db.session import SessionLocal
from go_hotel.connectors.mock_hotel import connector
from go_hotel.payments.mock import payment_provider
from go_hotel.repositories.sql import repo


def seed(client, token="pm_success"):
    search=client.post("/v1/search/hotels",json={"destination":{"city_code":"TYO"},"stay":{"check_in":"2026-09-01","check_out":"2026-09-05"},"currency":"CNY"}).json()
    offer=search["data"]["hotels"][0]["best_offer"]
    pb=client.post(f"/v1/offers/{offer['offer_id']}/prebook",json={"currency":"CNY"}).json()["data"]
    order=client.post("/v1/orders",json={"prebook_id":pb["prebook_id"],"account_id":"acct_1l"}).json()["data"]
    pay=client.post(f"/v1/orders/{order['order_id']}/payments",json={"payment_method_token":token,"amount_minor":order["total_amount_minor"],"currency":"CNY"})
    return order,pay


def test_authorize_book_capture_sequence(client):
    order,pay=seed(client)
    assert pay.status_code==200 and pay.json()["data"]["status"]=="AUTHORIZED"
    assert payment_provider.capture_calls==0
    current=client.get(f"/v1/orders/{order['order_id']}").json()["data"]
    assert current["status"]=="PAYMENT_AUTHORIZED"
    confirm=client.post(f"/internal/v1/orders/{order['order_id']}/confirm")
    assert confirm.status_code==200
    assert confirm.json()["data"]["status"]=="CONFIRMED"
    assert payment_provider.capture_calls==1
    with SessionLocal() as s:
        p=s.scalar(select(PaymentRow).where(PaymentRow.order_id==order["order_id"]))
        assert p.status=="CAPTURED"
        orch=s.scalar(select(PaymentOrchestrationRow).where(PaymentOrchestrationRow.order_id==order["order_id"]))
        assert orch.phase=="COMPLETED"


def test_definitive_supplier_booking_failure_voids_authorization_no_capture(client):
    order,pay=seed(client)
    connector.fail_book=True
    res=client.post(f"/internal/v1/orders/{order['order_id']}/confirm")
    assert res.status_code==503
    current=client.get(f"/v1/orders/{order['order_id']}").json()["data"]
    assert current["status"]=="FAILED"
    assert payment_provider.capture_calls==0
    assert payment_provider.void_calls==1
    with SessionLocal() as s:
        p=s.scalar(select(PaymentRow).where(PaymentRow.order_id==order["order_id"]))
        assert p.status=="VOIDED"
        events=[e.event_type for e in s.scalars(select(EventRow).where(EventRow.aggregate_id==order["order_id"]).order_by(EventRow.occurred_at)).all()]
        assert "BOOKING_FAILED_NO_CHARGE" in events


def test_ambiguous_supplier_booking_does_not_void_authorization(client):
    order,pay=seed(client)
    connector.ambiguous_book=True
    res=client.post(f"/internal/v1/orders/{order['order_id']}/confirm")
    assert res.status_code==503
    current=client.get(f"/v1/orders/{order['order_id']}").json()["data"]
    assert current["status"]=="RECONCILIATION_REQUIRED"
    assert payment_provider.capture_calls==0
    assert payment_provider.void_calls==0
    with SessionLocal() as s:
        p=s.scalar(select(PaymentRow).where(PaymentRow.order_id==order["order_id"]))
        assert p.status=="AUTHORIZED"


def test_rejected_supplier_lookup_after_unknown_result_voids_original_authorization(client):
    order,pay=seed(client)
    connector.ambiguous_book=True
    first=client.post(f"/internal/v1/orders/{order['order_id']}/confirm")
    assert first.status_code==503
    op=next(x for x in repo.recoverable_operations() if x["operation_type"]=="SUPPLIER_BOOK" and x["aggregate_id"]==order["order_id"])
    original_book_calls=connector.book_calls

    connector.ambiguous_book=False
    connector._rejected_bookings.add(op["operation_id"])

    retried=client.post(f"/internal/v1/orders/{order['order_id']}/confirm")
    assert retried.status_code==200
    assert retried.json()["data"]["status"]=="FAILED"
    assert payment_provider.capture_calls==0
    assert payment_provider.void_calls==1
    assert connector.book_calls==original_book_calls

    current=client.get(f"/v1/orders/{order['order_id']}").json()["data"]
    assert current["status"]=="FAILED"
    with SessionLocal() as s:
        p=s.scalar(select(PaymentRow).where(PaymentRow.order_id==order["order_id"]))
        assert p.status=="VOIDED"
        events=[e.event_type for e in s.scalars(select(EventRow).where(EventRow.aggregate_id==order["order_id"]).order_by(EventRow.occurred_at)).all()]
        assert events.count("BOOKING_FAILED_NO_CHARGE")==1


def test_capture_failure_after_supplier_booking_moves_to_reconciliation(client):
    order,pay=seed(client, token="pm_capture_fail")
    res=client.post(f"/internal/v1/orders/{order['order_id']}/confirm")
    assert res.status_code==503
    current=client.get(f"/v1/orders/{order['order_id']}").json()["data"]
    assert current["supplier_confirmation_no"].startswith("MOCK-")
    assert current["status"]=="RECONCILIATION_REQUIRED"
    assert payment_provider.capture_calls==1
    assert payment_provider.void_calls==0
