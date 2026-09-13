from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

from sqlalchemy import select

from go_hotel.connectors.base import ConnectorCapabilities, ConnectorMetadata
from go_hotel.db.models import (
    HostedDirectHotelRow,
    HostedDirectInventoryPoolRow,
    HostedDirectRateVariantRow,
    HostedDirectRoomOfferRow,
    HostedInventoryDayRow,
    HostedRateCalendarDayRow,
    OfferRow,
)
from go_hotel.db.session import SessionLocal
from go_hotel.domain.models import Offer, Prebook, PrebookStatus, new_id

HOTEL_ID = "HRBUB"
HOSTED_HOTEL_ID = "hdh_aoluguya_r31_test"
SLUG = "aoluguya-harbin"
SUPPLIER_ID = "sup_aoluguya_test"
SOURCE_URL = "https://www.hyatt.com/unbound-collection/en-US/hrbub-aoluguya/rooms"


def _now():
    return datetime.now(timezone.utc)


def _days(start: str, end: str):
    current = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    while current < stop:
        yield current.isoformat()
        current += timedelta(days=1)


def _oracle():
    p = Path(__file__).resolve().parents[1] / "data" / "aoluguya_official_room_oracle_20260906.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _room_id(i: int) -> str:
    return f"go-aol-room-{i:02d}"


def _pool_id(i: int) -> str:
    return f"hip_aol_r31_{i:02d}"


def _rate_id(i: int, plan: str) -> str:
    return f"hrv_aol_r31_{i:02d}_{plan}"


def _hosted_offer_id(i: int, plan: str) -> str:
    return f"hdo_aol_r31_{i:02d}_{plan}"


def room_catalog() -> list[dict]:
    data = _oracle()
    rooms = []
    for i, row in enumerate(data["rooms"], 1):
        rooms.append({
            "room_type_id": _room_id(i),
            "official_name": row[0],
            "area": row[1],
            "view": row[2],
            "source": data["source"],
            "source_url": data["rooms_url"],
            "captured_at": data["captured_at"],
        })
    return rooms


