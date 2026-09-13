from dataclasses import asdict
from fastapi import APIRouter
from sqlalchemy import select

from go_hotel.api.schemas import SearchRequest, PrebookRequest
from go_hotel.services.booking import booking_service
from go_hotel.judgment.service import judgment_service
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HostedDirectInventoryPoolRow
from go_hotel.connectors.aoluguya_test import HOTEL_ID as AOLUGUYA_HOTEL_ID, room_catalog
from go_hotel.core.config import settings

router = APIRouter(prefix="/v1")


def _aoluguya_room_lookup():
    return {r["room_type_id"]: r for r in room_catalog()}


@router.post("/search/hotels")
async def search_hotels(body: SearchRequest):
    offers = await booking_service.search(body.destination.city_code, body.stay.check_in, body.stay.check_out, body.currency)
    grouped = {}
    aol_rooms = _aoluguya_room_lookup() if any(o.hotel_id == AOLUGUYA_HOTEL_ID for o in offers) else {}
    for o in offers:
        judgment = judgment_service.public_summary_or_default(o.hotel_id)
        if o.hotel_id not in grouped:
            grouped[o.hotel_id] = {
                "hotel_id": o.hotel_id,
                "name": "AOLUGUYA" if o.hotel_id == AOLUGUYA_HOTEL_ID else "Conrad Tokyo",
                "go_score": judgment["go_score"],
                "guest_experience_score": 4.5,
                "recommendation_status": judgment["recommendation_status"],
                "judgment_id": judgment["judgment_id"],
                "offers": [],
                "test_data": bool(o.connector_id == "conn_aoluguya_hosted_test"),
            }
        room = aol_rooms.get(o.room_type_id, {})
        grouped[o.hotel_id]["offers"].append({
            "offer_id": o.offer_id,
            "canonical_room_id": o.room_type_id,
            "room_type_id": o.room_type_id,
            "room_name": room.get("official_name") or o.room_type_id,
            "room_area": room.get("area"),
            "room_view": room.get("view"),
            "rate_plan_id": o.rate_plan_id,
            "rate_plan_name": "TEST Flexible" if o.rate_plan_id.endswith("_flex") else ("TEST Breakfast for 2" if o.rate_plan_id.endswith("_breakfast") else o.rate_plan_id),
            "total_amount_minor": o.total_amount_minor,
            "price": o.total_amount_minor / 100,
            "currency": o.currency,
            "availability": o.inventory_units,
            "inventory": o.inventory_units,
            "meal_plan": o.meal_plan,
            "refundable": o.refundable,
            "cancellation_summary": "TEST ONLY · 入住前24小时可取消" if o.connector_id == "conn_aoluguya_hosted_test" else None,
            "official_direct": o.official_direct,
            "test_data": bool(o.connector_id == "conn_aoluguya_hosted_test"),
            "real_supplier_call": False if o.connector_id == "conn_aoluguya_hosted_test" else None,
        })
    hotels = list(grouped.values())
    for h in hotels:
        h["best_offer"] = min(h["offers"], key=lambda x: x["total_amount_minor"]) if h["offers"] else None
    return {"data": {"hotels": hotels, "test_mode": settings.aoluguya_direct_test_mode}}


@router.post("/offers/{offer_id}/prebook")
async def prebook(offer_id: str, body: PrebookRequest):
    pb = await booking_service.prebook(offer_id)
    return {"data": {
        "prebook_id": pb.prebook_id,
        "status": pb.status,
        "total_amount_minor": pb.total_amount_minor,
        "price": pb.total_amount_minor / 100,
        "currency": pb.currency,
        "expires_at": pb.expires_at.isoformat(),
        "test_data": offer_id.startswith("off_aol_test_"),
    }}


@router.get("/direct/aoluguya-harbin/runtime-readiness")
def aoluguya_runtime_readiness():
    return {"data": {
        "hotel_id": AOLUGUYA_HOTEL_ID,
        "official_room_count": len(room_catalog()),
        "official_room_source": "HYATT_OFFICIAL_WEB_ORACLE",
        "test_mode": settings.aoluguya_direct_test_mode,
        "real_inventory_configured": settings.aoluguya_real_inventory_configured,
        "real_rate_configured": settings.aoluguya_real_rate_configured,
        "real_payment_configured": settings.aoluguya_real_payment_configured,
        "booking_status": "TEST ONLY" if settings.aoluguya_direct_test_mode else ("READY" if settings.aoluguya_real_inventory_configured and settings.aoluguya_real_rate_configured else "暂不可预订"),
        "payment_status": "TEST ONLY" if settings.aoluguya_direct_test_mode else ("READY" if settings.aoluguya_real_payment_configured else "支付未开通"),
        "real_supplier_calls": 0 if settings.aoluguya_direct_test_mode else None,
        "real_payment_calls": 0 if settings.aoluguya_direct_test_mode else None,
    }}
