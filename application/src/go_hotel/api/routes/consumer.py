from __future__ import annotations
from fastapi import APIRouter, Header, Request, Depends, HTTPException
from go_hotel.security.deps import legacy_order_access
from go_hotel.core.config import settings
from pydantic import BaseModel
from sqlalchemy import select

from go_hotel.db.session import SessionLocal
from go_hotel.db.models import RailOrderRow
from go_hotel.db.models import (
    OrderRow, OfferRow, PrebookRow, PaymentRow, RefundRow, OrderChangeRow,
    StayCreditRow, ReviewSessionRow, EventRow, FlightOrderRow,
    HotelPartnerRoomTypeRow, DirectValueOfferRow,
)
from go_hotel.services.booking import booking_service
from go_hotel.truth.service import truth_service
from go_hotel.repositories.sql import repo
from go_hotel.core.errors import not_found
from go_hotel.domain.models import Event, new_id
from go_hotel.security.service import identity_service

router = APIRouter(tags=["sprint1x-consumer"])

HOTEL_COPY = {
    "htl_tokyo_001": {
        "name": "东京康莱德",
        "city": "东京，日本",
        "area": "汐留 / 银座",
        "summary": "城市高层景观、稳定服务与官方直订权益。",
        "go_reason": "位置、客房品质与履约稳定性表现均衡，适合城市商务与周末旅行。",
        "features": ["城市景观", "室内泳池", "健身房", "行政酒廊"],
    },
    "hotel_tokyo_001": {
        "name": "东京康莱德",
        "city": "东京，日本",
        "area": "汐留 / 银座",
        "summary": "城市高层景观、稳定服务与官方直订权益。",
        "go_reason": "位置、客房品质与履约稳定性表现均衡，适合城市商务与周末旅行。",
        "features": ["城市景观", "室内泳池", "健身房", "行政酒廊"],
    },
}

class CheckoutBody(BaseModel):
    payment_method_token: str = "pm_success"


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") and v else v


def _money(v, currency):
    return {"amount_minor": int(v or 0), "currency": currency}

def _consumer_account(request: Request, legacy_account_id: str | None = None):
    token=request.cookies.get("go_consumer_access")
    auth=request.headers.get("Authorization") or ""
    if not token and auth.lower().startswith("bearer "):
        token=auth.split(" ",1)[1].strip()
    if token:
        try:
            p=identity_service.authenticate(token)
            if p.actor_type=="CONSUMER": return p.user_id
        except Exception: raise HTTPException(401, detail='AUTHENTICATION_REQUIRED')
        raise HTTPException(403, detail='CONSUMER_IDENTITY_REQUIRED')
    if settings.app_env.lower() not in {'local','test','demo'}:
        raise HTTPException(401, detail='AUTHENTICATION_REQUIRED')
    # Backward-compatible local engineering path; production consumer UI uses authenticated principal.
    return legacy_account_id or "acct_demo"


@router.get("/v1/consumer/home")
def consumer_home():
    return {"data": {
        "brand": "GO",
        "headline": "发现全世界，直接向官方预订",
        "hotel_search": {"city_code": "TYO", "check_in": "2026-09-01", "check_out": "2026-09-05", "adults": 2, "rooms": 1},
        "modules": ["GO直联", "GO推荐", "GO礼遇", "GO Offer"],
    }}