class AoluguyaHostedTestConnector:
    connector_id = "conn_aoluguya_hosted_test"
    metadata = ConnectorMetadata(
        connector_id=connector_id,
        display_name="AOLUGUYA Hosted Direct TEST Adapter",
        version="R3.1",
        capabilities=ConnectorCapabilities(webhooks=False, idempotent_book=True),
    )

    def __init__(self):
        self.book_calls = 0
        self._confirmations: set[str] = set()

    def reset(self):
        self.book_calls = 0
        self._confirmations.clear()

    def _ensure_catalog_and_calendar(self, check_in: str, check_out: str) -> None:
        today = _now()
        with SessionLocal.begin() as s:
            hotel = s.get(HostedDirectHotelRow, HOSTED_HOTEL_ID)
            if not hotel:
                s.add(HostedDirectHotelRow(
                    hosted_hotel_id=HOSTED_HOTEL_ID,
                    supplier_name="哈尔滨敖麓谷雅酒店",
                    page_slug=SLUG,
                    city="哈尔滨",
                    contact_json={"test_data": True, "source": "HYATT_OFFICIAL_WEB_ORACLE", "real_supplier_call": False},
                    state="TEST_ONLY_NOT_LIVE",
                    updated_at=today,
                ))
            for i, room in enumerate(room_catalog(), 1):
                pool_id = _pool_id(i)
                pool = s.get(HostedDirectInventoryPoolRow, pool_id)
                if not pool:
                    s.add(HostedDirectInventoryPoolRow(
                        inventory_pool_id=pool_id,
                        hosted_hotel_id=HOSTED_HOTEL_ID,
                        physical_room_key=room["room_type_id"],
                        physical_room_name=room["official_name"],
                        room_details_json={**room, "test_data": True, "real_inventory": False},
                        capacity_total=3,
                        capacity_available=3,
                        updated_at=today,
                    ))
                # Inventory is shared by both test rate plans. Create each dated
                # inventory row once per physical room, before rate-plan expansion.
                s.flush()
                for ds in _days(check_in, check_out):
                    inv = s.scalar(select(HostedInventoryDayRow).where(
                        HostedInventoryDayRow.inventory_pool_id == pool_id,
                        HostedInventoryDayRow.stay_date == ds,
                    ))
                    if not inv:
                        s.add(HostedInventoryDayRow(
                            inventory_day_id=new_id("hid"), inventory_pool_id=pool_id, stay_date=ds,
                            capacity_total=3, capacity_available=3, sale_state="TEST_OPEN", updated_at=today,
                        ))
                s.flush()

                for plan, breakfast, multiplier in (("flex", 0, 1.0), ("breakfast", 2, 1.12)):
                    hosted_offer_id = _hosted_offer_id(i, plan)
                    base_price = 68000 + i * 8000
                    price = int(base_price * multiplier)
                    hdo = s.get(HostedDirectRoomOfferRow, hosted_offer_id)
                    if not hdo:
                        s.add(HostedDirectRoomOfferRow(
                            hosted_offer_id=hosted_offer_id,
                            hosted_hotel_id=HOSTED_HOTEL_ID,
                            room_name=room["official_name"],
                            rate_name="TEST Flexible" if plan == "flex" else "TEST Breakfast for 2",
                            price_minor=price,
                            currency="CNY",
                            inventory=3,
                            cancellation_policy="TEST ONLY · 入住前24小时可取消",
                            state="TEST_ONLY",
                            updated_at=today,
                        ))
                    rid = _rate_id(i, plan)
                    rv = s.get(HostedDirectRateVariantRow, rid)
                    if not rv:
                        s.add(HostedDirectRateVariantRow(
                            rate_variant_id=rid,
                            inventory_pool_id=pool_id,
                            hosted_offer_id=hosted_offer_id,
                            breakfast_count=breakfast,
                            benefits_json=[{"code": "TEST_ONLY", "label": "测试报价，非真实酒店报价"}],
                            payment_mode="TEST_ONLY",
                            state="TEST_ONLY",
                        ))
                    s.flush()
                    for ds in _days(check_in, check_out):
                        rate = s.scalar(select(HostedRateCalendarDayRow).where(
                            HostedRateCalendarDayRow.rate_variant_id == rid,
                            HostedRateCalendarDayRow.stay_date == ds,
                        ))
                        if not rate:
                            s.add(HostedRateCalendarDayRow(
                                rate_calendar_day_id=new_id("hrc"), rate_variant_id=rid, stay_date=ds,
                                price_minor=price, sale_state="TEST_OPEN", min_stay=1, max_stay=30,
                                advance_min_days=0, advance_max_days=365, max_adults=4, max_children=2,
                                extra_bed_allowed=False, updated_at=today,
                            ))
                    s.flush()

    async def search(self, city_code: str, check_in: str, check_out: str, currency: str) -> list[Offer]:
        if city_code != "HRB" or currency != "CNY":
            return []
        if date.fromisoformat(check_out) <= date.fromisoformat(check_in):
            return []
        self._ensure_catalog_and_calendar(check_in, check_out)
        nights = list(_days(check_in, check_out))
        offers: list[Offer] = []
        with SessionLocal() as s:
            for i, room in enumerate(room_catalog(), 1):
                for plan, meal in (("flex", "ROOM_ONLY"), ("breakfast", "BREAKFAST_2")):
                    pool_id = _pool_id(i)
                    rid = _rate_id(i, plan)
                    inv_rows = s.scalars(select(HostedInventoryDayRow).where(
                        HostedInventoryDayRow.inventory_pool_id == pool_id,
                        HostedInventoryDayRow.stay_date.in_(nights),
                    )).all()
                    rate_rows = s.scalars(select(HostedRateCalendarDayRow).where(
                        HostedRateCalendarDayRow.rate_variant_id == rid,
                        HostedRateCalendarDayRow.stay_date.in_(nights),
                    )).all()
                    if len(inv_rows) != len(nights) or len(rate_rows) != len(nights):
                        continue
                    availability = min(r.capacity_available for r in inv_rows)
                    if availability <= 0 or any(r.sale_state != "TEST_OPEN" for r in inv_rows):
                        continue
                    if any(r.sale_state != "TEST_OPEN" for r in rate_rows):
                        continue
                    total = sum(r.price_minor for r in rate_rows)
                    offer_key = f"{room['room_type_id']}:{rid}:{check_in}:{check_out}:{currency}"
                    offers.append(Offer(
                        offer_id="off_aol_test_" + sha256(offer_key.encode()).hexdigest()[:20],
                        hotel_id=HOTEL_ID,
                        room_type_id=room["room_type_id"],
                        rate_plan_id=rid,
                        total_amount_minor=total,
                        currency=currency,
                        check_in=check_in,
                        check_out=check_out,
                        official_direct=True,
                        fare_rule_id="fr_aol_test_24h",
                        connector_id=self.connector_id,
                        supplier_id=SUPPLIER_ID,
                        base_amount_minor=total,
                        tax_amount_minor=0,
                        fee_amount_minor=0,
                        meal_plan=meal,
                        refundable=True,
                        inventory_units=availability,
                        cancellation_deadline=f"{check_in}T00:00:00+08:00",
                    ))
        return offers

    async def prebook(self, offer: Offer) -> Prebook:
        nights = list(_days(offer.check_in, offer.check_out))
        pool_id = _pool_id(int(offer.room_type_id.rsplit("-", 1)[1]))
        with SessionLocal() as s:
            rows = s.scalars(select(HostedInventoryDayRow).where(
                HostedInventoryDayRow.inventory_pool_id == pool_id,
                HostedInventoryDayRow.stay_date.in_(nights),
            )).all()
            available = len(rows) == len(nights) and all(r.capacity_available > 0 and r.sale_state == "TEST_OPEN" for r in rows)
        if not available:
            return Prebook(new_id("pb"), offer.offer_id, offer.total_amount_minor, offer.currency,
                           status=PrebookStatus.INVENTORY_LOST, inventory_held=False, price_locked=False,
                           hold_type="SOFT", fare_rule_id=offer.fare_rule_id)
        return Prebook(new_id("pb"), offer.offer_id, offer.total_amount_minor, offer.currency,
                       status=PrebookStatus.PREBOOKED, inventory_held=False, price_locked=True,
                       hold_type="SOFT", fare_rule_id=offer.fare_rule_id)

    async def book(self, order_id: str, prebook: Prebook, idempotency_key: str | None = None) -> str:
        if not prebook:
            raise RuntimeError("PREBOOK_REQUIRED")
        with SessionLocal.begin() as s:
            offer = s.get(OfferRow, prebook.offer_id)
            if not offer or offer.connector_id != self.connector_id:
                raise RuntimeError("AOLUGUYA_TEST_OFFER_REQUIRED")
            nights = list(_days(offer.check_in, offer.check_out))
            pool_id = _pool_id(int(offer.room_type_id.rsplit("-", 1)[1]))
            rows = s.scalars(select(HostedInventoryDayRow).where(
                HostedInventoryDayRow.inventory_pool_id == pool_id,
                HostedInventoryDayRow.stay_date.in_(nights),
            ).with_for_update()).all()
            if len(rows) != len(nights) or any(r.capacity_available <= 0 for r in rows):
                raise RuntimeError("INVENTORY_RACE_LOST")
            for r in rows:
                r.capacity_available -= 1
                r.updated_at = _now()
        self.book_calls += 1
        confirmation = "TEST-AOL-" + sha256((idempotency_key or order_id).encode()).hexdigest()[:12].upper()
        self._confirmations.add(confirmation)
        return confirmation

    async def status(self, confirmation_no: str) -> str:
        return "CONFIRMED" if confirmation_no.startswith("TEST-AOL-") else "NOT_FOUND"

    async def cancel(self, confirmation_no: str) -> str:
        return "CANCELLED"

    async def change(self, confirmation_no: str, new_check_in: str, new_check_out: str, idempotency_key: str | None = None) -> str:
        raise RuntimeError("AOLUGUYA_TEST_CHANGE_NOT_IMPLEMENTED")

    async def health(self):
        return {"status": "UP", "connector_id": self.connector_id, "test_only": True, "real_supplier_call": False}


connector = AoluguyaHostedTestConnector()
