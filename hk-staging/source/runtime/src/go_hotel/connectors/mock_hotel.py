from __future__ import annotations
import asyncio
from hashlib import sha256
from go_hotel.domain.models import Offer, Prebook, new_id
from go_hotel.connectors.base import ConnectorMetadata, ConnectorCapabilities

class MockHotelConnector:
    connector_id = "conn_mock_hotel"
    metadata = ConnectorMetadata(connector_id=connector_id, display_name="GO Mock Hotel", version="1.0", capabilities=ConnectorCapabilities(webhooks=True))

    def __init__(self):
        self.book_calls = 0
        self.delay_seconds = 0.0
        self._bookings: dict[str, str] = {}
        self.prebook_price_delta_minor = 0
        self.inventory_available = True
        self.prebook_hold_type = "SOFT"
        self.fail_book = False
        self.ambiguous_book = False
        self.date_price_delta: dict[str, int] = {}

    def reset(self) -> None:
        self.book_calls = 0; self.delay_seconds = 0.0; self._bookings.clear(); self.prebook_price_delta_minor = 0; self.inventory_available = True; self.prebook_hold_type = "SOFT"; self.fail_book = False; self.ambiguous_book = False; self.date_price_delta = {}

    async def search(self, city_code: str, check_in: str, check_out: str, currency: str) -> list[Offer]:
        if city_code != "TYO": return []
        return [Offer(new_id("off"), "htl_conrad_tokyo", "room_bay_king", "rate_go_standard", 1_443_200 + self.date_price_delta.get(check_in, 0), currency, check_in, check_out)]

    async def prebook(self, offer: Offer) -> Prebook:
        if not self.inventory_available:
            return Prebook(new_id("pb"), offer.offer_id, offer.total_amount_minor, offer.currency, status=__import__("go_hotel.domain.models", fromlist=["PrebookStatus"]).PrebookStatus.INVENTORY_LOST, inventory_held=False, price_locked=False, hold_type=self.prebook_hold_type, fare_rule_id=offer.fare_rule_id)
        amount = offer.total_amount_minor + self.prebook_price_delta_minor
        return Prebook(new_id("pb"), offer.offer_id, amount, offer.currency, inventory_held=(self.prebook_hold_type == "HARD"), price_locked=True, hold_type=self.prebook_hold_type, fare_rule_id=offer.fare_rule_id)

    async def book(self, order_id: str, prebook: Prebook, idempotency_key: str | None = None) -> str:
        key = idempotency_key or order_id
        if key in self._bookings: return self._bookings[key]
        self.book_calls += 1
        if self.delay_seconds: await asyncio.sleep(self.delay_seconds)
        if self.fail_book:
            raise RuntimeError("SUPPLIER_BOOKING_REJECTED")
        if self.ambiguous_book:
            # Simulates timeout/unknown result: external state may be uncertain.
            raise TimeoutError("SUPPLIER_BOOKING_RESULT_UNKNOWN")
        confirmation = "MOCK-" + sha256(key.encode()).hexdigest()[:10].upper()
        self._bookings[key] = confirmation
        return confirmation

    async def status(self, confirmation_no: str) -> str: return "CONFIRMED" if confirmation_no in self._bookings.values() else "NOT_FOUND"
    async def cancel(self, confirmation_no: str) -> str: return "CANCELLED"
    async def change(self, confirmation_no: str, new_check_in: str, new_check_out: str, idempotency_key: str | None = None) -> str:
        if confirmation_no not in self._bookings.values(): raise RuntimeError("SUPPLIER_BOOKING_NOT_FOUND")
        return confirmation_no + "-CHG"
    async def health(self): return {"status":"UP","connector_id":self.connector_id}

connector = MockHotelConnector()
