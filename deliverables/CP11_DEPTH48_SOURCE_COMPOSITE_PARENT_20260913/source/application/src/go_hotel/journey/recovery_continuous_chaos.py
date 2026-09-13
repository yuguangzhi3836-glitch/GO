from datetime import datetime, timezone, timedelta
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    JourneyRecoveryChaosPolicyRow,JourneyRecoveryChaosScheduleRow,JourneyRecoveryChaosCampaignRow,
    JourneyRecoveryReadinessAssessmentRow,JourneyRecoveryReadinessTrendRow,
    JourneyRecoveryProductionReadinessGateRow,JourneyRecoveryProductionReleaseWaiverRow,
    JourneyRecoveryReleaseGateHistoryRow,
)
from go_hotel.journey.recovery_trust_plane_chaos import recovery_trust_plane_chaos_service as chaos, active_policy_in_session

def now(): return datetime.now(timezone.utc)
def aware(v): return v if v is None or v.tzinfo else v.replace(tzinfo=timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'

class RecoveryContinuousChaosService:
    def create_schedule(self,environment,schedule_key,cadence_seconds,scenarios,actor):
        if cadence_seconds < 60: raise ValueError('CHAOS_SCHEDULE_MINIMUM_CADENCE_60_SECONDS')
        with SessionLocal() as s:
            p=active_policy_in_session(s,environment)
            if not p: raise ValueError('ACTIVE_CHAOS_POLICY_REQUIRED')
            x=JourneyRecoveryChaosScheduleRow(chaos_schedule_id=nid('jrcs'),environment=environment,chaos_policy_id=p.chaos_policy_id,schedule_key=schedule_key,cadence_seconds=cadence_seconds,scenarios_json=scenarios,state='ACTIVE',last_run_at=None,next_run_at=now(),created_by=actor,created_at=now(),supplier_fact_unchanged=True)
            s.add(x);s.commit();return self.schedule(x.chaos_schedule_id)

    def tick(self,environment,actor):
        ran=[]
        with SessionLocal() as s:
            due=s.execute(select(JourneyRecoveryChaosScheduleRow).where(JourneyRecoveryChaosScheduleRow.environment==environment,JourneyRecoveryChaosScheduleRow.state=='ACTIVE',JourneyRecoveryChaosScheduleRow.next_run_at<=now()).order_by(JourneyRecoveryChaosScheduleRow.next_run_at)).scalars().all()
            ids=[x.chaos_schedule_id for x in due]
        for sid in ids:
            with SessionLocal() as s:
                sch=s.get(JourneyRecoveryChaosScheduleRow,sid)
                if not sch or sch.state!='ACTIVE' or aware(sch.next_run_at)>now(): continue
                scenarios=list(sch.scenarios_json or []); key=f'{sch.schedule_key}-{int(now().timestamp())}'
            c=chaos.create_campaign(environment,key,scenarios,actor)
            chaos.run_campaign(c['chaos_campaign_id'],actor,'scheduled-chaos://')
            a=chaos.assess_readiness(c['chaos_campaign_id'],actor)
            g=chaos.evaluate_gate(a['readiness_assessment_id'],f'scheduled-gate://{c["chaos_campaign_id"]}',actor)
            t=self.evaluate_trend(environment,actor)
            with SessionLocal() as s:
                sch=s.get(JourneyRecoveryChaosScheduleRow,sid); sch.last_run_at=now(); sch.next_run_at=now()+timedelta(seconds=sch.cadence_seconds); s.commit()
            ran.append({'schedule_id':sid,'campaign_id':c['chaos_campaign_id'],'assessment_id':a['readiness_assessment_id'],'gate_id':g['production_readiness_gate_id'],'trend_id':t['readiness_trend_id']})
        return {'environment':environment,'ran':ran,'supplier_fact_unchanged':True}

    def evaluate_trend(self,environment,actor):
        with SessionLocal() as s:
            xs=s.execute(select(JourneyRecoveryReadinessAssessmentRow).where(JourneyRecoveryReadinessAssessmentRow.environment==environment).order_by(JourneyRecoveryReadinessAssessmentRow.assessed_at.desc())).scalars().all()
            if not xs: raise ValueError('READINESS_ASSESSMENT_REQUIRED')
            latest=xs[0]; prev=xs[1] if len(xs)>1 else None
            score_delta=round(latest.readiness_score-(prev.readiness_score if prev else latest.readiness_score),2)
            rto_delta=latest.max_observed_rto_seconds-(prev.max_observed_rto_seconds if prev else latest.max_observed_rto_seconds)
            rpo_delta=latest.max_observed_rpo_seconds-(prev.max_observed_rpo_seconds if prev else latest.max_observed_rpo_seconds)
            p=s.get(JourneyRecoveryChaosPolicyRow,latest.chaos_policy_id)
            age=max(0,int((now()-aware(latest.assessed_at)).total_seconds()))
            reasons=[]
            if score_delta < -5: reasons.append('READINESS_SCORE_REGRESSION')
            if rto_delta > max(5,int(p.max_rto_seconds*0.1)): reasons.append('RTO_REGRESSION')
            if rpo_delta > max(1,int(p.max_rpo_seconds*0.1)): reasons.append('RPO_REGRESSION')
            if age > p.evidence_ttl_seconds: reasons.append('READINESS_EVIDENCE_AGED_OUT')
            state='REGRESSED' if reasons else ('IMPROVING' if score_delta>0 or rto_delta<0 or rpo_delta<0 else 'STABLE')
            x=JourneyRecoveryReadinessTrendRow(readiness_trend_id=nid('jrrt'),environment=environment,chaos_policy_id=latest.chaos_policy_id,latest_assessment_id=latest.readiness_assessment_id,previous_assessment_id=prev.readiness_assessment_id if prev else None,score_delta=score_delta,rto_delta_seconds=rto_delta,rpo_delta_seconds=rpo_delta,evidence_age_seconds=age,trend_state=state,reason_codes_json=reasons,evaluated_by=actor,evaluated_at=now(),supplier_fact_unchanged=True)
            s.add(x);s.commit();return self.trend(x.readiness_trend_id)

    def request_waiver(self,environment,reason,risk_summary,evidence_reference,risk_acceptor,starts_at,expires_at,actor,remediation_owner=None,remediation_summary=None):
        st=aware(starts_at); ex=aware(expires_at)
        if not all([reason,risk_summary,evidence_reference,risk_acceptor]): raise ValueError('WAIVER_COMPLETE_RISK_EVIDENCE_REQUIRED')
        if ex<=st or ex<=now(): raise ValueError('INVALID_WAIVER_WINDOW')
        if (ex-st).total_seconds()>86400: raise ValueError('WAIVER_MAX_DURATION_24_HOURS')
        try:
            from go_hotel.journey.recovery_exception_debt_burndown import recovery_exception_debt_burndown_service as burndown
            burndown.pre_request_waiver(environment,actor)
        except ImportError:
            pass
        try:
            from go_hotel.journey.recovery_waiver_exposure_governance import recovery_waiver_exposure_governance_service as exposure
            exposure.pre_request_waiver(environment,remediation_owner,actor)
        except ImportError:
            exposure=None
        with SessionLocal() as s:
            x=JourneyRecoveryProductionReleaseWaiverRow(production_release_waiver_id=nid('jrpw'),environment=environment,reason=reason,risk_summary=risk_summary,evidence_reference=evidence_reference,risk_acceptor=risk_acceptor,requested_by=actor,requested_at=now(),starts_at=st,expires_at=ex,approver_one=None,approver_one_at=None,approver_two=None,approver_two_at=None,state='PENDING_APPROVAL',supplier_fact_unchanged=True)
            s.add(x);s.commit();wid=x.production_release_waiver_id
        if exposure:
            exposure.post_request_waiver(wid,environment,remediation_owner,remediation_summary,actor)
        return self.waiver(wid)

    def approve_waiver(self,waiver_id,actor):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryProductionReleaseWaiverRow,waiver_id)
            if not x: raise ValueError('WAIVER_NOT_FOUND')
            if x.requested_by==actor: raise ValueError('WAIVER_MAKER_CHECKER_REQUIRED')
            if aware(x.expires_at)<=now(): x.state='EXPIRED';s.commit();raise ValueError('WAIVER_EXPIRED')
            if x.approver_one is None:
                x.approver_one=actor;x.approver_one_at=now();x.state='AWAITING_SECOND_APPROVAL'
            elif x.approver_one==actor: raise ValueError('TWO_DISTINCT_WAIVER_APPROVERS_REQUIRED')
            elif x.approver_two is None:
                x.approver_two=actor;x.approver_two_at=now();x.state='APPROVED'
            else: raise ValueError('WAIVER_ALREADY_FULLY_APPROVED')
            s.commit();return self.waiver(waiver_id)

    def active_waiver(self,environment):
        with SessionLocal() as s:
            xs=s.execute(select(JourneyRecoveryProductionReleaseWaiverRow).where(JourneyRecoveryProductionReleaseWaiverRow.environment==environment,JourneyRecoveryProductionReleaseWaiverRow.state.in_(['APPROVED','ACTIVE'])).order_by(JourneyRecoveryProductionReleaseWaiverRow.expires_at.desc())).scalars().all()
            for x in xs:
                if aware(x.expires_at)<=now(): x.state='EXPIRED';continue
                if aware(x.starts_at)<=now() and x.approver_one and x.approver_two:
                    x.state='ACTIVE';s.commit();return self._waiver(x)
            s.commit();return None

    def authorize_release(self,environment,manifest_id,actor):
        with SessionLocal() as s:
            p=active_policy_in_session(s,environment)
            if not p: return {'allowed':True,'reason':'NO_ACTIVE_READINESS_POLICY'}
            g=s.execute(select(JourneyRecoveryProductionReadinessGateRow).where(JourneyRecoveryProductionReadinessGateRow.environment==environment).order_by(JourneyRecoveryProductionReadinessGateRow.evaluated_at.desc())).scalars().first()
            gate_ok=bool(g and g.gate_state=='PASS' and aware(g.valid_until)>=now())
        w=None if gate_ok else self.active_waiver(environment)
        allowed=gate_ok or bool(w); reason='READINESS_GATE_PASS' if gate_ok else ('APPROVED_TIME_BOUND_WAIVER' if w else 'READINESS_GATE_BLOCKED_NO_WAIVER')
        with SessionLocal() as s:
            h=JourneyRecoveryReleaseGateHistoryRow(release_gate_history_id=nid('jrgh'),environment=environment,release_manifest_id=manifest_id,gate_id=g.production_readiness_gate_id if g else None,waiver_id=w['production_release_waiver_id'] if w else None,decision='ALLOW' if allowed else 'BLOCK',decision_reason=reason,evidence_json={'gate_state':g.gate_state if g else None,'gate_valid_until':aware(g.valid_until).isoformat() if g else None,'waiver':w},actor=actor,evaluated_at=now(),supplier_fact_unchanged=True)
            s.add(h);s.commit()
        if allowed and w:
            try:
                from go_hotel.journey.recovery_waiver_exposure_governance import recovery_waiver_exposure_governance_service as exposure
                exposure.record_waiver_release(environment,w['production_release_waiver_id'],manifest_id,actor)
            except ImportError:
                pass
        return {'allowed':allowed,'reason':reason,'waiver':w,'supplier_fact_unchanged':True}

    def status(self,environment):
        with SessionLocal() as s:
            schedules=s.execute(select(JourneyRecoveryChaosScheduleRow).where(JourneyRecoveryChaosScheduleRow.environment==environment).order_by(JourneyRecoveryChaosScheduleRow.created_at.desc())).scalars().all()
            trends=s.execute(select(JourneyRecoveryReadinessTrendRow).where(JourneyRecoveryReadinessTrendRow.environment==environment).order_by(JourneyRecoveryReadinessTrendRow.evaluated_at.desc())).scalars().all()
            waivers=s.execute(select(JourneyRecoveryProductionReleaseWaiverRow).where(JourneyRecoveryProductionReleaseWaiverRow.environment==environment).order_by(JourneyRecoveryProductionReleaseWaiverRow.requested_at.desc())).scalars().all()
            hist=s.execute(select(JourneyRecoveryReleaseGateHistoryRow).where(JourneyRecoveryReleaseGateHistoryRow.environment==environment).order_by(JourneyRecoveryReleaseGateHistoryRow.evaluated_at.desc())).scalars().all()
            return {'environment':environment,'schedules':[self._schedule(x) for x in schedules[:20]],'trends':[self._trend(x) for x in trends[:20]],'waivers':[self._waiver(x) for x in waivers[:20]],'gate_history':[{'release_gate_history_id':x.release_gate_history_id,'release_manifest_id':x.release_manifest_id,'decision':x.decision,'decision_reason':x.decision_reason,'gate_id':x.gate_id,'waiver_id':x.waiver_id,'evaluated_at':x.evaluated_at.isoformat()} for x in hist[:50]],'active_waiver':self.active_waiver(environment),'supplier_fact_unchanged':True}

    def schedule(self,i):
        with SessionLocal() as s:return self._schedule(s.get(JourneyRecoveryChaosScheduleRow,i))
    def trend(self,i):
        with SessionLocal() as s:return self._trend(s.get(JourneyRecoveryReadinessTrendRow,i))
    def waiver(self,i):
        with SessionLocal() as s:return self._waiver(s.get(JourneyRecoveryProductionReleaseWaiverRow,i))
    def _schedule(self,x): return {'chaos_schedule_id':x.chaos_schedule_id,'environment':x.environment,'chaos_policy_id':x.chaos_policy_id,'schedule_key':x.schedule_key,'cadence_seconds':x.cadence_seconds,'scenarios':x.scenarios_json,'state':x.state,'last_run_at':x.last_run_at.isoformat() if x.last_run_at else None,'next_run_at':x.next_run_at.isoformat(),'supplier_fact_unchanged':True}
    def _trend(self,x): return {'readiness_trend_id':x.readiness_trend_id,'environment':x.environment,'latest_assessment_id':x.latest_assessment_id,'previous_assessment_id':x.previous_assessment_id,'score_delta':x.score_delta,'rto_delta_seconds':x.rto_delta_seconds,'rpo_delta_seconds':x.rpo_delta_seconds,'evidence_age_seconds':x.evidence_age_seconds,'trend_state':x.trend_state,'reason_codes':x.reason_codes_json,'evaluated_at':x.evaluated_at.isoformat(),'supplier_fact_unchanged':True}
    def _waiver(self,x): return {'production_release_waiver_id':x.production_release_waiver_id,'environment':x.environment,'reason':x.reason,'risk_summary':x.risk_summary,'evidence_reference':x.evidence_reference,'risk_acceptor':x.risk_acceptor,'requested_by':x.requested_by,'starts_at':x.starts_at.isoformat(),'expires_at':x.expires_at.isoformat(),'approver_one':x.approver_one,'approver_two':x.approver_two,'state':x.state,'supplier_fact_unchanged':True}

recovery_continuous_chaos_service=RecoveryContinuousChaosService()
