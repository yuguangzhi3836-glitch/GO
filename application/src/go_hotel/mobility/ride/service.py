from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from go_hotel.core.production_truth_gate import production_truth_required
from go_hotel.db.models import MobilityRefundRow, MobilityRideOrderRow
from go_hotel.mobility.ride.flight_sync import engineering_policy, reject_client_rules, snapshot_policy, flight_ride_sync
from go_hotel.db.session import SessionLocal
from go_hotel.autonomy.durable import transaction
from go_hotel.domain.models import new_id
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence, list_vertical_evidence
from go_hotel.services.vertical_lifecycle_projection import project_vertical_lifecycle
from go_hotel.services.vertical_money_bridge import vertical_money_bridge
from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class RideService:
    def search(self, pickup: str, dropoff: str, pickup_at: str, currency: str = "CNY"):
        production_truth_required("RIDE", "SEARCH")
        return [
            {"offer_id": "ride_standard", "vehicle_class": "COMFORT", "total_amount_minor": 16800, "currency": currency, "included_wait_minutes": 60, "service_policy": engineering_policy("ride_standard"), "meet_and_greet": True, "cancellation": {"free_until_hours": 24, "late_fee_minor": 8400}, "external_live": False},
            {"offer_id": "ride_premium", "vehicle_class": "PREMIUM", "total_amount_minor": 26800, "currency": currency, "included_wait_minutes": 90, "service_policy": engineering_policy("ride_premium"), "meet_and_greet": True, "cancellation": {"free_until_hours": 24, "late_fee_minor": 13400}, "external_live": False},
        ]

    def create(self, account: str, body: dict):
        production_truth_required("RIDE", "CREATE_ORDER")
        reject_client_rules(body)
        prices = {"ride_standard": 16800, "ride_premium": 26800}
        total = prices.get(body["offer_id"])
        if total is None:
            raise ValueError("RIDE_OFFER_NOT_FOUND")
        with SessionLocal.begin() as s:
            o = MobilityRideOrderRow(
                order_id=new_id("ride_ord"), account_id=account, status="PAYMENT_PENDING",
                pickup=body["pickup"], dropoff=body["dropoff"], pickup_at=body["pickup_at"],
                vehicle_class="PREMIUM" if body["offer_id"] == "ride_premium" else "COMFORT",
                total_amount_minor=total, currency=body.get("currency", "CNY"),
                passengers=body.get("passengers", []), flight_no=body.get("flight_no"),
                supplier_reference=None,
                created_at=now(), updated_at=now(),
            )
            s.add(o); s.flush()
            from go_hotel.services.vertical_reservation_expiry import issue_in
            issue_in(s, "RIDE", o)
            append_vertical_evidence(s, "RIDE", o.order_id, "ORDER_CREATED", o.status, {"offer_id": body["offer_id"], "external_live": False})
            snapshot_policy(s, o, body['offer_id'])
            if body.get('flight_tracking_enabled'):
                flight_ride_sync.bind_in(s, account, o.order_id, {
                    'flight_identity': body.get('flight_identity'), 'authority_id': body.get('flight_authority_id'),
                    'tracking_enabled': True, 'delay_protection_enabled': body.get('delay_protection_enabled', False),
                    'expected_revision': 0}, creating=True)
            result=self.out(o)
            result["service_policy"]=engineering_policy(body["offer_id"])
        vertical_source_runtime_service.decide("RIDE",result["order_id"],[{"source_id":"ride-engineering-source","source_type":"FLEET_OFFICIAL","authorized":True,"available":True,"evidence_reference":f"ride-offer://{body['offer_id']}"}])
        return result

    def out(self, o):
        return {"vertical": "RIDE", "order_id": o.order_id, "status": o.status, "pickup": o.pickup,
                "dropoff": o.dropoff, "pickup_at": o.pickup_at, "vehicle_class": o.vehicle_class,
                "total_amount_minor": o.total_amount_minor, "currency": o.currency,
                "passengers": o.passengers, "flight_no": o.flight_no,
                "supplier_reference": o.supplier_reference if o.status in {"CONFIRMED","IN_PROGRESS"} else None,
                **__import__("go_hotel.services.vertical_reservation_expiry", fromlist=["projection"]).projection("RIDE", o), "external_live": False}

    def get(self, account: str, order_id: str):
        with SessionLocal() as s:
            o = s.get(MobilityRideOrderRow, order_id)
            if not o or o.account_id != account:
                raise ValueError("MOBILITY_ORDER_NOT_FOUND")
            out = self.out(o); out["evidence"] = list_vertical_evidence(s, "RIDE", order_id); return out

    def trips(self, account: str):
        with SessionLocal() as s:
            return [self.out(x) for x in s.scalars(select(MobilityRideOrderRow).where(MobilityRideOrderRow.account_id == account)).all()]

    def modify(self, account: str, order_id: str, new_time: str):
        production_truth_required("RIDE", "MODIFY")
        with transaction(SessionLocal) as s:
            o = s.get(MobilityRideOrderRow, order_id, with_for_update=True)
            if not o or o.account_id != account or o.status != "CONFIRMED":
                raise ValueError("MOBILITY_ORDER_NOT_CHANGEABLE")
            o.pickup_at = new_time; o.updated_at = now()
            append_vertical_evidence(s, "RIDE", order_id, "MODIFIED", o.status, {"new_time": new_time})
            return self.out(o)

    def refund_quote(self, account: str, order_id: str):
        production_truth_required("RIDE", "REFUND_QUOTE")
        from go_hotel.mobility.ride.refunds import quote
        return quote(account,order_id)

    def cancel(self, account: str, order_id: str, accepted_hash=None):
        production_truth_required("RIDE", "CANCEL")
        from go_hotel.mobility.ride.refunds import cancel
        return cancel(account,order_id,accepted_hash)

    def fulfill(self, account: str, order_id: str, action: str, evidence_reference: str):
        if not str(evidence_reference or '').strip(): raise ValueError('FULFILLMENT_EVIDENCE_REQUIRED')
        production_truth_required("RIDE", "FULFILLMENT")
        action = action.upper()
        with transaction(SessionLocal) as s:
            o = s.get(MobilityRideOrderRow, order_id, with_for_update=True)
            if not o or o.account_id != account:
                raise ValueError("MOBILITY_ORDER_NOT_FOUND")
            target = {("CONFIRMED", "START"): "IN_PROGRESS", ("IN_PROGRESS", "COMPLETE"): "COMPLETED"}.get((o.status, action))
            if not target:
                raise ValueError("MOBILITY_ILLEGAL_STATE_TRANSITION")
            o.status = target; o.updated_at = now()
            append_vertical_evidence(s, "RIDE", order_id, f"FULFILLMENT_{action}", target, {"evidence_reference": evidence_reference, "supplier_reference": o.supplier_reference}); project_vertical_lifecycle(s,"RIDE",o,evidence_reference,facts={"action":action,"supplier_reference":o.supplier_reference})
            return self.out(o)

    def admin_external_state(self, order_id: str, state: str, evidence_reference: str, actor: str, confirmation_episode_reference: str | None = None):
        if not str(evidence_reference or '').strip() or not str(actor or '').strip(): raise ValueError('EXTERNAL_STATE_ACTOR_AND_EVIDENCE_REQUIRED')
        state = state.upper()
        if state not in {"UNKNOWN_EXTERNAL_STATE", "CONFIRMED", "FAILED"}:
            raise ValueError("MOBILITY_EXTERNAL_STATE_INVALID")
        with transaction(SessionLocal) as s:
            o = s.get(MobilityRideOrderRow, order_id, with_for_update=True)
            if not o:
                raise ValueError("MOBILITY_ORDER_NOT_FOUND")
            if state == "UNKNOWN_EXTERNAL_STATE":
                # The transaction acquires the order row before checking state
                # (and BEGIN IMMEDIATE serializes SQLite test writers). A second
                # concurrent opener therefore observes the committed UNKNOWN and
                # loses without appending evidence or mutating the order.
                if o.status == "UNKNOWN_EXTERNAL_STATE":
                    raise ValueError("RIDE_UNKNOWN_EPISODE_ALREADY_OPEN")
                if o.status not in {"CONFIRMED", "IN_PROGRESS"}:
                    raise ValueError("MOBILITY_ILLEGAL_STATE_TRANSITION")
                from go_hotel.mobility.ride.recovery_evidence import reject_reused_unknown_episode
                reject_reused_unknown_episode(s, o, evidence_reference)
                previous_status=o.status
                o.status = state; kind = "EXTERNAL_STATE_UNKNOWN"
                payload={"evidence_reference": evidence_reference, "actor": actor, "supplier_reference": o.supplier_reference, "previous_status": previous_status}
            elif state == "FAILED":
                if o.status != "UNKNOWN_EXTERNAL_STATE":
                    raise ValueError("MOBILITY_RECONCILIATION_NOT_REQUIRED")
                # A terminal fleet decision must identify the current UNKNOWN
                # episode just like CONFIRMED. Otherwise a delayed failure from
                # an older episode could terminate a newer recovery attempt.
                from go_hotel.mobility.ride.recovery_evidence import previous_phase
                previous_phase(s, o, confirmation_episode_reference)
                o.status = "FAILED"; kind = "RECONCILED_TO_FAILED"
                payload={"evidence_reference": evidence_reference, "actor": actor,
                    "supplier_reference": o.supplier_reference,
                    "confirmation_episode_reference": confirmation_episode_reference}
            else:
                if o.status != "UNKNOWN_EXTERNAL_STATE":
                    raise ValueError("MOBILITY_RECONCILIATION_NOT_REQUIRED")
                from go_hotel.mobility.ride.recovery_evidence import previous_phase
                previous_status=previous_phase(s,o,confirmation_episode_reference)
                o.status = previous_status; kind = "RECONCILED_TO_"+previous_status
                payload={"evidence_reference": evidence_reference, "actor": actor, "supplier_reference": o.supplier_reference, "restored_status": previous_status, "confirmation_episode_reference": confirmation_episode_reference}
            o.updated_at = now(); append_vertical_evidence(s, "RIDE", order_id, kind, o.status, payload); project_vertical_lifecycle(s,"RIDE",o,evidence_reference,facts={"actor":actor,"native_status":o.status})
            return self.out(o)


ride_service = RideService()