@router.get("/v1/consumer/hotels/{hotel_id}")
def consumer_hotel_detail(hotel_id: str):
    with SessionLocal() as s:
        offers = s.scalars(select(OfferRow).where(OfferRow.hotel_id == hotel_id).order_by(OfferRow.created_at.desc()).limit(20)).all()
        room_ids = {o.room_type_id for o in offers if o.room_type_id}
        room_rows = s.scalars(select(HotelPartnerRoomTypeRow).where(HotelPartnerRoomTypeRow.room_type_id.in_(room_ids))).all() if room_ids else []
        room_by_id = {r.room_type_id: r for r in room_rows}
        direct_value = s.scalars(select(DirectValueOfferRow).where(DirectValueOfferRow.hotel_id == hotel_id, DirectValueOfferRow.status == "ACTIVE").order_by(DirectValueOfferRow.updated_at.desc()).limit(1)).first()
    copy = HOTEL_COPY.get(hotel_id, {
        "name": "GO Hotel",
        "city": "东京，日本",
        "area": "市中心",
        "summary": "经 GO 统一身份与报价模型归一的可订酒店。",
        "go_reason": "以真实交易条件、履约和独立判断作为展示基础。",
        "features": ["官方可订", "价格透明"],
    })
    rooms = []
    property_benefits=[]
    if direct_value:
        if direct_value.upgrade_priority: property_benefits.append({"code":"UPGRADE_PRIORITY","name_zh":"有房优先升级"})
        if direct_value.late_checkout_priority: property_benefits.append({"code":"LATE_CHECKOUT_PRIORITY","name_zh":f"延迟退房优先至 {direct_value.late_checkout_time or '酒店确认'}"})
        if direct_value.breakfast_option and direct_value.breakfast_option != "NONE": property_benefits.append({"code":"BREAKFAST","name_zh":"官方早餐礼遇"})
        if direct_value.cash_discount_bps: property_benefits.append({"code":"CASH_VALUE","name_zh":"官方现金价优"})
        for item in (direct_value.benefits_json or []):
            if isinstance(item, dict): property_benefits.append(item)
            elif isinstance(item, str): property_benefits.append({"code":"CUSTOM","name_zh":item})
    for o in offers:
        rr = room_by_id.get(o.room_type_id)
        benefits=list(property_benefits)
        rooms.append({
            "offer_id": o.offer_id,
            "room_type_id": o.room_type_id,
            "rate_plan_id": o.rate_plan_id,
            "room_type_name": rr.name_zh if rr else None,
            "room_type_name_en": rr.name_en if rr else None,
            "room_attributes": dict(rr.attributes_json or {}) if rr else {},
            "occupancy": dict(rr.occupancy_json or {}) if rr else {},
            "bed_configurations": list(rr.bed_configurations_json or []) if rr else [],
            "room_media": list(rr.media_json or []) if rr else [],
            "total_amount_minor": o.total_amount_minor,
            "currency": o.currency,
            "meal_plan": o.meal_plan,
            "refundable": o.refundable,
            "cancellation_deadline": o.cancellation_deadline,
            "official_direct": o.official_direct,
            "official_benefits": benefits if o.official_direct else [],
            "connector_id": o.connector_id,
            "expires_at": _iso(o.expires_at),
        })
    return {"data": {"hotel_id": hotel_id, **copy, "offers": rooms, "official_benefits": property_benefits}}


