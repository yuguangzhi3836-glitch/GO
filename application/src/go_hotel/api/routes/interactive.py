from __future__ import annotations
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    OrderRow, PaymentRow, RefundRow, OrderChangeRow, StayCreditRow, EventRow,
    SupplierLiabilityRow, SupplierFaultCaseRow, CompensationPaymentRow,
    RiskEventRuntimeRow, RiskEvidenceRuntimeRow, RiskRemediationRow,
    JudgmentRuntimeRow, JudgmentEvidencePackageRow, RecommendationDecisionRow,
    SupplierFinancialAccountRow, SupplierConnectorOnboardingRow, ApprovalRequestRow,
)
from go_hotel.security.deps import supplier_principal, require_permission, assert_supplier_order, assert_supplier_risk
from go_hotel.security.service import Principal, audit_service
from go_hotel.fare.service import fare_service

router=APIRouter(tags=['sprint1t-interactive-workbench'])

class ChangeQuoteBody(BaseModel):
    new_check_in:str
    new_check_out:str
class ChangeExecuteBody(BaseModel):
    change_quote_id:str
    payment_method_token:str='pm_console'
class CancelExecuteBody(BaseModel):
    cancellation_quote_id:str
class EvidenceBody(BaseModel):
    evidence_type:str
    payload:dict=Field(default_factory=dict)
    content_ref:str|None=None
class RemediationBody(BaseModel):
    action:str
    evidence_ids:list[str]=Field(default_factory=list)

def _iso(v): return v.isoformat() if hasattr(v,'isoformat') else v

def _order_obj(r):
    return {'order_id':r.order_id,'supplier_id':r.supplier_id,'hotel_id':r.hotel_id,'account_id':r.account_id,'status':r.status,'total_amount_minor':r.total_amount_minor,'currency':r.currency,'supplier_confirmation_no':r.supplier_confirmation_no,'updated_at':_iso(r.updated_at)}

@router.get('/v1/supplier/orders/{order_id}/workbench')
def supplier_order_workbench(order_id:str,p:Principal=Depends(supplier_principal)):
    assert_supplier_order(p,order_id)
    with SessionLocal() as s:
        o=s.get(OrderRow,order_id)
        pays=s.scalars(select(PaymentRow).where(PaymentRow.order_id==order_id).order_by(PaymentRow.created_at)).all()
        refs=s.scalars(select(RefundRow).where(RefundRow.order_id==order_id).order_by(RefundRow.created_at)).all()
        chgs=s.scalars(select(OrderChangeRow).where(OrderChangeRow.order_id==order_id).order_by(OrderChangeRow.created_at)).all()
        credits=s.scalars(select(StayCreditRow).where(StayCreditRow.original_order_id==order_id).order_by(StayCreditRow.created_at)).all()
        events=s.scalars(select(EventRow).where(EventRow.aggregate_id==order_id).order_by(EventRow.occurred_at)).all()
        return {'data':{
            'order':_order_obj(o),
            'fare_options':{'actions':[{'type':'SUPPLIER_CANCEL_REQUEST','allowed':o.status=='CONFIRMED'},
                {'type':'CUSTOMER_FARE_CHANGE','allowed':False,'reason':'CUSTOMER_CONFIRMATION_REQUIRED'}]},
            'payments':[{'payment_id':x.payment_id,'payment_type':x.payment_type,'amount_minor':x.amount_minor,'currency':x.currency,'status':x.status,'created_at':_iso(x.created_at)} for x in pays],
            'refunds':[{'refund_id':x.refund_id,'amount_minor':x.amount_minor,'currency':x.currency,'status':x.status,'created_at':_iso(x.created_at),'completed_at':_iso(x.completed_at)} for x in refs],
            'changes':[{'change_id':x.change_id,'status':x.status,'additional_payment_minor':x.additional_payment_minor,'created_at':_iso(x.created_at),'confirmed_at':_iso(x.confirmed_at)} for x in chgs],
            'stay_credits':[{'stay_credit_id':x.stay_credit_id,'credit_value_minor':x.credit_value_minor,'currency':x.currency,'status':x.status,'expires_at':_iso(x.expires_at)} for x in credits],
            'timeline':[{'event_id':x.event_id,'event_type':x.event_type,'occurred_at':_iso(x.occurred_at),'payload':x.payload} for x in events[-100:]],
        }}

