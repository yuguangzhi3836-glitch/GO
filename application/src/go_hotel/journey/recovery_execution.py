from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
from json import dumps
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    JourneyRecoveryPlanRow, JourneyRecoveryOptionRow,
    JourneyRecoveryExecutionRow, JourneyRecoveryExecutionItemRow,
    JourneyRecoveryExecutionEventRow, JourneyRecoveryReconciliationJobRow, JourneyRecoverySupplierOperationRow, JourneyRecoveryReliabilityProfileRow,
)
from go_hotel.recovery_adapters.registry import recovery_adapter_registry
from go_hotel.journey.recovery_reconciliation import recovery_reconciliation_service
from go_hotel.journey.recovery_evidence import recovery_evidence_service

TERMINAL_SUCCESS={"CONFIRMED"}
ACTION_REQUIRED={"PRICE_CHANGED","SOLD_OUT","RULE_BLOCKED","PAYMENT_REQUIRED","PAYMENT_FAILED","UNKNOWN_EXTERNAL_STATE","EXPIRED"}
TERMINAL_FAILURE={"FAILED"}

def now(): return datetime.now(timezone.utc)
def new_id(p): return f"{p}_{uuid4().hex[:18]}"
def stable_hash(v): return sha256(dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def as_utc(v):
    if v is None:return None
    if v.tzinfo is None:return v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc)

def _event(s,eid,item_id,event_type,status,evidence=None,request_id=None):
    s.add(JourneyRecoveryExecutionEventRow(event_id=new_id('jree'),execution_id=eid,execution_item_id=item_id,event_type=event_type,status=status,request_id=request_id,evidence_json=evidence or {},created_at=now()))

def _item_label(i):
    return {"RIDE":"接送机","RENTAL":"租车","HOTEL":"酒店","RAIL":"铁路","ATTRACTION":"门票","FLIGHT":"航班"}.get(i.vertical,i.vertical)

