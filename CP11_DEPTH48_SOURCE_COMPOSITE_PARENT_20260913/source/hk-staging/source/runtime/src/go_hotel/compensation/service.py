from __future__ import annotations
from datetime import timezone
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    OrderRow, PrebookRow, OfferRow, PaymentRow, RefundRow,
    SupplierFaultCaseRow, SupplierFinancialAccountRow, SupplierLiabilityRow,
    CompensationPaymentRow, ProtectionFundLedgerRow,
)
from go_hotel.domain.models import Event, OrderStatus, PaymentStatus, new_id, now_utc
from go_hotel.repositories.sql import repo
from go_hotel.connectors.registry import registry
from go_hotel.connectors.resilience import ResilientConnector
from go_hotel.core.config import settings
from go_hotel.core.errors import not_found, conflict, unprocessable, unavailable
from go_hotel.services.hotel_money_bridge import hotel_money_bridge

SUPPLIER_FAULT_REASONS = {
    "OVERBOOKING", "NO_ROOM", "HOTEL_OPERATIONAL_ERROR", "HOTEL_SYSTEM_ERROR",
    "PROPERTY_SELF_CLOSURE", "ROOM_UNAVAILABLE", "UNJUSTIFIED_CANCELLATION",
}
EXTERNAL_REASONS = {"GOVERNMENT_ORDER", "NATURAL_DISASTER", "PUBLIC_SAFETY_EVENT", "FORCE_MAJEURE"}
GUEST_FAULT_REASONS = {"GUEST_FRAUD", "GUEST_INELIGIBLE"}

