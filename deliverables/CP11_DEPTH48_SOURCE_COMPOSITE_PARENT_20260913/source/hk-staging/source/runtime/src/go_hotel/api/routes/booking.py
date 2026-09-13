from fastapi import APIRouter, Header
from go_hotel.api.schemas import CreateOrderRequest, PaymentRequest
from go_hotel.core.errors import conflict, not_found
from go_hotel.repositories.sql import repo
from go_hotel.services.booking import booking_service
from go_hotel.services.booking_data_release import release_booking_data
from go_hotel.domain.models import Event, new_id

router = APIRouter()

def idem(operation: str, key: str | None, payload: dict):
    if not key: return None
    rec = repo.get_idempotency(operation, key)
    if rec and rec["request_hash"] != repo.hash_payload(payload):
        conflict("IDEMPOTENCY_CONFLICT", "Idempotency key reused with different payload")
    return rec

@router.post("/v1/orders")
async def create_order(body: CreateOrderRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    payload = body.model_dump(); rec = idem("create_order", idempotency_key, payload)
    if rec: return rec["response"]
    released = release_booking_data(body.account_id, 'HOTEL', body.traveler_ids, body.guests, vault_release_ids=body.vault_release_ids, requester_id=body.account_id)
    order = await booking_service.create_order(body.prebook_id, body.account_id)
    if released['release_ids']:
        repo.append_event(Event(new_id('evt'), 'VAULT_BOOKING_DATA_RELEASED', 'HOTEL_ORDER', order.order_id, {
            'traveler_ids': released['traveler_ids'], 'release_ids': released['release_ids'], 'purpose': 'TRAVEL_BOOKING', 'minimum_necessary': True
        }))
    response = {"data": {"order_id": order.order_id, "status": order.status, "total_amount_minor": order.total_amount_minor, "currency": order.currency}}
    if idempotency_key: repo.save_idempotency("create_order", idempotency_key, payload, response, order.order_id)
    return response

@router.post("/v1/orders/{order_id}/payments")
async def pay(order_id: str, body: PaymentRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    payload = body.model_dump() | {"order_id": order_id}; rec = idem("payment", idempotency_key, payload)
    if rec: return rec["response"]
    payment = await booking_service.pay(order_id, body.amount_minor, body.currency, body.payment_method_token)
    response = {"data": {"payment_id": payment.payment_id, "status": payment.status, "amount_minor": payment.amount_minor, "currency": payment.currency}}
    if idempotency_key: repo.save_idempotency("payment", idempotency_key, payload, response, payment.payment_id)
    return response

@router.post("/internal/v1/orders/{order_id}/confirm")
async def confirm(order_id: str):
    order = await booking_service.confirm(order_id)
    return {"data": {"order_id": order.order_id, "status": order.status, "supplier_confirmation_no": order.supplier_confirmation_no}}

@router.get("/v1/orders/{order_id}")
async def get_order(order_id: str):
    order = repo.get_order(order_id)
    if not order: not_found("ORDER_NOT_FOUND", "Order not found")
    return {"data": {"order_id": order.order_id, "hotel_id": order.hotel_id, "status": order.status, "total_amount_minor": order.total_amount_minor, "currency": order.currency, "supplier_confirmation_no": order.supplier_confirmation_no}}

@router.get("/internal/v1/orders/{order_id}/events")
async def order_events(order_id: str):
    return {"data": repo.event_dicts(order_id)}

@router.get("/internal/v1/orders/{order_id}/payment-orchestration")
async def payment_orchestration(order_id: str):
    data = repo.orchestration_for_order(order_id)
    if not data: not_found("PAYMENT_ORCHESTRATION_NOT_FOUND", "Payment orchestration not found")
    return {"data": data}
