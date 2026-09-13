from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from go_hotel.core.production_truth_gate import production_truth_required
from go_hotel.db.models import MobilityRefundRow, MobilityRideOrderRow, RideFlightTrackingBindingRow
from go_hotel.db.session import SessionLocal
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
            {"offer_id": "ride_standard", "vehicle_class": "COMFORT", "total_amount_minor": 16800, "currency": currency, "included_wait_minutes": 60, "meet_and_greet": True, "cancellation": {"free_until_hours": 24, "late_fee_minor": 8400}, "external_live": False},
            {"offer_id": "ride_premium", "vehicle_class": "PREMIUM", "total_amount_minor": 26800, "currency": currency, "included_wait_minutes": 90, "meet_and_greet": True, "cancellation": {"free_until_hours": 24, "late_fee_minor": 13400}, "external_live": False},
        ]

    def create(self, account: str, body: dict):
        production_truth_required("RIDE", "CREATE_ORDER")
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
            append_vertical_evidence(s, "RIDE", o.order_id, "ORDER_CREATED", o.status, {"offer_id": body["offer_id"], "external_live": False})
            if body.get("flight_no") and body.get("flight_tracking_enabled"):
                included = 90 if body["offer_id"] == "ride_premium" else 60
                extra = max(0, int(body.get("delay_protection_free_wait_minutes", 0)))
                cap = max(included, int(body.get("max_free_wait_minutes") or included + extra))
                s.add(RideFlightTrackingBindingRow(
                    ride_flight_tracking_binding_id=new_id("rftb"), ride_order_id=o.order_id,
                    flight_no=body["flight_no"].upper().replace(" ", ""), tracking_enabled=True,
                    original_pickup_at=o.pickup_at, current_pickup_at=o.pickup_at,
                    included_wait_minutes=included, delay_protection_enabled=bool(body.get("delay_protection_enabled", False)),
                    delay_protection_free_wait_minutes=extra, max_free_wait_minutes=cap,
                    supplier_rule_snapshot_json=body.get("supplier_rule_snapshot", {}),
                    sync_state="TRACKING_ACTIVE", updated_at=now(),
                ))
            result=self.out(o)
        vertical_source_runtime_service.decide("RIDE",result["order_id"],[{"source_id":"ride-engineering-source","source_type":"FLEET_OFFICIAL","authorized":True,"available":True,"evidence_reference":f"ride-offer://{body['offer_id']}"}])
        return result

    def out(self, o):
        return {"vertical": "RIDE", "order_id": o.order_id, "status": o.status, "pickup": o.pickup,
                "dropoff": o.dropoff, "pickup_at": o.pickup_at, "vehicle_class": o.vehicle_class,
                "total_amount_minor": o.total_amount_minor, "currency": o.currency,
                "passengers": o.passengers, "flight_no": o.flight_no,
                "supplier_reference": o.supplier_reference if o.status in {"CONFIRMED","IN_PROGRESS"} else None, "external_live": False}

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
        with SessionLocal.begin() as s:
            o = s.get(MobilityRideOrderRow, order_id)
            if not o or o.account_id != account or o.status != "CONFIRMED":
                raise ValueError("MOBILITY_ORDER_NOT_CHANGEABLE")
            o.pickup_at = new_time; o.updated_at = now()
            append_vertical_evidence(s, "RIDE", order_id, "MODIFIED", o.status, {"new_time": new_time})
            return self.out(o)

    def refund_quote(self, account: str, order_id: str):
        production_truth_required("RIDE", "REFUND_QUOTE")
        o = self.get(account, order_id)
        if o["status"] != "CONFIRMED":
            raise ValueError("MOBILITY_ORDER_NOT_CANCELLABLE")
        return {"order_id": order_id, "fee_minor": 0, "refund_amount_minor": o["total_amount_minor"], "currency": o["currency"], "refund_to": "ORIGINAL_PAYMENT_METHOD"}

    def cancel(self, account: str, order_id: str):
        production_truth_required("RIDE", "CANCEL")
        quote=self.refund_quote(account,order_id)
        movement=vertical_money_bridge.refund('RIDE',order_id,quote["refund_amount_minor"],f'ride-refund://{order_id}',f'ride-refund:{order_id}')
        if movement['state']!='CONFIRMED': raise ValueError('MOBILITY_REFUND_MONEY_NOT_CONFIRMED')
        with SessionLocal.begin() as s:
            o = s.get(MobilityRideOrderRow, order_id)
            existing=s.scalar(select(MobilityRefundRow).where(MobilityRefundRow.order_id==order_id,MobilityRefundRow.vertical=='RIDE',MobilityRefundRow.status=='REFUND_COMPLETED').order_by(MobilityRefundRow.created_at.desc()))
            if existing:return {"refund_id":existing.refund_id,"order_id":order_id,"status":existing.status,"refund_amount_minor":existing.refund_amount_minor,"currency":existing.currency}
            if not o or o.account_id != account or o.status != "CONFIRMED": raise ValueError("MOBILITY_ORDER_NOT_CANCELLABLE")
            amount = quote["refund_amount_minor"]; o.status = "REFUNDED"; o.updated_at = now()
            r = MobilityRefundRow(refund_id=new_id("mob_ref"), order_id=order_id, vertical="RIDE", fee_minor=quote["fee_minor"], refund_amount_minor=amount, currency=o.currency, status="REFUND_COMPLETED", created_at=now())
            s.add(r); append_vertical_evidence(s, "RIDE", order_id, "REFUND_COMPLETED", o.status, {"refund_id": r.refund_id, "refund_amount_minor": amount,"money_movement_id":movement['money_movement_id']}); project_vertical_lifecycle(s,"RIDE",o,"refund:"+r.refund_id,facts={"refund_id":r.refund_id,"refund_amount_minor":amount,"money_movement_id":movement['money_movement_id']})
            s.flush(); return {"refund_id": r.refund_id, "order_id": order_id, "status": r.status, "refund_amount_minor": amount, "currency": o.currency}

    def fulfill(self, account: str, order_id: str, action: str, evidence_reference: str):
        if not str(evidence_reference or '').strip(): raise ValueError('FULFILLMENT_EVIDENCE_REQUIRED')
        production_truth_required("RIDE", "FULFILLMENT")
        action = action.upper()
        with SessionLocal.begin() as s:
            o = s.get(MobilityRideOrderRow, order_id)
            if not o or o.account_id != account:
                raise ValueError("MOBILITY_ORDER_NOT_FOUND")
            target = {("CONFIRMED", "START"): "IN_PROGRESS", ("IN_PROGRESS", "COMPLETE"): "COMPLETED"}.get((o.status, action))
            if not target:
                raise ValueError("MOBILITY_ILLEGAL_STATE_TRANSITION")
            o.status = target; o.updated_at = now()
            append_vertical_evidence(s, "RIDE", order_id, f"FULFILLMENT_{action}", target, {"evidence_reference": evidence_reference, "supplier_reference": o.supplier_reference}); project_vertical_lifecycle(s,"RIDE",o,evidence_reference,facts={"action":action,"supplier_reference":o.supplier_reference})
            return self.out(o)

    def admin_external_state(self, order_id: str, state: str, evidence_reference: str, actor: str):
        if not str(evidence_reference or '').strip() or not str(actor or '').strip(): raise ValueError('EXTERNAL_STATE_ACTOR_AND_EVIDENCE_REQUIRED')
        state = state.upper()
        if state not in {"UNKNOWN_EXTERNAL_STATE", "CONFIRMED", "FAILED"}:
            raise ValueError("MOBILITY_EXTERNAL_STATE_INVALID")
        with SessionLocal.begin() as s:
            o = s.get(MobilityRideOrderRow, order_id)
            if not o:
                raise ValueError("MOBILITY_ORDER_NOT_FOUND")
            if state == "UNKNOWN_EXTERNAL_STATE":
                if o.status not in {"CONFIRMED", "IN_PROGRESS"}:
                    raise ValueError("MOBILITY_ILLEGAL_STATE_TRANSITION")
                previous_status=o.status
                o.status = state; kind = "EXTERNAL_STATE_UNKNOWN"
                payload={"evidence_reference": evidence_reference, "actor": actor, "supplier_reference": o.supplier_reference, "previous_status": previous_status}
            elif state == "FAILED":
                if o.status != "UNKNOWN_EXTERNAL_STATE":
                    raise ValueError("MOBILITY_RECONCILIATION_NOT_REQUIRED")
                o.status = "FAILED"; kind = "RECONCILED_TO_FAILED"
                payload={"evidence_reference": evidence_reference, "actor": actor, "supplier_reference": o.supplier_reference}
            else:
                if o.status != "UNKNOWN_EXTERNAL_STATE":
                    raise ValueError("MOBILITY_RECONCILIATION_NOT_REQUIRED")
                evidence=list_vertical_evidence(s, "RIDE", order_id)
                unknown=next((x for x in reversed(evidence) if x.get("kind")=="EXTERNAL_STATE_UNKNOWN"),None)
                previous_status=((unknown or {}).get("payload") or {}).get("previous_status") or "CONFIRMED"
                if previous_status not in {"CONFIRMED","IN_PROGRESS"}: previous_status="CONFIRMED"
                o.status = previous_status; kind = "RECONCILED_TO_"+previous_status
                payload={"evidence_reference": evidence_reference, "actor": actor, "supplier_reference": o.supplier_reference, "restored_status": previous_status}
            o.updated_at = now(); append_vertical_evidence(s, "RIDE", order_id, kind, o.status, payload); project_vertical_lifecycle(s,"RIDE",o,evidence_reference,facts={"actor":actor,"native_status":o.status})
            return self.out(o)


ride_service = RideService()
