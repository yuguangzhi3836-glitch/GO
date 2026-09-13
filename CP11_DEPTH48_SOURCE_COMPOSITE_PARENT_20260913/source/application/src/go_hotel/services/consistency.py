from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
import json
from go_hotel.core.errors import conflict, unprocessable
from go_hotel.domain.models import PrebookStatus, new_id, Event
from go_hotel.repositories.sql import repo

def benefit_fingerprint(offer) -> str:
    # Sprint 1K baseline: benefits are not yet a first-class table in runtime; fingerprint the stable fields available now.
    raw={"fare_rule_id":offer.fare_rule_id,"meal_plan":offer.meal_plan,"refundable":offer.refundable,"cancellation_deadline":offer.cancellation_deadline}
    return sha256(json.dumps(raw,sort_keys=True).encode()).hexdigest()

class BookingConsistencyGuard:
    def validate_prebook_result(self, offer, prebook):
        if prebook.status == PrebookStatus.INVENTORY_LOST:
            return "UNCHANGED", "LOST", "UNCHANGED", "UNCHANGED"
        price = "UNCHANGED" if prebook.total_amount_minor == offer.total_amount_minor else "CHANGED"
        policy = "UNCHANGED" if (prebook.fare_rule_id in (None, offer.fare_rule_id)) else "CHANGED"
        benefit = "UNCHANGED" if (prebook.benefits_fingerprint in (None, benefit_fingerprint(offer))) else "CHANGED"
        inventory = "HELD" if prebook.inventory_held else "AVAILABLE_NOT_HELD"
        return price, inventory, policy, benefit

    def assert_order_can_be_created(self, prebook, offer):
        now=datetime.now(timezone.utc)
        exp=prebook.expires_at if prebook.expires_at.tzinfo else prebook.expires_at.replace(tzinfo=timezone.utc)
        reasons=[]
        if prebook.status != PrebookStatus.PREBOOKED: reasons.append("PREBOOK_NOT_ACTIVE")
        if exp <= now: reasons.append("QUOTE_EXPIRED")
        if prebook.total_amount_minor != offer.total_amount_minor: reasons.append("PRICE_NOT_ACCEPTED")
        if prebook.fare_rule_id not in (None, offer.fare_rule_id): reasons.append("POLICY_CHANGED")
        result="PASS" if not reasons else "FAIL"
        if reasons: unprocessable("BOOKING_CONSISTENCY_FAILED", ",".join(reasons))
        return result,reasons

    def assert_before_payment(self, order, prebook, offer):
        reasons=[]
        now=datetime.now(timezone.utc)
        exp=prebook.expires_at if prebook.expires_at.tzinfo else prebook.expires_at.replace(tzinfo=timezone.utc)
        if exp <= now: reasons.append("QUOTE_EXPIRED")
        if order.total_amount_minor != prebook.total_amount_minor: reasons.append("ORDER_PREBOOK_PRICE_MISMATCH")
        if order.currency != prebook.currency: reasons.append("ORDER_PREBOOK_CURRENCY_MISMATCH")
        result="PASS" if not reasons else "FAIL"
        repo.save_consistency_check(order_id=order.order_id, prebook_id=prebook.prebook_id, stage="BEFORE_PAYMENT", result=result, reason_codes=reasons, snapshot={"order_total":order.total_amount_minor,"prebook_total":prebook.total_amount_minor,"expires_at":prebook.expires_at.isoformat()})
        if reasons: unprocessable("BOOKING_CONSISTENCY_FAILED", ",".join(reasons))

    def assert_before_booking(self, order, prebook, offer):
        reasons=[]
        if order.total_amount_minor != prebook.total_amount_minor: reasons.append("ORDER_PREBOOK_PRICE_MISMATCH")
        if prebook.fare_rule_id not in (None, offer.fare_rule_id): reasons.append("POLICY_CHANGED_AFTER_PAYMENT")
        result="PASS" if not reasons else "FAIL"
        repo.save_consistency_check(order_id=order.order_id, prebook_id=prebook.prebook_id, stage="BEFORE_BOOK", result=result, reason_codes=reasons, snapshot={"hold_type":prebook.hold_type,"inventory_held":prebook.inventory_held,"price_locked":prebook.price_locked})
        if reasons: conflict("BOOKING_CONSISTENCY_FAILED", ",".join(reasons))

booking_consistency_guard=BookingConsistencyGuard()
