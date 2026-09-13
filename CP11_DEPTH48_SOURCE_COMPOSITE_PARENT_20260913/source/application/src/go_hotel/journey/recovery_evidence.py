from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
from json import dumps
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.models import JourneyRecoveryCommandLedgerRow,JourneyRecoveryEvidenceChainRow,JourneyRecoveryOperationalCaseRow,JourneyRecoveryExecutionItemRow,JourneyRecoverySupplierOperationRow,JourneyRecoveryReconciliationJobRow

def now(): return datetime.now(timezone.utc)
def new_id(p): return f"{p}_{uuid4().hex[:18]}"
def canon(v): return dumps(v or {},sort_keys=True,separators=(',',':'),default=str)
def h(v): return sha256(v.encode()).hexdigest()
def utc(v):
    if v is None:return None
    return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)

class RecoveryEvidenceService:
    def append_command(self,s,e,i,op,command_kind,payload=None,actor_type='SYSTEM',actor_id=None,request_id=None,payment_id=None,refund_id=None,supplier_command_id=None):
        prev=s.execute(select(JourneyRecoveryCommandLedgerRow).where(JourneyRecoveryCommandLedgerRow.execution_item_id==i.execution_item_id).order_by(JourneyRecoveryCommandLedgerRow.sequence_no.desc())).scalars().first()
        seq=(prev.sequence_no+1) if prev else 1;payload=payload or {};ph=h(canon(payload));prev_hash=prev.entry_hash if prev else None
        entry_hash=h(canon({'execution_id':e.execution_id,'execution_item_id':i.execution_item_id,'supplier_operation_id':op.supplier_operation_id if op else None,'sequence_no':seq,'command_kind':command_kind,'actor_type':actor_type,'actor_id':actor_id,'request_id':request_id,'payment_id':payment_id,'refund_id':refund_id,'supplier_command_id':supplier_command_id,'payload_hash':ph,'previous_hash':prev_hash}))
        r=JourneyRecoveryCommandLedgerRow(command_ledger_id=new_id('jrcl'),execution_id=e.execution_id,execution_item_id=i.execution_item_id,supplier_operation_id=op.supplier_operation_id if op else None,sequence_no=seq,command_kind=command_kind,actor_type=actor_type,actor_id=actor_id,request_id=request_id,payment_id=payment_id,refund_id=refund_id,supplier_command_id=supplier_command_id,payload_hash=ph,previous_hash=prev_hash,entry_hash=entry_hash,payload_json=payload,created_at=now());s.add(r);s.flush();return r
    def append_evidence(self,s,e,i,op,evidence_kind,source,evidence=None,external_event_id=None,external_operation_id=None,supplier_confirmation_id=None,observed_status=None):
        prev=s.execute(select(JourneyRecoveryEvidenceChainRow).where(JourneyRecoveryEvidenceChainRow.execution_item_id==i.execution_item_id).order_by(JourneyRecoveryEvidenceChainRow.sequence_no.desc())).scalars().first()
        seq=(prev.sequence_no+1) if prev else 1;evidence=evidence or {};eh=h(canon(evidence));prev_hash=prev.entry_hash if prev else None
        entry_hash=h(canon({'execution_id':e.execution_id,'execution_item_id':i.execution_item_id,'supplier_operation_id':op.supplier_operation_id if op else None,'sequence_no':seq,'evidence_kind':evidence_kind,'source':source,'external_event_id':external_event_id,'external_operation_id':external_operation_id,'supplier_confirmation_id':supplier_confirmation_id,'observed_status':observed_status,'evidence_hash':eh,'previous_hash':prev_hash}))
        r=JourneyRecoveryEvidenceChainRow(evidence_chain_id=new_id('jrec'),execution_id=e.execution_id,execution_item_id=i.execution_item_id,supplier_operation_id=op.supplier_operation_id if op else None,sequence_no=seq,evidence_kind=evidence_kind,source=source,external_event_id=external_event_id,external_operation_id=external_operation_id,supplier_confirmation_id=supplier_confirmation_id,observed_status=observed_status,evidence_hash=eh,previous_hash=prev_hash,entry_hash=entry_hash,evidence_json=evidence,created_at=now());s.add(r);s.flush();return r
    def ensure_case(self,s,e,i,op=None,job=None,reason=None,severity='HIGH'):
        c=s.execute(select(JourneyRecoveryOperationalCaseRow).where(JourneyRecoveryOperationalCaseRow.execution_item_id==i.execution_item_id)).scalars().first()
        if not c:
            c=JourneyRecoveryOperationalCaseRow(operational_case_id=new_id('jroc'),execution_id=e.execution_id,execution_item_id=i.execution_item_id,supplier_operation_id=op.supplier_operation_id if op else None,reconciliation_job_id=job.reconciliation_job_id if job else None,state='OPEN',severity=severity,assigned_to=None,assignment_note=None,manual_review_reason=reason,opened_at=now(),assigned_at=None,acknowledged_at=None,resolved_at=None,updated_at=now(),current_escalation_level=0,closure_evidence_status='PENDING');s.add(c);s.flush()
            from go_hotel.journey.recovery_sla import recovery_sla_service
            recovery_sla_service.attach_case(s,c,i,op)
        else:
            c.supplier_operation_id=c.supplier_operation_id or (op.supplier_operation_id if op else None);c.reconciliation_job_id=(job.reconciliation_job_id if job else c.reconciliation_job_id);c.manual_review_reason=reason or c.manual_review_reason
            if severity and severity!=c.severity:
                c.severity=severity;c.sla_policy_id=None
                from go_hotel.journey.recovery_sla import recovery_sla_service
                recovery_sla_service.attach_case(s,c,i,op)
            c.updated_at=now()
        return c
    def resolve_case(self,s,item_id):
        c=s.execute(select(JourneyRecoveryOperationalCaseRow).where(JourneyRecoveryOperationalCaseRow.execution_item_id==item_id)).scalars().first()
        if c and c.state!='RESOLVED':c.state='RESOLVED';c.resolved_at=now();c.updated_at=now()
    def verify_item(self,s,item_id):
        out={}
        for key,model,payload_attr,hash_attr in [('command',JourneyRecoveryCommandLedgerRow,'payload_json','payload_hash'),('evidence',JourneyRecoveryEvidenceChainRow,'evidence_json','evidence_hash')]:
            rows=s.execute(select(model).where(model.execution_item_id==item_id).order_by(model.sequence_no)).scalars().all();prev=None;ok=True
            for r in rows:
                if r.previous_hash!=prev or h(canon(getattr(r,payload_attr)))!=getattr(r,hash_attr):ok=False;break
                # recompute structural hash excluding ids/time
                if key=='command': data={'execution_id':r.execution_id,'execution_item_id':r.execution_item_id,'supplier_operation_id':r.supplier_operation_id,'sequence_no':r.sequence_no,'command_kind':r.command_kind,'actor_type':r.actor_type,'actor_id':r.actor_id,'request_id':r.request_id,'payment_id':r.payment_id,'refund_id':r.refund_id,'supplier_command_id':r.supplier_command_id,'payload_hash':r.payload_hash,'previous_hash':r.previous_hash}
                else:data={'execution_id':r.execution_id,'execution_item_id':r.execution_item_id,'supplier_operation_id':r.supplier_operation_id,'sequence_no':r.sequence_no,'evidence_kind':r.evidence_kind,'source':r.source,'external_event_id':r.external_event_id,'external_operation_id':r.external_operation_id,'supplier_confirmation_id':r.supplier_confirmation_id,'observed_status':r.observed_status,'evidence_hash':r.evidence_hash,'previous_hash':r.previous_hash}
                if h(canon(data))!=r.entry_hash:ok=False;break
                prev=r.entry_hash
            out[key]={'valid':ok,'entries':len(rows),'head_hash':prev}
        out['valid']=out['command']['valid'] and out['evidence']['valid'];return out

recovery_evidence_service=RecoveryEvidenceService()
