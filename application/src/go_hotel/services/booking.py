from __future__ import annotations
from datetime import datetime, timezone
from go_hotel.connectors.registry import registry
from go_hotel.connectors.resilience import ResilientConnector, ConnectorTimeout
from go_hotel.core.config import settings
from go_hotel.core.errors import conflict, not_found, unprocessable, unavailable
from go_hotel.core.faults import faults
from go_hotel.domain.models import Event, Order, OrderStatus, Payment, PaymentStatus, PrebookStatus, new_id
from go_hotel.payments.mock import payment_provider
from go_hotel.services.hotel_money_bridge import hotel_money_bridge
from go_hotel.services.consumer_unified_lifecycle import consumer_unified_lifecycle_service
from go_hotel.repositories.sql import repo
from go_hotel.routing.router import traffic_router
from go_hotel.merge.engine import offer_merge_engine
from go_hotel.services.consistency import booking_consistency_guard, benefit_fingerprint
from go_hotel.services import catalog_fare_snapshot as fare_snapshot

class BookingService:
    def _connector(self, connector_id: str | None = None):
        base = registry.get(connector_id) if connector_id else registry.default()
        return ResilientConnector(base, timeout_seconds=settings.connector_timeout_seconds, retries=settings.connector_retry_count)

    async def search(self, city_code: str, check_in: str, check_out: str, currency: str):
        request_key = f"{city_code}:{check_in}:{check_out}:{currency}"
        candidates, decision = await traffic_router.search(request_key=request_key, city_code=city_code, check_in=check_in, check_out=check_out, currency=currency)
        # Merge equivalent multi-source room/rate offers after routing eligibility.
        # GO Recommendation / GO Score are intentionally absent from this transaction merge path.
        raw_offers=[]
        for c in candidates:
            c.offer.connector_id=c.connector_id
            c.offer.supplier_id=c.supplier_id
            raw_offers.append(c.offer)
        offers, merge_decisions = offer_merge_engine.merge(raw_offers)
        merge_by_offer={d.selected_offer_id:d for d in merge_decisions}
        for offer in offers:
            md=merge_by_offer.get(offer.offer_id)
            repo.save_offer_with_event(offer, Event(new_id("evt"), "CANONICAL_OFFER_CREATED", "HOTEL_OFFER", offer.offer_id, {"hotel_id": offer.hotel_id, "connector_id": offer.connector_id, "routing_decision_id": decision.decision_id, "merge_decision_id": md.decision_id if md else None}))
            fare_snapshot.seed_mock_offer(offer)
        return offers

    async def prebook(self, offer_id: str):
        offer = repo.get_offer(offer_id)
        if not offer: not_found("OFFER_NOT_FOUND", "Offer not found")
        offer_exp = offer.expires_at if offer.expires_at.tzinfo else offer.expires_at.replace(tzinfo=timezone.utc)
        if offer_exp <= datetime.now(timezone.utc): unprocessable("OFFER_EXPIRED", "Offer expired")
        try:
            fare_snapshot.offer_rule(offer_id)
        except ValueError as exc:
            conflict(str(exc), 'The supplier fare rules need confirmation before booking')
        prebook = await self._connector(offer.connector_id).prebook(offer)
        if prebook.fare_rule_id is None: prebook.fare_rule_id = offer.fare_rule_id
        if prebook.benefits_fingerprint is None: prebook.benefits_fingerprint = benefit_fingerprint(offer)
        price_status, inventory_status, policy_status, benefit_status = booking_consistency_guard.validate_prebook_result(offer, prebook)
        revalidation_id=new_id("prv")
        repo.save_prebook_revalidation(revalidation_id=revalidation_id, offer=offer, prebook=prebook, price_status=price_status, inventory_status=inventory_status, policy_status=policy_status, benefit_status=benefit_status, snapshot={"offer_total":offer.total_amount_minor,"supplier_total":prebook.total_amount_minor,"fare_rule_id":offer.fare_rule_id,"lock_expires_at":prebook.expires_at.isoformat(),"inventory_held":prebook.inventory_held})
        if prebook.status == PrebookStatus.INVENTORY_LOST:
            repo.save_prebook_with_event(prebook, Event(new_id("evt"), "PREBOOK_INVENTORY_LOST", "PREBOOK", prebook.prebook_id, {"offer_id":offer_id,"revalidation_id":revalidation_id}))
            unprocessable("HOTEL_INVENTORY_CHANGED", "Inventory is no longer available")
        if price_status == "CHANGED":
            prebook.status=PrebookStatus.REPRICE_REQUIRED
            repo.save_prebook_with_event(prebook, Event(new_id("evt"), "PREBOOK_PRICE_CHANGED", "PREBOOK", prebook.prebook_id, {"offer_id":offer_id,"revalidation_id":revalidation_id,"old_total_minor":offer.total_amount_minor,"new_total_minor":prebook.total_amount_minor}))
            unprocessable("HOTEL_RATE_CHANGED", "Hotel rate changed during prebook")
        if policy_status == "CHANGED" or benefit_status == "CHANGED":
            prebook.status=PrebookStatus.CONSISTENCY_FAILED
            repo.save_prebook_with_event(prebook, Event(new_id("evt"), "PREBOOK_POLICY_OR_BENEFIT_CHANGED", "PREBOOK", prebook.prebook_id, {"offer_id":offer_id,"revalidation_id":revalidation_id}))
            unprocessable("HOTEL_TERMS_CHANGED", "Fare policy or benefits changed during prebook")
        repo.save_prebook_with_event(prebook, Event(new_id("evt"), "PREBOOK_SUCCEEDED", "PREBOOK", prebook.prebook_id, {"offer_id": offer_id,"revalidation_id":revalidation_id,"hold_type":prebook.hold_type,"inventory_held":prebook.inventory_held,"lock_expires_at":prebook.expires_at.isoformat()}))
        return prebook

    async def create_order(self, prebook_id: str, account_id: str, expected_rule_hash=None, fare_confirmed=False, simulation_fixture=False):
        prebook = repo.get_prebook(prebook_id)
        if not prebook: not_found("PREBOOK_NOT_FOUND", "Prebook not found")
        if prebook.status != PrebookStatus.PREBOOKED: conflict("PREBOOK_STATE_CONFLICT", "Prebook is not available")
        offer = repo.get_offer(prebook.offer_id)
        if not offer: not_found("OFFER_NOT_FOUND", "Offer not found")
        booking_consistency_guard.assert_order_can_be_created(prebook, offer)
        order = Order(new_id("ord"), prebook_id, offer.hotel_id, account_id, prebook.total_amount_minor, prebook.currency, supplier_id=offer.supplier_id)
        try:
            repo.create_order_with_event(order, Event(new_id("evt"), "ORDER_CREATED", "HOTEL_ORDER", order.order_id, {"prebook_id": prebook_id}),
                fare_acceptance={'expected_hash': expected_rule_hash, 'confirmed': fare_confirmed, 'simulation_fixture': simulation_fixture})
        except ValueError as exc:
            conflict(str(exc), 'Confirm the current hotel fare rules before creating the order')
        return order

    def _finalize_hotel_truth(self, order_id: str):
        order=repo.get_order(order_id)
        if not order or order.status!=OrderStatus.CONFIRMED:
            return order
        iid=hotel_money_bridge.ensure_original_root(order_id)
        consumer_unified_lifecycle_service.project({
            'account_id':order.account_id,'vertical':'HOTEL','order_id':order.order_id,'supplier_id':order.supplier_id,
            'title':f'HOTEL {order.order_id}','lifecycle_state':'CONFIRMED','payment_state':'PAID','refund_state':'NOT_REQUESTED',
            'change_allowed':True,'cancel_allowed':True,'facts':{'payment_intent_id':iid,'supplier_confirmation_no':order.supplier_confirmation_no},
            'evidence_reference':f'hotel-capture://{order_id}','source_updated_at':datetime.now(timezone.utc).isoformat()
        })
        return order

    async def pay(self, order_id: str, amount_minor: int, currency: str, payment_method_token: str):
        """Authorize only. Customer funds are captured only after supplier booking succeeds."""
        order = repo.get_order(order_id)
        if not order: not_found("ORDER_NOT_FOUND", "Order not found")
        if amount_minor != order.total_amount_minor or currency != order.currency:
            unprocessable("PAYMENT_AMOUNT_MISMATCH", "Payment amount does not match order")
        existing = repo.get_authorized_payment_for_order(order_id)
        if order.status in (OrderStatus.PAYMENT_AUTHORIZED, OrderStatus.BOOKING_PENDING, OrderStatus.CAPTURE_PENDING, OrderStatus.CONFIRMED) and existing:
            return existing
        if order.status != OrderStatus.PAYMENT_PENDING:
            conflict("ORDER_STATE_CONFLICT", "Order is not awaiting payment authorization")
        prebook = repo.get_prebook(order.prebook_id)
        offer = repo.get_offer(prebook.offer_id) if prebook else None
        if not prebook or not offer: not_found("PREBOOK_NOT_FOUND", "Prebook consistency data missing")
        booking_consistency_guard.assert_before_payment(order, prebook, offer)

        payload = {"order_id": order_id, "amount_minor": amount_minor, "currency": currency}
        op, acquired = repo.begin_external_operation("PAYMENT_AUTHORIZE", order_id, payload)
        if op.get("hash_conflict"): conflict("PAYMENT_OPERATION_CONFLICT", "A different authorization already exists for this order")
        if not acquired:
            if op.get("status") == "COMPLETED":
                p = repo.get_payment_by_operation(op["operation_id"])
                if p: return p
            conflict("PAYMENT_OPERATION_IN_PROGRESS", "A payment authorization is already in progress")

        payment = await payment_provider.authorize(order_id, amount_minor, currency, payment_method_token, idempotency_key=op["operation_id"])
        if payment.status == PaymentStatus.FAILED:
            repo.save_failed_payment(payment, op["operation_id"], Event(new_id("evt"), "PAYMENT_AUTHORIZATION_FAILED", "HOTEL_ORDER", order_id, {"payment_id": payment.payment_id}))
            repo.mark_external_failed(op["operation_id"], "PAYMENT_AUTHORIZATION_DECLINED")
            unprocessable("PAYMENT_AUTHORIZATION_DECLINED", "Payment authorization was declined")

        repo.mark_external_success(op["operation_id"], payment.payment_id, {"payment_id":payment.payment_id,"amount_minor":amount_minor,"currency":currency,"status":payment.status.value})
        try:
            faults.hit("authorization_after_external_success")
            repo.commit_authorization_saga(payment, op["operation_id"])
        except Exception as exc:
            repo.mark_reconcile_required(op["operation_id"], str(exc))
            unavailable("PAYMENT_AUTHORIZATION_RECONCILIATION_REQUIRED", "Authorization succeeded; local recovery has been scheduled")
        return payment

    async def _void_after_definitive_booking_failure(self, order_id: str, payment: Payment, reason: str):
        void_op, acquired = repo.begin_external_operation("PAYMENT_VOID", order_id, {"payment_id":payment.payment_id,"reason":reason})
        if acquired:
            result = await payment_provider.void(payment.payment_id, idempotency_key=void_op["operation_id"])
            if result.status != PaymentStatus.VOIDED:
                repo.mark_reconcile_required(void_op["operation_id"], "PAYMENT_VOID_FAILED")
                repo.mark_order_reconciliation_required(order_id, "BOOKING_FAILED_VOID_RECONCILIATION", "PAYMENT_VOID_FAILED")
                unavailable("PAYMENT_VOID_RECONCILIATION_REQUIRED", "Booking failed and authorization void requires reconciliation")
            repo.mark_external_success(void_op["operation_id"], payment.payment_id, {"status":"VOIDED"})
            repo.mark_external_completed(void_op["operation_id"], {"status":"VOIDED","payment_id":payment.payment_id})
        return repo.fail_booking_and_void_authorization(order_id, payment.payment_id, reason)

    async def confirm(self, order_id: str):
        """Orchestrate AUTHORIZED -> supplier book -> CAPTURED. No capture before confirmed booking."""
        order = repo.get_order(order_id)
        if not order: not_found("ORDER_NOT_FOUND", "Order not found")
        if order.status == OrderStatus.CONFIRMED: return order
        payment = repo.get_authorized_payment_for_order(order_id)
        if not payment:
            conflict("BOOK_PAYMENT_NOT_AUTHORIZED", "Payment authorization is required before booking")

        request_hash = repo.hash_payload({"order_id": order_id, "payment_id": payment.payment_id})
        op, acquired = repo.start_confirmation_saga(order_id, request_hash)
        if op.get("missing"): not_found("ORDER_NOT_FOUND", "Order not found")
        if op.get("already_confirmed"): return repo.get_order(order_id)
        if op.get("invalid_state"): conflict("BOOK_PAYMENT_NOT_AUTHORIZED", "Order must be payment-authorized before booking")
        if not acquired:
            if op.get("status") == "COMPLETED":
                # Supplier may already be booked; continue capture if needed.
                order = repo.get_order(order_id)
                if order.status == OrderStatus.CAPTURE_PENDING:
                    return await self.capture_after_booking(order_id, payment)
                return order
            if op.get("status") in ("EXTERNAL_SUCCEEDED", "RECONCILE_REQUIRED"):
                return await self.recover_confirmation(op)
            conflict("BOOK_OPERATION_IN_PROGRESS", "Supplier booking is already in progress")

        prebook = repo.get_prebook(order.prebook_id)
        offer = repo.get_offer(prebook.offer_id) if prebook else None
        connector_id = offer.connector_id if offer else None
        if prebook and offer: booking_consistency_guard.assert_before_booking(order, prebook, offer)
        try:
            confirmation = await self._connector(connector_id).book(order_id, prebook, idempotency_key=op["operation_id"])
        except (TimeoutError, ConnectorTimeout) as exc:
            # Unknown external result: never void because supplier may have booked.
            repo.mark_reconcile_required(op["operation_id"], str(exc))
            repo.mark_order_reconciliation_required(order_id, "SUPPLIER_BOOK_RESULT_UNKNOWN", str(exc))
            unavailable("BOOKING_RECONCILIATION_REQUIRED", "Supplier booking result is unknown; authorization remains on hold pending reconciliation")
        except Exception as exc:
            # Definitive rejection: safe compensation is to void authorization.
            repo.mark_external_failed(op["operation_id"], str(exc))
            await self._void_after_definitive_booking_failure(order_id, payment, str(exc))
            unavailable("SUPPLIER_BOOKING_FAILED_NO_CHARGE", "Hotel booking failed; payment authorization was voided and no capture occurred")

        repo.mark_external_success(op["operation_id"], confirmation, {"confirmation_no": confirmation})
        try:
            faults.hit("confirm_after_external_success")
            order = repo.commit_supplier_booking_before_capture(op["operation_id"], confirmation)
        except Exception as exc:
            repo.mark_reconcile_required(op["operation_id"], str(exc))
            repo.mark_order_reconciliation_required(order_id, "SUPPLIER_BOOKED_LOCAL_COMMIT_UNKNOWN", str(exc), confirmation)
            unavailable("BOOKING_RECONCILIATION_REQUIRED", "Supplier booking succeeded; local recovery has been scheduled")
        return await self.capture_after_booking(order_id, payment)

    async def capture_after_booking(self, order_id: str, payment: Payment):
        capture_op, acquired = repo.begin_external_operation("PAYMENT_CAPTURE_AFTER_BOOK", order_id, {"payment_id":payment.payment_id,"order_id":order_id})
        if not acquired:
            if capture_op.get("status") == "COMPLETED": return self._finalize_hotel_truth(order_id)
            if capture_op.get("status") in ("EXTERNAL_SUCCEEDED","RECONCILE_REQUIRED"):
                return await self.recover_capture(capture_op)
            conflict("PAYMENT_CAPTURE_IN_PROGRESS", "Payment capture is already in progress")
        result = await payment_provider.capture(payment.payment_id, idempotency_key=capture_op["operation_id"])
        if result.status != PaymentStatus.CAPTURED:
            repo.mark_external_failed(capture_op["operation_id"], "PAYMENT_CAPTURE_FAILED_AFTER_BOOKING")
            repo.mark_order_reconciliation_required(order_id, "SUPPLIER_BOOKED_CAPTURE_FAILED", "PAYMENT_CAPTURE_FAILED_AFTER_BOOKING", repo.get_order(order_id).supplier_confirmation_no)
            unavailable("PAYMENT_CAPTURE_RECONCILIATION_REQUIRED", "Hotel is booked but payment capture failed; case moved to reconciliation")
        repo.mark_external_success(capture_op["operation_id"], result.payment_id, {"payment_id":result.payment_id,"status":"CAPTURED"})
        try:
            faults.hit("capture_after_external_success")
            order=repo.commit_capture_after_booking(result.payment_id, capture_op["operation_id"]); return self._finalize_hotel_truth(order.order_id)
        except Exception as exc:
            repo.mark_reconcile_required(capture_op["operation_id"], str(exc))
            repo.mark_order_reconciliation_required(order_id, "CAPTURED_LOCAL_COMMIT_UNKNOWN", str(exc), repo.get_order(order_id).supplier_confirmation_no)
            unavailable("PAYMENT_CAPTURE_RECONCILIATION_REQUIRED", "Capture succeeded; local recovery has been scheduled")

    async def recover_authorization(self, op: dict):
        result = op.get("result_payload") or {}
        payment = Payment(result.get("payment_id") or op.get("external_reference"), op["aggregate_id"], int(result["amount_minor"]), result["currency"], PaymentStatus.AUTHORIZED)
        return repo.commit_authorization_saga(payment, op["operation_id"])

    async def recover_confirmation(self, op: dict):
        order = repo.get_order(op["aggregate_id"])
        prebook = repo.get_prebook(order.prebook_id) if order else None
        offer = repo.get_offer(prebook.offer_id) if prebook else None
        payment = repo.get_authorized_payment_for_order(order.order_id) if order else None
        connector = self._connector(offer.connector_id if offer else None)
        confirmation = (op.get("result_payload") or {}).get("confirmation_no") or op.get("external_reference")
        if confirmation:
            status = await connector.status(confirmation)
            if status == "CONFIRMED":
                if order.status != OrderStatus.CAPTURE_PENDING:
                    order = repo.commit_supplier_booking_before_capture(op["operation_id"], confirmation)
                return await self.capture_after_booking(order.order_id, payment)
        else:
            lookup_booking = getattr(connector, "lookup_booking", None)
            if lookup_booking is None:
                lookup_booking = getattr(getattr(connector, "inner", None), "lookup_booking", None)
            if lookup_booking is None:
                raise RuntimeError("Supplier booking status remains unresolved")
            observed = await lookup_booking(op["operation_id"])
            status = str((observed or {}).get("status") or "").upper()
            confirmation = (observed or {}).get("confirmation")
            if status == "CONFIRMED" and confirmation:
                order = repo.commit_supplier_booking_before_capture(op["operation_id"], confirmation)
                return await self.capture_after_booking(order.order_id, payment)
            if status == "REJECTED" and payment:
                repo.mark_external_completed(op["operation_id"], {"status": "REJECTED"})
                return await self._void_after_definitive_booking_failure(order.order_id, payment, "SUPPLIER_BOOKING_REJECTED")
        raise RuntimeError("Supplier booking status remains unresolved")

    async def recover_capture(self, op: dict):
        order_id=op["aggregate_id"]
        payment=repo.get_authorized_payment_for_order(order_id)
        if not payment:
            captured=repo.get_captured_payment_for_order(order_id)
            if captured: return repo.get_order(order_id)
            raise RuntimeError("Missing payment during capture recovery")
        status=await payment_provider.status(payment.payment_id)
        if status == PaymentStatus.CAPTURED:
            return repo.commit_capture_after_booking(payment.payment_id, op["operation_id"])
        raise RuntimeError(f"Payment capture status remains {status}")

booking_service = BookingService()
