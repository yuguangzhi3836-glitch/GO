from __future__ import annotations
import asyncio
from hashlib import sha256
from go_hotel.domain.models import Offer, Prebook, new_id
from go_hotel.connectors.base import ConnectorMetadata, ConnectorCapabilities

class MockHotelConnector:
    connector_id = "conn_mock_hotel"
    metadata = ConnectorMetadata(connector_id=connector_id, display_name="GO Mock Hotel", version="1.0", capabilities=ConnectorCapabilities(webhooks=True, hard_inventory_hold=True, hard_hold_release=True, idempotent_hard_hold_release=True))

    def __init__(self):
        self.book_calls = 0
        self.cancel_calls = 0
        self._cancelled: set[str] = set()
        self._known_confirmations: set[str] = set()
        self.delay_seconds = 0.0
        self._bookings: dict[str, str] = {}
        self._rejected_bookings: set[str] = set()
        self._prebooks: dict[str, Prebook] = {}
        self._hard_hold_releases: dict[str, str] = {}
        self.release_hold_calls = 0
        self.ambiguous_release_hold = False
        self.prebook_price_delta_minor = 0
        self.inventory_available = True
        self.prebook_hold_type = "SOFT"
        self.fail_book = False
        self.ambiguous_book = False
        self.date_price_delta: dict[str, int] = {}
        self._changes: dict[str, dict] = {}
        self._rejected_changes: set[str] = set()
        self.change_calls = 0
        self.fail_change = False
        self.ambiguous_change = False

    def reset(self) -> None:
        self._changes.clear(); self._rejected_changes.clear(); self.change_calls=0; self.fail_change=False; self.ambiguous_change=False
        self._rejected_bookings.clear(); self._prebooks.clear(); self._hard_hold_releases.clear(); self.release_hold_calls=0; self.ambiguous_release_hold=False
        self.book_calls = 0; self.delay_seconds = 0.0; self._bookings.clear(); self._cancelled.clear(); self._known_confirmations.clear(); self.cancel_calls=0; self.prebook_price_delta_minor = 0; self.inventory_available = True; self.prebook_hold_type = "SOFT"; self.fail_book = False; self.ambiguous_book = False; self.date_price_delta = {}

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
            self._rejected_bookings.add(key)
            raise RuntimeError("SUPPLIER_BOOKING_REJECTED")
        if self.ambiguous_book:
            # Simulates timeout/unknown result: external state may be uncertain.
            raise TimeoutError("SUPPLIER_BOOKING_RESULT_UNKNOWN")
        confirmation = "MOCK-" + sha256(key.encode()).hexdigest()[:10].upper()
        self._bookings[key] = confirmation
        self._known_confirmations.add(confirmation)
        return confirmation

    async def prebook_with_key(self, offer: Offer, key: str) -> Prebook:
        if key not in self._prebooks:self._prebooks[key]=await self.prebook(offer)
        return self._prebooks[key]

    async def lookup_prebook(self, key: str) -> Prebook | None:
        return self._prebooks.get(key)

    async def lookup_booking(self, key: str) -> dict:
        confirmation=self._bookings.get(key)
        if confirmation:return {'status':await self.status(confirmation),'confirmation':confirmation}
        return {'status':'REJECTED' if key in self._rejected_bookings else 'UNKNOWN','confirmation':None}

    async def book_credit(self, order_id: str, prebook: Prebook, guest: dict, idempotency_key: str) -> str:
        if not guest.get('full_name') or not guest.get('mobile'):raise ValueError('HOTEL_GUEST_NAME_AND_CONTACT_REQUIRED')
        return await self.book(order_id,prebook,idempotency_key)

    async def release_prebook_hold(self, prebook_id: str, idempotency_key: str) -> str:
        if idempotency_key in self._hard_hold_releases:
            old = self._hard_hold_releases[idempotency_key]
            if old != prebook_id: raise ValueError("SUPPLIER_HARD_HOLD_RELEASE_KEY_CONFLICT")
            return "RELEASED"
        self.release_hold_calls += 1
        if self.ambiguous_release_hold:
            raise TimeoutError("SUPPLIER_HARD_HOLD_RELEASE_UNKNOWN")
        self._hard_hold_releases[idempotency_key] = prebook_id
        return "RELEASED"

    async def lookup_prebook_hold(self, prebook_id: str, idempotency_key: str) -> str:
        return "RELEASED" if self._hard_hold_releases.get(idempotency_key) == prebook_id else "UNKNOWN"

    async def status(self, confirmation_no: str) -> str: return "CANCELLED" if confirmation_no in self._cancelled else "CONFIRMED" if confirmation_no in self._known_confirmations else "NOT_FOUND"
    async def cancel(self, confirmation_no: str) -> str:
        self.cancel_calls+=1
        if confirmation_no not in self._known_confirmations:return "NOT_FOUND"
        self._cancelled.add(confirmation_no);return "CANCELLED"
    async def change(self, confirmation_no: str, new_check_in: str, new_check_out: str, idempotency_key: str | None = None) -> str:
        key=idempotency_key or confirmation_no+':'+new_check_in+':'+new_check_out
        facts={'original_confirmation':confirmation_no,'check_in':new_check_in,'check_out':new_check_out}
        if key in self._changes:
            old=self._changes[key]
            if any(old[k]!=v for k,v in facts.items()):raise ValueError('SUPPLIER_CHANGE_KEY_CONFLICT')
            return old['confirmation']
        self.change_calls+=1
        if self.delay_seconds:await asyncio.sleep(self.delay_seconds)
        if self.fail_change or confirmation_no not in self._known_confirmations or confirmation_no in self._cancelled:
            self._rejected_changes.add(key);raise RuntimeError('SUPPLIER_CHANGE_REJECTED')
        if self.ambiguous_change:raise TimeoutError('SUPPLIER_CHANGE_UNKNOWN')
        changed='MOCK-CHG-'+sha256(key.encode()).hexdigest()[:10].upper()
        self._changes[key]={**facts,'confirmation':changed,'status':'CONFIRMED'}
        self._known_confirmations.add(changed);return changed

    async def change_locked(self, confirmation_no, check_in, check_out, quoted_prebook, key):
        from datetime import datetime,timezone
        pb=next((x for x in self._prebooks.values() if x.prebook_id==quoted_prebook['prebook_id']),None)
        # A repeated already-known result does not depend on a now-expired hold.
        if key in self._changes:return await self.change(confirmation_no,check_in,check_out,key)
        if (not pb or not self.inventory_available or not pb.price_locked or
            pb.status.value!='PREBOOKED' or pb.expires_at<=datetime.now(timezone.utc) or
            (pb.offer_id,pb.total_amount_minor,pb.currency)!=(quoted_prebook['offer_id'],quoted_prebook['amount_minor'],quoted_prebook['currency'])):
            self._rejected_changes.add(key);raise RuntimeError('SUPPLIER_CHANGE_HOLD_REJECTED')
        return await self.change(confirmation_no,check_in,check_out,key)

    async def lookup_change(self,key):
        if key in self._changes:return dict(self._changes[key])
        return {'status':'REJECTED' if key in self._rejected_changes else 'UNKNOWN','confirmation':None}
    async def health(self): return {"status":"UP","connector_id":self.connector_id}

connector = MockHotelConnector()
