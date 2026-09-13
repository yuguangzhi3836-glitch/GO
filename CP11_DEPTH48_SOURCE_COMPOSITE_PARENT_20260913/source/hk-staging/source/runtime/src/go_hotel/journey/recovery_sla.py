from __future__ import annotations
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from sqlalchemy import select, or_
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoverySlaPolicyRow,JourneyRecoveryOpsQueueRow,JourneyRecoveryOperationalEventRow,JourneyRecoveryOperationalCaseRow,JourneyRecoveryExecutionItemRow,JourneyRecoverySupplierOperationRow,JourneyRecoveryEvidenceChainRow
from go_hotel.journey.recovery_reliability import recovery_reliability_service
from go_hotel.journey.recovery_strategy_governance import recovery_strategy_governance_service

def now(): return datetime.now(timezone.utc)
def new_id(p): return f"{p}_{uuid4().hex[:18]}"
def utc(v): return v.replace(tzinfo=timezone.utc) if v and v.tzinfo is None else v

DEFAULT_POLICIES={
 'CRITICAL':{'ack':300,'resolve':1800,'queue':'recovery_p0','steps':[{'after_seconds':300,'level':1,'alert':'ON_CALL'},{'after_seconds':900,'level':2,'alert':'OPS_LEAD'},{'after_seconds':1800,'level':3,'alert':'INCIDENT_COMMANDER'}]},
 'HIGH':{'ack':600,'resolve':3600,'queue':'recovery_p1','steps':[{'after_seconds':600,'level':1,'alert':'ON_CALL'},{'after_seconds':1800,'level':2,'alert':'OPS_LEAD'},{'after_seconds':3600,'level':3,'alert':'DUTY_MANAGER'}]},
 'MEDIUM':{'ack':1800,'resolve':14400,'queue':'recovery_p2','steps':[{'after_seconds':1800,'level':1,'alert':'QUEUE'},{'after_seconds':7200,'level':2,'alert':'OPS_LEAD'}]},
}
DEFAULT_PLAYBOOK=[
 {'step':1,'action':'Verify supplier operation by external operation id or stable idempotency key'},
 {'step':2,'action':'Review latest webhook/poll evidence and payment/refund references'},
 {'step':3,'action':'Use supplier console or approved support channel; never resend mutation solely due to timeout'},
 {'step':4,'action':'Attach resolution evidence before case closure'},
]

