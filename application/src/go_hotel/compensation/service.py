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
        from go_hotel.services.hosted_money import require_isolated
        from go_hotel.services.alipay_safeguarded_settlement import transaction
        require_isolated()
        if any(type(x) is not int or not 0<=x<=2**63-1 for x in [settlement_minor,reserve_minor,bank_minor]):unprocessable('INVALID_FUND_BALANCE','Integer, non-negative simulated balances are required')
        now=now_utc()
        with transaction() as s:
            row=s.get(SupplierFinancialAccountRow, supplier_id,with_for_update=True)
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

    async def supplier_cancel(self, order_id: str, supplier_id: str, reason_code: str, evidence_ids: list[str], actor_id: str) -> dict:
        from go_hotel.services.catalog_supplier_remedy import request
        return request(order_id,supplier_id,reason_code,evidence_ids,actor_id)

    def apply_future_settlement(self, supplier_id: str, amount_minor: int, reference: str|None=None, key: str|None=None, actor: str|None=None) -> dict:
        from go_hotel.db.models import (
            CatalogFaultRecoveryRow, HostedFaultRecoveryRow, HostedSupplierDisruptionRow,
        )
        with SessionLocal() as s:
            if s.scalar(select(SupplierLiabilityRow.liability_id).join(HostedSupplierDisruptionRow,HostedSupplierDisruptionRow.case_id==SupplierLiabilityRow.case_id).where(SupplierLiabilityRow.supplier_id==supplier_id)):
                conflict('SCOPED_FAULT_RECOVERY_REQUIRED','Use the idempotent hosted fault settlement recovery workflow')
            if reference:
                for model in (CatalogFaultRecoveryRow, HostedFaultRecoveryRow):
                    old=s.scalar(select(model).where(model.request_json['settlement_reference'].as_string()==reference))
                    if not old:
                        continue
                    before=old.request_json
                    receipt_supplier=before.get('supplier_id',before.get('hotel_id'))
                    same=(receipt_supplier,before['amount_minor'],before['currency'])==(supplier_id,amount_minor,'CNY')
                    if not same:
                        conflict('RECOVERY_RECEIPT_IDEMPOTENCY_CONFLICT','Settlement receipt already bound to a different supplier or amount')
        if not reference or not key or not actor:conflict('SCOPED_FAULT_RECOVERY_REQUIRED','A unique confirmed settlement receipt and actor are required')
        from go_hotel.services.catalog_fault_funding import recover
        result=recover(supplier_id,amount_minor,reference,key,actor)
        return result|{'remaining_available_minor':result['new_available_minor']}

    def get_case(self, case_id: str) -> dict:
        from go_hotel.db.models import CatalogSupplierRemedyRow
        from go_hotel.services.catalog_supplier_remedy import status
        with SessionLocal() as s:
            if s.get(CatalogSupplierRemedyRow,case_id):return status(case_id,internal=True)
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
            from go_hotel.db.models import CatalogSupplierRemedyRow
            from go_hotel.services.catalog_supplier_remedy import status
            if s.get(CatalogSupplierRemedyRow,case.case_id):return status(case.case_id,account_id,internal=account_id is None)
            liability=s.scalar(select(SupplierLiabilityRow).where(SupplierLiabilityRow.order_id==order_id))
            refund=s.scalar(select(RefundRow).where(RefundRow.order_id==order_id).order_by(RefundRow.created_at.desc()))
            comp=s.scalar(select(CompensationPaymentRow).where(CompensationPaymentRow.order_id==order_id).order_by(CompensationPaymentRow.created_at.desc()))
            return {"case_id":case.case_id,"case_state":case.status,"fault_party":case.fault_party,"reason_code":case.reason_code,"decision_id":(case.decision_json or {}).get("decision_id"),"refund":{"status":refund.status,"amount_minor":refund.amount_minor,"currency":refund.currency} if refund else None,"compensation":{"status":comp.status,"amount_minor":comp.amount_minor,"currency":comp.currency} if comp else None,"liability":{"status":liability.status,"total_return_minor":liability.total_return_minor,"consumer_protection_advanced":liability.protection_fund_minor>0} if liability else None,"supplier_recovery_hidden_from_consumer":account_id is not None}

    def governance_status(self) -> dict:
        with SessionLocal() as s:
            cases=s.scalars(select(SupplierFaultCaseRow).order_by(SupplierFaultCaseRow.created_at.desc())).all();liabilities=s.scalars(select(SupplierLiabilityRow).order_by(SupplierLiabilityRow.created_at.desc())).all();fund=s.scalars(select(ProtectionFundLedgerRow).order_by(ProtectionFundLedgerRow.created_at.desc())).all()
            return {"cases":[{"case_id":x.case_id,"order_id":x.order_id,"supplier_id":x.supplier_id,"status":x.status,"fault_party":x.fault_party,"reason_code":x.reason_code,"decision_id":(x.decision_json or {}).get("decision_id")} for x in cases],"liabilities":[self.get_liability(x.liability_id) for x in liabilities],"protection_fund":[{"entry_id":x.entry_id,"liability_id":x.liability_id,"entry_type":x.entry_type,"amount_minor":x.amount_minor,"status":x.status} for x in fund]}

compensation_service=CompensationService()
