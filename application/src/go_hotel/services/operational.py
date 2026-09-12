from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import select, func, desc
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    OrderRow, RefundRow, StayCreditRow, SupplierLiabilityRow, SupplierFaultCaseRow,
    RiskEventRuntimeRow, JudgmentRuntimeRow, RecommendationDecisionRow,
    ConnectorSlaWindowRow, SupplierConnectorOnboardingRow, SupplierFinancialAccountRow,
    CompensationPaymentRow, ProtectionFundLedgerRow, OutboxRow, WebhookInboxRow,
    ExternalOperationRow, PaymentOrchestrationRow, PaymentRow, ConnectorHealthRow,
)


def _dt(v):
    return v.isoformat() if isinstance(v, datetime) else v


def _page(rows, limit:int, offset:int):
    return {"items": rows, "limit": limit, "offset": offset, "count": len(rows)}


class OperationalDashboardService:
    # Supplier Console -------------------------------------------------
    def supplier_dashboard(self, supplier_id:str) -> dict:
        with SessionLocal() as s:
            from go_hotel.services.transaction_order_view import supplier_counts
            order_counts, refund_counts = supplier_counts(supplier_id)
            credit_counts=dict(s.execute(select(StayCreditRow.status, func.count()).join(OrderRow, OrderRow.order_id==StayCreditRow.original_order_id).where(OrderRow.supplier_id==supplier_id).group_by(StayCreditRow.status)).all())
            risk_counts=dict(s.execute(select(RiskEventRuntimeRow.status, func.count()).join(OrderRow, OrderRow.order_id==RiskEventRuntimeRow.order_id).where(OrderRow.supplier_id==supplier_id).group_by(RiskEventRuntimeRow.status)).all())
            liability=s.scalar(select(func.coalesce(func.sum(SupplierLiabilityRow.negative_balance_minor),0)).where(SupplierLiabilityRow.supplier_id==supplier_id)) or 0
            finance=s.get(SupplierFinancialAccountRow,supplier_id)
            active_connectors=s.scalar(select(func.count()).select_from(SupplierConnectorOnboardingRow).where(SupplierConnectorOnboardingRow.supplier_id==supplier_id,SupplierConnectorOnboardingRow.status=='ACTIVE')) or 0
            return {
                "supplier_id":supplier_id,
                "orders":order_counts,
                "refunds":refund_counts,
                "stay_credits":credit_counts,
                "risk_cases":risk_counts,
                "financial_risk":{"negative_balance_minor":int(liability),"settlement_available_minor":int(finance.settlement_available_minor if finance else 0),"reserve_available_minor":int(finance.reserve_available_minor if finance else 0),"debit_mandate_active":bool(finance.debit_mandate_active if finance else False)},
                "connectors":{"active":int(active_connectors)},
                "generated_at":datetime.now(timezone.utc).isoformat(),
            }

    def supplier_orders(self,supplier_id:str,status:str|None=None,limit:int=50,offset:int=0)->dict:
        with SessionLocal() as s:
            q=select(OrderRow).where(OrderRow.supplier_id==supplier_id)
            if status: q=q.where(OrderRow.status==status)
            rows=s.scalars(q.order_by(OrderRow.updated_at.desc()).offset(offset).limit(limit)).all()
            return _page([{"order_id":r.order_id,"hotel_id":r.hotel_id,"account_id":r.account_id,"status":r.status,"total_amount_minor":r.total_amount_minor,"currency":r.currency,"supplier_confirmation_no":r.supplier_confirmation_no,"updated_at":_dt(r.updated_at)} for r in rows],limit,offset)

    def supplier_refunds(self,supplier_id:str,status:str|None=None,limit:int=50,offset:int=0)->dict:
        from go_hotel.services.transaction_order_view import supplier_refunds
        return supplier_refunds(supplier_id,status,limit,offset)

    def supplier_stay_credits(self,supplier_id:str,status:str|None=None,limit:int=50,offset:int=0)->dict:
        with SessionLocal() as s:
            q=select(StayCreditRow).join(OrderRow,OrderRow.order_id==StayCreditRow.original_order_id).where(OrderRow.supplier_id==supplier_id)
            if status:q=q.where(StayCreditRow.status==status)
            rows=s.scalars(q.order_by(StayCreditRow.created_at.desc()).offset(offset).limit(limit)).all()
            return _page([{"stay_credit_id":r.stay_credit_id,"original_order_id":r.original_order_id,"property_id":r.property_id,"credit_value_minor":r.credit_value_minor,"currency":r.currency,"status":r.status,"expires_at":_dt(r.expires_at),"redemption_order_id":r.redemption_order_id} for r in rows],limit,offset)

    def supplier_liabilities(self,supplier_id:str,status:str|None=None,limit:int=50,offset:int=0)->dict:
        with SessionLocal() as s:
            q=select(SupplierLiabilityRow).where(SupplierLiabilityRow.supplier_id==supplier_id)
            if status:q=q.where(SupplierLiabilityRow.status==status)
            rows=s.scalars(q.order_by(SupplierLiabilityRow.created_at.desc()).offset(offset).limit(limit)).all()
            return _page([{"liability_id":r.liability_id,"case_id":r.case_id,"order_id":r.order_id,"status":r.status,"refund_minor":r.refund_minor,"compensation_minor":r.compensation_minor,"total_return_minor":r.total_return_minor,"settlement_offset_minor":r.settlement_offset_minor,"reserve_offset_minor":r.reserve_offset_minor,"bank_debit_minor":r.bank_debit_minor,"protection_fund_minor":r.protection_fund_minor,"negative_balance_minor":r.negative_balance_minor,"decision_id":r.decision_id,"created_at":_dt(r.created_at)} for r in rows],limit,offset)

    def supplier_risk_cases(self,supplier_id:str,status:str|None=None,limit:int=50,offset:int=0)->dict:
        with SessionLocal() as s:
            q=select(RiskEventRuntimeRow).join(OrderRow,OrderRow.order_id==RiskEventRuntimeRow.order_id).where(OrderRow.supplier_id==supplier_id)
            if status:q=q.where(RiskEventRuntimeRow.status==status)
            rows=s.scalars(q.order_by(RiskEventRuntimeRow.updated_at.desc()).offset(offset).limit(limit)).all()
            return _page([{"risk_event_id":r.risk_event_id,"hotel_id":r.hotel_id,"order_id":r.order_id,"review_id":r.review_id,"risk_type":r.risk_type,"severity":r.severity,"status":r.status,"confidence_bps":r.confidence_bps,"decision_id":r.decision_id,"public_notice":r.public_notice,"updated_at":_dt(r.updated_at)} for r in rows],limit,offset)

    def supplier_judgments(self,supplier_id:str,limit:int=50,offset:int=0)->dict:
        with SessionLocal() as s:
            hotel_ids=select(OrderRow.hotel_id).where(OrderRow.supplier_id==supplier_id).distinct()
            rows=s.scalars(select(JudgmentRuntimeRow).where(JudgmentRuntimeRow.hotel_id.in_(hotel_ids)).order_by(JudgmentRuntimeRow.created_at.desc()).offset(offset).limit(limit)).all()
            result=[]
            for r in rows:
                rec=s.scalar(select(RecommendationDecisionRow).where(RecommendationDecisionRow.judgment_id==r.judgment_id).order_by(RecommendationDecisionRow.created_at.desc()))
                result.append({"judgment_id":r.judgment_id,"hotel_id":r.hotel_id,"go_score":r.go_score_milli/1000,"status":r.status,"confidence_bps":r.confidence_bps,"recommendation_status":rec.status if rec else None,"public_go_score":rec.public_go_score_milli/1000 if rec and rec.public_go_score_milli is not None else None,"created_at":_dt(r.created_at)})
            return _page(result,limit,offset)

    def supplier_connectors(self,supplier_id:str)->dict:
        with SessionLocal() as s:
            obs=s.scalars(select(SupplierConnectorOnboardingRow).where(SupplierConnectorOnboardingRow.supplier_id==supplier_id).order_by(SupplierConnectorOnboardingRow.updated_at.desc())).all()
            items=[]
            for o in obs:
                sla=s.get(ConnectorSlaWindowRow,o.connector_id)
                items.append({"onboarding_id":o.onboarding_id,"connector_id":o.connector_id,"environment":o.environment,"status":o.status,"rollout_percent":o.rollout_percent,"sla":{"health_status":sla.health_status,"composite_score_bps":sla.composite_score_bps,"success_rate_bps":sla.success_rate_bps,"confirmation_latency_ms_p95":sla.confirmation_latency_ms_p95} if sla else None,"updated_at":_dt(o.updated_at)})
            return {"items":items,"count":len(items)}

    # GO Admin --------------------------------------------------------
    def admin_dashboard(self)->dict:
        with SessionLocal() as s:
            def counts(model,field): return dict(s.execute(select(field,func.count()).group_by(field)).all())
            negative=s.scalar(select(func.coalesce(func.sum(SupplierFinancialAccountRow.negative_balance_minor),0))) or 0
            fund_out=s.scalar(select(func.coalesce(func.sum(ProtectionFundLedgerRow.amount_minor),0)).where(ProtectionFundLedgerRow.entry_type=='ADVANCE')) or 0
            return {
                "orders":counts(OrderRow,OrderRow.status),
                "refunds":counts(RefundRow,RefundRow.status),
                "stay_credits":counts(StayCreditRow,StayCreditRow.status),
                "liabilities":counts(SupplierLiabilityRow,SupplierLiabilityRow.status),
                "risk_cases":counts(RiskEventRuntimeRow,RiskEventRuntimeRow.status),
                "connectors":counts(ConnectorSlaWindowRow,ConnectorSlaWindowRow.health_status),
                "outbox":counts(OutboxRow,OutboxRow.status),
                "financial":{"supplier_negative_balance_minor":int(negative),"consumer_protection_advances_minor":int(fund_out)},
                "generated_at":datetime.now(timezone.utc).isoformat(),
            }

    def admin_queues(self,limit:int=50)->dict:
        with SessionLocal() as s:
            queues={
                "payment_reconciliation":[{"order_id":r.order_id,"phase":r.phase,"last_error":r.last_error,"updated_at":_dt(r.updated_at)} for r in s.scalars(select(PaymentOrchestrationRow).where(PaymentOrchestrationRow.phase.like('%RECONCIL%')).order_by(PaymentOrchestrationRow.updated_at).limit(limit)).all()],
                "external_recovery":[{"operation_id":r.operation_id,"operation_type":r.operation_type,"aggregate_id":r.aggregate_id,"status":r.status,"last_error":r.last_error,"updated_at":_dt(r.updated_at)} for r in s.scalars(select(ExternalOperationRow).where(ExternalOperationRow.status.in_(['RECONCILE_REQUIRED','EXTERNAL_SUCCEEDED'])).order_by(ExternalOperationRow.updated_at).limit(limit)).all()],
                "refund_failures":[{"refund_id":r.refund_id,"order_id":r.order_id,"amount_minor":r.amount_minor,"status":r.status} for r in s.scalars(select(RefundRow).where(RefundRow.status=='FAILED').order_by(RefundRow.created_at).limit(limit)).all()],
                "supplier_liability":[{"liability_id":r.liability_id,"supplier_id":r.supplier_id,"order_id":r.order_id,"status":r.status,"negative_balance_minor":r.negative_balance_minor} for r in s.scalars(select(SupplierLiabilityRow).where(SupplierLiabilityRow.status.notin_(['CLEARED'])).order_by(SupplierLiabilityRow.created_at).limit(limit)).all()],
                "risk_review":[{"risk_event_id":r.risk_event_id,"hotel_id":r.hotel_id,"risk_type":r.risk_type,"severity":r.severity,"status":r.status} for r in s.scalars(select(RiskEventRuntimeRow).where(RiskEventRuntimeRow.status.in_(['CANDIDATE','UNDER_REVIEW','REMEDIATION_REQUIRED'])).order_by(RiskEventRuntimeRow.updated_at).limit(limit)).all()],
                "connector_health":[{"connector_id":r.connector_id,"health_status":r.health_status,"composite_score_bps":r.composite_score_bps,"updated_at":_dt(r.updated_at)} for r in s.scalars(select(ConnectorSlaWindowRow).where(ConnectorSlaWindowRow.health_status!='HEALTHY').order_by(ConnectorSlaWindowRow.composite_score_bps).limit(limit)).all()],
                "outbox_dead_or_retry":[{"outbox_id":r.outbox_id,"event_type":r.event_type,"aggregate_id":r.aggregate_id,"status":r.status,"attempt_count":r.attempt_count,"last_error":r.last_error} for r in s.scalars(select(OutboxRow).where(OutboxRow.status.in_(['PENDING','DEAD_LETTERED'])).order_by(OutboxRow.created_at).limit(limit)).all()],
            }
            return {"queues":queues,"counts":{k:len(v) for k,v in queues.items()}}

    def admin_orders(self,status:str|None=None,supplier_id:str|None=None,limit:int=50,offset:int=0)->dict:
        with SessionLocal() as s:
            q=select(OrderRow)
            if status:q=q.where(OrderRow.status==status)
            if supplier_id:q=q.where(OrderRow.supplier_id==supplier_id)
            rows=s.scalars(q.order_by(OrderRow.updated_at.desc()).offset(offset).limit(limit)).all()
            return _page([{"order_id":r.order_id,"supplier_id":r.supplier_id,"hotel_id":r.hotel_id,"account_id":r.account_id,"status":r.status,"total_amount_minor":r.total_amount_minor,"currency":r.currency,"supplier_confirmation_no":r.supplier_confirmation_no,"version":r.version,"updated_at":_dt(r.updated_at)} for r in rows],limit,offset)

    def admin_refunds(self,status:str|None=None,limit:int=50,offset:int=0)->dict:
        with SessionLocal() as s:
            q=select(RefundRow,OrderRow.supplier_id).join(OrderRow,OrderRow.order_id==RefundRow.order_id)
            if status:q=q.where(RefundRow.status==status)
            rows=s.execute(q.order_by(RefundRow.created_at.desc()).offset(offset).limit(limit)).all()
            return _page([{"refund_id":r.refund_id,"order_id":r.order_id,"supplier_id":sid,"amount_minor":r.amount_minor,"currency":r.currency,"status":r.status,"provider_refund_id":r.provider_refund_id,"created_at":_dt(r.created_at)} for r,sid in rows],limit,offset)

    def admin_liabilities(self,status:str|None=None,limit:int=50,offset:int=0)->dict:
        with SessionLocal() as s:
            q=select(SupplierLiabilityRow)
            if status:q=q.where(SupplierLiabilityRow.status==status)
            rows=s.scalars(q.order_by(SupplierLiabilityRow.created_at.desc()).offset(offset).limit(limit)).all()
            return _page([{"liability_id":r.liability_id,"supplier_id":r.supplier_id,"order_id":r.order_id,"status":r.status,"compensation_minor":r.compensation_minor,"protection_fund_minor":r.protection_fund_minor,"negative_balance_minor":r.negative_balance_minor,"decision_id":r.decision_id} for r in rows],limit,offset)

    def admin_risks(self,status:str|None=None,limit:int=50,offset:int=0)->dict:
        with SessionLocal() as s:
            q=select(RiskEventRuntimeRow)
            if status:q=q.where(RiskEventRuntimeRow.status==status)
            rows=s.scalars(q.order_by(RiskEventRuntimeRow.updated_at.desc()).offset(offset).limit(limit)).all()
            return _page([{"risk_event_id":r.risk_event_id,"hotel_id":r.hotel_id,"order_id":r.order_id,"risk_type":r.risk_type,"severity":r.severity,"status":r.status,"confidence_bps":r.confidence_bps,"decision_id":r.decision_id,"updated_at":_dt(r.updated_at)} for r in rows],limit,offset)

    def admin_judgments(self,status:str|None=None,limit:int=50,offset:int=0)->dict:
        with SessionLocal() as s:
            q=select(JudgmentRuntimeRow)
            if status:q=q.where(JudgmentRuntimeRow.status==status)
            rows=s.scalars(q.order_by(JudgmentRuntimeRow.created_at.desc()).offset(offset).limit(limit)).all()
            out=[]
            for r in rows:
                rec=s.scalar(select(RecommendationDecisionRow).where(RecommendationDecisionRow.judgment_id==r.judgment_id).order_by(RecommendationDecisionRow.created_at.desc()))
                out.append({"judgment_id":r.judgment_id,"hotel_id":r.hotel_id,"go_score":r.go_score_milli/1000,"status":r.status,"confidence_bps":r.confidence_bps,"evidence_package_id":r.evidence_package_id,"model_version":r.model_version,"rule_version":r.rule_version,"recommendation_status":rec.status if rec else None,"created_at":_dt(r.created_at)})
            return _page(out,limit,offset)

    def admin_connectors(self)->dict:
        with SessionLocal() as s:
            rows=s.scalars(select(ConnectorSlaWindowRow).order_by(ConnectorSlaWindowRow.composite_score_bps.desc())).all()
            return {"items":[{"connector_id":r.connector_id,"health_status":r.health_status,"composite_score_bps":r.composite_score_bps,"success_rate_bps":r.success_rate_bps,"confirmation_latency_ms_p95":r.confirmation_latency_ms_p95,"cancel_success_rate_bps":r.cancel_success_rate_bps,"inventory_accuracy_bps":r.inventory_accuracy_bps,"price_consistency_bps":r.price_consistency_bps,"sample_size":r.sample_size,"updated_at":_dt(r.updated_at)} for r in rows],"count":len(rows)}

    def admin_settlement(self)->dict:
        with SessionLocal() as s:
            accounts=s.scalars(select(SupplierFinancialAccountRow).order_by(SupplierFinancialAccountRow.negative_balance_minor.desc())).all()
            return {"items":[{"supplier_id":r.supplier_id,"settlement_available_minor":r.settlement_available_minor,"reserve_available_minor":r.reserve_available_minor,"bank_available_minor":r.bank_available_minor,"debit_mandate_active":r.debit_mandate_active,"negative_balance_minor":r.negative_balance_minor,"updated_at":_dt(r.updated_at)} for r in accounts],"count":len(accounts)}

operational_dashboard_service=OperationalDashboardService()
