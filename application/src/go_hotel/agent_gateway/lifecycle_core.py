from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from .canonical_core import GoTransactionCore as TransactionCore, _parse_ref
from .contracts import AgentContext, ExpireRequest, LifecycleExecuteRequest, LifecycleQuoteRequest
from .real_core import _digest, _jsonable


class GoTransactionCore(TransactionCore):
    """Universal Agent Transaction Lifecycle P0.2.

    This adapter owns no lifecycle, inventory, money, supplier or order store.
    It delegates to the existing GO vertical engines and only normalizes the
    protocol contract plus idempotency boundary.
    """

    async def lifecycle_quote(self, ctx: AgentContext, req: LifecycleQuoteRequest) -> dict[str, Any]:
        account = ctx.require_traveler()
        vertical, oid = _parse_ref(req.order_id)
        action = req.action.upper()
        if action not in {"CANCEL", "CHANGE", "REFUND"}:
            raise ValueError("LIFECYCLE_QUOTE_ACTION_INVALID")
        payload = {"account": account, "order_id": req.order_id, "action": action, "changes": dict(req.changes)}

        async def execute():
            quote = await (self._change_quote(account, vertical, oid, dict(req.changes))
                           if action == "CHANGE" else self._cancel_refund_quote(account, vertical, oid))
            out = _jsonable(quote)
            out.setdefault("order_id", oid)
            out["agent_order_id"] = req.order_id
            out["action"] = action
            out.setdefault("quote_id", out.get("change_quote_id"))
            out["quote_hash"] = out.get("quote_hash") or _digest({k: v for k, v in out.items() if k != "quote_hash"})
            return out

        return await self._idempotent("AGENT_LIFECYCLE_QUOTE", req.idempotency_key, payload, execute)

    async def _cancel_refund_quote(self, account: str, vertical: str, oid: str):
        if vertical == "HOTEL":
            from go_hotel.fare.service import fare_service
            return fare_service.cancellation_quote(oid)
        if vertical == "FLIGHT":
            from go_hotel.flight.service import flight_service
            return flight_service.refund_quote(account, oid)
        if vertical == "RAIL":
            from go_hotel.rail.service import rail_service
            return rail_service.refund_quote(account, oid)
        if vertical == "RIDE":
            from go_hotel.mobility.ride.service import ride_service
            return ride_service.refund_quote(account, oid)
        if vertical == "RENTAL":
            from go_hotel.mobility.rental.service import rental_service
            return rental_service.refund_quote(account, oid)
        from go_hotel.attractions.service import attraction_service
        return attraction_service.refund_quote(account, oid)

    async def _change_quote(self, account: str, vertical: str, oid: str, changes: dict[str, Any]):
        if vertical == "HOTEL":
            from go_hotel.fare.service import fare_service
            return await fare_service.change_quote(oid, changes["new_check_in"], changes["new_check_out"])
        if vertical == "FLIGHT":
            from go_hotel.flight.service import flight_service
            return flight_service.change_quote(account, oid, changes["new_departure_date"])
        if vertical == "RAIL":
            from go_hotel.rail.service import rail_service
            return rail_service.change_quote(account, oid, changes["new_travel_date"], changes.get("new_seat_class"))
        if vertical == "RIDE":
            native = await self._native_order(account, vertical, oid)
            if native.get("status") != "CONFIRMED":
                raise ValueError("MOBILITY_ORDER_NOT_CHANGEABLE")
            return {
                "quote_id": "ride-change:" + _digest({"order": native, "new_time": changes["new_time"]})[:24],
                "order_id": oid,
                "new_time": changes["new_time"],
                "currency": native["currency"],
                "total_due_minor": 0,
                "order_revision": _digest(native),
                "external_live": False,
            }
        if vertical == "RENTAL":
            from go_hotel.mobility.rental.changes import quote
            return quote(account, oid, changes["new_pickup_at"], changes["new_return_at"])
        from go_hotel.attractions.service import attraction_service
        return attraction_service.change_quote(account, oid, changes["new_visit_date"], changes.get("new_session_time"))

    async def lifecycle_execute(self, ctx: AgentContext, req: LifecycleExecuteRequest) -> dict[str, Any]:
        account = ctx.require_traveler()
        vertical, oid = _parse_ref(req.order_id)
        action = req.action.upper()
        if action not in {"CANCEL", "CHANGE", "REFUND"}:
            raise ValueError("LIFECYCLE_ACTION_INVALID")
        if not req.quote_hash:
            raise ValueError("ACCEPTED_LIFECYCLE_QUOTE_HASH_REQUIRED")
        payload = {
            "account": account, "order_id": req.order_id, "action": action,
            "quote_id": req.quote_id, "quote_hash": req.quote_hash,
            "changes": dict(req.changes), "payment_method_id": req.payment_method_id,
        }

        async def execute():
            native = (await self._execute_change(account, vertical, oid, req)
                      if action == "CHANGE" else await self._execute_cancel_refund(account, vertical, oid, req))
            order = asdict(await self.get_order(ctx, req.order_id))
            return {
                "action": action,
                "order_id": req.order_id,
                "native_result": _jsonable(native),
                "order_truth": order,
                "transaction_version": order["transaction_version"],
            }

        return await self._idempotent("AGENT_LIFECYCLE_" + action, req.idempotency_key, payload, execute)

    async def _execute_cancel_refund(self, account: str, vertical: str, oid: str, req: LifecycleExecuteRequest):
        if vertical == "HOTEL":
            if not req.quote_id:
                raise ValueError("QUOTE_ID_REQUIRED")
            from go_hotel.fare.service import fare_service
            return await fare_service.cancel(oid, req.quote_id, req.quote_hash, True, account)
        if vertical == "FLIGHT":
            from go_hotel.flight.service import flight_service
            return flight_service.refund(account, oid, req.quote_hash)
        if vertical == "RAIL":
            from go_hotel.rail.service import rail_service
            return rail_service.refund(account, oid, req.quote_hash)
        if vertical == "RIDE":
            from go_hotel.mobility.ride.service import ride_service
            return ride_service.cancel(account, oid, req.quote_hash)
        if vertical == "RENTAL":
            from go_hotel.mobility.rental.service import rental_service
            return rental_service.cancel(account, oid, req.quote_hash)
        from go_hotel.attractions.service import attraction_service
        return attraction_service.refund(account, oid, req.quote_hash)

    async def _execute_change(self, account: str, vertical: str, oid: str, req: LifecycleExecuteRequest):
        if not req.quote_id:
            raise ValueError("QUOTE_ID_REQUIRED")
        if vertical != "HOTEL":
            await self._verify_change_quote_hash(account, vertical, oid, req)
        if vertical == "HOTEL":
            if not req.payment_method_id:
                raise ValueError("CHANGE_PAYMENT_METHOD_REQUIRED")
            from go_hotel.fare.service import fare_service
            return await fare_service.change(oid, req.quote_id, req.payment_method_id, req.quote_hash, True, account)
        if vertical == "FLIGHT":
            from go_hotel.flight.service import flight_service
            return flight_service.execute_change(account, oid, req.quote_id)
        if vertical == "RAIL":
            from go_hotel.rail.service import rail_service
            return rail_service.execute_change(account, oid, req.quote_id)
        if vertical == "RIDE":
            native = await self._native_order(account, vertical, oid)
            expected = "ride-change:" + _digest({"order": native, "new_time": dict(req.changes)["new_time"]})[:24]
            if req.quote_id != expected:
                raise ValueError("RIDE_CHANGE_QUOTE_STALE")
            from go_hotel.mobility.ride.service import ride_service
            return ride_service.modify(account, oid, dict(req.changes)["new_time"])
        if vertical == "RENTAL":
            from go_hotel.db.session import SessionLocal
            from go_hotel.db.models import RentalChangeQuoteRow
            with SessionLocal() as s:
                q = s.get(RentalChangeQuoteRow, req.quote_id)
                if not q or q.order_id != oid:
                    raise ValueError("RENTAL_CHANGE_QUOTE_NOT_FOUND")
                difference, currency = q.difference_minor, q.currency
            from go_hotel.mobility.rental.changes import execute
            return execute(account, oid, req.quote_id, difference, currency)
        from go_hotel.attractions.service import attraction_service
        return attraction_service.execute_change(account, oid, req.quote_id)

    async def _verify_change_quote_hash(self, account: str, vertical: str, oid: str, req: LifecycleExecuteRequest):
        changes = dict(req.changes)
        if vertical == "RIDE":
            native = await self._native_order(account, vertical, oid)
            q = {
                "quote_id": "ride-change:" + _digest({"order": native, "new_time": changes["new_time"]})[:24],
                "order_id": oid, "new_time": changes["new_time"], "currency": native["currency"],
                "total_due_minor": 0, "order_revision": _digest(native), "external_live": False,
            }
        else:
            from go_hotel.db.session import SessionLocal
            with SessionLocal() as db:
                if vertical == "FLIGHT":
                    from go_hotel.db.models import FlightChangeQuoteRow as Row
                    r = db.get(Row, req.quote_id)
                    if not r or r.order_id != oid: raise ValueError("FLIGHT_CHANGE_QUOTE_INVALID")
                    q = {"quote_id": r.quote_id, "order_id": oid, "new_departure_date": r.new_departure_date,
                         "new_flight_number": r.new_flight_number, "fare_difference_minor": r.fare_difference_minor,
                         "change_fee_minor": r.change_fee_minor, "total_due_minor": r.total_due_minor,
                         "currency": r.currency, "expires_at": r.expires_at.isoformat()}
                elif vertical == "RAIL":
                    from go_hotel.db.models import RailChangeQuoteRow as Row
                    r = db.get(Row, req.quote_id)
                    if not r or r.order_id != oid: raise ValueError("RAIL_CHANGE_QUOTE_INVALID")
                    q = {"quote_id": r.quote_id, "order_id": oid, "new_travel_date": r.new_travel_date,
                         "new_train_no": r.new_train_no, "new_seat_class": r.new_seat_class,
                         "fare_difference_minor": r.fare_difference_minor, "change_fee_minor": r.change_fee_minor,
                         "total_due_minor": r.total_due_minor, "currency": r.currency,
                         "expires_at": r.expires_at.isoformat()}
                elif vertical == "ATTRACTION":
                    from go_hotel.db.models import AttractionChangeQuoteRow as Row
                    r = db.get(Row, req.quote_id)
                    if not r or r.order_id != oid: raise ValueError("ATTRACTION_CHANGE_QUOTE_NOT_FOUND")
                    q = {"quote_id": r.quote_id, "order_id": oid, "new_visit_date": r.new_visit_date,
                         "new_session_time": r.new_session_time, "change_fee_minor": r.change_fee_minor,
                         "total_due_minor": r.total_due_minor, "currency": r.currency,
                         "expires_at": r.expires_at.isoformat()}
                elif vertical == "RENTAL":
                    from go_hotel.db.models import RentalChangeQuoteRow as Row
                    r = db.get(Row, req.quote_id)
                    if not r or r.order_id != oid: raise ValueError("RENTAL_CHANGE_QUOTE_NOT_FOUND")
                    q = {"quote_id": r.quote_id, "order_id": oid, "new_pickup_at": r.new_pickup_at,
                         "new_return_at": r.new_return_at, "old_amount_minor": r.old_amount_minor,
                         "new_amount_minor": r.new_amount_minor, "difference_minor": r.difference_minor,
                         "currency": r.currency, "status": r.status, "expires_at": r.expires_at.isoformat()}
                else:
                    raise ValueError("CHANGE_VERTICAL_INVALID")
        wrapped = _jsonable(q)
        wrapped["agent_order_id"] = req.order_id
        wrapped["action"] = "CHANGE"
        wrapped.setdefault("quote_id", req.quote_id)
        expected = _digest({k: v for k, v in wrapped.items() if k != "quote_hash"})
        if expected != req.quote_hash:
            raise ValueError("CHANGE_QUOTE_RECONFIRM_REQUIRED")

    async def release(self, ctx: AgentContext, reserve_id: str, idempotency_key: str):
        account = ctx.require_traveler()
        vertical, oid = _parse_ref(reserve_id)
        payload = {"account": account, "reserve_id": reserve_id}

        async def execute():
            if vertical in {"RAIL", "ATTRACTION"}:
                from go_hotel.services.vertical_capacity import cancel_unpaid
                if vertical == "RAIL":
                    from go_hotel.rail.service import rail_service
                    output = rail_service._order
                else:
                    from go_hotel.attractions.service import attraction_service
                    output = attraction_service.out
                native = cancel_unpaid(vertical, account, oid, output)
                return {"action": "RELEASE", "reserve_id": reserve_id, "state": "RELEASED",
                        "capacity_released": True, "order_truth": _jsonable(native)}
            native = await self._release_unpaid_unheld(account, vertical, oid)
            return {"action": "RELEASE", "reserve_id": reserve_id, "state": "RELEASED",
                    "capacity_released": False, "order_truth": native}

        return await self._idempotent("AGENT_RELEASE", idempotency_key, payload, execute)

    async def _release_unpaid_unheld(self, account: str, vertical: str, oid: str):
        from sqlalchemy import select
        from go_hotel.db.session import SessionLocal
        from go_hotel.db.models import (OrderRow, PrebookRow, PaymentRow, FlightOrderRow,
            MobilityRideOrderRow, MobilityRentalOrderRow, OmnichannelPaymentIntentRow)

        if vertical == "HOTEL":
            from go_hotel.repositories.sql import repo
            from go_hotel.domain.models import Event, new_id, now_utc
            with SessionLocal.begin() as s:
                o = s.get(OrderRow, oid, with_for_update=True)
                if not o or o.account_id != account: raise ValueError("ORDER_NOT_FOUND")
                if o.status == "CANCELLED": return _jsonable(repo._order(o))
                if o.status != "PAYMENT_PENDING": raise ValueError("UNPAID_RELEASE_NOT_ALLOWED")
                started = s.scalar(select(PaymentRow.payment_id).where(PaymentRow.order_id == oid)) or s.scalar(
                    select(OmnichannelPaymentIntentRow.payment_intent_id).where(
                        OmnichannelPaymentIntentRow.business_type == "HOTEL_ORDER",
                        OmnichannelPaymentIntentRow.business_id == oid))
                if started: raise ValueError("PAYMENT_ALREADY_STARTED_RECONCILIATION_REQUIRED")
                pb = s.get(PrebookRow, o.prebook_id)
                if not pb: raise ValueError("PREBOOK_NOT_FOUND")
                if pb.inventory_held:
                    from go_hotel.services.hotel_hard_hold_release import release_locked
                    return await release_locked(s, o, pb, account, oid)
                o.status = "CANCELLED"; o.version += 1; o.updated_at = now_utc()
                repo._append_event_and_outbox(s, Event(new_id("evt"), "UNPAID_ORDER_CANCELLED", "HOTEL_ORDER", oid,
                    {"account_id": account, "inventory_held": False, "release": "AGENT"}))
            return _jsonable(repo.get_order(oid))

        from go_hotel.autonomy.durable import transaction
        from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence
        from go_hotel.services.vertical_lifecycle_projection import project_vertical_lifecycle
        model = {"FLIGHT": FlightOrderRow, "RIDE": MobilityRideOrderRow, "RENTAL": MobilityRentalOrderRow}.get(vertical)
        if model is None: raise ValueError("UNPAID_RELEASE_VERTICAL_INVALID")
        with transaction(SessionLocal) as s:
            o = s.get(model, oid, with_for_update=True)
            if not o or o.account_id != account: raise ValueError(vertical + "_ORDER_NOT_FOUND")
            if o.status != "CANCELLED":
                if o.status != "PAYMENT_PENDING": raise ValueError("UNPAID_RELEASE_NOT_ALLOWED")
                started = s.scalar(select(OmnichannelPaymentIntentRow.payment_intent_id).where(
                    OmnichannelPaymentIntentRow.business_type == vertical + "_ORDER",
                    OmnichannelPaymentIntentRow.business_id == oid))
                if started: raise ValueError("PAYMENT_ALREADY_STARTED_RECONCILIATION_REQUIRED")
                o.status = "CANCELLED"; o.updated_at = datetime.now(UTC).replace(tzinfo=None)
                append_vertical_evidence(s, vertical, oid, "UNPAID_ORDER_CANCELLED", o.status,
                    {"account_id": account, "capacity_released": False})
                project_vertical_lifecycle(s, vertical, o, "agent-release://" + oid,
                    facts={"unpaid": True, "capacity_released": False})
        return await self._native_order(account, vertical, oid)

    async def expire(self, ctx: AgentContext, req: ExpireRequest) -> dict[str, Any]:
        account = ctx.require_traveler()
        vertical, oid = _parse_ref(req.reserve_id)
        payload = {"account": account, "reserve_id": req.reserve_id}

        async def execute():
            if vertical in {"RAIL", "ATTRACTION"}:
                from go_hotel.services.vertical_reservation_expiry import expire_one
                state = expire_one(vertical, oid)
            elif vertical in {"HOTEL", "FLIGHT"}:
                state = await self._expire_prebook_deadline(account, vertical, oid)
            elif vertical in {"RIDE", "RENTAL"}:
                from go_hotel.services.vertical_reservation_expiry import expire_one
                state = expire_one(vertical, oid)
            else:
                raise ValueError("AGENT_EXPIRE_NATIVE_DEADLINE_REQUIRED:" + vertical)
            order = asdict(await self.get_order(ctx, req.reserve_id))
            return {"action": "EXPIRE", "reserve_id": req.reserve_id, "state": state,
                    "order_truth": order, "transaction_version": order["transaction_version"]}

        return await self._idempotent("AGENT_EXPIRE", req.idempotency_key, payload, execute)

    async def _expire_prebook_deadline(self, account: str, vertical: str, oid: str):
        from sqlalchemy import select
        from go_hotel.db.session import SessionLocal
        from go_hotel.db.models import (OrderRow, PrebookRow, PaymentRow, FlightOrderRow,
            FlightPrebookRow, OmnichannelPaymentIntentRow)
        now = datetime.now(UTC)

        if vertical == "HOTEL":
            from go_hotel.repositories.sql import repo
            from go_hotel.domain.models import Event, new_id, now_utc
            with SessionLocal.begin() as s:
                o = s.get(OrderRow, oid, with_for_update=True)
                if not o or o.account_id != account: raise ValueError("ORDER_NOT_FOUND")
                if o.status == "CANCELLED": return "UNCHANGED"
                if o.status != "PAYMENT_PENDING": return "PAYMENT_STARTED"
                pb = s.get(PrebookRow, o.prebook_id)
                if not pb: raise ValueError("PREBOOK_NOT_FOUND")
                exp = pb.expires_at if pb.expires_at.tzinfo else pb.expires_at.replace(tzinfo=UTC)
                if exp > now: return "NOT_DUE"
                started = s.scalar(select(PaymentRow.payment_id).where(PaymentRow.order_id == oid)) or s.scalar(
                    select(OmnichannelPaymentIntentRow.payment_intent_id).where(
                        OmnichannelPaymentIntentRow.business_type == "HOTEL_ORDER",
                        OmnichannelPaymentIntentRow.business_id == oid))
                if started: return "PAYMENT_STARTED"
                if pb.inventory_held: raise ValueError("HOTEL_HARD_HOLD_EXPIRY_REQUIRES_CONNECTOR_RELEASE")
                o.status = "CANCELLED"; o.version += 1; o.updated_at = now_utc()
                repo._append_event_and_outbox(s, Event(new_id("evt"), "UNPAID_RESERVATION_EXPIRED", "HOTEL_ORDER", oid,
                    {"prebook_id": pb.prebook_id, "inventory_held": False}))
                return "EXPIRED"

        from go_hotel.autonomy.durable import transaction
        from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence
        from go_hotel.services.vertical_lifecycle_projection import project_vertical_lifecycle
        with transaction(SessionLocal) as s:
            o = s.get(FlightOrderRow, oid, with_for_update=True)
            if not o or o.account_id != account: raise ValueError("FLIGHT_ORDER_NOT_FOUND")
            if o.status == "CANCELLED": return "UNCHANGED"
            if o.status != "PAYMENT_PENDING": return "PAYMENT_STARTED"
            pb = s.get(FlightPrebookRow, o.prebook_id)
            if not pb: raise ValueError("FLIGHT_PREBOOK_NOT_FOUND")
            exp = pb.expires_at if pb.expires_at.tzinfo else pb.expires_at.replace(tzinfo=UTC)
            if exp > now: return "NOT_DUE"
            started = s.scalar(select(OmnichannelPaymentIntentRow.payment_intent_id).where(
                OmnichannelPaymentIntentRow.business_type == "FLIGHT_ORDER",
                OmnichannelPaymentIntentRow.business_id == oid))
            if started: return "PAYMENT_STARTED"
            o.status = "CANCELLED"; o.updated_at = datetime.now(UTC).replace(tzinfo=None)
            append_vertical_evidence(s, "FLIGHT", oid, "UNPAID_RESERVATION_EXPIRED", o.status,
                {"prebook_id": pb.prebook_id, "capacity_released": False})
            project_vertical_lifecycle(s, "FLIGHT", o, "agent-expiry://" + oid,
                facts={"unpaid": True, "capacity_released": False})
            return "EXPIRED"
