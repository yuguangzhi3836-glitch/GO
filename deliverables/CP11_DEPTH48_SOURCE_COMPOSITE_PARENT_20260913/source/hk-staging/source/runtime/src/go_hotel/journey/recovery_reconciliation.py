from __future__ import annotations
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from json import dumps
from uuid import uuid4
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    JourneyRecoveryExecutionRow, JourneyRecoveryExecutionItemRow, JourneyRecoveryExecutionEventRow,
    JourneyRecoverySupplierOperationRow, JourneyRecoveryReconciliationJobRow,
    JourneyRecoveryReconciliationObservationRow,
)
from go_hotel.recovery_adapters.registry import recovery_adapter_registry
from go_hotel.journey.recovery_evidence import recovery_evidence_service
from go_hotel.journey.recovery_reliability import recovery_reliability_service
from go_hotel.journey.recovery_strategy_governance import recovery_strategy_governance_service

def now(): return datetime.now(timezone.utc)
def new_id(p): return f"{p}_{uuid4().hex[:18]}"
def stable(v): return sha256(dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def utc(v):
    if v is None:return None
    return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)

def event(s,eid,item_id,event_type,status,evidence=None):
    s.add(JourneyRecoveryExecutionEventRow(event_id=new_id('jree'),execution_id=eid,execution_item_id=item_id,event_type=event_type,status=status,request_id=None,evidence_json=evidence or {},created_at=now()))

