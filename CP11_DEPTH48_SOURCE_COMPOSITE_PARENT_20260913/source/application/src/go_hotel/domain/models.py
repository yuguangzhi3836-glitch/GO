from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import StrEnum
from typing import Any
from uuid import uuid4


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class PrebookStatus(StrEnum):
    PREBOOKED = "PREBOOKED"
    REPRICE_REQUIRED = "REPRICE_REQUIRED"
    INVENTORY_LOST = "INVENTORY_LOST"
    CONSISTENCY_FAILED = "CONSISTENCY_FAILED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


class OrderStatus(StrEnum):
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAYMENT_AUTHORIZED = "PAYMENT_AUTHORIZED"
    BOOKING_PENDING = "BOOKING_PENDING"
    CAPTURE_PENDING = "CAPTURE_PENDING"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    # Legacy states retained for backward-compatible reads/migrations.
    PAID = "PAID"
    CONFIRMATION_PENDING = "CONFIRMATION_PENDING"
    CONFIRMED = "CONFIRMED"
    CHANGE_PENDING = "CHANGE_PENDING"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    CONVERTED_TO_CREDIT = "CONVERTED_TO_CREDIT"
    FAILED = "FAILED"


class PaymentStatus(StrEnum):
    CREATED = "CREATED"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    VOIDED = "VOIDED"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"


@dataclass
class Offer:
    offer_id: str
    hotel_id: str
    room_type_id: str
    rate_plan_id: str
    total_amount_minor: int
    currency: str
    check_in: str
    check_out: str
    official_direct: bool = True
    fare_rule_id: str = "fr_standard_v1"
    connector_id: str = "conn_mock_hotel"
    supplier_id: str | None = "sup_mock"
    base_amount_minor: int | None = None
    tax_amount_minor: int = 0
    fee_amount_minor: int = 0
    meal_plan: str = "ROOM_ONLY"
    refundable: bool = True
    cancellation_deadline: str | None = None
    inventory_units: int | None = None
    expires_at: datetime = field(default_factory=lambda: now_utc() + timedelta(minutes=15))


@dataclass
class Prebook:
    prebook_id: str
    offer_id: str
    total_amount_minor: int
    currency: str
    status: PrebookStatus = PrebookStatus.PREBOOKED
    expires_at: datetime = field(default_factory=lambda: now_utc() + timedelta(minutes=10))
    hold_type: str = "SOFT"
    inventory_held: bool = False
    price_locked: bool = True
    fare_rule_id: str | None = None
    benefits_fingerprint: str | None = None


@dataclass
class Order:
    order_id: str
    prebook_id: str
    hotel_id: str
    account_id: str
    total_amount_minor: int
    currency: str
    status: OrderStatus = OrderStatus.PAYMENT_PENDING
    supplier_confirmation_no: str | None = None
    supplier_id: str | None = "sup_mock"


@dataclass
class Payment:
    payment_id: str
    order_id: str
    amount_minor: int
    currency: str
    status: PaymentStatus = PaymentStatus.CREATED


@dataclass
class Event:
    event_id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    payload: dict[str, Any]
    occurred_at: datetime = field(default_factory=now_utc)


class RefundStatus(StrEnum):
    REQUESTED = "REQUESTED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class StayCreditStatus(StrEnum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    REDEEMING = "REDEEMING"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"

@dataclass
class Refund:
    refund_id: str
    order_id: str
    payment_id: str
    amount_minor: int
    currency: str
    status: RefundStatus = RefundStatus.REQUESTED

@dataclass
class StayCredit:
    stay_credit_id: str
    original_order_id: str
    account_id: str
    property_id: str
    credit_value_minor: int
    currency: str
    valid_from: datetime
    expires_at: datetime
    status: StayCreditStatus = StayCreditStatus.ACTIVE
