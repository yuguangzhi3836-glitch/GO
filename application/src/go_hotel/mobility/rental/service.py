from __future__ import annotations

from datetime import UTC, datetime
from math import ceil

from sqlalchemy import select

from go_hotel.core.production_truth_gate import production_truth_required
from go_hotel.db.models import MobilityRefundRow, MobilityRentalOrderRow, RentalChangeQuoteRow
from go_hotel.db.session import SessionLocal
from go_hotel.domain.models import new_id
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence, list_vertical_evidence
from go_hotel.services.vertical_lifecycle_projection import project_vertical_lifecycle
from go_hotel.services.vertical_money_bridge import vertical_money_bridge
from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service
from go_hotel.mobility.rental.changes import transaction, owned, adjustment_ids, isolated


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)

def rental_days(pickup_at: str, return_at: str) -> int:
    try:
        start=datetime.fromisoformat(pickup_at.replace('Z','+00:00'))
        end=datetime.fromisoformat(return_at.replace('Z','+00:00'))
        seconds=(end-start).total_seconds()
    except (ValueError, TypeError):
        raise ValueError('RENTAL_DATES_INVALID') from None
    if not 0 < seconds <= 365*86400:
        raise ValueError('RENTAL_PERIOD_INVALID')
    return ceil(seconds/86400)