class RecoveryReconciliationService:
    def supplier_idempotency_key(self,e,i):
        return f"go-recovery:{stable([e.intent_id,i.execution_item_id,i.rule_version,i.quote_id])[:48]}"

    def ensure_operation(self,s,e,i):
        op=s.execute(select(JourneyRecoverySupplierOperationRow).where(JourneyRecoverySupplierOperationRow.execution_item_id==i.execution_item_id)).scalars().first()
        if op:return op
        adapter=recovery_adapter_registry.for_vertical(i.vertical)
        op=JourneyRecoverySupplierOperationRow(
            supplier_operation_id=new_id('jrso'),execution_id=e.execution_id,execution_item_id=i.execution_item_id,
            vertical=i.vertical,adapter_key=adapter.metadata.adapter_key,
            supplier_idempotency_key=self.supplier_idempotency_key(e,i),command_type='RECOVERY_CHANGE',status='CREATED',
            external_operation_id=None,supplier_confirmation_id=None,
            request_json={'order_id':i.order_id,'quote_id':i.quote_id,'rule_version':i.rule_version,'currency':i.currency},
            response_json={},last_error=None,created_at=now(),sent_at=None,last_observed_at=None,completed_at=None,updated_at=now())
        s.add(op);s.flush();return op

    def enqueue(self,s,e,i,op,trigger='MUTATION_UNKNOWN',delay_seconds=0,max_attempts=8):
        active=s.execute(select(JourneyRecoveryReconciliationJobRow).where(
            JourneyRecoveryReconciliationJobRow.supplier_operation_id==op.supplier_operation_id,
            JourneyRecoveryReconciliationJobRow.state.in_(['PENDING','RETRY','RUNNING'])
        )).scalars().first()
        if active:return active
        profile=recovery_reliability_service.effective(s,i.vertical,op.adapter_key)
        governance=recovery_strategy_governance_service.evaluate(s,profile,i.execution_item_id)
        gp=governance['applied']
        effective_delay=(gp['initial_poll_seconds'] if delay_seconds==0 else delay_seconds)
        effective_max_attempts=gp['max_attempts']
        recovery_reliability_service.record_decision(s,i,op,profile,'RECONCILIATION_POLICY',{'initial_poll_seconds':effective_delay,'max_attempts':effective_max_attempts,'trigger':trigger})
        j=JourneyRecoveryReconciliationJobRow(
            reconciliation_job_id=new_id('jrrj'),supplier_operation_id=op.supplier_operation_id,
            execution_id=e.execution_id,execution_item_id=i.execution_item_id,state='PENDING',trigger_source=trigger,
            attempt_count=0,max_attempts=effective_max_attempts,next_attempt_at=now()+timedelta(seconds=effective_delay),
            lease_token=None,lease_until=None,last_error=None,resolution_json={},created_at=now(),updated_at=now())
        s.add(j);s.flush();recovery_evidence_service.ensure_case(s,e,i,op,j,trigger,'HIGH' if trigger=='MUTATION_UNKNOWN' else 'MEDIUM');event(s,e.execution_id,i.execution_item_id,'RECOVERY_RECONCILIATION_ENQUEUED','PENDING',{'job_id':j.reconciliation_job_id,'trigger':trigger});return j

    def record_observation(self,s,op,i,source,obs):
        ext=obs.external_event_id
        if ext:
            prior=s.execute(select(JourneyRecoveryReconciliationObservationRow).where(
                JourneyRecoveryReconciliationObservationRow.source==source,
                JourneyRecoveryReconciliationObservationRow.external_event_id==ext
            )).scalars().first()
            if prior:return prior
        row=JourneyRecoveryReconciliationObservationRow(
            observation_id=new_id('jrro'),supplier_operation_id=op.supplier_operation_id,execution_item_id=i.execution_item_id,
            source=source,external_event_id=ext,observed_status=obs.status,supplier_confirmation_id=obs.supplier_confirmation_id,
            evidence_json=obs.evidence or {},created_at=now())
        s.add(row);op.last_observed_at=now();op.updated_at=now();e=s.get(JourneyRecoveryExecutionRow,op.execution_id);recovery_evidence_service.append_evidence(s,e,i,op,'SUPPLIER_OBSERVATION',source,obs.evidence or {},external_event_id=obs.external_event_id,external_operation_id=op.external_operation_id,supplier_confirmation_id=obs.supplier_confirmation_id,observed_status=obs.status);return row


    def _rollup_execution(self,s,e):
        items=s.execute(select(JourneyRecoveryExecutionItemRow).where(JourneyRecoveryExecutionItemRow.execution_id==e.execution_id)).scalars().all()
        action={"PRICE_CHANGED","SOLD_OUT","RULE_BLOCKED","PAYMENT_REQUIRED","PAYMENT_FAILED","UNKNOWN_EXTERNAL_STATE","EXPIRED"}
        e.completed_items=sum(x.status=='CONFIRMED' for x in items);e.action_required_items=sum(x.status in action for x in items);e.failed_items=sum(x.status=='FAILED' for x in items);e.updated_at=now()
        if e.completed_items==len(items): e.status='COMPLETED';e.completed_at=now()
        elif e.action_required_items and e.completed_items: e.status='PARTIALLY_COMPLETED'
        elif e.action_required_items: e.status='ACTION_REQUIRED'
        elif e.failed_items and e.completed_items: e.status='PARTIALLY_COMPLETED'
        elif e.failed_items==len(items): e.status='FAILED';e.completed_at=now()
        else: e.status='EXECUTING'

    def _apply(self,s,e,i,op,job,obs,source):
        self.record_observation(s,op,i,source,obs)
        if obs.status=='CONFIRMED':
            op.status='CONFIRMED';op.supplier_confirmation_id=obs.supplier_confirmation_id or op.supplier_confirmation_id;op.completed_at=now()
            i.status='CONFIRMED';i.failure_reason=None;i.reconciliation_state='RESOLVED_CONFIRMED';i.supplier_confirmation_id=op.supplier_confirmation_id
            if job: job.state='RESOLVED';job.resolution_json={'status':'CONFIRMED','source':source,'supplier_confirmation_id':op.supplier_confirmation_id}
            recovery_evidence_service.append_evidence(s,e,i,op,'FINAL_EXTERNAL_FACT',source,obs.evidence or {},external_event_id=obs.external_event_id,external_operation_id=op.external_operation_id,supplier_confirmation_id=op.supplier_confirmation_id,observed_status='CONFIRMED');event(s,e.execution_id,i.execution_item_id,'RECOVERY_RECONCILIATION_RESOLVED','CONFIRMED',{'source':source,'supplier_confirmation_id':op.supplier_confirmation_id});recovery_evidence_service.resolve_case(s,i.execution_item_id);self._rollup_execution(s,e)
            return 'RESOLVED'
        if obs.status=='NOT_APPLIED':
            op.status='NOT_APPLIED';i.status='PENDING';i.failure_reason=None;i.reconciliation_state='RESOLVED_NOT_APPLIED'
            if job: job.state='RESOLVED';job.resolution_json={'status':'NOT_APPLIED','source':source,'safe_to_retry':True}
            recovery_evidence_service.append_evidence(s,e,i,op,'FINAL_EXTERNAL_FACT',source,obs.evidence or {},external_event_id=obs.external_event_id,external_operation_id=op.external_operation_id,observed_status='NOT_APPLIED');event(s,e.execution_id,i.execution_item_id,'RECOVERY_RECONCILIATION_RESOLVED','NOT_APPLIED',{'source':source,'safe_to_retry':True});recovery_evidence_service.resolve_case(s,i.execution_item_id);self._rollup_execution(s,e)
            return 'RESOLVED'
        if obs.status=='FAILED':
            op.status='FAILED';i.status='FAILED';i.failure_reason='SUPPLIER_CONFIRMED_FAILURE';i.reconciliation_state='RESOLVED_FAILED'
            if job: job.state='RESOLVED';job.resolution_json={'status':'FAILED','source':source}
            recovery_evidence_service.append_evidence(s,e,i,op,'FINAL_EXTERNAL_FACT',source,obs.evidence or {},external_event_id=obs.external_event_id,external_operation_id=op.external_operation_id,observed_status='FAILED');event(s,e.execution_id,i.execution_item_id,'RECOVERY_RECONCILIATION_RESOLVED','FAILED',{'source':source});recovery_evidence_service.resolve_case(s,i.execution_item_id);self._rollup_execution(s,e)
            return 'RESOLVED'
        return 'PENDING'

    def ingest_webhook(self,adapter_key,payload):
        adapter=recovery_adapter_registry.by_key(adapter_key);obs=adapter.parse_webhook(payload)
        with SessionLocal() as s:
            ext=payload.get('external_operation_id')
            idem=payload.get('idempotency_key')
            q=select(JourneyRecoverySupplierOperationRow).where(JourneyRecoverySupplierOperationRow.adapter_key==adapter_key)
            if ext:q=q.where(JourneyRecoverySupplierOperationRow.external_operation_id==ext)
            elif idem:q=q.where(JourneyRecoverySupplierOperationRow.supplier_idempotency_key==idem)
            else:raise ValueError('RECOVERY_WEBHOOK_CORRELATION_REQUIRED')
            op=s.execute(q).scalars().first()
            if not op:raise ValueError('RECOVERY_SUPPLIER_OPERATION_NOT_FOUND')
            i=s.get(JourneyRecoveryExecutionItemRow,op.execution_item_id);e=s.get(JourneyRecoveryExecutionRow,op.execution_id)
            job=s.execute(select(JourneyRecoveryReconciliationJobRow).where(JourneyRecoveryReconciliationJobRow.supplier_operation_id==op.supplier_operation_id,JourneyRecoveryReconciliationJobRow.state.in_(['PENDING','RETRY','RUNNING']))).scalars().first()
            outcome=self._apply(s,e,i,op,job,obs,'WEBHOOK')
            if job:job.lease_token=None;job.lease_until=None;job.updated_at=now()
            s.commit();return {'supplier_operation_id':op.supplier_operation_id,'execution_item_id':i.execution_item_id,'observed_status':obs.status,'outcome':outcome}

    def run_once(self,limit=50,lease_seconds=30):
        claimed=[]
        with SessionLocal() as s:
            rows=s.execute(select(JourneyRecoveryReconciliationJobRow).where(
                JourneyRecoveryReconciliationJobRow.state.in_(['PENDING','RETRY','RUNNING']),
                JourneyRecoveryReconciliationJobRow.next_attempt_at<=now(),
                or_(JourneyRecoveryReconciliationJobRow.lease_until.is_(None),JourneyRecoveryReconciliationJobRow.lease_until<now())
            ).order_by(JourneyRecoveryReconciliationJobRow.next_attempt_at).limit(limit)).scalars().all()
            for j in rows:
                token=new_id('lease');j.state='RUNNING';j.lease_token=token;j.lease_until=now()+timedelta(seconds=lease_seconds);j.updated_at=now();claimed.append((j.reconciliation_job_id,token))
            s.commit()
        stats={'claimed':len(claimed),'resolved':0,'retried':0,'dead_letter':0,'manual_review':0,'errors':0}
        for jid,token in claimed:
            try:self._process_claim(jid,token,stats)
            except Exception:
                stats['errors']+=1
                with SessionLocal.begin() as s:
                    j=s.get(JourneyRecoveryReconciliationJobRow,jid)
                    if j and j.lease_token==token:
                        j.state='RETRY';j.last_error='WORKER_EXCEPTION';j.lease_token=None;j.lease_until=None;j.next_attempt_at=now()+timedelta(seconds=30);j.updated_at=now()
        return stats

    def _process_claim(self,jid,token,stats):
        with SessionLocal() as s:
            j=s.get(JourneyRecoveryReconciliationJobRow,jid)
            if not j or j.lease_token!=token:return
            op=s.get(JourneyRecoverySupplierOperationRow,j.supplier_operation_id);i=s.get(JourneyRecoveryExecutionItemRow,j.execution_item_id);e=s.get(JourneyRecoveryExecutionRow,j.execution_id)
            adapter=recovery_adapter_registry.by_key(op.adapter_key)
            j.attempt_count+=1;j.updated_at=now()
            recovery_evidence_service.append_command(s,e,i,op,'SUPPLIER_POLL',{'external_operation_id':op.external_operation_id,'idempotency_key':op.supplier_idempotency_key,'attempt':j.attempt_count},actor_type='WORKER')
            obs=adapter.poll(external_operation_id=op.external_operation_id,idempotency_key=op.supplier_idempotency_key,order_id=i.order_id,facts=i.facts_json or {})
            outcome=self._apply(s,e,i,op,j,obs,'POLL')
            if outcome=='RESOLVED':stats['resolved']+=1
            else:
                if j.attempt_count>=j.max_attempts:
                    j.state='DEAD_LETTER';j.last_error='RECONCILIATION_ATTEMPTS_EXHAUSTED';i.reconciliation_state='MANUAL_REVIEW';i.failure_reason='UNKNOWN_EXTERNAL_STATE_UNRESOLVED';stats['dead_letter']+=1;stats['manual_review']+=1
                    event(s,e.execution_id,i.execution_item_id,'RECOVERY_RECONCILIATION_DEAD_LETTER','ACTION_REQUIRED',{'job_id':jid,'attempts':j.attempt_count});recovery_evidence_service.ensure_case(s,e,i,op,j,'RECONCILIATION_ATTEMPTS_EXHAUSTED','CRITICAL');self._rollup_execution(s,e)
                else:
                    profile=recovery_reliability_service.effective(s,i.vertical,op.adapter_key)
                    cap=profile.recommended_max_poll_seconds if profile else 300
                    base=profile.recommended_initial_poll_seconds if profile else 1
                    delay=min(cap,max(base,base*(2**min(j.attempt_count-1,8))))
                    recovery_reliability_service.record_decision(s,i,op,profile,'POLL_BACKOFF',{'attempt':j.attempt_count,'delay_seconds':delay,'cap_seconds':cap})
                    j.state='RETRY';j.next_attempt_at=now()+timedelta(seconds=delay);stats['retried']+=1
            j.lease_token=None;j.lease_until=None;j.updated_at=now();s.commit()

    def manual_resolve(self,job_id,resolution,supplier_confirmation_id=None,actor_id=None,evidence_reference=None,evidence_payload=None):
        with SessionLocal() as s:
            j=s.get(JourneyRecoveryReconciliationJobRow,job_id)
            if not j:raise ValueError('RECOVERY_RECONCILIATION_JOB_NOT_FOUND')
            if j.state not in {'DEAD_LETTER','MANUAL_REVIEW'}:raise ValueError('RECOVERY_RECONCILIATION_JOB_NOT_MANUAL')
            op=s.get(JourneyRecoverySupplierOperationRow,j.supplier_operation_id);i=s.get(JourneyRecoveryExecutionItemRow,j.execution_item_id);e=s.get(JourneyRecoveryExecutionRow,j.execution_id)
            recovery_evidence_service.append_command(s,e,i,op,'MANUAL_RESOLUTION',{'resolution':resolution,'supplier_confirmation_id':supplier_confirmation_id,'evidence_reference':evidence_reference},actor_type='GO_ADMIN',actor_id=actor_id)
            recovery_evidence_service.append_evidence(s,e,i,op,'MANUAL_VERIFIED_EVIDENCE','MANUAL',{'evidence_reference':evidence_reference,'evidence':evidence_payload or {}},external_operation_id=op.external_operation_id,supplier_confirmation_id=supplier_confirmation_id,observed_status=resolution)
            if resolution=='CONFIRMED':
                from go_hotel.recovery_adapters.base import RecoveryObservation
                self._apply(s,e,i,op,j,RecoveryObservation('CONFIRMED',supplier_confirmation_id or op.supplier_confirmation_id,None,{'manual':True}),'MANUAL')
            elif resolution=='NOT_APPLIED':
                from go_hotel.recovery_adapters.base import RecoveryObservation
                self._apply(s,e,i,op,j,RecoveryObservation('NOT_APPLIED',None,None,{'manual':True}),'MANUAL')
            else:raise ValueError('RECOVERY_MANUAL_RESOLUTION_INVALID')
            j.state='RESOLVED';j.updated_at=now();s.commit();return {'job_id':job_id,'state':j.state,'resolution':resolution}

recovery_reconciliation_service=RecoveryReconciliationService()