@router.post("/v1/consumer/orders/{order_id}/checkout",dependencies=[Depends(legacy_order_access)])
async def consumer_checkout(order_id: str, body: CheckoutBody, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    order = repo.get_order(order_id)
    if not order:
        not_found("ORDER_NOT_FOUND", "Order not found")
    payment = await booking_service.pay(order_id, order.total_amount_minor, order.currency, body.payment_method_token)
    confirmed = await booking_service.confirm(order_id)
    return {"data": {
        "order_id": confirmed.order_id,
        "status": confirmed.status,
        "payment_id": payment.payment_id,
        "payment_status": repo.get_captured_payment_for_order(order_id).status.value if repo.get_captured_payment_for_order(order_id) else payment.status.value,
        "supplier_confirmation_no": confirmed.supplier_confirmation_no,
        "total_amount_minor": confirmed.total_amount_minor,
        "currency": confirmed.currency,
    }}


@router.get("/v1/consumer/trips")
def consumer_trips(request: Request, account_id: str | None = None):
    account_id=_consumer_account(request,account_id)
    with SessionLocal() as s:
        rows = s.scalars(select(OrderRow).where(OrderRow.account_id == account_id).order_by(OrderRow.updated_at.desc())).all()
        result = []
        for r in rows:
            refund = s.scalar(select(RefundRow).where(RefundRow.order_id == r.order_id).order_by(RefundRow.created_at.desc()))
            credit = s.scalar(select(StayCreditRow).where(StayCreditRow.original_order_id == r.order_id).order_by(StayCreditRow.created_at.desc()))
            review = s.scalar(select(ReviewSessionRow).where(ReviewSessionRow.order_id == r.order_id))
            result.append({
                "vertical": "HOTEL",
                "order_id": r.order_id,
                "hotel_id": r.hotel_id,
                "hotel_name": HOTEL_COPY.get(r.hotel_id, {}).get("name", "GO Hotel"),
                "status": r.status,
                "total_amount_minor": r.total_amount_minor,
                "currency": r.currency,
                "supplier_confirmation_no": r.supplier_confirmation_no,
                "refund": None if not refund else {"refund_id": refund.refund_id, "amount_minor": refund.amount_minor, "status": refund.status},
                "stay_credit": None if not credit else {"stay_credit_id": credit.stay_credit_id, "credit_value_minor": credit.credit_value_minor, "status": credit.status, "expires_at": _iso(credit.expires_at)},
                "review": None if not review else {"review_id": review.review_id, "status": review.status, "raw_star_input": review.raw_star_input},
                "updated_at": _iso(r.updated_at),
            })
        flights = s.scalars(select(FlightOrderRow).where(FlightOrderRow.account_id == account_id).order_by(FlightOrderRow.updated_at.desc())).all()
        for f in flights:
            seg=(f.current_itinerary or [{}])[0]
            result.append({
                "vertical":"FLIGHT", "order_id":f.order_id, "status":f.status, "total_amount_minor":f.total_amount_minor, "currency":f.currency,
                "origin":seg.get("origin"), "destination":seg.get("destination"), "departure_date":seg.get("departure_date"),
                "flight_number":seg.get("carrier_code","")+seg.get("flight_number",""), "pnr":f.pnr, "ticket_numbers":f.ticket_numbers, "updated_at":_iso(f.updated_at)
            })
        rails = s.scalars(select(RailOrderRow).where(RailOrderRow.account_id == account_id).order_by(RailOrderRow.updated_at.desc())).all()
        for rr in rails:
            j=rr.current_journey or {}
            result.append({
                "vertical":"RAIL", "order_id":rr.order_id, "status":rr.status, "total_amount_minor":rr.total_amount_minor, "currency":rr.currency,
                "origin_station":j.get("origin_station"), "destination_station":j.get("destination_station"), "travel_date":j.get("travel_date"),
                "train_no":j.get("train_no"), "seat_class":j.get("seat_class"), "booking_reference":rr.booking_reference, "ticket_numbers":rr.ticket_numbers, "updated_at":_iso(rr.updated_at)
            })
        result.sort(key=lambda x:x.get("updated_at") or "", reverse=True)
    return {"data": {"items": result, "count": len(result)}}


@router.get("/v1/consumer/orders/{order_id}/detail")
def consumer_order_detail(order_id: str, request: Request, account_id: str | None = None):
    account_id=_consumer_account(request,account_id)
    with SessionLocal() as s:
        o = s.get(OrderRow, order_id)
        if not o or o.account_id != account_id:
            not_found("ORDER_NOT_FOUND", "Order not found")
        pb = s.get(PrebookRow, o.prebook_id)
        off = s.get(OfferRow, pb.offer_id) if pb else None
        payments = s.scalars(select(PaymentRow).where(PaymentRow.order_id == order_id).order_by(PaymentRow.created_at)).all()
        refunds = s.scalars(select(RefundRow).where(RefundRow.order_id == order_id).order_by(RefundRow.created_at)).all()
        changes = s.scalars(select(OrderChangeRow).where(OrderChangeRow.order_id == order_id).order_by(OrderChangeRow.created_at)).all()
        credits = s.scalars(select(StayCreditRow).where(StayCreditRow.original_order_id == order_id).order_by(StayCreditRow.created_at)).all()
        review = s.scalar(select(ReviewSessionRow).where(ReviewSessionRow.order_id == order_id))
        events = s.scalars(select(EventRow).where(EventRow.aggregate_id == order_id).order_by(EventRow.occurred_at)).all()
        from go_hotel.compensation.service import compensation_service
        supplier_remedy=compensation_service.remedy_status(order_id,account_id)
        current_change=next((x for x in reversed(changes) if x.status=='CONFIRMED'),None)
        from go_hotel.db.models import CatalogCreditAllocationRow,CatalogCreditContractRow
        from go_hotel.services.catalog_credit_value import public as credit_public
        from go_hotel.services.catalog_stay_credit import allocation_public
        credit_allocation=s.get(CatalogCreditAllocationRow,order_id)
        from go_hotel.services.catalog_fare_snapshot import order_rule
        try:fare_rule=order_rule(order_id) if not credit_allocation else None
        except ValueError:fare_rule={'reconciliation_required':True}
        from go_hotel.services.catalog_cash_fare import status as cash_fare_status
        try: cash_after_sales=cash_fare_status(order_id)
        except ValueError: cash_after_sales={'reconciliation_required':True}
        return {"data": {
            "order": {
                "order_id": o.order_id,
                "hotel_id": o.hotel_id,
                "hotel_name": HOTEL_COPY.get(o.hotel_id, {}).get("name", "GO Hotel"),
                "status": o.status,
                "total_amount_minor": o.total_amount_minor,
                "currency": o.currency,
                "supplier_confirmation_no": o.supplier_confirmation_no,
                "created_at": _iso(o.created_at),
                "updated_at": _iso(o.updated_at),
            },
            "supplier_remedy": supplier_remedy,
            "fare_rule": fare_rule,
            "cash_after_sales": cash_after_sales,
            "credit_redemption": allocation_public(credit_allocation) if credit_allocation else None,
            "stay": None if not off else {"check_in": current_change.new_check_in if current_change else off.check_in, "check_out": current_change.new_check_out if current_change else off.check_out, "room_type_id": off.room_type_id, "meal_plan": off.meal_plan, "refundable": off.refundable},
            "payments": [{"payment_id": x.payment_id, "payment_type": x.payment_type, "amount_minor": x.amount_minor, "currency": x.currency, "status": x.status} for x in payments],
            "refunds": [{"refund_id": x.refund_id, "amount_minor": x.amount_minor, "currency": x.currency, "status": x.status, "completed_at": _iso(x.completed_at)} for x in refunds],
            "changes": [{"change_id": x.change_id, "status": x.status, "additional_payment_minor": x.additional_payment_minor, "confirmed_at": _iso(x.confirmed_at)} for x in changes],
            "stay_credits": [credit_public(x,s.get(CatalogCreditContractRow,x.stay_credit_id)) for x in credits],
            "review": None if not review else truth_service.get_review(review.review_id),
            "timeline": [{"event_type": x.event_type, "occurred_at": _iso(x.occurred_at), "payload": x.payload} for x in events[-100:]],
        }}


@router.post("/internal/v1/demo/orders/{order_id}/complete-stay")
def demo_complete_stay(order_id: str):
    """Sprint 1X deterministic E2E helper. Not a public production fulfillment endpoint."""
    order = repo.get_order(order_id)
    if not order:
        not_found("ORDER_NOT_FOUND", "Order not found")
    repo.append_event(Event(new_id("evt"), "CHECKED_IN", "HOTEL_ORDER", order_id, {}))
    repo.append_event(Event(new_id("evt"), "CHECKED_OUT", "HOTEL_ORDER", order_id, {}))
    repo.append_event(Event(new_id("evt"), "FULFILLMENT_COMPLETED", "HOTEL_ORDER", order_id, {}))
    review = truth_service.create_eligibility(order_id, True, "FIRST_INVITE")
    truth_service.send_first_invite(review["review_id"])
    truth_service.mark_not_reviewed(review["review_id"])
    return {"data": {"order_id": order_id, "fulfillment_status": "COMPLETED", "review": truth_service.get_review(review["review_id"])}}
