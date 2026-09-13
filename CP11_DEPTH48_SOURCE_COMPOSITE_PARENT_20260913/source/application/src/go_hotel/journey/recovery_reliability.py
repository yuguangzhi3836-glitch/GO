from __future__ import annotations
from datetime import datetime,timezone
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoverySupplierOperationRow,JourneyRecoveryReconciliationJobRow,JourneyRecoveryReconciliationObservationRow,JourneyRecoveryOperationalCaseRow,JourneyRecoveryExecutionItemRow,JourneyRecoveryReliabilityProfileRow,JourneyRecoveryReliabilityDecisionRow

def now():return datetime.now(timezone.utc)
def utc(v):return v.replace(tzinfo=timezone.utc) if v and v.tzinfo is None else v
def nid(p):return f'{p}_{uuid4().hex[:18]}'
class RecoveryReliabilityService:
    def profile_id(self,vertical,adapter_key):return f'{vertical}:{adapter_key}'
    def rebuild(self):
        with SessionLocal() as s:
            ops=s.execute(select(JourneyRecoverySupplierOperationRow)).scalars().all();groups={}
            for op in ops:groups.setdefault((op.vertical,op.adapter_key),[]).append(op)
            out=[]
            for (vertical,adapter),rows in groups.items():
                jobs=s.execute(select(JourneyRecoveryReconciliationJobRow).where(JourneyRecoveryReconciliationJobRow.supplier_operation_id.in_([x.supplier_operation_id for x in rows]))).scalars().all() if rows else []
                cases=s.execute(select(JourneyRecoveryOperationalCaseRow).where(JourneyRecoveryOperationalCaseRow.supplier_operation_id.in_([x.supplier_operation_id for x in rows]))).scalars().all() if rows else []
                obs=s.execute(select(JourneyRecoveryReconciliationObservationRow).where(JourneyRecoveryReconciliationObservationRow.supplier_operation_id.in_([x.supplier_operation_id for x in rows]))).scalars().all() if rows else []
                n=len(rows);unknown=sum(x.status in {'UNKNOWN','ACCEPTED_ASYNC'} for x in rows);confirmed=sum(x.status=='CONFIRMED' for x in rows);failed=sum(x.status=='FAILED' for x in rows);manual=sum((c.manual_review_reason is not None) for c in cases)
                conf_secs=[(utc(x.completed_at)-utc(x.sent_at)).total_seconds() for x in rows if x.completed_at and x.sent_at and (utc(x.completed_at)-utc(x.sent_at)).total_seconds()>=0]
                poll_attempts=[j.attempt_count for j in jobs]
                wh=[o for o in obs if o.source=='WEBHOOK'];whlags=[]
                opmap={x.supplier_operation_id:x for x in rows}
                for o in wh:
                    op=opmap.get(o.supplier_operation_id)
                    if op and op.sent_at:whlags.append(max(0,(utc(o.created_at)-utc(op.sent_at)).total_seconds()))
                timeout=unknown/n if n else 0;manual_rate=manual/n if n else 0;confirm_rate=confirmed/n if n else 0;confidence=min(1.0,n/20.0)
                score=timeout*0.5+manual_rate*0.35+(1-confirm_rate)*0.15
                band='HIGH' if score>=0.45 else ('MEDIUM' if score>=0.2 else 'LOW')
                init=30 if band=='HIGH' else (15 if band=='MEDIUM' else 5);maxpoll=600 if band=='HIGH' else (300 if band=='MEDIUM' else 120);maxatt=12 if band=='HIGH' else (10 if band=='MEDIUM' else 8);ackm=0.75 if band=='HIGH' else (0.9 if band=='MEDIUM' else 1.0);resm=1.5 if band=='HIGH' else (1.2 if band=='MEDIUM' else 1.0)
                pid=self.profile_id(vertical,adapter);p=s.get(JourneyRecoveryReliabilityProfileRow,pid)
                vals=dict(vertical=vertical,adapter_key=adapter,sample_count=n,async_count=sum(x.status=='ACCEPTED_ASYNC' for x in rows),unknown_count=unknown,confirmed_count=confirmed,failed_count=failed,manual_review_count=manual,avg_confirmation_seconds=(sum(conf_secs)/len(conf_secs) if conf_secs else None),avg_webhook_lag_seconds=(sum(whlags)/len(whlags) if whlags else None),avg_poll_attempts=(sum(poll_attempts)/len(poll_attempts) if poll_attempts else None),timeout_rate=timeout,manual_review_rate=manual_rate,confirmation_rate=confirm_rate,confidence=confidence,risk_band=band,recommended_initial_poll_seconds=init,recommended_max_poll_seconds=maxpoll,recommended_max_attempts=maxatt,recommended_ack_multiplier=ackm,recommended_resolution_multiplier=resm,metrics_json={'score':round(score,4),'observations':len(obs),'jobs':len(jobs)},calculated_at=now())
                if not p:p=JourneyRecoveryReliabilityProfileRow(reliability_profile_id=pid,**vals);s.add(p)
                else:
                    for k,v in vals.items():setattr(p,k,v)
                out.append(pid)
            s.commit();return {'profiles_rebuilt':len(out),'profile_ids':out}
    def get(self,vertical,adapter_key):
        with SessionLocal() as s:return self._serialize(s.get(JourneyRecoveryReliabilityProfileRow,self.profile_id(vertical,adapter_key)))
    def _serialize(self,p):
        if not p:return None
        return {k:getattr(p,k) for k in ['reliability_profile_id','vertical','adapter_key','sample_count','async_count','unknown_count','confirmed_count','failed_count','manual_review_count','avg_confirmation_seconds','avg_webhook_lag_seconds','avg_poll_attempts','timeout_rate','manual_review_rate','confirmation_rate','confidence','risk_band','recommended_initial_poll_seconds','recommended_max_poll_seconds','recommended_max_attempts','recommended_ack_multiplier','recommended_resolution_multiplier']}|{'metrics':p.metrics_json,'calculated_at':p.calculated_at.isoformat()}
    def list(self):
        with SessionLocal() as s:return [self._serialize(x) for x in s.execute(select(JourneyRecoveryReliabilityProfileRow).order_by(JourneyRecoveryReliabilityProfileRow.risk_band,JourneyRecoveryReliabilityProfileRow.adapter_key)).scalars().all()]
    def effective(self,s,vertical,adapter_key):
        p=s.get(JourneyRecoveryReliabilityProfileRow,self.profile_id(vertical,adapter_key));return p
    def record_decision(self,s,item,op,p,kind,params):
        band=p.risk_band if p else 'UNKNOWN';r=JourneyRecoveryReliabilityDecisionRow(reliability_decision_id=nid('jrrd'),execution_item_id=item.execution_item_id,supplier_operation_id=op.supplier_operation_id if op else None,reliability_profile_id=p.reliability_profile_id if p else None,decision_kind=kind,risk_band=band,parameters_json=params,explanation_json={'historical_memory_used':bool(p),'sample_count':p.sample_count if p else 0,'confidence':p.confidence if p else 0.0,'supplier_fact_unchanged':True},created_at=now());s.add(r);return r
recovery_reliability_service=RecoveryReliabilityService()