@router.post('/v1/supplier/orders/{order_id}/cancellation-quote')
def supplier_cancellation_quote(order_id:str,p:Principal=Depends(supplier_principal)):
    assert_supplier_order(p,order_id); return {'data':fare_service.cancellation_quote(order_id)}

@router.post('/v1/supplier/orders/{order_id}/cancel')
async def supplier_cancel(order_id:str,body:CancelExecuteBody,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key'),p:Principal=Depends(supplier_principal)):
    assert_supplier_order(p,order_id)
    raise HTTPException(409,detail='SUPPLIER_CANCELLATION_REQUIRES_INDEPENDENT_REVIEW')

@router.post('/v1/supplier/orders/{order_id}/change-quote')
async def supplier_change_quote(order_id:str,body:ChangeQuoteBody,p:Principal=Depends(supplier_principal)):
    assert_supplier_order(p,order_id); return {'data':await fare_service.change_quote(order_id,body.new_check_in,body.new_check_out)}

@router.post('/v1/supplier/orders/{order_id}/change')
async def supplier_change(order_id:str,body:ChangeExecuteBody,p:Principal=Depends(supplier_principal)):
    assert_supplier_order(p,order_id)
    raise HTTPException(409,detail='CUSTOMER_CHANGE_AND_PAYMENT_CONSENT_REQUIRED')

@router.get('/v1/supplier/risk-cases/{risk_id}/workbench')
def supplier_risk_workbench(risk_id:str,p:Principal=Depends(supplier_principal)):
    assert_supplier_risk(p,risk_id)
    with SessionLocal() as s:
        r=s.get(RiskEventRuntimeRow,risk_id)
        ev=s.scalars(select(RiskEvidenceRuntimeRow).where(RiskEvidenceRuntimeRow.risk_event_id==risk_id).order_by(RiskEvidenceRuntimeRow.created_at)).all()
        rem=s.scalars(select(RiskRemediationRow).where(RiskRemediationRow.risk_event_id==risk_id).order_by(RiskRemediationRow.created_at)).all()
        return {'data':{'risk':{'risk_event_id':r.risk_event_id,'type':r.type,'severity':r.severity,'status':r.status,'confidence_bps':r.confidence_bps,'order_id':r.order_id,'review_id':r.review_id,'decision_id':r.decision_id,'confirmed_at':_iso(r.confirmed_at)},'evidence':[{'evidence_id':x.evidence_id,'source_type':x.source_type,'evidence_type':x.evidence_type,'payload':x.payload,'content_ref':x.content_ref,'created_at':_iso(x.created_at)} for x in ev],'remediation':[{'remediation_id':x.remediation_id,'action':x.action,'status':x.status,'evidence_ids':x.evidence_ids,'submitted_at':_iso(x.submitted_at),'verified_at':_iso(x.verified_at)} for x in rem]}}

@router.get('/v1/supplier/liabilities/{liability_id}/workbench')
def supplier_liability_workbench(liability_id:str,p:Principal=Depends(supplier_principal)):
    with SessionLocal() as s:
        l=s.get(SupplierLiabilityRow,liability_id)
        if not l or l.supplier_id!=p.supplier_id: raise HTTPException(404,detail='LIABILITY_NOT_FOUND')
        c=s.get(SupplierFaultCaseRow,l.case_id) if l.case_id else None
        pays=s.scalars(select(CompensationPaymentRow).where(CompensationPaymentRow.liability_id==liability_id)).all()
        return {'data':{'liability':{k:getattr(l,k) for k in ['liability_id','case_id','order_id','supplier_id','status','refund_minor','compensation_minor','total_minor','settlement_offset_minor','reserve_offset_minor','bank_debit_minor','protection_fund_minor','negative_balance_minor']},'fault_case':({'case_id':c.case_id,'reason_code':c.reason_code,'fault_status':c.fault_status,'decision_id':c.decision_id,'evidence_ids':c.evidence_ids} if c else None),'compensation_payments':[{'compensation_payment_id':x.compensation_payment_id,'amount_minor':x.amount_minor,'status':x.status,'source':x.source,'created_at':_iso(x.created_at)} for x in pays]}}

@router.get('/internal/v1/admin/settlement/{supplier_id}')
def admin_settlement_detail(supplier_id:str,p:Principal=Depends(require_permission('admin:finance'))):
    with SessionLocal() as s:
        a=s.get(SupplierFinancialAccountRow,supplier_id)
        ls=s.scalars(select(SupplierLiabilityRow).where(SupplierLiabilityRow.supplier_id==supplier_id).order_by(SupplierLiabilityRow.created_at.desc()).limit(100)).all()
        return {'data':{'account':None if not a else {'supplier_id':a.supplier_id,'settlement_available_minor':a.settlement_available_minor,'reserve_available_minor':a.reserve_available_minor,'bank_available_minor':a.bank_available_minor,'debit_mandate_active':a.debit_mandate_active,'negative_balance_minor':a.negative_balance_minor,'updated_at':_iso(a.updated_at)},'liabilities':[{'liability_id':x.liability_id,'order_id':x.order_id,'status':x.status,'total_minor':x.total_minor,'negative_balance_minor':x.negative_balance_minor,'created_at':_iso(x.created_at)} for x in ls]}}

@router.get('/internal/v1/admin/judgments/{judgment_id}/evidence-replay')
def judgment_evidence_replay(judgment_id:str,p:Principal=Depends(require_permission('admin:trust'))):
    with SessionLocal() as s:
        j=s.get(JudgmentRuntimeRow,judgment_id)
        if not j: raise HTTPException(404,detail='JUDGMENT_NOT_FOUND')
        ep=s.get(JudgmentEvidencePackageRow,j.evidence_package_id)
        rec=s.scalar(select(RecommendationDecisionRow).where(RecommendationDecisionRow.judgment_id==judgment_id).order_by(RecommendationDecisionRow.created_at.desc()))
        return {'data':{'judgment':{'judgment_id':j.judgment_id,'hotel_id':j.hotel_id,'status':j.status,'go_score':j.go_score,'dimensions':j.dimensions,'risk_summary':j.risk_summary,'confidence_bps':j.confidence_bps,'model_version':j.model_version,'prompt_version':j.prompt_version,'rule_version':j.rule_version,'created_at':_iso(j.created_at)},'evidence_package':None if not ep else {'evidence_package_id':ep.evidence_package_id,'feature_snapshot':ep.feature_snapshot,'evidence_refs':ep.evidence_refs,'content_hash':ep.content_hash,'sealed_at':_iso(ep.sealed_at)},'recommendation':None if not rec else {'decision_id':rec.decision_id,'status':rec.status,'reason_codes':rec.reason_codes,'created_at':_iso(rec.created_at)}}}

@router.get('/internal/v1/admin/connector-onboardings')
def connector_onboardings(p:Principal=Depends(require_permission('admin:connector'))):
    with SessionLocal() as s:
        rows=s.scalars(select(SupplierConnectorOnboardingRow).order_by(SupplierConnectorOnboardingRow.updated_at.desc())).all()
        return {'data':{'items':[{'onboarding_id':x.onboarding_id,'supplier_id':x.supplier_id,'connector_id':x.connector_id,'environment':x.environment,'status':x.status,'rollout_percent':x.rollout_percent,'updated_at':_iso(x.updated_at)} for x in rows],'count':len(rows)}}

@router.get('/internal/v1/approvals')
def list_approvals(status:str|None=None,p:Principal=Depends(require_permission('admin:read'))):
    with SessionLocal() as s:
        q=select(ApprovalRequestRow)
        if status:q=q.where(ApprovalRequestRow.status==status)
        rows=s.scalars(q.order_by(ApprovalRequestRow.created_at.desc()).limit(200)).all()
        return {'data':{'items':[{'approval_id':x.approval_id,'operation_type':x.operation_type,'subject_type':x.subject_type,'subject_id':x.subject_id,'requested_by':x.requested_by,'approved_by':x.approved_by,'status':x.status,'request_payload':x.request_payload,'approval_note':x.approval_note,'created_at':_iso(x.created_at),'expires_at':_iso(x.expires_at)} for x in rows],'count':len(rows)}}