class CompensationService:
    def _context(self, order_id: str):
        with SessionLocal() as s:
            order=s.get(OrderRow, order_id)
            if not order: not_found("ORDER_NOT_FOUND", "Order not found")
            pb=s.get(PrebookRow, order.prebook_id)
            offer=s.get(OfferRow, pb.offer_id) if pb else None
            if not pb or not offer: not_found("ORDER_CONTEXT_MISSING", "Order booking context missing")
            return order, pb, offer

    def _connector(self, connector_id: str):
        return ResilientConnector(registry.get(connector_id), timeout_seconds=settings.connector_timeout_seconds, retries=settings.connector_retry_count)

    def configure_supplier_finance(self, supplier_id: str, settlement_minor: int, reserve_minor: int, bank_minor: int, mandate_active: bool) -> dict:
        now=now_utc()
        with SessionLocal.begin() as s:
            row=s.get(SupplierFinancialAccountRow, supplier_id)
            if row is None:
                row=SupplierFinancialAccountRow(supplier_id=supplier_id, settlement_available_minor=settlement_minor, reserve_available_minor=reserve_minor, bank_available_minor=bank_minor, debit_mandate_active=mandate_active, negative_balance_minor=0, updated_at=now)
                s.add(row)
            else:
                row.settlement_available_minor=settlement_minor; row.reserve_available_minor=reserve_minor; row.bank_available_minor=bank_minor; row.debit_mandate_active=mandate_active; row.updated_at=now
        return self.get_supplier_finance(supplier_id)

    def get_supplier_finance(self, supplier_id: str) -> dict:
        with SessionLocal() as s:
            r=s.get(SupplierFinancialAccountRow, supplier_id)
            if not r: not_found("SUPPLIER_FINANCIAL_ACCOUNT_NOT_FOUND", "Supplier financial account not found")
            return {"supplier_id":r.supplier_id,"settlement_available_minor":r.settlement_available_minor,"reserve_available_minor":r.reserve_available_minor,"bank_available_minor":r.bank_available_minor,"debit_mandate_active":r.debit_mandate_active,"negative_balance_minor":r.negative_balance_minor}

    def _fault_decision(self, reason_code: str) -> tuple[str,str]:
        if reason_code in SUPPLIER_FAULT_REASONS: return "SUPPLIER", "SUPPLIER_FAULT_CONFIRMED"
        if reason_code in EXTERNAL_REASONS: return "EXTERNAL", "EXTERNAL_CAUSE_CONFIRMED"
        if reason_code in GUEST_FAULT_REASONS: return "GUEST", "GUEST_FAULT_CONFIRMED"
        return "UNRESOLVED", "EVIDENCE_REQUIRED"

    async def supplier_cancel(self, order_id: str, supplier_id: str, reason_code: str, evidence_ids: list[str]) -> dict:
        order,pb,offer=self._context(order_id)
        if order.status != OrderStatus.CONFIRMED.value:
            conflict("ORDER_STATE_CONFLICT", "Only confirmed orders can enter supplier cancellation")
        case_id=new_id("sfc")
        with SessionLocal.begin() as s:
            existing=s.scalar(select(SupplierFaultCaseRow).where(SupplierFaultCaseRow.order_id==order_id))
            if existing:
                return self.get_case(existing.case_id)
            s.add(SupplierFaultCaseRow(case_id=case_id,order_id=order_id,supplier_id=supplier_id,reason_code=reason_code,status="CAUSE_CLASSIFICATION",fault_party=None,evidence_json=evidence_ids,decision_json=None,created_at=now_utc()))
        repo.append_event(Event(new_id("evt"),"SUPPLIER_CANCEL_REQUESTED","HOTEL_ORDER",order_id,{"case_id":case_id,"supplier_id":supplier_id,"reason_code":reason_code}))
        fault_party,status=self._fault_decision(reason_code)
        decision_id=new_id("dec")
        with SessionLocal.begin() as s:
            c=s.get(SupplierFaultCaseRow,case_id); c.fault_party=fault_party; c.status=status; c.decision_json={"decision_id":decision_id,"reason_code":reason_code,"evidence_ids":evidence_ids}; c.decided_at=now_utc()
        repo.append_event(Event(new_id("evt"),status,"SUPPLIER_FAULT_CASE",case_id,{"order_id":order_id,"decision_id":decision_id,"fault_party":fault_party}))
        if status == "EVIDENCE_REQUIRED":
            return self.get_case(case_id)
        result=await self._connector(offer.connector_id).cancel(order.supplier_confirmation_no)
        if result != "CANCELLED": unavailable("SUPPLIER_CANCEL_EXECUTION_FAILED", "Supplier cancellation execution failed")
        with SessionLocal.begin() as s:
            r=s.get(OrderRow,order_id); r.status=OrderStatus.CANCELLED.value; r.version+=1; r.updated_at=now_utc()
        repo.append_event(Event(new_id("evt"),"CANCEL_CONFIRMED","HOTEL_ORDER",order_id,{"initiator":"SUPPLIER","case_id":case_id}))
        if fault_party == "SUPPLIER":
            return await self._execute_supplier_fault_remedy(case_id, decision_id)
        if fault_party == "EXTERNAL":
            refund=await self._refund_original(order_id, order.total_amount_minor, order.currency)
            return self.get_case(case_id) | {"refund":refund,"double_compensation":False}
        return self.get_case(case_id) | {"double_compensation":False}

    async def _refund_original(self, order_id: str, amount_minor: int, currency: str) -> dict:
        with SessionLocal() as s:
            pay=s.scalar(select(PaymentRow).where(PaymentRow.order_id==order_id,PaymentRow.payment_type=="ORIGINAL_BOOKING",PaymentRow.status==PaymentStatus.CAPTURED.value).order_by(PaymentRow.created_at.desc()))
            if not pay: not_found("CAPTURED_PAYMENT_NOT_FOUND", "Captured original payment not found")
        rid=new_id("ref")
        with SessionLocal.begin() as s:
            s.add(RefundRow(refund_id=rid,order_id=order_id,payment_id=pay.payment_id,amount_minor=amount_minor,currency=currency,status="PROCESSING",created_at=now_utc()))
        repo.append_event(Event(new_id("evt"),"REFUND_REQUESTED","REFUND",rid,{"order_id":order_id,"amount_minor":amount_minor,"initiator":"SUPPLIER_FAULT"}))
        try:
            movement=hotel_money_bridge.refund(order_id,amount_minor,f"supplier-fault-refund://{rid}",f"supplier-fault-refund:{rid}")
        except ValueError as exc:
            with SessionLocal.begin() as s: s.get(RefundRow,rid).status="FAILED"
            unavailable("REFUND_MONEY_MOVEMENT_FAILED", str(exc))
        with SessionLocal.begin() as s:
            rr=s.get(RefundRow,rid); rr.status="COMPLETED"; rr.provider_refund_id=movement["money_movement_id"]; rr.completed_at=now_utc()
        repo.append_event(Event(new_id("evt"),"REFUND_COMPLETED","REFUND",rid,{"order_id":order_id,"amount_minor":amount_minor}))
        return {"refund_id":rid,"amount_minor":amount_minor,"currency":currency,"status":"COMPLETED"}

    async def _execute_supplier_fault_remedy(self, case_id: str, decision_id: str) -> dict:
        with SessionLocal() as s:
            c=s.get(SupplierFaultCaseRow,case_id); order=s.get(OrderRow,c.order_id)
            supplier_id=c.supplier_id
        refund=await self._refund_original(order.order_id, order.total_amount_minor, order.currency)
        compensation=order.total_amount_minor
        liability_id=new_id("liab")
        repo.append_event(Event(new_id("evt"),"DOUBLE_COMPENSATION_REQUIRED","HOTEL_ORDER",order.order_id,{"case_id":case_id,"actual_paid_minor":order.total_amount_minor,"refund_minor":order.total_amount_minor,"compensation_minor":compensation,"total_return_minor":order.total_amount_minor*2}))
        settlement=reserve=bank=protection=negative=0
        remaining=compensation
        with SessionLocal.begin() as s:
            acct=s.get(SupplierFinancialAccountRow,supplier_id)
            if acct is None:
                acct=SupplierFinancialAccountRow(supplier_id=supplier_id,settlement_available_minor=0,reserve_available_minor=0,bank_available_minor=0,debit_mandate_active=False,negative_balance_minor=0,updated_at=now_utc()); s.add(acct); s.flush()
            settlement=min(acct.settlement_available_minor,remaining); acct.settlement_available_minor-=settlement; remaining-=settlement
            reserve=min(acct.reserve_available_minor,remaining); acct.reserve_available_minor-=reserve; remaining-=reserve
            if remaining and acct.debit_mandate_active:
                bank=min(acct.bank_available_minor,remaining); acct.bank_available_minor-=bank; remaining-=bank
            if remaining:
                protection=remaining
                negative=remaining
                acct.negative_balance_minor+=remaining
                remaining=0
            acct.updated_at=now_utc()
            status="CLEARED" if negative==0 else "NEGATIVE_BALANCE"
            s.add(SupplierLiabilityRow(liability_id=liability_id,case_id=case_id,supplier_id=supplier_id,order_id=order.order_id,actual_paid_minor=order.total_amount_minor,refund_minor=order.total_amount_minor,compensation_minor=compensation,total_return_minor=order.total_amount_minor*2,settlement_offset_minor=settlement,reserve_offset_minor=reserve,bank_debit_minor=bank,protection_fund_minor=protection,negative_balance_minor=negative,status=status,decision_id=decision_id,created_at=now_utc(),cleared_at=now_utc() if status=="CLEARED" else None))
        if settlement: repo.append_event(Event(new_id("evt"),"SETTLEMENT_OFFSET_APPLIED","SUPPLIER_LIABILITY",liability_id,{"amount_minor":settlement}))
        if reserve: repo.append_event(Event(new_id("evt"),"RESERVE_OFFSET_APPLIED","SUPPLIER_LIABILITY",liability_id,{"amount_minor":reserve}))
        if bank: repo.append_event(Event(new_id("evt"),"BANK_DEBIT_SUCCEEDED","SUPPLIER_LIABILITY",liability_id,{"amount_minor":bank}))
        elif compensation-settlement-reserve>0:
            repo.append_event(Event(new_id("evt"),"BANK_DEBIT_SKIPPED_OR_FAILED","SUPPLIER_LIABILITY",liability_id,{"mandate_required":True}))
        if protection:
            with SessionLocal.begin() as s:
                s.add(ProtectionFundLedgerRow(entry_id=new_id("pf"),liability_id=liability_id,order_id=order.order_id,supplier_id=supplier_id,entry_type="ADVANCE",amount_minor=protection,status="POSTED",created_at=now_utc()))
            repo.append_event(Event(new_id("evt"),"CONSUMER_PROTECTION_ADVANCE_CREATED","SUPPLIER_LIABILITY",liability_id,{"amount_minor":protection}))
            repo.append_event(Event(new_id("evt"),"SUPPLIER_NEGATIVE_BALANCE_CREATED","SUPPLIER_LIABILITY",liability_id,{"amount_minor":negative}))
        comp_id=new_id("comp")
        with SessionLocal.begin() as s:
            s.add(CompensationPaymentRow(compensation_id=comp_id,liability_id=liability_id,order_id=order.order_id,amount_minor=compensation,currency=order.currency,source_breakdown={"settlement":settlement,"reserve":reserve,"bank_debit":bank,"protection_fund":protection},status="COMPLETED",created_at=now_utc(),completed_at=now_utc()))
        repo.append_event(Event(new_id("evt"),"COMPENSATION_COMPLETED","HOTEL_ORDER",order.order_id,{"compensation_id":comp_id,"amount_minor":compensation,"liability_id":liability_id}))
        return self.get_case(case_id) | {"refund":refund,"compensation":{"compensation_id":comp_id,"amount_minor":compensation,"currency":order.currency,"status":"COMPLETED"},"liability":self.get_liability(liability_id),"double_compensation":True,"total_return_minor":order.total_amount_minor*2}

    def apply_future_settlement(self, supplier_id: str, amount_minor: int) -> dict:
        if amount_minor < 0:
            unprocessable("INVALID_SETTLEMENT_AMOUNT", "Settlement amount must be non-negative")
        recovered=0
        allocations=[]
        with SessionLocal.begin() as s:
            acct=s.get(SupplierFinancialAccountRow,supplier_id)
            if acct is None:
                acct=SupplierFinancialAccountRow(supplier_id=supplier_id,settlement_available_minor=0,reserve_available_minor=0,bank_available_minor=0,debit_mandate_active=False,negative_balance_minor=0,updated_at=now_utc()); s.add(acct); s.flush()
            remaining=amount_minor
            liabilities=s.scalars(select(SupplierLiabilityRow).where(SupplierLiabilityRow.supplier_id==supplier_id,SupplierLiabilityRow.negative_balance_minor>0).order_by(SupplierLiabilityRow.created_at)).all()
            for li in liabilities:
                if remaining<=0: break
                amt=min(li.negative_balance_minor,remaining)
                li.negative_balance_minor-=amt; recovered+=amt; remaining-=amt
                acct.negative_balance_minor=max(acct.negative_balance_minor-amt,0)
                li.settlement_offset_minor+=amt
                if li.negative_balance_minor==0:
                    li.status="CLEARED"; li.cleared_at=now_utc()
                s.add(ProtectionFundLedgerRow(entry_id=new_id("pf"),liability_id=li.liability_id,order_id=li.order_id,supplier_id=supplier_id,entry_type="RECOVERY",amount_minor=amt,status="POSTED",created_at=now_utc()))
                allocations.append({"liability_id":li.liability_id,"amount_minor":amt})
            acct.settlement_available_minor+=remaining
            acct.updated_at=now_utc()
            negative_after=acct.negative_balance_minor
            settlement_available=acct.settlement_available_minor
        for a in allocations:
            repo.append_event(Event(new_id("evt"),"FUTURE_SETTLEMENT_NEGATIVE_BALANCE_OFFSET","SUPPLIER_LIABILITY",a["liability_id"],{"amount_minor":a["amount_minor"],"supplier_id":supplier_id}))
            repo.append_event(Event(new_id("evt"),"CONSUMER_PROTECTION_FUND_RECOVERED","SUPPLIER_LIABILITY",a["liability_id"],{"amount_minor":a["amount_minor"]}))
        return {"supplier_id":supplier_id,"incoming_settlement_minor":amount_minor,"recovered_minor":recovered,"remaining_available_minor":settlement_available,"negative_balance_minor":negative_after,"allocations":allocations}

    def get_case(self, case_id: str) -> dict:
        with SessionLocal() as s:
            c=s.get(SupplierFaultCaseRow,case_id)
            if not c: not_found("SUPPLIER_FAULT_CASE_NOT_FOUND", "Supplier fault case not found")
            return {"case_id":c.case_id,"order_id":c.order_id,"supplier_id":c.supplier_id,"reason_code":c.reason_code,"status":c.status,"fault_party":c.fault_party,"evidence_ids":c.evidence_json,"decision":c.decision_json}

    def get_liability(self, liability_id: str) -> dict:
        with SessionLocal() as s:
            r=s.get(SupplierLiabilityRow,liability_id)
            if not r: not_found("SUPPLIER_LIABILITY_NOT_FOUND", "Supplier liability not found")
            return {"liability_id":r.liability_id,"supplier_id":r.supplier_id,"order_id":r.order_id,"actual_paid_minor":r.actual_paid_minor,"refund_minor":r.refund_minor,"compensation_minor":r.compensation_minor,"total_return_minor":r.total_return_minor,"settlement_offset_minor":r.settlement_offset_minor,"reserve_offset_minor":r.reserve_offset_minor,"bank_debit_minor":r.bank_debit_minor,"protection_fund_minor":r.protection_fund_minor,"negative_balance_minor":r.negative_balance_minor,"status":r.status,"decision_id":r.decision_id}

    def remedy_status(self, order_id: str, account_id: str|None=None) -> dict|None:
        with SessionLocal() as s:
            order=s.get(OrderRow,order_id)
            if not order or (account_id is not None and order.account_id!=account_id): not_found("ORDER_NOT_FOUND","Order not found")
            case=s.scalar(select(SupplierFaultCaseRow).where(SupplierFaultCaseRow.order_id==order_id))
            if not case: return None
            liability=s.scalar(select(SupplierLiabilityRow).where(SupplierLiabilityRow.order_id==order_id))
            refund=s.scalar(select(RefundRow).where(RefundRow.order_id==order_id).order_by(RefundRow.created_at.desc()))
            comp=s.scalar(select(CompensationPaymentRow).where(CompensationPaymentRow.order_id==order_id).order_by(CompensationPaymentRow.created_at.desc()))
            return {"case_id":case.case_id,"case_state":case.status,"fault_party":case.fault_party,"reason_code":case.reason_code,"decision_id":(case.decision_json or {}).get("decision_id"),"refund":{"status":refund.status,"amount_minor":refund.amount_minor,"currency":refund.currency} if refund else None,"compensation":{"status":comp.status,"amount_minor":comp.amount_minor,"currency":comp.currency} if comp else None,"liability":{"status":liability.status,"total_return_minor":liability.total_return_minor,"consumer_protection_advanced":liability.protection_fund_minor>0} if liability else None,"supplier_recovery_hidden_from_consumer":account_id is not None}

    def governance_status(self) -> dict:
        with SessionLocal() as s:
            cases=s.scalars(select(SupplierFaultCaseRow).order_by(SupplierFaultCaseRow.created_at.desc())).all();liabilities=s.scalars(select(SupplierLiabilityRow).order_by(SupplierLiabilityRow.created_at.desc())).all();fund=s.scalars(select(ProtectionFundLedgerRow).order_by(ProtectionFundLedgerRow.created_at.desc())).all()
            return {"cases":[{"case_id":x.case_id,"order_id":x.order_id,"supplier_id":x.supplier_id,"status":x.status,"fault_party":x.fault_party,"reason_code":x.reason_code,"decision_id":(x.decision_json or {}).get("decision_id")} for x in cases],"liabilities":[self.get_liability(x.liability_id) for x in liabilities],"protection_fund":[{"entry_id":x.entry_id,"liability_id":x.liability_id,"entry_type":x.entry_type,"amount_minor":x.amount_minor,"status":x.status} for x in fund]}

compensation_service=CompensationService()
