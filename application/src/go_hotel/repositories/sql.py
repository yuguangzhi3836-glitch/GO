from __future__ import annotations
from hashlib import sha256
import json
from datetime import timedelta
from sqlalchemy import select, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from go_hotel.db.models import (
    OfferRow, PrebookRow, OrderRow, PaymentRow, EventRow, OutboxRow, IdempotencyRow,
    ExternalOperationRow, WebhookInboxRow, ConnectorCursorRow, ConnectorCertificationRow, ConnectorHealthRow, ReconciliationRunRow,
    PrebookRevalidationRow, BookingConsistencyCheckRow, PaymentOrchestrationRow,
)
from go_hotel.db.session import SessionLocal
from go_hotel.domain.models import Offer, Prebook, Order, Payment, Event, PrebookStatus, OrderStatus, PaymentStatus, now_utc, new_id
from go_hotel.core.config import settings

class SqlRepository:
    def _offer(self, r: OfferRow) -> Offer:
        return Offer(offer_id=r.offer_id, hotel_id=r.hotel_id, room_type_id=r.room_type_id, rate_plan_id=r.rate_plan_id, total_amount_minor=r.total_amount_minor, currency=r.currency, check_in=r.check_in, check_out=r.check_out, official_direct=r.official_direct, fare_rule_id=r.fare_rule_id, connector_id=r.connector_id, supplier_id=r.supplier_id, base_amount_minor=r.base_amount_minor, tax_amount_minor=r.tax_amount_minor, fee_amount_minor=r.fee_amount_minor, meal_plan=r.meal_plan, refundable=r.refundable, cancellation_deadline=r.cancellation_deadline, inventory_units=r.inventory_units, expires_at=r.expires_at)

    def _prebook(self, r: PrebookRow) -> Prebook:
        return Prebook(r.prebook_id, r.offer_id, r.total_amount_minor, r.currency, PrebookStatus(r.status), r.expires_at, r.hold_type, r.inventory_held, r.price_locked, r.fare_rule_id, r.benefits_fingerprint)

    def _order(self, r: OrderRow) -> Order:
        return Order(order_id=r.order_id, prebook_id=r.prebook_id, hotel_id=r.hotel_id, account_id=r.account_id, total_amount_minor=r.total_amount_minor, currency=r.currency, status=OrderStatus(r.status), supplier_confirmation_no=r.supplier_confirmation_no, supplier_id=r.supplier_id)

    def _payment(self, r: PaymentRow) -> Payment:
        return Payment(r.payment_id, r.order_id, r.amount_minor, r.currency, PaymentStatus(r.status))

    def save_offer_with_event(self, offer: Offer, event: Event) -> None:
        with SessionLocal.begin() as s:
            s.merge(OfferRow(offer_id=offer.offer_id, hotel_id=offer.hotel_id, room_type_id=offer.room_type_id, rate_plan_id=offer.rate_plan_id, total_amount_minor=offer.total_amount_minor, currency=offer.currency, check_in=offer.check_in, check_out=offer.check_out, official_direct=offer.official_direct, fare_rule_id=offer.fare_rule_id, connector_id=offer.connector_id, supplier_id=offer.supplier_id, base_amount_minor=offer.base_amount_minor, tax_amount_minor=offer.tax_amount_minor, fee_amount_minor=offer.fee_amount_minor, meal_plan=offer.meal_plan, refundable=offer.refundable, cancellation_deadline=offer.cancellation_deadline, inventory_units=offer.inventory_units, expires_at=offer.expires_at, created_at=event.occurred_at))
            self._append_event_and_outbox(s, event)

    def get_offer(self, offer_id: str) -> Offer | None:
        with SessionLocal() as s:
            r = s.get(OfferRow, offer_id)
            return self._offer(r) if r else None

    def save_prebook_with_event(self, pb: Prebook, event: Event) -> None:
        with SessionLocal.begin() as s:
            s.add(PrebookRow(prebook_id=pb.prebook_id, offer_id=pb.offer_id, total_amount_minor=pb.total_amount_minor, currency=pb.currency, status=pb.status.value, expires_at=pb.expires_at, created_at=event.occurred_at, hold_type=pb.hold_type, inventory_held=pb.inventory_held, price_locked=pb.price_locked, fare_rule_id=pb.fare_rule_id, benefits_fingerprint=pb.benefits_fingerprint))
            self._append_event_and_outbox(s, event)

    def get_prebook(self, prebook_id: str) -> Prebook | None:
        with SessionLocal() as s:
            r = s.get(PrebookRow, prebook_id)
            return self._prebook(r) if r else None


    def save_prebook_revalidation(self, *, revalidation_id: str, offer: Offer, prebook: Prebook | None, price_status: str, inventory_status: str, policy_status: str, benefit_status: str, snapshot: dict) -> None:
        with SessionLocal.begin() as s:
            s.add(PrebookRevalidationRow(revalidation_id=revalidation_id, offer_id=offer.offer_id, prebook_id=prebook.prebook_id if prebook else None, connector_id=offer.connector_id, original_total_minor=offer.total_amount_minor, supplier_total_minor=prebook.total_amount_minor if prebook else None, currency=offer.currency, price_status=price_status, inventory_status=inventory_status, policy_status=policy_status, benefit_status=benefit_status, hold_type=prebook.hold_type if prebook else "NONE", lock_expires_at=prebook.expires_at if prebook else None, snapshot=snapshot, created_at=now_utc()))

    def save_consistency_check(self, *, order_id: str, prebook_id: str, stage: str, result: str, reason_codes: list[str], snapshot: dict) -> str:
        check_id = new_id("bcc")
        with SessionLocal.begin() as s:
            s.add(BookingConsistencyCheckRow(check_id=check_id, order_id=order_id, prebook_id=prebook_id, stage=stage, result=result, reason_codes=reason_codes, snapshot=snapshot, checked_at=now_utc()))
        return check_id

    def get_latest_revalidation_for_prebook(self, prebook_id: str) -> dict | None:
        with SessionLocal() as s:
            r=s.scalar(select(PrebookRevalidationRow).where(PrebookRevalidationRow.prebook_id==prebook_id).order_by(PrebookRevalidationRow.created_at.desc()))
            if not r: return None
            return {"revalidation_id":r.revalidation_id,"price_status":r.price_status,"inventory_status":r.inventory_status,"policy_status":r.policy_status,"benefit_status":r.benefit_status,"hold_type":r.hold_type,"lock_expires_at":r.lock_expires_at,"snapshot":r.snapshot}
    def create_order_with_event(self, order: Order, event: Event, fare_acceptance=None) -> None:
        now = event.occurred_at
        with SessionLocal.begin() as s:
            row=OrderRow(order_id=order.order_id, prebook_id=order.prebook_id, hotel_id=order.hotel_id, account_id=order.account_id, total_amount_minor=order.total_amount_minor, currency=order.currency, status=order.status.value, supplier_confirmation_no=order.supplier_confirmation_no, supplier_id=order.supplier_id, version=1, created_at=now, updated_at=now)
            s.add(row)
            if fare_acceptance is not None:
                from go_hotel.services.catalog_fare_snapshot import snapshot_order_in_session
                snap=snapshot_order_in_session(s,row,**fare_acceptance)
                self._append_event_and_outbox(s,Event(new_id('evt'),'ORDER_FARE_RULE_ACCEPTED','HOTEL_ORDER',order.order_id,
                    {'version_id':snap.version_id,'snapshot_hash':snap.snapshot_hash,'acceptance_kind':snap.acceptance_kind}))
            self._append_event_and_outbox(s, event)

    def get_order(self, order_id: str) -> Order | None:
        with SessionLocal() as s:
            r = s.get(OrderRow, order_id)
            return self._order(r) if r else None

    def get_payment_by_operation(self, operation_id: str) -> Payment | None:
        with SessionLocal() as s:
            r = s.scalar(select(PaymentRow).where(PaymentRow.external_operation_id == operation_id))
            return self._payment(r) if r else None

    def get_captured_payment_for_order(self, order_id: str) -> Payment | None:
        with SessionLocal() as s:
            r = s.scalar(select(PaymentRow).where(PaymentRow.order_id == order_id, PaymentRow.status == PaymentStatus.CAPTURED.value).order_by(PaymentRow.created_at.desc()))
            return self._payment(r) if r else None

    def save_failed_payment(self, payment: Payment, operation_id: str, event: Event) -> None:
        with SessionLocal.begin() as s:
            if not s.get(PaymentRow, payment.payment_id):
                s.add(PaymentRow(payment_id=payment.payment_id, order_id=payment.order_id, payment_type="ORIGINAL_BOOKING", external_operation_id=operation_id, amount_minor=payment.amount_minor, currency=payment.currency, status=payment.status.value, created_at=now_utc()))
            self._append_event_and_outbox(s, event)

    def commit_payment_saga(self, payment: Payment, operation_id: str, events: list[Event]) -> Order:
        """Atomic local commit after provider success. Safe to call repeatedly during recovery."""
        with SessionLocal.begin() as s:
            r = s.execute(select(OrderRow).where(OrderRow.order_id == payment.order_id).with_for_update()).scalar_one()
            existing = s.scalar(select(PaymentRow).where(PaymentRow.external_operation_id == operation_id))
            if existing is None:
                s.add(PaymentRow(payment_id=payment.payment_id, order_id=payment.order_id, payment_type="ORIGINAL_BOOKING", external_operation_id=operation_id, amount_minor=payment.amount_minor, currency=payment.currency, status=payment.status.value, created_at=now_utc()))
            if r.status == OrderStatus.PAYMENT_PENDING.value:
                r.status = OrderStatus.PAID.value
                r.updated_at = now_utc()
                r.version += 1
                for e in events:
                    if s.get(EventRow, e.event_id) is None:
                        self._append_event_and_outbox(s, e)
            elif r.status not in (OrderStatus.PAID.value, OrderStatus.CONFIRMATION_PENDING.value, OrderStatus.CONFIRMED.value):
                raise RuntimeError(f"Cannot apply captured payment in order state {r.status}")
            op = s.get(ExternalOperationRow, operation_id)
            op.status = "COMPLETED"
            op.completed_at = now_utc()
            op.updated_at = now_utc()
            return self._order(r)

    def get_authorized_payment_for_order(self, order_id: str) -> Payment | None:
        with SessionLocal() as s:
            r = s.scalar(select(PaymentRow).where(PaymentRow.order_id == order_id, PaymentRow.status == PaymentStatus.AUTHORIZED.value).order_by(PaymentRow.created_at.desc()))
            return self._payment(r) if r else None

    def commit_authorization_saga(self, payment: Payment, operation_id: str) -> Order:
        """Persist authorization only. No customer funds are captured here."""
        with SessionLocal.begin() as s:
            r = s.execute(select(OrderRow).where(OrderRow.order_id == payment.order_id).with_for_update()).scalar_one()
            existing = s.scalar(select(PaymentRow).where(PaymentRow.external_operation_id == operation_id))
            if existing is None:
                s.add(PaymentRow(payment_id=payment.payment_id, order_id=payment.order_id, payment_type="ORIGINAL_BOOKING", external_operation_id=operation_id, amount_minor=payment.amount_minor, currency=payment.currency, status=PaymentStatus.AUTHORIZED.value, created_at=now_utc()))
            else:
                existing.status = PaymentStatus.AUTHORIZED.value
            if r.status == OrderStatus.PAYMENT_PENDING.value:
                r.status = OrderStatus.PAYMENT_AUTHORIZED.value; r.updated_at = now_utc(); r.version += 1
                self._append_event_and_outbox(s, Event(new_id("evt"), "PAYMENT_AUTHORIZED", "HOTEL_ORDER", r.order_id, {"payment_id":payment.payment_id,"amount_minor":payment.amount_minor}))
            orch=s.scalar(select(PaymentOrchestrationRow).where(PaymentOrchestrationRow.order_id==r.order_id))
            if orch is None:
                s.add(PaymentOrchestrationRow(orchestration_id=new_id("porch"), order_id=r.order_id, payment_id=payment.payment_id, phase="AUTHORIZED", compensation_status="NONE", created_at=now_utc(), updated_at=now_utc()))
            else:
                orch.payment_id=payment.payment_id; orch.phase="AUTHORIZED"; orch.updated_at=now_utc()
            op=s.get(ExternalOperationRow, operation_id); op.status="COMPLETED"; op.completed_at=now_utc(); op.updated_at=now_utc()
            return self._order(r)

    def commit_supplier_booking_before_capture(self, operation_id: str, confirmation_no: str) -> Order:
        with SessionLocal.begin() as s:
            op=s.execute(select(ExternalOperationRow).where(ExternalOperationRow.operation_id==operation_id).with_for_update()).scalar_one()
            r=s.execute(select(OrderRow).where(OrderRow.order_id==op.aggregate_id).with_for_update()).scalar_one()
            if r.status not in (OrderStatus.BOOKING_PENDING.value, OrderStatus.CAPTURE_PENDING.value, OrderStatus.RECONCILIATION_REQUIRED.value):
                raise RuntimeError(f"Cannot apply supplier booking in state {r.status}")
            r.supplier_confirmation_no=confirmation_no; r.status=OrderStatus.CAPTURE_PENDING.value; r.updated_at=now_utc(); r.version += 1
            self._append_event_and_outbox(s, Event(new_id("evt"), "SUPPLIER_CONFIRMATION_RECEIVED", "HOTEL_ORDER", r.order_id, {"confirmation_no":confirmation_no}))
            orch=s.scalar(select(PaymentOrchestrationRow).where(PaymentOrchestrationRow.order_id==r.order_id))
            if orch: orch.phase="SUPPLIER_BOOKED_CAPTURE_PENDING"; orch.supplier_confirmation_no=confirmation_no; orch.updated_at=now_utc()
            op.status="COMPLETED"; op.external_reference=confirmation_no; op.result_payload={"confirmation_no":confirmation_no}; op.completed_at=now_utc(); op.updated_at=now_utc()
            return self._order(r)

    def commit_capture_after_booking(self, payment_id: str, capture_operation_id: str) -> Order:
        with SessionLocal.begin() as s:
            p=s.execute(select(PaymentRow).where(PaymentRow.payment_id==payment_id).with_for_update()).scalar_one()
            r=s.execute(select(OrderRow).where(OrderRow.order_id==p.order_id).with_for_update()).scalar_one()
            if r.status == OrderStatus.CONFIRMED.value: return self._order(r)
            if r.status != OrderStatus.CAPTURE_PENDING.value: raise RuntimeError(f"Cannot capture in order state {r.status}")
            p.status=PaymentStatus.CAPTURED.value
            r.status=OrderStatus.CONFIRMED.value; r.updated_at=now_utc(); r.version += 1
            pb=s.get(PrebookRow, r.prebook_id)
            if pb: pb.status=PrebookStatus.CONSUMED.value
            self._append_event_and_outbox(s, Event(new_id("evt"), "PAYMENT_CAPTURED", "HOTEL_ORDER", r.order_id, {"payment_id":p.payment_id,"amount_minor":p.amount_minor}))
            self._append_event_and_outbox(s, Event(new_id("evt"), "ORDER_CONFIRMED", "HOTEL_ORDER", r.order_id, {"confirmation_no":r.supplier_confirmation_no}))
            orch=s.scalar(select(PaymentOrchestrationRow).where(PaymentOrchestrationRow.order_id==r.order_id))
            if orch: orch.phase="COMPLETED"; orch.updated_at=now_utc()
            op=s.get(ExternalOperationRow, capture_operation_id)
            if op: op.status="COMPLETED"; op.completed_at=now_utc(); op.updated_at=now_utc()
            return self._order(r)

    def fail_booking_and_void_authorization(self, order_id: str, payment_id: str, reason: str) -> Order:
        with SessionLocal.begin() as s:
            r=s.execute(select(OrderRow).where(OrderRow.order_id==order_id).with_for_update()).scalar_one()
            p=s.execute(select(PaymentRow).where(PaymentRow.payment_id==payment_id).with_for_update()).scalar_one()
            p.status=PaymentStatus.VOIDED.value; r.status=OrderStatus.FAILED.value; r.updated_at=now_utc(); r.version += 1
            self._append_event_and_outbox(s, Event(new_id("evt"), "SUPPLIER_BOOKING_FAILED", "HOTEL_ORDER", order_id, {"reason":reason}))
            self._append_event_and_outbox(s, Event(new_id("evt"), "PAYMENT_AUTHORIZATION_VOIDED", "HOTEL_ORDER", order_id, {"payment_id":payment_id}))
            self._append_event_and_outbox(s, Event(new_id("evt"), "BOOKING_FAILED_NO_CHARGE", "HOTEL_ORDER", order_id, {}))
            orch=s.scalar(select(PaymentOrchestrationRow).where(PaymentOrchestrationRow.order_id==order_id))
            if orch: orch.phase="BOOKING_FAILED_VOIDED"; orch.compensation_status="AUTH_VOIDED"; orch.last_error=reason; orch.updated_at=now_utc()
            return self._order(r)

    def mark_order_reconciliation_required(self, order_id: str, phase: str, error: str, confirmation_no: str | None=None) -> None:
        with SessionLocal.begin() as s:
            r=s.execute(select(OrderRow).where(OrderRow.order_id==order_id).with_for_update()).scalar_one()
            r.status=OrderStatus.RECONCILIATION_REQUIRED.value; r.updated_at=now_utc(); r.version += 1
            if confirmation_no: r.supplier_confirmation_no=confirmation_no
            self._append_event_and_outbox(s, Event(new_id("evt"), "BOOKING_PAYMENT_RECONCILIATION_REQUIRED", "HOTEL_ORDER", order_id, {"phase":phase,"error":error,"confirmation_no":confirmation_no}))
            orch=s.scalar(select(PaymentOrchestrationRow).where(PaymentOrchestrationRow.order_id==order_id))
            if orch: orch.phase=phase; orch.last_error=error; orch.supplier_confirmation_no=confirmation_no or orch.supplier_confirmation_no; orch.updated_at=now_utc()

    def orchestration_for_order(self, order_id: str) -> dict | None:
        with SessionLocal() as s:
            r=s.scalar(select(PaymentOrchestrationRow).where(PaymentOrchestrationRow.order_id==order_id))
            if not r: return None
            return {"orchestration_id":r.orchestration_id,"order_id":r.order_id,"payment_id":r.payment_id,"phase":r.phase,"supplier_confirmation_no":r.supplier_confirmation_no,"compensation_status":r.compensation_status,"last_error":r.last_error}

    def start_confirmation_saga(self, order_id: str, request_hash: str) -> tuple[dict, bool]:
        business_key = f"SUPPLIER_BOOK:{order_id}"
        operation_id = new_id("op")
        now = now_utc()
        try:
            with SessionLocal.begin() as s:
                r = s.execute(select(OrderRow).where(OrderRow.order_id == order_id).with_for_update()).scalar_one_or_none()
                if r is None:
                    return {"missing": True}, False
                existing = s.scalar(select(ExternalOperationRow).where(ExternalOperationRow.business_key == business_key))
                if existing:
                    return self._operation_dict(existing), False
                if r.status == OrderStatus.CONFIRMED.value:
                    return {"already_confirmed": True}, False
                if r.status != OrderStatus.PAYMENT_AUTHORIZED.value:
                    return {"invalid_state": r.status}, False
                op = ExternalOperationRow(operation_id=operation_id, operation_type="SUPPLIER_BOOK", aggregate_id=order_id, business_key=business_key, request_hash=request_hash, status="STARTED", attempt_count=1, request_payload={"order_id": order_id}, created_at=now, updated_at=now)
                s.add(op)
                r.status = OrderStatus.BOOKING_PENDING.value
                r.updated_at = now
                r.version += 1
                self._append_event_and_outbox(s, Event(new_id("evt"), "SUPPLIER_BOOKING_STARTED", "HOTEL_ORDER", order_id, {}))
                return self._operation_dict(op), True
        except IntegrityError:
            with SessionLocal() as s:
                existing = s.scalar(select(ExternalOperationRow).where(ExternalOperationRow.business_key == business_key))
                return self._operation_dict(existing), False

    def commit_confirmation_saga(self, operation_id: str, confirmation_no: str) -> Order:
        with SessionLocal.begin() as s:
            op = s.execute(select(ExternalOperationRow).where(ExternalOperationRow.operation_id == operation_id).with_for_update()).scalar_one()
            r = s.execute(select(OrderRow).where(OrderRow.order_id == op.aggregate_id).with_for_update()).scalar_one()
            if r.status == OrderStatus.CONFIRMED.value:
                op.status = "COMPLETED"; op.completed_at = now_utc(); op.updated_at = now_utc()
                return self._order(r)
            if r.status != OrderStatus.CONFIRMATION_PENDING.value:
                raise RuntimeError(f"Cannot confirm order in state {r.status}")
            r.supplier_confirmation_no = confirmation_no
            r.status = OrderStatus.CONFIRMED.value
            r.updated_at = now_utc(); r.version += 1
            pb = s.get(PrebookRow, r.prebook_id)
            if pb: pb.status = PrebookStatus.CONSUMED.value
            self._append_event_and_outbox(s, Event(new_id("evt"), "SUPPLIER_CONFIRMATION_RECEIVED", "HOTEL_ORDER", r.order_id, {"confirmation_no": confirmation_no}))
            self._append_event_and_outbox(s, Event(new_id("evt"), "ORDER_CONFIRMED", "HOTEL_ORDER", r.order_id, {"confirmation_no": confirmation_no}))
            op.status = "COMPLETED"; op.external_reference = confirmation_no; op.result_payload = {"confirmation_no": confirmation_no}; op.completed_at = now_utc(); op.updated_at = now_utc()
            return self._order(r)

    def begin_external_operation(self, operation_type: str, aggregate_id: str, payload: dict) -> tuple[dict, bool]:
        business_key = f"{operation_type}:{aggregate_id}"
        digest = self.hash_payload(payload)
        now = now_utc()
        operation_id = new_id("op")
        try:
            with SessionLocal.begin() as s:
                existing = s.scalar(select(ExternalOperationRow).where(ExternalOperationRow.business_key == business_key))
                if existing:
                    if existing.status != "FAILED" and existing.request_hash != digest:
                        return self._operation_dict(existing) | {"hash_conflict": True}, False
                    if existing.status == "FAILED":
                        # Preserve the failed attempt for audit, but free the single active business key
                        # so a new payment attempt can use a new provider idempotency key.
                        existing.business_key = f"{business_key}:FAILED:{existing.operation_id}"
                        existing.updated_at = now
                    else:
                        return self._operation_dict(existing), False
                op = ExternalOperationRow(operation_id=operation_id, operation_type=operation_type, aggregate_id=aggregate_id, business_key=business_key, request_hash=digest, status="STARTED", attempt_count=1, request_payload=payload, created_at=now, updated_at=now)
                s.add(op)
                s.flush()
                return self._operation_dict(op), True
        except IntegrityError:
            with SessionLocal() as s:
                existing = s.scalar(select(ExternalOperationRow).where(ExternalOperationRow.business_key == business_key))
                return self._operation_dict(existing), False

    def mark_external_success(self, operation_id: str, external_reference: str, result_payload: dict) -> None:
        with SessionLocal.begin() as s:
            op = s.execute(select(ExternalOperationRow).where(ExternalOperationRow.operation_id == operation_id).with_for_update()).scalar_one()
            op.status = "EXTERNAL_SUCCEEDED"
            op.external_reference = external_reference
            op.result_payload = result_payload
            op.updated_at = now_utc()
            op.next_retry_at = now_utc()

    def mark_external_completed(self, operation_id: str, result_payload: dict | None = None) -> None:
        with SessionLocal.begin() as s:
            op = s.get(ExternalOperationRow, operation_id)
            if not op: return
            op.status = "COMPLETED"; op.updated_at = now_utc(); op.completed_at = now_utc(); op.next_retry_at = None
            if result_payload is not None: op.result_payload = result_payload

    def mark_external_failed(self, operation_id: str, error: str) -> None:
        with SessionLocal.begin() as s:
            op = s.get(ExternalOperationRow, operation_id)
            op.status = "FAILED"; op.last_error = error; op.updated_at = now_utc(); op.next_retry_at = None

    def mark_reconcile_required(self, operation_id: str, error: str) -> None:
        with SessionLocal.begin() as s:
            op = s.get(ExternalOperationRow, operation_id)
            op.status = "RECONCILE_REQUIRED"; op.last_error = error; op.updated_at = now_utc(); op.next_retry_at = now_utc() + timedelta(seconds=settings.saga_retry_seconds)

    def recoverable_operations(self, limit: int = 100) -> list[dict]:
        now = now_utc()
        with SessionLocal() as s:
            rows = s.scalars(select(ExternalOperationRow).where(ExternalOperationRow.status.in_(["EXTERNAL_SUCCEEDED", "RECONCILE_REQUIRED"]), or_(ExternalOperationRow.next_retry_at.is_(None), ExternalOperationRow.next_retry_at <= now)).order_by(ExternalOperationRow.updated_at).limit(limit)).all()
            return [self._operation_dict(r) for r in rows]

    def get_external_operation(self, operation_id: str) -> dict | None:
        with SessionLocal() as s:
            r = s.get(ExternalOperationRow, operation_id)
            return self._operation_dict(r) if r else None

    @staticmethod
    def _operation_dict(r: ExternalOperationRow | None) -> dict:
        if r is None: return {}
        return {"operation_id": r.operation_id, "operation_type": r.operation_type, "aggregate_id": r.aggregate_id, "business_key": r.business_key, "request_hash": r.request_hash, "status": r.status, "attempt_count": r.attempt_count, "external_reference": r.external_reference, "request_payload": r.request_payload, "result_payload": r.result_payload, "last_error": r.last_error}

    def event_dicts(self, aggregate_id: str) -> list[dict]:
        with SessionLocal() as s:
            rows = s.scalars(select(EventRow).where(EventRow.aggregate_id == aggregate_id).order_by(EventRow.occurred_at, EventRow.event_id)).all()
            return [{"event_id":r.event_id,"event_type":r.event_type,"aggregate_type":r.aggregate_type,"aggregate_id":r.aggregate_id,"payload":r.payload,"occurred_at":r.occurred_at} for r in rows]

    def get_idempotency(self, operation: str, key: str) -> dict | None:
        with SessionLocal() as s:
            r = s.get(IdempotencyRow, {"idempotency_key": key, "operation": operation})
            return None if not r else {"request_hash": r.request_hash, "response_code": r.response_code, "response": r.response_body, "resource_id": r.resource_id}

    def claim_idempotency(self, operation: str, key: str, payload: dict) -> tuple[str, dict | None]:
        """Atomically claim a request key before any side effect.

        Returns (CLAIMED, None), (REPLAY, record), or (IN_PROGRESS, record).
        A different request fingerprint for the same operation/key is a hard conflict.
        """
        digest = self.hash_payload(payload)
        try:
            with SessionLocal.begin() as s:
                dialect = s.get_bind().dialect.name
                if dialect in {'postgresql', 'sqlite'}:
                    # Expected duplicate keys are a normal result, not a failed
                    # transaction followed by another connection acquisition.
                    # Only this composite key is ignored; other integrity errors
                    # must still propagate. The database chooses the sole winner.
                    factory = pg_insert if dialect == 'postgresql' else sqlite_insert
                    stmt = factory(IdempotencyRow.__table__).values(
                        idempotency_key=key, operation=operation, request_hash=digest,
                        response_code=102, response_body={'status': 'IN_PROGRESS'},
                        resource_id=None, created_at=now_utc(),
                    ).on_conflict_do_nothing(index_elements=['idempotency_key', 'operation'])
                    inserted = s.scalar(stmt.returning(IdempotencyRow.idempotency_key))
                    if inserted is not None:
                        return 'CLAIMED', None
                    r = s.get(IdempotencyRow, {'idempotency_key': key, 'operation': operation})
                    if not r or r.request_hash != digest:
                        raise ValueError('IDEMPOTENCY_CONFLICT')
                    rec = {'request_hash': r.request_hash, 'response_code': r.response_code,
                           'response': r.response_body, 'resource_id': r.resource_id}
                    return ('IN_PROGRESS' if r.response_code == 102 else 'REPLAY'), rec
                s.add(IdempotencyRow(
                    idempotency_key=key, operation=operation, request_hash=digest,
                    response_code=102, response_body={"status":"IN_PROGRESS"},
                    resource_id=None, created_at=now_utc(),
                ))
            return "CLAIMED", None
        except IntegrityError:
            if dialect in {'postgresql', 'sqlite'}:
                raise
            rec = self.get_idempotency(operation, key)
            if not rec or rec["request_hash"] != digest:
                raise ValueError("IDEMPOTENCY_CONFLICT")
            if rec["response_code"] == 102:
                return "IN_PROGRESS", rec
            return "REPLAY", rec

    def complete_idempotency(self, operation: str, key: str, payload: dict, response: dict, resource_id: str | None = None, response_code: int = 200) -> dict:
        digest = self.hash_payload(payload)
        table = IdempotencyRow.__table__
        with SessionLocal.begin() as s:
            # Recheck ownership in the write itself: a preceding read can become
            # stale if another transaction releases and replaces the claim.
            changed = s.execute(table.update().where(
                table.c.operation == operation,
                table.c.idempotency_key == key,
                table.c.request_hash == digest,
            ).values(response_code=response_code, response_body=response,
                     resource_id=resource_id)).rowcount
            if changed != 1:
                raise ValueError("IDEMPOTENCY_CLAIM_LOST")
        return response

    def release_idempotency_claim(self, operation: str, key: str, payload: dict) -> None:
        """Release only an unfinished claim owned by the same request fingerprint."""
        digest = self.hash_payload(payload)
        table = IdempotencyRow.__table__
        with SessionLocal.begin() as s:
            # A concurrent completion must leave its receipt replayable.
            s.execute(table.delete().where(
                table.c.operation == operation,
                table.c.idempotency_key == key,
                table.c.request_hash == digest,
                table.c.response_code == 102,
            ))

    def bind_idempotency_resource(self, operation, key, payload, resource_id, token, *, new_claim):
        """Bind a Flight recovery command to a fenced, renewable local lease.

        The lease only permits automatic recovery after payment_snapshot proves
        that no external payment was invoked. It is never an external fence."""
        
        if not isinstance(resource_id, str) or not 1 <= len(resource_id) <= 64:
            raise ValueError("IDEMPOTENCY_RESOURCE_INVALID")
        digest = self.hash_payload(payload)
        with SessionLocal.begin() as s:
            if s.bind.dialect.name == 'sqlite':
                s.execute(text('BEGIN IMMEDIATE'))
            row = s.get(IdempotencyRow, {'operation': operation, 'idempotency_key': key}, with_for_update=True)
            if not row or row.request_hash != digest:
                raise ValueError('IDEMPOTENCY_CLAIM_LOST')
            if row.resource_id not in {None, resource_id}:
                raise ValueError('IDEMPOTENCY_RESOURCE_CONFLICT')
            if row.response_code != 102:
                if row.response_code != 200:
                    raise ValueError('IDEMPOTENCY_RECONCILIATION_REQUIRED')
                if row.resource_id != resource_id:
                    raise ValueError('IDEMPOTENCY_RESOURCE_CONFLICT')
                return 'REPLAY', row.response_body
            if new_claim:
                if row.resource_id is not None or row.response_body != {'status': 'IN_PROGRESS'}:
                    raise ValueError('IDEMPOTENCY_CLAIM_LOST')
                mode = 'START'
            else:
                if row.resource_id != resource_id or row.response_body.get('status') not in {'RECOVERY_REQUIRED', 'WAITING_RESOURCE'}:
                    return 'IN_PROGRESS', None
                mode = 'RECOVER' if row.response_body.get('status') == 'RECOVERY_REQUIRED' else 'START'
            # Different HTTP keys must not race the same payment callback.
            # Lock order is always request row, then the resource row; no
            # transaction locks another request row while holding the resource.
            guard_id = {'operation': 'RESOURCE:' + operation, 'idempotency_key': resource_id}
            guard = s.get(IdempotencyRow, guard_id, with_for_update=True)
            if guard is None:
                try:
                    with s.begin_nested():
                        guard = IdempotencyRow(**guard_id, request_hash=digest, response_code=102,
                            response_body={'status': 'UNCLAIMED'}, resource_id=resource_id, created_at=now_utc())
                        s.add(guard)
                        s.flush()
                except IntegrityError:
                    guard = s.get(IdempotencyRow, guard_id, with_for_update=True)
            if not guard or guard.request_hash != digest or guard.resource_id != resource_id:
                raise ValueError('IDEMPOTENCY_RESOURCE_CONFLICT')
            if guard.response_code != 102:
                if guard.response_code != 200:
                    raise ValueError('IDEMPOTENCY_RECONCILIATION_REQUIRED')
                row.resource_id = resource_id
                row.response_code = guard.response_code
                row.response_body = guard.response_body
                return 'REPLAY', guard.response_body
            if guard.response_body.get('status') == 'RUNNING':
                row.resource_id = resource_id
                row.response_body = {'status': 'WAITING_RESOURCE'}
                return 'IN_PROGRESS', None
            if guard.response_body.get('status') == 'RECOVERY_REQUIRED':
                mode = 'RECOVER'
            elif guard.response_body.get('status') != 'UNCLAIMED':
                return 'IN_PROGRESS', None
            row.resource_id = resource_id
            lease_until_ms = int(now_utc().timestamp() * 1000) + 15000
            running = {'status': 'RUNNING', 'execution_token': token, 'lease_until_ms': lease_until_ms,
                       'heartbeat_ms': lease_until_ms - 15000, 'payload': payload}
            row.response_body = running
            guard.response_body = dict(running)
            return mode, None

    def heartbeat_recoverable_idempotency(self, operation, key, resource_id, token, lease_ms=15000):
        """Renew a running Flight command only while both request and resource fences match."""
        if not 1000 <= lease_ms <= 60000:
            raise ValueError('IDEMPOTENCY_LEASE_INVALID')
        with SessionLocal.begin() as s:
            if s.bind.dialect.name == 'sqlite':
                s.execute(text('BEGIN IMMEDIATE'))
            row = s.get(IdempotencyRow, {'operation': operation, 'idempotency_key': key}, with_for_update=True)
            guard = s.get(IdempotencyRow, {'operation': 'RESOURCE:' + operation, 'idempotency_key': resource_id}, with_for_update=True)
            if not row or not guard or row.resource_id != resource_id or guard.resource_id != resource_id:
                raise ValueError('IDEMPOTENCY_EXECUTION_LOST')
            for record in (row, guard):
                body = record.response_body
                if record.response_code != 102 or body.get('status') != 'RUNNING' or body.get('execution_token') != token:
                    raise ValueError('IDEMPOTENCY_EXECUTION_LOST')
            now_ms = int(now_utc().timestamp() * 1000)
            body = {**row.response_body, 'heartbeat_ms': now_ms, 'lease_until_ms': now_ms + lease_ms}
            row.response_body = body
            guard.response_body = dict(body)
            return body['lease_until_ms']

    def claim_expired_flight_recovery(self, limit=20, lease_ms=15000):
        """Atomically take over only a stale Flight local-simulation command.

        The caller must still validate payment_snapshot before replaying it.
        """
        if not 1 <= limit <= 100 or not 1000 <= lease_ms <= 60000:
            raise ValueError('IDEMPOTENCY_LEASE_INVALID')
        claimed = []
        with SessionLocal.begin() as s:
            if s.bind.dialect.name == 'sqlite':
                s.execute(text('BEGIN IMMEDIATE'))
            now_ms = int(now_utc().timestamp() * 1000)
            # Match bind/heartbeat/finish lock order: request, then resource.
            # The old resource-first order could deadlock with a live heartbeat.
            rows = s.scalars(select(IdempotencyRow).where(
                IdempotencyRow.operation.in_(['FLIGHT_CHECKOUT', 'FLIGHT_EXECUTE_CHANGE']),
                IdempotencyRow.response_code == 102).with_for_update(skip_locked=True)).all()
            for request in rows:
                body = dict(request.response_body or {})
                if body.get('status') != 'RUNNING' or int(body.get('lease_until_ms') or now_ms + 1) > now_ms:
                    continue
                operation = request.operation
                guard = s.get(IdempotencyRow, {'operation': 'RESOURCE:' + operation,
                    'idempotency_key': request.resource_id}, with_for_update=True)
                if (not guard or guard.response_code != 102
                        or guard.response_body.get('status') != 'RUNNING'
                        or guard.response_body.get('execution_token') != body.get('execution_token')
                        or guard.request_hash != request.request_hash
                        or int(guard.response_body.get('lease_until_ms') or now_ms + 1) > now_ms):
                    continue
                # The request row is authoritative for the reconstructable
                # command payload; the resource row is its exclusion fence.
                payload = request.response_body.get('payload')
                if not isinstance(payload, dict):
                    # Legacy RUNNING rows cannot be reconstructed; retain the fence.
                    continue
                token = new_id('flight_recovery')
                next_body = {'status': 'RUNNING', 'execution_token': token, 'heartbeat_ms': now_ms,
                             'lease_until_ms': now_ms + lease_ms, 'payload': payload, 'recovered_from': body.get('execution_token')}
                request.response_body = next_body
                guard.response_body = dict(next_body)
                claimed.append({'operation': operation, 'key': request.idempotency_key,
                    'resource_id': guard.resource_id, 'payload': payload, 'token': token})
                if len(claimed) >= limit:
                    break
        return claimed

    def finish_recoverable_idempotency(self, operation, key, payload, resource_id, token, action, response=None):
        """Fence every completion, failure marker and safe release by token."""
        if action not in {'COMPLETE', 'RECOVERY_REQUIRED', 'RELEASE'}:
            raise ValueError('IDEMPOTENCY_ACTION_INVALID')
        digest = self.hash_payload(payload)
        with SessionLocal.begin() as s:
            if s.bind.dialect.name == 'sqlite':
                s.execute(text('BEGIN IMMEDIATE'))
            row = s.get(IdempotencyRow, {'operation': operation, 'idempotency_key': key}, with_for_update=True)
            if not row or row.request_hash != digest or row.resource_id != resource_id:
                raise ValueError('IDEMPOTENCY_CLAIM_LOST')
            # A completion commit may succeed while its acknowledgement fails.
            # Failure handling may observe it but must never replace its result.
            if row.response_code != 102:
                if action == 'RECOVERY_REQUIRED' and row.response_code == 200:
                    return
                raise ValueError('IDEMPOTENCY_EXECUTION_LOST')
            if (row.response_body.get('status') != 'RUNNING'
                    or row.response_body.get('execution_token') != token):
                raise ValueError('IDEMPOTENCY_EXECUTION_LOST')
            guard = s.get(IdempotencyRow, {'operation': 'RESOURCE:' + operation,
                'idempotency_key': resource_id}, with_for_update=True)
            if (not guard or guard.request_hash != digest or guard.resource_id != resource_id
                    or guard.response_code != 102
                    or guard.response_body.get('status') != 'RUNNING'
                    or guard.response_body.get('execution_token') != token):
                raise ValueError('IDEMPOTENCY_EXECUTION_LOST')
            if action == 'RELEASE':
                s.delete(row)
                s.delete(guard)
            elif action == 'COMPLETE':
                row.response_code = 200
                row.response_body = response
                guard.response_code = 200
                guard.response_body = response
            else:
                row.response_body = {'status': 'RECOVERY_REQUIRED'}
                guard.response_body = {'status': 'RECOVERY_REQUIRED'}

    def save_idempotency(self, operation: str, key: str, payload: dict, response: dict, resource_id: str | None = None, response_code: int = 200) -> dict:
        digest = self.hash_payload(payload)
        try:
            with SessionLocal.begin() as s:
                s.add(IdempotencyRow(idempotency_key=key, operation=operation, request_hash=digest, response_code=response_code, response_body=response, resource_id=resource_id, created_at=now_utc()))
            return response
        except IntegrityError:
            rec = self.get_idempotency(operation, key)
            if rec and rec["request_hash"] == digest:
                return rec["response"]
            raise

    @staticmethod
    def hash_payload(payload: dict) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",",":"), default=str).encode()
        return sha256(raw).hexdigest()

    def ingest_webhook(self, connector_id: str, external_event_id: str, aggregate_id: str, event_type: str, sequence: int | None, payload: dict, signature_valid: bool) -> tuple[dict, bool]:
        now = now_utc(); webhook_id = new_id("wh")
        try:
            with SessionLocal.begin() as s:
                row = WebhookInboxRow(webhook_id=webhook_id, connector_id=connector_id, external_event_id=external_event_id, aggregate_id=aggregate_id, event_type=event_type, external_sequence=sequence, signature_valid=signature_valid, raw_payload=payload, status="RECEIVED" if signature_valid else "REJECTED_SIGNATURE", received_at=now)
                s.add(row); s.flush()
                return self._webhook_dict(row), True
        except IntegrityError:
            with SessionLocal() as s:
                row = s.scalar(select(WebhookInboxRow).where(WebhookInboxRow.connector_id == connector_id, WebhookInboxRow.external_event_id == external_event_id))
                return self._webhook_dict(row), False

    def process_webhook(self, webhook_id: str) -> dict:
        with SessionLocal.begin() as s:
            row = s.execute(select(WebhookInboxRow).where(WebhookInboxRow.webhook_id == webhook_id).with_for_update()).scalar_one()
            if row.status in ("APPLIED", "IGNORED_STALE", "REJECTED_SIGNATURE", "FAILED"):
                return self._webhook_dict(row)
            if not row.signature_valid:
                row.status = "REJECTED_SIGNATURE"; row.processed_at = now_utc(); return self._webhook_dict(row)
            cursor = s.get(ConnectorCursorRow, {"connector_id": row.connector_id, "aggregate_id": row.aggregate_id})
            seq = row.external_sequence
            if seq is not None and cursor and seq <= cursor.last_sequence:
                row.status = "IGNORED_STALE"; row.processed_at = now_utc(); return self._webhook_dict(row)
            order = s.execute(select(OrderRow).where(OrderRow.order_id == row.aggregate_id).with_for_update()).scalar_one_or_none()
            if order is None:
                row.status = "FAILED"; row.processing_error = "ORDER_NOT_FOUND"; row.processed_at = now_utc(); return self._webhook_dict(row)
            if row.event_type == "BOOKING_CONFIRMED":
                confirmation = str(row.raw_payload.get("confirmation_no") or "")
                if order.status in (OrderStatus.PAYMENT_AUTHORIZED.value, OrderStatus.BOOKING_PENDING.value, OrderStatus.RECONCILIATION_REQUIRED.value):
                    order.status = OrderStatus.CAPTURE_PENDING.value
                    order.supplier_confirmation_no = confirmation or order.supplier_confirmation_no
                    order.updated_at = now_utc(); order.version += 1
                    self._append_event_and_outbox(s, Event(new_id("evt"), "SUPPLIER_WEBHOOK_CONFIRMED", "HOTEL_ORDER", order.order_id, {"confirmation_no": order.supplier_confirmation_no, "external_event_id": row.external_event_id, "capture_required": True}))
                elif order.status not in (OrderStatus.CAPTURE_PENDING.value, OrderStatus.CONFIRMED.value):
                    row.status = "FAILED"; row.processing_error = f"ORDER_STATE_CONFLICT:{order.status}"; row.processed_at = now_utc(); return self._webhook_dict(row)
            else:
                row.status = "FAILED"; row.processing_error = "WEBHOOK_EVENT_UNSUPPORTED"; row.processed_at = now_utc(); return self._webhook_dict(row)
            if seq is not None:
                if cursor is None:
                    cursor = ConnectorCursorRow(connector_id=row.connector_id, aggregate_id=row.aggregate_id, last_sequence=seq, last_external_event_id=row.external_event_id, updated_at=now_utc()); s.add(cursor)
                else:
                    cursor.last_sequence = seq; cursor.last_external_event_id = row.external_event_id; cursor.updated_at = now_utc()
            row.status = "APPLIED"; row.processed_at = now_utc()
            return self._webhook_dict(row)

    @staticmethod
    def _webhook_dict(r: WebhookInboxRow) -> dict:
        return {"webhook_id": r.webhook_id, "connector_id": r.connector_id, "external_event_id": r.external_event_id, "aggregate_id": r.aggregate_id, "event_type": r.event_type, "external_sequence": r.external_sequence, "signature_valid": r.signature_valid, "status": r.status, "processing_error": r.processing_error}


    def save_connector_certification(self, report: dict) -> None:
        with SessionLocal.begin() as s:
            s.add(ConnectorCertificationRow(connector_id=report["connector_id"], passed=bool(report["passed"]), report=report, certified_at=now_utc()))

    def save_connector_health(self, connector_id: str, healthy: bool, detail: dict) -> None:
        with SessionLocal.begin() as s:
            row=s.get(ConnectorHealthRow, connector_id)
            if row is None:
                s.add(ConnectorHealthRow(connector_id=connector_id, healthy=healthy, detail=detail, checked_at=now_utc()))
            else:
                row.healthy=healthy; row.detail=detail; row.checked_at=now_utc()

    def orders_for_reconciliation(self, limit: int=100) -> list[dict]:
        with SessionLocal() as s:
            rows=s.scalars(select(OrderRow).where(OrderRow.supplier_confirmation_no.is_not(None)).order_by(OrderRow.updated_at).limit(limit)).all()
            return [{"order_id":r.order_id,"status":r.status,"supplier_confirmation_no":r.supplier_confirmation_no} for r in rows]

    def record_reconciliation(self, order_id: str, connector_id: str, local_status: str, external_status: str | None, result: str, error: str | None=None) -> None:
        with SessionLocal.begin() as s:
            s.add(ReconciliationRunRow(order_id=order_id, connector_id=connector_id, local_status=local_status, external_status=external_status, result=result, error=error, checked_at=now_utc()))

    def append_event(self, event: Event) -> None:
        with SessionLocal.begin() as s:
            self.append_event_in_session(s, event)

    def append_event_in_session(self, s, event: Event) -> None:
        """Stage an event/outbox pair in the caller's existing transaction."""
        self._append_event_and_outbox(s, event)

    def _append_event_and_outbox(self, s, event: Event) -> None:
        s.add(EventRow(event_id=event.event_id, event_type=event.event_type, aggregate_type=event.aggregate_type, aggregate_id=event.aggregate_id, payload=event.payload, occurred_at=event.occurred_at))
        s.add(OutboxRow(event_id=event.event_id, topic="domain.events", event_type=event.event_type, aggregate_id=event.aggregate_id, payload={"event_id": event.event_id, "event_type": event.event_type, "aggregate_type": event.aggregate_type, "aggregate_id": event.aggregate_id, "occurred_at": event.occurred_at.isoformat(), "payload": event.payload}, status="PENDING", attempt_count=0, available_at=event.occurred_at, created_at=event.occurred_at))

repo = SqlRepository()