class RentalService:
    def search(self, pickup_location: str, return_location: str, pickup_at: str, return_at: str, currency: str = "CNY"):
        production_truth_required("RENTAL", "SEARCH")
        days=rental_days(pickup_at,return_at)
        return [
            {"offer_id": "rental_compact", "vehicle_class": "COMPACT", "total_amount_minor": 42000*days, "rental_days":days, "daily_rate_minor":42000, "currency": currency, "insurance": {"type": "BASIC", "excess_minor": 500000}, "mileage": {"type": "UNLIMITED"}, "deposit_minor": 200000, "cancellation": {"free_until_hours": 24}, "external_live": False},
            {"offer_id": "rental_suv", "vehicle_class": "SUV", "total_amount_minor": 66000*days, "rental_days":days, "daily_rate_minor":66000, "currency": currency, "insurance": {"type": "FULL", "excess_minor": 0}, "mileage": {"type": "UNLIMITED"}, "deposit_minor": 300000, "cancellation": {"free_until_hours": 24}, "external_live": False},
        ]

    def create(self, account: str, body: dict):
        production_truth_required("RENTAL", "CREATE_ORDER")
        data = {"rental_compact": ("COMPACT", 126000, {"type": "BASIC", "excess_minor": 500000}, 200000),
                "rental_suv": ("SUV", 198000, {"type": "FULL", "excess_minor": 0}, 300000)}.get(body["offer_id"])
        if not data:
            raise ValueError("RENTAL_OFFER_NOT_FOUND")
        days=rental_days(body['pickup_at'],body['return_at'])
        with SessionLocal.begin() as s:
            vc, total, ins, dep = data
            total=total//3*days
            o = MobilityRentalOrderRow(
                order_id=new_id("rent_ord"), account_id=account, status="PAYMENT_PENDING",
                pickup_location=body["pickup_location"], return_location=body["return_location"],
                pickup_at=body["pickup_at"], return_at=body["return_at"], vehicle_class=vc,
                insurance=ins, mileage={"type": "UNLIMITED"}, deposit_minor=dep,
                total_amount_minor=total, currency=body.get("currency", "CNY"), drivers=body.get("drivers", []),
                supplier_reference=None, created_at=now(), updated_at=now(),
            )
            s.add(o); s.flush()
            from go_hotel.services.vertical_reservation_expiry import issue_in
            issue_in(s, "RENTAL", o)
            append_vertical_evidence(s, "RENTAL", o.order_id, "ORDER_CREATED", o.status, {
                "supplier_reference": o.supplier_reference, "offer_id": body["offer_id"], "deposit_minor": dep,
                "insurance": ins, "external_live": False,
            })
            result=self.out(o)
        vertical_source_runtime_service.decide("RENTAL",result["order_id"],[{"source_id":"rental-engineering-source","source_type":"RENTAL_COMPANY_OFFICIAL","authorized":True,"available":True,"evidence_reference":f"rental-offer://{body['offer_id']}"}])
        return result

    def out(self, o):
        return {"vertical": "RENTAL", "order_id": o.order_id, "status": o.status,
                "pickup_location": o.pickup_location, "return_location": o.return_location,
                "pickup_at": o.pickup_at, "return_at": o.return_at, "vehicle_class": o.vehicle_class,
                "insurance": o.insurance, "mileage": o.mileage, "deposit_minor": o.deposit_minor,
                "total_amount_minor": o.total_amount_minor, "currency": o.currency, "drivers": o.drivers,
                "supplier_reference": o.supplier_reference if o.status in {"CONFIRMED","IN_PROGRESS"} else None,
                **__import__("go_hotel.services.vertical_reservation_expiry", fromlist=["projection"]).projection("RENTAL", o), "external_live": False}

    def get(self, account: str, order_id: str):
        with SessionLocal() as s:
            o = s.get(MobilityRentalOrderRow, order_id)
            if not o or o.account_id != account:
                raise ValueError("MOBILITY_ORDER_NOT_FOUND")
            out = self.out(o)
            pending=s.scalar(select(RentalChangeQuoteRow).where(RentalChangeQuoteRow.order_id==order_id,RentalChangeQuoteRow.status=='MONEY_PENDING'))
            out['pending_change']={'quote_id':pending.quote_id,'difference_minor':pending.difference_minor,'currency':pending.currency,'new_pickup_at':pending.new_pickup_at,'new_return_at':pending.new_return_at,'new_amount_minor':pending.new_amount_minor} if pending else None
            out["evidence"] = list_vertical_evidence(s, "RENTAL", order_id); return out

    def trips(self, account: str):
        with SessionLocal() as s:
            return [self.out(x) for x in s.scalars(select(MobilityRentalOrderRow).where(MobilityRentalOrderRow.account_id == account)).all()]

    def modify(self, account: str, order_id: str, new_time: str):
        production_truth_required("RENTAL", "MODIFY")
        with transaction() as s:
            o = s.get(MobilityRentalOrderRow, order_id, with_for_update=True)
            if not o or o.account_id != account or o.status != "CONFIRMED":
                raise ValueError("MOBILITY_ORDER_NOT_CHANGEABLE")
            if rental_days(new_time,o.return_at)!=rental_days(o.pickup_at,o.return_at):
                raise ValueError('RENTAL_REPRICE_CONFIRMATION_REQUIRED')
            o.pickup_at = new_time; o.updated_at = now()
            append_vertical_evidence(s, "RENTAL", order_id, "MODIFIED", o.status, {"new_time": new_time})
            return self.out(o)

    def refund_quote(self, account: str, order_id: str):
        production_truth_required("RENTAL", "REFUND_QUOTE")
        from go_hotel.services import refund_consent
        with transaction() as s:
            o=owned(s,account,order_id)
            if o.status!='CONFIRMED':raise ValueError('MOBILITY_ORDER_NOT_CANCELLABLE')
            return refund_consent.bind('RENTAL',o,{'order_id':order_id,'fee_minor':0,
                'refund_amount_minor':o.total_amount_minor,'currency':o.currency,'refund_to':'ORIGINAL_PAYMENT_METHOD'})

    def cancel(self, account: str, order_id: str, accepted_hash=None):
        production_truth_required("RENTAL", "CANCEL")
        isolated()
        from go_hotel.services import refund_consent, mobility_refund_consent as consent
        def result(r):
            return {'refund_id':r.refund_id,'order_id':order_id,'status':r.status,
                    'refund_amount_minor':r.refund_amount_minor,'currency':r.currency}
        def verify_receipts(s,r,movement):
            from types import SimpleNamespace
            from collections import Counter
            from go_hotel.services.vertical_refund_recovery import _confirmed_money_in
            from go_hotel.db.models import OmnichannelMoneyMovementRow as Movement
            ids=_confirmed_money_in(s,SimpleNamespace(vertical='RENTAL',order_id=order_id,
                account_id=account,adjustment_ids_json=adjustment_ids(s,order_id),
                quote_json={'currency':r.currency,'refund_amount_minor':r.refund_amount_minor}),movement)
            expected=Counter((item['payment_intent_id'],item['capture_id'],item['amount_minor'],item['key'])
                for item in r.settlement_plan_json)
            receipts=[s.get(Movement,mid) for mid in ids]
            observed=Counter((item.root_payment_intent_id,item.parent_movement_id,
                item.amount_minor,item.idempotency_key) for item in receipts)
            if observed!=expected:raise ValueError('REFUND_RECEIPT_PLAN_MISMATCH')
            return ids
        def completed(s,o,r):
            if o.status!='REFUNDED':raise ValueError('RENTAL_REFUND_RECONCILIATION_REQUIRED')
            from go_hotel.services.ticket_operations import _events
            _events(s,'RENTAL',order_id)
            evidence=[x['payload'] for x in list_vertical_evidence(s,'RENTAL',order_id)
                if x['kind']=='REFUND_COMPLETED' and x['payload'].get('refund_id')==r.refund_id]
            if len(evidence)!=1 or evidence[0].get('refund_amount_minor')!=r.refund_amount_minor:
                raise ValueError('REFUND_COMPLETION_EVIDENCE_INVALID')
            verify_receipts(s,r,evidence[0])
            return result(r)
        with transaction() as s:
            o=owned(s,account,order_id)
            r=s.scalar(select(MobilityRefundRow).where(MobilityRefundRow.order_id==order_id,
                MobilityRefundRow.vertical=='RENTAL').order_by(MobilityRefundRow.created_at.desc()))
            if r:consent.existing(s,o,r,accepted_hash,'RENTAL')
            if r and r.status=='REFUND_COMPLETED':
                return completed(s,o,r)
            if r and r.status=='REFUND_PENDING':
                if o.status!='REFUND_PENDING':raise ValueError('RENTAL_REFUND_RECONCILIATION_REQUIRED')
            else:
                if o.status!='CONFIRMED':raise ValueError('MOBILITY_ORDER_NOT_CANCELLABLE')
                q=refund_consent.bind('RENTAL',o,{'order_id':order_id,'fee_minor':0,
                    'refund_amount_minor':o.total_amount_minor,'currency':o.currency,'refund_to':'ORIGINAL_PAYMENT_METHOD'})
                refund_consent.verify(q,accepted_hash)
                refund_id=new_id('mob_ref')
                plan=vertical_money_bridge.plan_refund('RENTAL',order_id,adjustment_ids(s,order_id),
                    o.total_amount_minor,'rental-cancel:'+refund_id)
                r=MobilityRefundRow(refund_id=refund_id,order_id=order_id,vertical='RENTAL',fee_minor=0,
                    refund_amount_minor=o.total_amount_minor,currency=o.currency,status='REFUND_PENDING',
                    settlement_plan_json=plan,created_at=now())
                consent.freeze(s,o,r,q,accepted_hash,'RENTAL')
                s.add(r);o.status='REFUND_PENDING';o.updated_at=now()
                append_vertical_evidence(s,'RENTAL',order_id,'REFUND_REQUESTED',o.status,
                    {'refund_id':refund_id,'refund_amount_minor':r.refund_amount_minor,'refund_to':'ORIGINAL_PAYMENT_METHOD'})
                project_vertical_lifecycle(s,'RENTAL',o,'rental-refund://'+refund_id)
            refund_id=r.refund_id;plan=r.settlement_plan_json
        movement=vertical_money_bridge.execute_refund_plan(plan,'rental-refund://'+refund_id)
        if movement['state']!='CONFIRMED':raise ValueError('MOBILITY_REFUND_MONEY_NOT_CONFIRMED')
        with transaction() as s:
            o=owned(s,account,order_id);r=s.get(MobilityRefundRow,refund_id,with_for_update=True)
            consent.existing(s,o,r,accepted_hash,'RENTAL')
            if r.status=='REFUND_COMPLETED':
                return completed(s,o,r)
            if o.status!='REFUND_PENDING':raise ValueError('RENTAL_REFUND_RECONCILIATION_REQUIRED')
            # A provider/executor status alone cannot complete a refund. Verify
            # durable receipts against this owner's original and change roots.
            confirmed_ids=verify_receipts(s,r,movement)
            r.status='REFUND_COMPLETED';o.status='REFUNDED';o.updated_at=now()
            facts={'refund_id':refund_id,'refund_amount_minor':r.refund_amount_minor,
                   'money_movement_ids':confirmed_ids}
            append_vertical_evidence(s,'RENTAL',order_id,'REFUND_COMPLETED',o.status,facts)
            project_vertical_lifecycle(s,'RENTAL',o,'rental-refund://'+refund_id,facts=facts)
            return result(r)

    def fulfill(self, account: str, order_id: str, action: str, evidence_reference: str):
        if not str(evidence_reference or '').strip(): raise ValueError('FULFILLMENT_EVIDENCE_REQUIRED')
        production_truth_required("RENTAL", "FULFILLMENT")
        action = action.upper()
        with transaction() as s:
            o = s.get(MobilityRentalOrderRow, order_id, with_for_update=True)
            if not o or o.account_id != account:
                raise ValueError("MOBILITY_ORDER_NOT_FOUND")
            target = {("CONFIRMED", "PICKUP"): "IN_PROGRESS", ("IN_PROGRESS", "RETURN"): "COMPLETED"}.get((o.status, action))
            if not target:
                raise ValueError("MOBILITY_ILLEGAL_STATE_TRANSITION")
            o.status = target; o.updated_at = now()
            append_vertical_evidence(s, "RENTAL", order_id, f"FULFILLMENT_{action}", target, {"evidence_reference": evidence_reference, "supplier_reference": o.supplier_reference}); project_vertical_lifecycle(s,"RENTAL",o,evidence_reference,facts={"action":action,"supplier_reference":o.supplier_reference})
            return self.out(o)

    def admin_external_state(self, order_id: str, state: str, evidence_reference: str, actor: str):
        if not str(evidence_reference or '').strip() or not str(actor or '').strip(): raise ValueError('EXTERNAL_STATE_ACTOR_AND_EVIDENCE_REQUIRED')
        state = state.upper()
        if state not in {"UNKNOWN_EXTERNAL_STATE", "CONFIRMED", "FAILED"}:
            raise ValueError("MOBILITY_EXTERNAL_STATE_INVALID")
        with transaction() as s:
            o = s.get(MobilityRentalOrderRow, order_id, with_for_update=True)
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
                evidence=list_vertical_evidence(s, "RENTAL", order_id)
                unknown=next((x for x in reversed(evidence) if x.get("kind")=="EXTERNAL_STATE_UNKNOWN"),None)
                previous_status=((unknown or {}).get("payload") or {}).get("previous_status") or "CONFIRMED"
                if previous_status not in {"CONFIRMED","IN_PROGRESS"}: previous_status="CONFIRMED"
                o.status = previous_status; kind = "RECONCILED_TO_"+previous_status
                payload={"evidence_reference": evidence_reference, "actor": actor, "supplier_reference": o.supplier_reference, "restored_status": previous_status}
            o.updated_at = now(); append_vertical_evidence(s, "RENTAL", order_id, kind, o.status, payload); project_vertical_lifecycle(s,"RENTAL",o,evidence_reference,facts={"actor":actor,"native_status":o.status})
            return self.out(o)


rental_service = RentalService()
