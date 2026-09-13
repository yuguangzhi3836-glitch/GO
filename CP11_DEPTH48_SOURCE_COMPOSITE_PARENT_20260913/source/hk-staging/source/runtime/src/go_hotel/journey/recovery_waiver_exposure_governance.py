from datetime import datetime, timezone, timedelta
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    JourneyRecoveryWaiverExposurePolicyRow,JourneyRecoveryExceptionDebtRow,
    JourneyRecoveryWaiverRemediationRow,JourneyRecoveryWaiverExposureEventRow,
    JourneyRecoveryProductionReleaseWaiverRow,JourneyRecoveryReleaseGateHistoryRow,
)

def now(): return datetime.now(timezone.utc)
def aware(v): return v if v is None or v.tzinfo else v.replace(tzinfo=timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'

class RecoveryWaiverExposureGovernanceService:
    def active_policy_in_session(self,s,environment):
        return s.execute(select(JourneyRecoveryWaiverExposurePolicyRow).where(JourneyRecoveryWaiverExposurePolicyRow.environment==environment,JourneyRecoveryWaiverExposurePolicyRow.state=='ACTIVE').order_by(JourneyRecoveryWaiverExposurePolicyRow.version_no.desc())).scalars().first()

    def create_policy(self,policy_key,environment,rolling_window_hours,max_waiver_count,max_consecutive_waiver_releases,max_exposure_seconds,max_exception_debt_points,remediation_sla_seconds,escalation_after_seconds,actor):
        vals=[rolling_window_hours,max_waiver_count,max_consecutive_waiver_releases,max_exposure_seconds,remediation_sla_seconds,escalation_after_seconds]
        if any(int(v)<=0 for v in vals) or max_exception_debt_points<=0: raise ValueError('INVALID_WAIVER_EXPOSURE_POLICY')
        with SessionLocal() as s:
            prev=s.execute(select(JourneyRecoveryWaiverExposurePolicyRow).where(JourneyRecoveryWaiverExposurePolicyRow.policy_key==policy_key,JourneyRecoveryWaiverExposurePolicyRow.environment==environment).order_by(JourneyRecoveryWaiverExposurePolicyRow.version_no.desc())).scalars().first()
            for p in s.execute(select(JourneyRecoveryWaiverExposurePolicyRow).where(JourneyRecoveryWaiverExposurePolicyRow.environment==environment,JourneyRecoveryWaiverExposurePolicyRow.state=='ACTIVE')).scalars().all(): p.state='SUPERSEDED'
            x=JourneyRecoveryWaiverExposurePolicyRow(waiver_exposure_policy_id=nid('jrwep'),policy_key=policy_key,version_no=(prev.version_no+1 if prev else 1),environment=environment,rolling_window_hours=rolling_window_hours,max_waiver_count=max_waiver_count,max_consecutive_waiver_releases=max_consecutive_waiver_releases,max_exposure_seconds=max_exposure_seconds,max_exception_debt_points=max_exception_debt_points,remediation_sla_seconds=remediation_sla_seconds,escalation_after_seconds=escalation_after_seconds,state='ACTIVE',created_by=actor,created_at=now(),supplier_fact_unchanged=True)
            s.add(x);s.commit();return self.policy(x.waiver_exposure_policy_id)

    def _metrics(self,s,p):
        t=now();ws=t-timedelta(hours=p.rolling_window_hours)
        waivers=s.execute(select(JourneyRecoveryProductionReleaseWaiverRow).where(JourneyRecoveryProductionReleaseWaiverRow.environment==p.environment,JourneyRecoveryProductionReleaseWaiverRow.requested_at>=ws).order_by(JourneyRecoveryProductionReleaseWaiverRow.requested_at)).scalars().all()
        exposure=0
        for w in waivers:
            if not w.approver_two: continue
            start=max(aware(w.starts_at),ws); end=min(aware(w.expires_at),t)
            if end>start: exposure+=int((end-start).total_seconds())
        hist=s.execute(select(JourneyRecoveryReleaseGateHistoryRow).where(JourneyRecoveryReleaseGateHistoryRow.environment==p.environment,JourneyRecoveryReleaseGateHistoryRow.evaluated_at>=ws,JourneyRecoveryReleaseGateHistoryRow.decision=='ALLOW').order_by(JourneyRecoveryReleaseGateHistoryRow.evaluated_at.desc())).scalars().all()
        consecutive=0
        for h in hist:
            if h.decision_reason=='APPROVED_TIME_BOUND_WAIVER': consecutive+=1
            else: break
        rem=s.execute(select(JourneyRecoveryWaiverRemediationRow).where(JourneyRecoveryWaiverRemediationRow.environment==p.environment,JourneyRecoveryWaiverRemediationRow.state.notin_(['RESOLVED']))).scalars().all()
        overdue=sum(1 for r in rem if aware(r.due_at)<t)
        return ws,len(waivers),consecutive,exposure,len(rem),overdue

    def evaluate_debt(self,environment,actor='system'):
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment)
            if not p: return {'environment':environment,'policy_active':False,'debt_state':'NOT_GOVERNED','supplier_fact_unchanged':True}
            ws,count,consecutive,exposure,open_rem,overdue=self._metrics(s,p)
            points=round((count/max(1,p.max_waiver_count))*25+(consecutive/max(1,p.max_consecutive_waiver_releases))*25+(exposure/max(1,p.max_exposure_seconds))*30+overdue*20,2)
            reasons=[]
            if count>=p.max_waiver_count: reasons.append('ROLLING_WAIVER_BUDGET_EXHAUSTED')
            if consecutive>=p.max_consecutive_waiver_releases: reasons.append('CONSECUTIVE_WAIVER_LIMIT_REACHED')
            if exposure>=p.max_exposure_seconds: reasons.append('RISK_EXPOSURE_TIME_BUDGET_EXHAUSTED')
            if points>=p.max_exception_debt_points: reasons.append('EXCEPTION_DEBT_THRESHOLD_EXCEEDED')
            if overdue: reasons.append('REMEDIATION_SLA_OVERDUE')
            hard={'ROLLING_WAIVER_BUDGET_EXHAUSTED','CONSECUTIVE_WAIVER_LIMIT_REACHED','RISK_EXPOSURE_TIME_BUDGET_EXHAUSTED','EXCEPTION_DEBT_THRESHOLD_EXCEEDED'}
            state='BLOCKED' if any(x in hard for x in reasons) else ('WATCH' if reasons or points>=p.max_exception_debt_points*0.7 else 'HEALTHY')
            x=JourneyRecoveryExceptionDebtRow(exception_debt_id=nid('jred'),environment=environment,waiver_exposure_policy_id=p.waiver_exposure_policy_id,rolling_window_start=ws,rolling_waiver_count=count,consecutive_waiver_releases=consecutive,exposure_seconds=exposure,open_remediation_count=open_rem,overdue_remediation_count=overdue,debt_points=points,debt_state=state,reason_codes_json=reasons,evaluated_by=actor,evaluated_at=now(),supplier_fact_unchanged=True)
            s.add(x);s.commit();return self.debt(x.exception_debt_id)

    def pre_request_waiver(self,environment,remediation_owner,actor):
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment)
            if not p:return None
            if not remediation_owner: raise ValueError('REMEDIATION_OWNER_REQUIRED_BY_WAIVER_EXPOSURE_POLICY')
        d=self.evaluate_debt(environment,actor)
        if d['debt_state']=='BLOCKED': raise ValueError('NEW_PRODUCTION_WAIVER_BLOCKED_BY_EXCEPTION_DEBT:'+','.join(d['reason_codes']))
        return d

    def post_request_waiver(self,waiver_id,environment,remediation_owner,remediation_summary,actor):
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment)
            if not p:return None
            w=s.get(JourneyRecoveryProductionReleaseWaiverRow,waiver_id)
            if not w: raise ValueError('WAIVER_NOT_FOUND')
            opened=now()
            r=JourneyRecoveryWaiverRemediationRow(waiver_remediation_id=nid('jrwr'),environment=environment,waiver_id=waiver_id,remediation_owner=remediation_owner,remediation_summary=remediation_summary or w.risk_summary,opened_at=opened,due_at=opened+timedelta(seconds=p.remediation_sla_seconds),acknowledged_at=None,resolved_at=None,resolution_evidence_reference=None,escalation_level=0,last_escalated_at=None,state='OPEN',supplier_fact_unchanged=True)
            s.add(r);self._event(s,environment,waiver_id,r.waiver_remediation_id,'WAIVER_REMEDIATION_OPENED',actor,{'owner':remediation_owner,'due_at':r.due_at.isoformat()});s.commit();return self.remediation(r.waiver_remediation_id)

    def record_waiver_release(self,environment,waiver_id,manifest_id,actor):
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment)
            if not p:return None
            self._event(s,environment,waiver_id,None,'WAIVER_RELEASE_AUTHORIZED',actor,{'release_manifest_id':manifest_id});s.commit()
        return self.evaluate_debt(environment,actor)

    def remediation_tick(self,environment,actor):
        escalated=[];t=now()
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment)
            if not p:return {'environment':environment,'escalated':[],'supplier_fact_unchanged':True}
            rows=s.execute(select(JourneyRecoveryWaiverRemediationRow).where(JourneyRecoveryWaiverRemediationRow.environment==environment,JourneyRecoveryWaiverRemediationRow.state.in_(['OPEN','ACKNOWLEDGED','OVERDUE','ESCALATED']))).scalars().all()
            for r in rows:
                due=aware(r.due_at)
                if due<t:
                    since=max(due,aware(r.last_escalated_at) if r.last_escalated_at else due)
                    if r.state not in {'OVERDUE','ESCALATED'}: r.state='OVERDUE'
                    if (t-since).total_seconds()>=p.escalation_after_seconds:
                        r.escalation_level+=1;r.last_escalated_at=t;r.state='ESCALATED';self._event(s,environment,r.waiver_id,r.waiver_remediation_id,'REMEDIATION_SLA_ESCALATED',actor,{'level':r.escalation_level,'owner':r.remediation_owner,'due_at':r.due_at.isoformat()});escalated.append(r.waiver_remediation_id)
            s.commit()
        self.evaluate_debt(environment,actor)
        return {'environment':environment,'escalated':escalated,'supplier_fact_unchanged':True}

    def acknowledge_remediation(self,remediation_id,actor):
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryWaiverRemediationRow,remediation_id)
            if not r:raise ValueError('WAIVER_REMEDIATION_NOT_FOUND')
            if r.state=='RESOLVED':raise ValueError('WAIVER_REMEDIATION_ALREADY_RESOLVED')
            r.acknowledged_at=now();r.state='ACKNOWLEDGED';self._event(s,r.environment,r.waiver_id,r.waiver_remediation_id,'REMEDIATION_ACKNOWLEDGED',actor,{});s.commit();return self.remediation(remediation_id)

    def resolve_remediation(self,remediation_id,evidence_reference,actor):
        if not evidence_reference:raise ValueError('REMEDIATION_RESOLUTION_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryWaiverRemediationRow,remediation_id)
            if not r:raise ValueError('WAIVER_REMEDIATION_NOT_FOUND')
            r.resolved_at=now();r.resolution_evidence_reference=evidence_reference;r.state='RESOLVED';self._event(s,r.environment,r.waiver_id,r.waiver_remediation_id,'REMEDIATION_RESOLVED',actor,{'evidence_reference':evidence_reference});env=r.environment;s.commit()
        self.evaluate_debt(env,actor);return self.remediation(remediation_id)

    def status(self,environment):
        d=self.evaluate_debt(environment,'status')
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment)
            rs=s.execute(select(JourneyRecoveryWaiverRemediationRow).where(JourneyRecoveryWaiverRemediationRow.environment==environment).order_by(JourneyRecoveryWaiverRemediationRow.opened_at.desc())).scalars().all()
            ev=s.execute(select(JourneyRecoveryWaiverExposureEventRow).where(JourneyRecoveryWaiverExposureEventRow.environment==environment).order_by(JourneyRecoveryWaiverExposureEventRow.created_at.desc())).scalars().all()
            return {'environment':environment,'policy':self._policy(p) if p else None,'exception_debt':d,'remediations':[self._remediation(x) for x in rs[:30]],'events':[{'event_id':x.waiver_exposure_event_id,'event_type':x.event_type,'waiver_id':x.waiver_id,'remediation_id':x.remediation_id,'evidence':x.evidence_json,'created_at':x.created_at.isoformat()} for x in ev[:50]],'supplier_fact_unchanged':True}

    def _event(self,s,environment,waiver_id,remediation_id,event_type,actor,evidence):
        s.add(JourneyRecoveryWaiverExposureEventRow(waiver_exposure_event_id=nid('jrwee'),environment=environment,waiver_id=waiver_id,remediation_id=remediation_id,event_type=event_type,evidence_json=evidence or {},actor=actor,created_at=now(),supplier_fact_unchanged=True))
    def policy(self,i):
        with SessionLocal() as s:return self._policy(s.get(JourneyRecoveryWaiverExposurePolicyRow,i))
    def debt(self,i):
        with SessionLocal() as s:return self._debt(s.get(JourneyRecoveryExceptionDebtRow,i))
    def remediation(self,i):
        with SessionLocal() as s:return self._remediation(s.get(JourneyRecoveryWaiverRemediationRow,i))
    def _policy(self,x): return {'waiver_exposure_policy_id':x.waiver_exposure_policy_id,'policy_key':x.policy_key,'version_no':x.version_no,'environment':x.environment,'rolling_window_hours':x.rolling_window_hours,'max_waiver_count':x.max_waiver_count,'max_consecutive_waiver_releases':x.max_consecutive_waiver_releases,'max_exposure_seconds':x.max_exposure_seconds,'max_exception_debt_points':x.max_exception_debt_points,'remediation_sla_seconds':x.remediation_sla_seconds,'escalation_after_seconds':x.escalation_after_seconds,'state':x.state,'supplier_fact_unchanged':True}
    def _debt(self,x): return {'exception_debt_id':x.exception_debt_id,'environment':x.environment,'rolling_window_start':x.rolling_window_start.isoformat(),'rolling_waiver_count':x.rolling_waiver_count,'consecutive_waiver_releases':x.consecutive_waiver_releases,'exposure_seconds':x.exposure_seconds,'open_remediation_count':x.open_remediation_count,'overdue_remediation_count':x.overdue_remediation_count,'debt_points':x.debt_points,'debt_state':x.debt_state,'reason_codes':x.reason_codes_json,'evaluated_at':x.evaluated_at.isoformat(),'supplier_fact_unchanged':True}
    def _remediation(self,x): return {'waiver_remediation_id':x.waiver_remediation_id,'environment':x.environment,'waiver_id':x.waiver_id,'remediation_owner':x.remediation_owner,'remediation_summary':x.remediation_summary,'opened_at':x.opened_at.isoformat(),'due_at':x.due_at.isoformat(),'acknowledged_at':x.acknowledged_at.isoformat() if x.acknowledged_at else None,'resolved_at':x.resolved_at.isoformat() if x.resolved_at else None,'resolution_evidence_reference':x.resolution_evidence_reference,'escalation_level':x.escalation_level,'last_escalated_at':x.last_escalated_at.isoformat() if x.last_escalated_at else None,'state':x.state,'supplier_fact_unchanged':True}

recovery_waiver_exposure_governance_service=RecoveryWaiverExposureGovernanceService()
