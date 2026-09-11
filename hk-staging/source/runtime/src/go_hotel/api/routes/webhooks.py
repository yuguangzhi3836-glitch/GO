import json
from fastapi import APIRouter, Header, HTTPException, Request
from go_hotel.services.webhooks import webhook_service
from go_hotel.services.booking import booking_service
from go_hotel.repositories.sql import repo

router = APIRouter(prefix="/internal/v1/connectors", tags=["internal", "webhooks"])

@router.post("/{connector_id}/webhooks")
async def connector_webhook(connector_id: str, request: Request, x_go_signature: str | None = Header(default=None, alias="X-GO-Signature")):
    raw = await request.body()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail={"code":"INVALID_WEBHOOK_JSON","message":"Invalid JSON"})
    row, created = webhook_service.ingest_and_process(connector_id, payload, raw, x_go_signature)
    if not row["signature_valid"]:
        raise HTTPException(status_code=401, detail={"code":"INVALID_WEBHOOK_SIGNATURE","message":"Webhook signature verification failed"})
    if created and row.get("status") == "APPLIED" and row.get("event_type") == "BOOKING_CONFIRMED":
        payment = repo.get_authorized_payment_for_order(row["aggregate_id"])
        if payment:
            await booking_service.capture_after_booking(row["aggregate_id"], payment)
    return {"data": row | {"duplicate": not created}}