class JourneyRecoveryExecutionService:
    """Sprint 3H orchestration boundary.

    Atomicity applies to captured user intent only. Each item has a separate supplier
    mutation command and state machine. A completed item is never rolled back merely
    because another item failed. UNKNOWN_EXTERNAL_STATE is reconciled before retry.
    """
    def _plan(self,s,account_id,journey_id,plan_id):
        p=s.get(JourneyRecoveryPlanRow,plan_id)
        if not p or p.account_id!=account_id or p.journey_id!=journey_id: raise ValueError('RECOVERY_PLAN_NOT_FOUND')
        return p
    def _execution(self,s,account_id,journey_id,execution_id):
        e=s.get(JourneyRecoveryExecutionRow,execution_id)
        if not e or e.account_id!=account_id or e.journey_id!=journey_id: raise ValueError('RECOVERY_EXECUTION_NOT_FOUND')
        return e

    def create(self,account_id,journey_id,plan_id,authorized_delta_minor,payment_method_ref=None,idempotency_key=None):
        with SessionLocal() as s:
            p=self._plan(s,account_id,journey_id,plan_id)
            if p.status!='SELECTED' or not p.selected_option_ids_json: raise ValueError('RECOVERY_PLAN_NOT_SELECTED')
            if as_utc(p.expires_at) and as_utc(p.expires_at)<now(): raise ValueError('RECOVERY_PLAN_EXPIRED')
            option_ids=sorted(set(p.selected_option_ids_json))
            opts=s.execute(select(JourneyRecoveryOptionRow).where(JourneyRecoveryOptionRow.plan_id==plan_id,JourneyRecoveryOptionRow.option_id.in_(option_ids))).scalars().all()
            if len(opts)!=len(option_ids): raise ValueError('RECOVERY_OPTION_NOT_FOUND')
            quoted=sum(max(0,o.total_delta_minor) for o in opts)
            if authorized_delta_minor<quoted: raise ValueError('AUTHORIZED_AMOUNT_BELOW_QUOTED_TOTAL')
            intent={"plan_id":plan_id,"option_ids":option_ids,"authorized_delta_minor":authorized_delta_minor,"currency":p.currency,"payment_method_ref":payment_method_ref,"automatic_substitution":False,"atomic_supplier_transaction":False}
            ih=stable_hash(intent)
            existing=s.execute(select(JourneyRecoveryExecutionRow).where(JourneyRecoveryExecutionRow.plan_id==plan_id,JourneyRecoveryExecutionRow.intent_hash==ih)).scalars().first()
            if existing:
                return self._serialize(s,existing)
            e=JourneyRecoveryExecutionRow(execution_id=new_id('jre'),journey_id=journey_id,account_id=account_id,plan_id=plan_id,intent_id=new_id('intent'),intent_hash=ih,status='AWAITING_CONFIRMATION',currency=p.currency,quoted_delta_minor=quoted,authorized_delta_minor=authorized_delta_minor,completed_items=0,action_required_items=0,failed_items=0,intent_json=intent|{"idempotency_key":idempotency_key},created_at=now(),confirmed_at=None,completed_at=None,updated_at=now())
            s.add(e);s.flush();_event(s,e.execution_id,None,'ATOMIC_USER_INTENT_CREATED','AWAITING_CONFIRMATION',{"plan_id":plan_id,"option_ids":option_ids,"authorized_delta_minor":authorized_delta_minor,"atomic_supplier_transaction":False},idempotency_key)
            for o in opts:
                facts=dict(o.quote_facts_json or {})
                item=JourneyRecoveryExecutionItemRow(execution_item_id=new_id('jrei'),execution_id=e.execution_id,option_id=o.option_id,journey_id=journey_id,account_id=account_id,vertical=o.vertical,order_id=o.order_id,rule_version=f"{o.vertical}_RECOVERY_RULE_V1",quote_id=f"rq_{o.option_id}",quoted_delta_minor=o.total_delta_minor,revalidated_delta_minor=o.total_delta_minor,currency=o.currency,payment_action_json={"required":o.total_delta_minor>0,"amount_minor":max(0,o.total_delta_minor),"currency":o.currency,"rail":"EXISTING_PAYMENT_REFUND_LEDGER","payment_method_ref":payment_method_ref},supplier_command_id=None,supplier_confirmation_id=None,status='PENDING',failure_reason=None,reconciliation_state='NOT_REQUIRED',attempt_count=0,facts_json=facts|{"execution_route":o.execution_route,"option_type":o.option_type},created_at=now(),updated_at=now())
                s.add(item)
            s.commit();return self.get(account_id,journey_id,e.execution_id)

    def confirm(self,account_id,journey_id,execution_id,request_id=None):
        with SessionLocal() as s:
            e=self._execution(s,account_id,journey_id,execution_id)
            if e.status not in {'AWAITING_CONFIRMATION','EXECUTING'}:
                return self._serialize(s,e)
            if not e.confirmed_at:
                e.confirmed_at=now();e.status='EXECUTING';e.updated_at=now();_event(s,e.execution_id,None,'ATOMIC_USER_INTENT_CONFIRMED','CONFIRMED',{"authorized_delta_minor":e.authorized_delta_minor},request_id)
            items=s.execute(select(JourneyRecoveryExecutionItemRow).where(JourneyRecoveryExecutionItemRow.execution_id==e.execution_id).order_by(JourneyRecoveryExecutionItemRow.created_at)).scalars().all()
            for i in items:
                if i.status in TERMINAL_SUCCESS|ACTION_REQUIRED|TERMINAL_FAILURE: continue
                self._execute_item(s,e,i,request_id)
            self._rollup(s,e,items);s.commit();return self.get(account_id,journey_id,execution_id)

    def _execute_item(self,s,e,i,request_id):
        i.attempt_count+=1;i.status='REVALIDATING';i.updated_at=now()
        adapter=recovery_adapter_registry.for_vertical(i.vertical)
        _event(s,e.execution_id,i.execution_item_id,'VERTICAL_REVALIDATION_STARTED','REVALIDATING',{'rule_version':i.rule_version,'quote_id':i.quote_id,'adapter_key':adapter.metadata.adapter_key},request_id)
        f=i.facts_json or {}
        rv=adapter.revalidate(order_id=i.order_id,quote_id=i.quote_id,rule_version=i.rule_version,expected_delta_minor=i.quoted_delta_minor,currency=i.currency,facts=f)
        if rv.status in {'EXPIRED','SOLD_OUT','RULE_BLOCKED'}:
            i.status=rv.status;i.failure_reason={'EXPIRED':'QUOTE_EXPIRED','SOLD_OUT':'SUPPLIER_INVENTORY_UNAVAILABLE','RULE_BLOCKED':'VERTICAL_RULE_BLOCKED'}[rv.status]
            _event(s,e.execution_id,i.execution_item_id,'VERTICAL_REVALIDATION_FAILED',rv.status,rv.evidence,request_id);return
        i.revalidated_delta_minor=rv.delta_minor
        if i.revalidated_delta_minor!=i.quoted_delta_minor:
            i.status='PRICE_CHANGED';i.failure_reason='REAUTHORIZATION_REQUIRED';i.payment_action_json=dict(i.payment_action_json or {})|{'required':i.revalidated_delta_minor>0,'amount_minor':max(0,i.revalidated_delta_minor),'reauthorization_required':True}
            _event(s,e.execution_id,i.execution_item_id,'PRICE_CHANGED','ACTION_REQUIRED',{'quoted_delta_minor':i.quoted_delta_minor,'revalidated_delta_minor':i.revalidated_delta_minor,'adapter_key':adapter.metadata.adapter_key},request_id);return
        if f.get('force_payment_failed'):
            i.status='PAYMENT_FAILED';i.failure_reason='PAYMENT_ORCHESTRATION_FAILED';_event(s,e.execution_id,i.execution_item_id,'PAYMENT_FAILED','ACTION_REQUIRED',{'uses_existing_payment_ledger':True},request_id);return
        op=recovery_reconciliation_service.ensure_operation(s,e,i)
        i.supplier_command_id=i.supplier_command_id or f"supcmd_{stable_hash([e.execution_id,i.execution_item_id])[:20]}"
        op.request_json=dict(op.request_json or {})|{'supplier_command_id':i.supplier_command_id,'authorized_delta_minor':i.revalidated_delta_minor,'idempotency_key':op.supplier_idempotency_key}
        op.status='SENDING';op.sent_at=op.sent_at or now();op.updated_at=now();i.status='EXECUTING'
        _event(s,e.execution_id,i.execution_item_id,'SUPPLIER_MUTATION_SENT','EXECUTING',{'supplier_command_id':i.supplier_command_id,'adapter_key':op.adapter_key,'supplier_idempotency_key':op.supplier_idempotency_key,'supplier_idempotency_required':True},request_id)
        recovery_evidence_service.append_command(s,e,i,op,'FINANCIAL_RAIL_REFERENCE',i.payment_action_json or {},request_id=request_id,payment_id=(i.payment_action_json or {}).get('payment_id'),refund_id=(i.payment_action_json or {}).get('refund_id'))
        recovery_evidence_service.append_command(s,e,i,op,'SUPPLIER_MUTATION',{'adapter_key':op.adapter_key,'idempotency_key':op.supplier_idempotency_key,'quote_id':i.quote_id,'rule_version':i.rule_version,'authorized_delta_minor':i.revalidated_delta_minor},request_id=request_id,supplier_command_id=i.supplier_command_id,payment_id=(i.payment_action_json or {}).get('payment_id'),refund_id=(i.payment_action_json or {}).get('refund_id'))
        result=adapter.mutate(order_id=i.order_id,command_type=op.command_type,idempotency_key=op.supplier_idempotency_key,quote_id=i.quote_id,rule_version=i.rule_version,authorized_delta_minor=i.revalidated_delta_minor,currency=i.currency,facts=f)
        op.external_operation_id=result.external_operation_id;op.response_json=result.evidence or {};op.updated_at=now()
        if result.status=='CONFIRMED':
            op.status='CONFIRMED';op.supplier_confirmation_id=result.supplier_confirmation_id;op.completed_at=now();i.supplier_confirmation_id=result.supplier_confirmation_id;i.status='CONFIRMED';i.failure_reason=None;i.reconciliation_state='NOT_REQUIRED';i.updated_at=now()
            _event(s,e.execution_id,i.execution_item_id,'SUPPLIER_CONFIRMED','CONFIRMED',{'supplier_confirmation_id':i.supplier_confirmation_id,'external_operation_id':op.external_operation_id,'adapter_key':op.adapter_key,'final_delta_minor':i.revalidated_delta_minor},request_id);recovery_evidence_service.append_evidence(s,e,i,op,'FINAL_EXTERNAL_FACT','MUTATION_RESPONSE',result.evidence or {},external_operation_id=op.external_operation_id,supplier_confirmation_id=i.supplier_confirmation_id,observed_status='CONFIRMED');recovery_evidence_service.resolve_case(s,i.execution_item_id);return
        if result.status in {'UNKNOWN','ACCEPTED'}:
            op.status='UNKNOWN' if result.status=='UNKNOWN' else 'ACCEPTED_ASYNC';i.status='UNKNOWN_EXTERNAL_STATE' if result.status=='UNKNOWN' else 'AWAITING_SUPPLIER_CONFIRMATION';i.failure_reason='SUPPLIER_TIMEOUT_AFTER_MUTATION' if result.status=='UNKNOWN' else None;i.reconciliation_state='REQUIRED'
            recovery_reconciliation_service.enqueue(s,e,i,op,'MUTATION_UNKNOWN' if result.status=='UNKNOWN' else 'ASYNC_ACCEPTED')
            _event(s,e.execution_id,i.execution_item_id,'SUPPLIER_MUTATION_UNKNOWN' if result.status=='UNKNOWN' else 'SUPPLIER_MUTATION_ACCEPTED',i.status,{'external_operation_id':op.external_operation_id,'supplier_idempotency_key':op.supplier_idempotency_key,'must_reconcile_before_retry':True},request_id);return
        op.status='FAILED';op.last_error='SUPPLIER_REJECTED';i.status='FAILED';i.failure_reason='SUPPLIER_REJECTED';i.reconciliation_state='NOT_REQUIRED';_event(s,e.execution_id,i.execution_item_id,'SUPPLIER_MUTATION_FAILED','FAILED',result.evidence,request_id)

    def resolve(self,account_id,journey_id,execution_id,item_id,action,authorized_delta_minor=None,request_id=None):
        with SessionLocal() as s:
            e=self._execution(s,account_id,journey_id,execution_id);i=s.get(JourneyRecoveryExecutionItemRow,item_id)
            if not i or i.execution_id!=e.execution_id or i.account_id!=account_id: raise ValueError('RECOVERY_EXECUTION_ITEM_NOT_FOUND')
            if i.status=='PRICE_CHANGED':
                if action!='ACCEPT_PRICE_CHANGE': raise ValueError('PRICE_REAUTHORIZATION_REQUIRED')
                if authorized_delta_minor is None or authorized_delta_minor<i.revalidated_delta_minor: raise ValueError('AUTHORIZED_AMOUNT_BELOW_REVALIDATED_PRICE')
                e.authorized_delta_minor=max(e.authorized_delta_minor,authorized_delta_minor);i.quoted_delta_minor=i.revalidated_delta_minor;i.facts_json=dict(i.facts_json or {})|{"revalidated_delta_minor":i.revalidated_delta_minor};i.status='PENDING';i.failure_reason=None;_event(s,e.execution_id,i.execution_item_id,'PRICE_REAUTHORIZED','READY',{"authorized_delta_minor":authorized_delta_minor},request_id);self._execute_item(s,e,i,request_id)
            elif i.status=='UNKNOWN_EXTERNAL_STATE':
                if action!='RECONCILE': raise ValueError('RECONCILIATION_REQUIRED')
                job=s.execute(select(JourneyRecoveryReconciliationJobRow).where(JourneyRecoveryReconciliationJobRow.execution_item_id==i.execution_item_id,JourneyRecoveryReconciliationJobRow.state.in_(['PENDING','RETRY','RUNNING'])).order_by(JourneyRecoveryReconciliationJobRow.created_at.desc())).scalars().first()
                if not job: raise ValueError('RECOVERY_RECONCILIATION_JOB_NOT_FOUND')
                job.next_attempt_at=now();job.lease_token=None;job.lease_until=None;job.state='PENDING';i.reconciliation_state='IN_PROGRESS';_event(s,e.execution_id,i.execution_item_id,'RECONCILIATION_REQUESTED','IN_PROGRESS',{'job_id':job.reconciliation_job_id},request_id)
                s.commit();recovery_reconciliation_service.run_once(10);return self.get(account_id,journey_id,execution_id)
            elif i.status in {'SOLD_OUT','RULE_BLOCKED','PAYMENT_FAILED','EXPIRED'}:
                if action!='ACKNOWLEDGE': raise ValueError('ACTION_NOT_SUPPORTED')
                _event(s,e.execution_id,i.execution_item_id,'USER_ACKNOWLEDGED_ITEM_FAILURE','ACKNOWLEDGED',{"status":i.status},request_id)
            else: raise ValueError('ITEM_NOT_ACTION_REQUIRED')
            items=s.execute(select(JourneyRecoveryExecutionItemRow).where(JourneyRecoveryExecutionItemRow.execution_id==e.execution_id).order_by(JourneyRecoveryExecutionItemRow.created_at)).scalars().all();self._rollup(s,e,items);s.commit();return self.get(account_id,journey_id,execution_id)

    def _rollup(self,s,e,items):
        e.completed_items=sum(i.status=='CONFIRMED' for i in items);e.action_required_items=sum(i.status in ACTION_REQUIRED for i in items);e.failed_items=sum(i.status in TERMINAL_FAILURE for i in items);e.updated_at=now()
        if e.completed_items==len(items): e.status='COMPLETED';e.completed_at=now()
        elif e.action_required_items and e.completed_items: e.status='PARTIALLY_COMPLETED'
        elif e.action_required_items: e.status='ACTION_REQUIRED'
        elif e.failed_items and e.completed_items: e.status='PARTIALLY_COMPLETED'
        elif e.failed_items==len(items): e.status='FAILED';e.completed_at=now()
        else:e.status='EXECUTING'
        _event(s,e.execution_id,None,'EXECUTION_ROLLUP',e.status,{"completed":e.completed_items,"action_required":e.action_required_items,"failed":e.failed_items,"total":len(items)})

    def get(self,account_id,journey_id,execution_id):
        with SessionLocal() as s:
            e=self._execution(s,account_id,journey_id,execution_id);return self._serialize(s,e)

    def _serialize(self,s,e):
        items=s.execute(select(JourneyRecoveryExecutionItemRow).where(JourneyRecoveryExecutionItemRow.execution_id==e.execution_id).order_by(JourneyRecoveryExecutionItemRow.created_at)).scalars().all()
        events=s.execute(select(JourneyRecoveryExecutionEventRow).where(JourneyRecoveryExecutionEventRow.execution_id==e.execution_id).order_by(JourneyRecoveryExecutionEventRow.created_at)).scalars().all()
        ops=s.execute(select(JourneyRecoverySupplierOperationRow).where(JourneyRecoverySupplierOperationRow.execution_id==e.execution_id)).scalars().all()
        jobs=s.execute(select(JourneyRecoveryReconciliationJobRow).where(JourneyRecoveryReconciliationJobRow.execution_id==e.execution_id).order_by(JourneyRecoveryReconciliationJobRow.created_at.desc())).scalars().all()
        op_by_item={x.execution_item_id:x for x in ops};job_by_item={}
        for x in jobs: job_by_item.setdefault(x.execution_item_id,x)
        reliability={}
        for item_id,op in op_by_item.items():
            p=s.get(JourneyRecoveryReliabilityProfileRow,f"{op.vertical}:{op.adapter_key}")
            if p: reliability[item_id]={"risk_band":p.risk_band,"confidence":p.confidence,"sample_count":p.sample_count,"timeout_rate":p.timeout_rate,"manual_review_rate":p.manual_review_rate,"expected_confirmation_seconds":p.avg_confirmation_seconds}
        return {"execution_id":e.execution_id,"intent_id":e.intent_id,"plan_id":e.plan_id,"journey_id":e.journey_id,"status":e.status,"currency":e.currency,"quoted_delta_minor":e.quoted_delta_minor,"authorized_delta_minor":e.authorized_delta_minor,"atomic_user_intent":True,"atomic_supplier_transaction":False,"completed_items":e.completed_items,"action_required_items":e.action_required_items,"failed_items":e.failed_items,"total_items":len(items),"summary":f"{e.completed_items} 项完成 · {e.action_required_items+e.failed_items} 项需要处理" if items else "等待恢复执行","items":[{"execution_item_id":i.execution_item_id,"option_id":i.option_id,"vertical":i.vertical,"label":_item_label(i),"order_id":i.order_id,"rule_version":i.rule_version,"quote_id":i.quote_id,"quoted_delta_minor":i.quoted_delta_minor,"revalidated_delta_minor":i.revalidated_delta_minor,"currency":i.currency,"payment_action":i.payment_action_json,"supplier_command_id":i.supplier_command_id,"supplier_confirmation_id":i.supplier_confirmation_id,"status":i.status,"failure_reason":i.failure_reason,"reconciliation_state":i.reconciliation_state,"attempt_count":i.attempt_count,"adapter_key":op_by_item[i.execution_item_id].adapter_key if i.execution_item_id in op_by_item else None,"supplier_idempotency_key":op_by_item[i.execution_item_id].supplier_idempotency_key if i.execution_item_id in op_by_item else None,"external_operation_id":op_by_item[i.execution_item_id].external_operation_id if i.execution_item_id in op_by_item else None,"reconciliation_job_state":job_by_item[i.execution_item_id].state if i.execution_item_id in job_by_item else None,"reliability_memory":reliability.get(i.execution_item_id),"risk_hint":"HISTORICALLY_UNSTABLE_SUPPLIER_PATH" if reliability.get(i.execution_item_id,{}).get("risk_band")=="HIGH" else None} for i in items],"events":[{"event_id":x.event_id,"execution_item_id":x.execution_item_id,"event_type":x.event_type,"status":x.status,"request_id":x.request_id,"evidence":x.evidence_json,"created_at":x.created_at.isoformat()} for x in events],"execution_boundary":"ATOMIC_INTENT_NON_ATOMIC_EXECUTION_EXPLICIT_OUTCOME"}

journey_recovery_execution_service=JourneyRecoveryExecutionService()
