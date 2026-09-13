from __future__ import annotations
from datetime import datetime,timezone
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoveryOperationalCaseRow,JourneyRecoveryExecutionItemRow,JourneyRecoverySupplierOperationRow,JourneyRecoveryReconciliationJobRow,JourneyRecoveryCommandLedgerRow,JourneyRecoveryEvidenceChainRow,JourneyRecoveryOperationalEventRow,JourneyRecoverySlaPolicyRow
from go_hotel.journey.recovery_evidence import recovery_evidence_service
from go_hotel.journey.recovery_sla import recovery_sla_service

def now():return datetime.now(timezone.utc)
def utc(v):return v.replace(tzinfo=timezone.utc) if v and v.tzinfo is None else v
class RecoveryControlPlaneService:
    def _row(self,s,c):
        i=s.get(JourneyRecoveryExecutionItemRow,c.execution_item_id);op=s.get(JourneyRecoverySupplierOperationRow,c.supplier_operation_id) if c.supplier_operation_id else None;j=s.get(JourneyRecoveryReconciliationJobRow,c.reconciliation_job_id) if c.reconciliation_job_id else None
        age=int((now()-utc(c.opened_at)).total_seconds()) if c.opened_at else 0
        p=s.get(JourneyRecoverySlaPolicyRow,c.sla_policy_id) if c.sla_policy_id else None
        ack_due=utc(c.acknowledge_due_at);res_due=utc(c.resolution_due_at)
        return {'operational_case_id':c.operational_case_id,'execution_id':c.execution_id,'execution_item_id':c.execution_item_id,'vertical':i.vertical if i else None,'order_id':i.order_id if i else None,'item_status':i.status if i else None,'supplier_operation_id':c.supplier_operation_id,'adapter_key':op.adapter_key if op else None,'external_operation_id':op.external_operation_id if op else None,'supplier_status':op.status if op else None,'reconciliation_job_id':c.reconciliation_job_id,'reconciliation_state':j.state if j else None,'attempt_count':j.attempt_count if j else 0,'max_attempts':j.max_attempts if j else 0,'state':c.state,'severity':c.severity,'assigned_to':c.assigned_to,'manual_review_reason':c.manual_review_reason,'age_seconds':age,'sla_policy_id':c.sla_policy_id,'queue_key':c.queue_key,'current_escalation_level':c.current_escalation_level or 0,'acknowledge_due_at':c.acknowledge_due_at.isoformat() if c.acknowledge_due_at else None,'resolution_due_at':c.resolution_due_at.isoformat() if c.resolution_due_at else None,'next_escalation_at':c.next_escalation_at.isoformat() if c.next_escalation_at else None,'acknowledge_breached':bool(ack_due and not c.acknowledged_at and now()>ack_due),'resolution_breached':bool(res_due and c.state!='RESOLVED' and now()>res_due),'playbook_key':c.playbook_key,'playbook':p.playbook_json if p else [],'required_evidence_kinds':p.required_evidence_kinds_json if p else ['FINAL_EXTERNAL_FACT'],'closure_evidence_status':c.closure_evidence_status,'opened_at':c.opened_at.isoformat(),'updated_at':c.updated_at.isoformat()}
    def list(self,state=None,limit=100):
        with SessionLocal() as s:
            q=select(JourneyRecoveryOperationalCaseRow)
            if state:q=q.where(JourneyRecoveryOperationalCaseRow.state==state)
            rows=s.execute(q.order_by(JourneyRecoveryOperationalCaseRow.opened_at.desc()).limit(limit)).scalars().all();return {'items':[self._row(s,x) for x in rows]}
    def detail(self,case_id):
        with SessionLocal() as s:
            c=s.get(JourneyRecoveryOperationalCaseRow,case_id)
            if not c:raise ValueError('RECOVERY_OPERATIONAL_CASE_NOT_FOUND')
            base=self._row(s,c);cmd=s.execute(select(JourneyRecoveryCommandLedgerRow).where(JourneyRecoveryCommandLedgerRow.execution_item_id==c.execution_item_id).order_by(JourneyRecoveryCommandLedgerRow.sequence_no)).scalars().all();ev=s.execute(select(JourneyRecoveryEvidenceChainRow).where(JourneyRecoveryEvidenceChainRow.execution_item_id==c.execution_item_id).order_by(JourneyRecoveryEvidenceChainRow.sequence_no)).scalars().all()
            base['command_ledger']=[{'sequence_no':x.sequence_no,'command_kind':x.command_kind,'actor_type':x.actor_type,'actor_id':x.actor_id,'request_id':x.request_id,'payment_id':x.payment_id,'refund_id':x.refund_id,'supplier_command_id':x.supplier_command_id,'entry_hash':x.entry_hash,'previous_hash':x.previous_hash,'payload':x.payload_json,'created_at':x.created_at.isoformat()} for x in cmd]
            base['evidence_chain']=[{'sequence_no':x.sequence_no,'evidence_kind':x.evidence_kind,'source':x.source,'observed_status':x.observed_status,'external_event_id':x.external_event_id,'external_operation_id':x.external_operation_id,'supplier_confirmation_id':x.supplier_confirmation_id,'entry_hash':x.entry_hash,'previous_hash':x.previous_hash,'evidence':x.evidence_json,'created_at':x.created_at.isoformat()} for x in ev]
            ops=s.execute(select(JourneyRecoveryOperationalEventRow).where(JourneyRecoveryOperationalEventRow.operational_case_id==c.operational_case_id).order_by(JourneyRecoveryOperationalEventRow.created_at)).scalars().all()
            base['operational_events']=[{'event_type':x.event_type,'actor_type':x.actor_type,'actor_id':x.actor_id,'from_queue_key':x.from_queue_key,'to_queue_key':x.to_queue_key,'escalation_level':x.escalation_level,'payload':x.payload_json,'created_at':x.created_at.isoformat()} for x in ops]
            base['closure_evidence_requirement']=recovery_sla_service.closure_check(s,c)
            base['chain_verification']=recovery_evidence_service.verify_item(s,c.execution_item_id);base['supplier_fact_mutable_by_admin']=False;return base
    def assign(self,case_id,actor_id,assignee,note=None):
        with SessionLocal() as s:
            c=s.get(JourneyRecoveryOperationalCaseRow,case_id)
            if not c:raise ValueError('RECOVERY_OPERATIONAL_CASE_NOT_FOUND')
            oldq=c.queue_key;c.assigned_to=assignee;c.assignment_note=note;c.assigned_at=now();c.state='ASSIGNED';c.updated_at=now();recovery_sla_service.event(s,c,'MANUAL_ASSIGNED','GO_ADMIN',actor_id,{'assignee':assignee,'note':note},oldq,c.queue_key,c.current_escalation_level);s.commit();return self.detail(case_id)
    def acknowledge(self,case_id,actor_id):
        with SessionLocal() as s:
            c=s.get(JourneyRecoveryOperationalCaseRow,case_id)
            if not c:raise ValueError('RECOVERY_OPERATIONAL_CASE_NOT_FOUND')
            c.acknowledged_at=now();c.state='ACKNOWLEDGED';c.updated_at=now();recovery_sla_service.event(s,c,'CASE_ACKNOWLEDGED','GO_ADMIN',actor_id,{},c.queue_key,c.queue_key,c.current_escalation_level);s.commit();return self.detail(case_id)
recovery_control_plane_service=RecoveryControlPlaneService()