class RecoverySlaService:
    def bootstrap(self,s):
        for key,name,oncall,backup in [('recovery_p0','Recovery P0','ops_recovery_primary','ops_recovery_lead'),('recovery_p1','Recovery P1','ops_recovery_primary','ops_recovery_backup'),('recovery_p2','Recovery P2','ops_recovery_queue','ops_recovery_backup')]:
            if not s.get(JourneyRecoveryOpsQueueRow,key):
                s.add(JourneyRecoveryOpsQueueRow(queue_key=key,name=name,timezone_name='UTC',on_call_owner=oncall,backup_owner=backup,enabled=True,metadata_json={'shift_model':'24x7 engineering baseline'},updated_at=now()))
        s.flush()
        for sev,cfg in DEFAULT_POLICIES.items():
            pid=f'default_{sev.lower()}'
            if not s.get(JourneyRecoverySlaPolicyRow,pid):
                s.add(JourneyRecoverySlaPolicyRow(sla_policy_id=pid,name=f'Default Recovery {sev}',vertical=None,adapter_key=None,severity=sev,queue_key=cfg['queue'],acknowledge_sla_seconds=cfg['ack'],resolution_sla_seconds=cfg['resolve'],escalation_steps_json=cfg['steps'],playbook_key='recovery_unknown_external_state_v1',playbook_json=DEFAULT_PLAYBOOK,required_evidence_kinds_json=['FINAL_EXTERNAL_FACT'],enabled=True,created_at=now(),updated_at=now()))
        s.flush()
    def match_policy(self,s,vertical,adapter_key,severity):
        self.bootstrap(s)
        rows=s.execute(select(JourneyRecoverySlaPolicyRow).where(JourneyRecoverySlaPolicyRow.enabled.is_(True),JourneyRecoverySlaPolicyRow.severity==severity)).scalars().all()
        def score(p):
            if p.vertical not in (None,vertical): return -1
            if p.adapter_key not in (None,adapter_key): return -1
            return (2 if p.vertical==vertical else 0)+(4 if p.adapter_key==adapter_key else 0)
        rows=[p for p in rows if score(p)>=0]
        return max(rows,key=score) if rows else s.get(JourneyRecoverySlaPolicyRow,'default_high')
    def event(self,s,c,event_type,actor_type='SYSTEM',actor_id=None,payload=None,from_queue=None,to_queue=None,level=None):
        r=JourneyRecoveryOperationalEventRow(operational_event_id=new_id('jroe'),operational_case_id=c.operational_case_id,event_type=event_type,actor_type=actor_type,actor_id=actor_id,from_queue_key=from_queue,to_queue_key=to_queue,escalation_level=level,payload_json=payload or {},created_at=now());s.add(r);return r
    def attach_case(self,s,c,i,op=None):
        if c.sla_policy_id:return c
        adapter_key=op.adapter_key if op else None;p=self.match_policy(s,i.vertical,adapter_key,c.severity)
        rp=recovery_reliability_service.effective(s,i.vertical,adapter_key) if adapter_key else None
        gov=recovery_strategy_governance_service.evaluate(s,rp,i.execution_item_id);ack_mult=gov['applied']['ack_multiplier'];res_mult=gov['applied']['resolution_multiplier']
        ack_seconds=max(60,int(p.acknowledge_sla_seconds*ack_mult));res_seconds=max(300,int(p.resolution_sla_seconds*res_mult))
        c.sla_policy_id=p.sla_policy_id;c.queue_key=p.queue_key;c.playbook_key=p.playbook_key;c.current_escalation_level=0;c.acknowledge_due_at=utc(c.opened_at)+timedelta(seconds=ack_seconds);c.resolution_due_at=utc(c.opened_at)+timedelta(seconds=res_seconds);steps=p.escalation_steps_json or [];c.next_escalation_at=utc(c.opened_at)+timedelta(seconds=min(int(steps[0]['after_seconds']),ack_seconds)) if steps else c.resolution_due_at;c.closure_evidence_status='PENDING';c.updated_at=now();
        recovery_reliability_service.record_decision(s,i,op,rp,'SLA_FEEDBACK',{'base_ack_seconds':p.acknowledge_sla_seconds,'effective_ack_seconds':ack_seconds,'base_resolution_seconds':p.resolution_sla_seconds,'effective_resolution_seconds':res_seconds})
        self.event(s,c,'SLA_ATTACHED',payload={'sla_policy_id':p.sla_policy_id,'queue_key':p.queue_key,'acknowledge_due_at':c.acknowledge_due_at.isoformat(),'resolution_due_at':c.resolution_due_at.isoformat(),'reliability_risk_band':rp.risk_band if rp else 'UNKNOWN'},to_queue=p.queue_key,level=0);return c
    def tick(self,limit=100):
        stats={'scanned':0,'escalated':0,'auto_assigned':0,'alerts':0}
        with SessionLocal() as s:
            self.bootstrap(s)
            cases=s.execute(select(JourneyRecoveryOperationalCaseRow).where(JourneyRecoveryOperationalCaseRow.state!='RESOLVED').order_by(JourneyRecoveryOperationalCaseRow.next_escalation_at).limit(limit)).scalars().all()
            for c in cases:
                stats['scanned']+=1;i=s.get(JourneyRecoveryExecutionItemRow,c.execution_item_id);op=s.get(JourneyRecoverySupplierOperationRow,c.supplier_operation_id) if c.supplier_operation_id else None
                self.attach_case(s,c,i,op);p=s.get(JourneyRecoverySlaPolicyRow,c.sla_policy_id);q=s.get(JourneyRecoveryOpsQueueRow,c.queue_key) if c.queue_key else None
                if not c.assigned_to and q and q.on_call_owner:
                    c.assigned_to=q.on_call_owner;c.assigned_at=now();c.state='ASSIGNED';self.event(s,c,'AUTO_ASSIGNED',payload={'owner':q.on_call_owner},to_queue=c.queue_key);stats['auto_assigned']+=1
                steps=p.escalation_steps_json or []
                due=[x for x in steps if int(x.get('level',0))>int(c.current_escalation_level or 0) and utc(c.opened_at)+timedelta(seconds=int(x.get('after_seconds',0)))<=now()]
                if due:
                    step=sorted(due,key=lambda x:int(x.get('level',0)))[-1];old=int(c.current_escalation_level or 0);new=int(step['level']);c.current_escalation_level=new;c.last_escalated_at=now();nxt=[x for x in steps if int(x.get('level',0))>new];c.next_escalation_at=utc(c.opened_at)+timedelta(seconds=int(sorted(nxt,key=lambda x:int(x['level']))[0]['after_seconds'])) if nxt else c.resolution_due_at;c.state='ESCALATED';self.event(s,c,'SLA_ESCALATED',payload={'from_level':old,'to_level':new,'alert':step.get('alert'),'ack_breached':not bool(c.acknowledged_at) and now()>utc(c.acknowledge_due_at),'resolution_breached':now()>utc(c.resolution_due_at)},to_queue=c.queue_key,level=new);self.event(s,c,'ALERT_EMITTED',payload={'channel':'OPS','target':step.get('alert'),'case_id':c.operational_case_id},to_queue=c.queue_key,level=new);stats['escalated']+=1;stats['alerts']+=1
                c.updated_at=now()
            s.commit();return stats
    def transfer(self,case_id,actor_id,queue_key,assignee=None,note=None):
        with SessionLocal() as s:
            self.bootstrap(s);c=s.get(JourneyRecoveryOperationalCaseRow,case_id);q=s.get(JourneyRecoveryOpsQueueRow,queue_key)
            if not c:raise ValueError('RECOVERY_OPERATIONAL_CASE_NOT_FOUND')
            if not q or not q.enabled:raise ValueError('RECOVERY_OPS_QUEUE_NOT_FOUND')
            old=c.queue_key;c.queue_key=queue_key;c.assigned_to=assignee or q.on_call_owner;c.assigned_at=now();c.assignment_note=note;c.state='ASSIGNED';c.updated_at=now();self.event(s,c,'RESPONSIBILITY_TRANSFERRED','GO_ADMIN',actor_id,{'note':note,'assigned_to':c.assigned_to},old,queue_key,c.current_escalation_level);s.commit();return case_id
    def closure_check(self,s,c):
        p=s.get(JourneyRecoverySlaPolicyRow,c.sla_policy_id) if c.sla_policy_id else None;required=(p.required_evidence_kinds_json if p else ['FINAL_EXTERNAL_FACT']) or []
        kinds=set(s.execute(select(JourneyRecoveryEvidenceChainRow.evidence_kind).where(JourneyRecoveryEvidenceChainRow.execution_item_id==c.execution_item_id)).scalars().all());missing=[x for x in required if x not in kinds];return {'satisfied':not missing,'required':required,'present':sorted(kinds),'missing':missing}
    def close(self,case_id,actor_id,note=None):
        with SessionLocal() as s:
            c=s.get(JourneyRecoveryOperationalCaseRow,case_id)
            if not c:raise ValueError('RECOVERY_OPERATIONAL_CASE_NOT_FOUND')
            check=self.closure_check(s,c)
            if not check['satisfied']:c.closure_evidence_status='BLOCKED';c.updated_at=now();s.commit();raise ValueError('RECOVERY_CASE_RESOLUTION_EVIDENCE_REQUIRED:'+','.join(check['missing']))
            c.closure_evidence_status='SATISFIED';c.state='RESOLVED';c.resolved_at=now();c.updated_at=now();self.event(s,c,'CASE_CLOSED','GO_ADMIN',actor_id,{'note':note,'evidence_requirement':check},to_queue=c.queue_key,level=c.current_escalation_level);s.commit();return case_id
    def policies(self):
        with SessionLocal() as s:
            self.bootstrap(s);s.commit();rows=s.execute(select(JourneyRecoverySlaPolicyRow).order_by(JourneyRecoverySlaPolicyRow.severity)).scalars().all();return [{'sla_policy_id':x.sla_policy_id,'name':x.name,'vertical':x.vertical,'adapter_key':x.adapter_key,'severity':x.severity,'queue_key':x.queue_key,'acknowledge_sla_seconds':x.acknowledge_sla_seconds,'resolution_sla_seconds':x.resolution_sla_seconds,'escalation_steps':x.escalation_steps_json,'playbook_key':x.playbook_key,'playbook':x.playbook_json,'required_evidence_kinds':x.required_evidence_kinds_json} for x in rows]
    def queues(self):
        with SessionLocal() as s:
            self.bootstrap(s);s.commit();rows=s.execute(select(JourneyRecoveryOpsQueueRow)).scalars().all();return [{'queue_key':x.queue_key,'name':x.name,'timezone':x.timezone_name,'on_call_owner':x.on_call_owner,'backup_owner':x.backup_owner,'enabled':x.enabled} for x in rows]
recovery_sla_service=RecoverySlaService()
