from datetime import datetime, timezone
from uuid import uuid4
from math import log
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import *

def now(): return datetime.now(timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'
def _psi(expected, actual):
    eps=1e-6; e=max(eps,min(1-eps,expected)); a=max(eps,min(1-eps,actual)); return (a-e)*log(a/e)

class RecoveryForecastDriftGovernanceService:
    def active_policy_in_session(self,s,environment):
        return s.execute(select(JourneyRecoveryForecastDriftPolicyRow).where(JourneyRecoveryForecastDriftPolicyRow.environment==environment,JourneyRecoveryForecastDriftPolicyRow.state=='ACTIVE').order_by(JourneyRecoveryForecastDriftPolicyRow.version_no.desc())).scalars().first()
    def create_policy(self,environment,minimum_sample_count=20,max_population_psi=.25,max_segment_psi=.3,max_residual_drift_pct=20,consecutive_breaches_required=2,baseline_window_key='BASELINE_30D',comparison_window_key='ROLLING_7D',actor='model-risk-governance'):
        if minimum_sample_count<2 or min(max_population_psi,max_segment_psi,max_residual_drift_pct)<0 or consecutive_breaches_required<1: raise ValueError('INVALID_FORECAST_DRIFT_POLICY')
        with SessionLocal() as s:
            prev=s.execute(select(JourneyRecoveryForecastDriftPolicyRow).where(JourneyRecoveryForecastDriftPolicyRow.environment==environment).order_by(JourneyRecoveryForecastDriftPolicyRow.version_no.desc())).scalars().first()
            x=JourneyRecoveryForecastDriftPolicyRow(forecast_drift_policy_id=nid('jfdp'),environment=environment,version_no=(prev.version_no+1 if prev else 1),minimum_sample_count=minimum_sample_count,max_population_psi=max_population_psi,max_segment_psi=max_segment_psi,max_residual_drift_pct=max_residual_drift_pct,consecutive_breaches_required=consecutive_breaches_required,baseline_window_key=baseline_window_key,comparison_window_key=comparison_window_key,requested_by=actor,approver_one=None,approver_two=None,state='PENDING_APPROVAL',created_at=now(),supplier_fact_unchanged=True);s.add(x);s.commit();return self.policy(x.forecast_drift_policy_id)
    def approve_policy(self,i,actor):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryForecastDriftPolicyRow,i)
            if not x: raise ValueError('FORECAST_DRIFT_POLICY_NOT_FOUND')
            if actor==x.requested_by: raise ValueError('FORECAST_DRIFT_MAKER_CHECKER_REQUIRED')
            if not x.approver_one: x.approver_one=actor;x.state='AWAITING_SECOND_APPROVAL'
            elif x.approver_one==actor: raise ValueError('TWO_DISTINCT_DRIFT_APPROVERS_REQUIRED')
            elif not x.approver_two:
                x.approver_two=actor
                for y in s.execute(select(JourneyRecoveryForecastDriftPolicyRow).where(JourneyRecoveryForecastDriftPolicyRow.environment==x.environment,JourneyRecoveryForecastDriftPolicyRow.state=='ACTIVE')).scalars().all(): y.state='SUPERSEDED'
                x.state='ACTIVE'
            s.commit();return self.policy(i)
    def assess(self,environment,horizon_hours,baseline_breach_rate,current_breach_rate,segment_baseline=None,segment_current=None,actor='forecast-drift-engine'):
        if horizon_hours not in (24,168): raise ValueError('UNSUPPORTED_FORECAST_HORIZON')
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment)
            if not p: raise ValueError('ACTIVE_FORECAST_DRIFT_POLICY_REQUIRED')
            role=s.execute(select(JourneyRecoveryForecastModelRoleRow).where(JourneyRecoveryForecastModelRoleRow.environment==environment,JourneyRecoveryForecastModelRoleRow.role=='CHAMPION',JourneyRecoveryForecastModelRoleRow.state=='ACTIVE').order_by(JourneyRecoveryForecastModelRoleRow.assigned_at.desc())).scalars().first()
            if not role: raise ValueError('ACTIVE_CHAMPION_REQUIRED')
            outs=s.execute(select(JourneyRecoveryRiskForecastOutcomeRow).where(JourneyRecoveryRiskForecastOutcomeRow.environment==environment,JourneyRecoveryRiskForecastOutcomeRow.risk_forecast_model_version_id==role.model_version_id,JourneyRecoveryRiskForecastOutcomeRow.horizon_hours==horizon_hours)).scalars().all()
            n=len(outs); pop=abs(_psi(float(baseline_breach_rate),float(current_breach_rate)))
            sb=segment_baseline or {}; sc=segment_current or {}; seg={k:abs(_psi(float(sb.get(k,.5)),float(sc.get(k,.5)))) for k in set(sb)|set(sc)}; maxseg=max(seg.values()) if seg else 0
            split=max(1,n//2); old=outs[:split]; recent=outs[split:] if n>split else outs[-1:]
            rnew=sum(x.absolute_error_points for x in recent)/len(recent) if recent else 0; rold=sum(x.absolute_error_points for x in old)/len(old) if old else (rnew or 1); residual=max(0,(rnew-rold)/max(rold,.0001)*100)
            reasons=[]
            if n<p.minimum_sample_count: reasons.append('MINIMUM_DRIFT_SAMPLE_NOT_MET')
            if n>=p.minimum_sample_count:
                if pop>p.max_population_psi: reasons.append('POPULATION_STABILITY_INDEX_BREACH')
                if maxseg>p.max_segment_psi: reasons.append('SEGMENT_DRIFT_BREACH')
                if residual>p.max_residual_drift_pct: reasons.append('FORECAST_RESIDUAL_DRIFT_BREACH')
            state='INSUFFICIENT_DATA' if n<p.minimum_sample_count else ('DRIFTED' if reasons else 'STABLE')
            a=JourneyRecoveryForecastDriftAssessmentRow(forecast_drift_assessment_id=nid('jfda'),environment=environment,policy_id=p.forecast_drift_policy_id,champion_model_version_id=role.model_version_id,horizon_hours=horizon_hours,sample_count=n,population_psi=round(pop,6),max_segment_psi=round(maxseg,6),residual_drift_pct=round(residual,4),drift_state=state,segment_metrics_json=seg,reason_codes_json=reasons,evaluated_at=now(),supplier_fact_unchanged=True);s.add(a);s.flush();self._event(s,environment,'DRIFT_ASSESSED',actor,{'state':state,'reason_codes':reasons},a.forecast_drift_assessment_id,None,None)
            s.commit();return self.assessment(a.forecast_drift_assessment_id)
    def request_refresh(self,assessment_id,evidence,actor='model-refresh-orchestrator'):
        if not evidence: raise ValueError('DRIFT_REFRESH_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            a=s.get(JourneyRecoveryForecastDriftAssessmentRow,assessment_id)
            if not a or a.drift_state!='DRIFTED': raise ValueError('DRIFTED_ASSESSMENT_REQUIRED')
            p=s.get(JourneyRecoveryForecastDriftPolicyRow,a.policy_id)
            recent=s.execute(select(JourneyRecoveryForecastDriftAssessmentRow).where(JourneyRecoveryForecastDriftAssessmentRow.environment==a.environment,JourneyRecoveryForecastDriftAssessmentRow.champion_model_version_id==a.champion_model_version_id,JourneyRecoveryForecastDriftAssessmentRow.drift_state=='DRIFTED').order_by(JourneyRecoveryForecastDriftAssessmentRow.evaluated_at.desc()).limit(p.consecutive_breaches_required)).scalars().all()
            if len(recent)<p.consecutive_breaches_required: raise ValueError('CONSECUTIVE_DRIFT_BREACHES_REQUIRED')
            m=s.get(JourneyRecoveryRiskForecastModelVersionRow,a.champion_model_version_id)
            r=JourneyRecoveryForecastRetrainingRequestRow(forecast_retraining_request_id=nid('jfrr'),environment=a.environment,source_drift_assessment_id=a.forecast_drift_assessment_id,champion_model_version_id=a.champion_model_version_id,requested_model_key=m.model_key,refresh_reason_codes_json=a.reason_codes_json,state='APPROVED_FOR_REFRESH',requested_at=now(),requested_by=actor,evidence_json=evidence,supplier_fact_unchanged=True);s.add(r);s.flush()
            pipe=JourneyRecoveryForecastRefreshPipelineRow(forecast_refresh_pipeline_id=nid('jfrp'),environment=a.environment,retraining_request_id=r.forecast_retraining_request_id,source_champion_model_version_id=m.risk_forecast_model_version_id,challenger_model_version_id=None,pipeline_state='REFRESH_REQUESTED',governance_next_step='GENERATE_CHALLENGER',created_at=now(),updated_at=now(),supplier_fact_unchanged=True);s.add(pipe);self._event(s,a.environment,'RETRAINING_REQUEST_CREATED',actor,evidence,a.forecast_drift_assessment_id,r.forecast_retraining_request_id,None);s.commit();return self.retraining(r.forecast_retraining_request_id)
    def generate_challenger(self,retraining_request_id,parameters=None,actor='model-refresh-orchestrator'):
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryForecastRetrainingRequestRow,retraining_request_id)
            if not r or r.state!='APPROVED_FOR_REFRESH': raise ValueError('APPROVED_RETRAINING_REQUEST_REQUIRED')
            champ=s.get(JourneyRecoveryRiskForecastModelVersionRow,r.champion_model_version_id)
            prev=s.execute(select(JourneyRecoveryRiskForecastModelVersionRow).where(JourneyRecoveryRiskForecastModelVersionRow.model_key==champ.model_key,JourneyRecoveryRiskForecastModelVersionRow.environment==r.environment).order_by(JourneyRecoveryRiskForecastModelVersionRow.version_no.desc())).scalars().first()
            m=JourneyRecoveryRiskForecastModelVersionRow(risk_forecast_model_version_id=nid('jrfm'),model_key=champ.model_key,version_no=(prev.version_no+1 if prev else champ.version_no+1),environment=r.environment,algorithm_key=champ.algorithm_key,parameters_json=parameters or dict(champ.parameters_json or {}),conservative_parameters_json=dict(champ.conservative_parameters_json or {}),minimum_samples=champ.minimum_samples,max_mae_points=champ.max_mae_points,max_brier_score=champ.max_brier_score,max_false_positive_rate=champ.max_false_positive_rate,max_false_negative_rate=champ.max_false_negative_rate,max_capacity_drift_pct=champ.max_capacity_drift_pct,requested_by=actor,board_approver_one=None,board_approver_two=None,state='PENDING_APPROVAL',created_at=now(),supplier_fact_unchanged=True);s.add(m);s.flush()
            s.add(JourneyRecoveryForecastModelRoleRow(forecast_model_role_id=nid('jfmr'),environment=r.environment,model_version_id=m.risk_forecast_model_version_id,role='CHALLENGER',state='ACTIVE',assigned_at=now(),supplier_fact_unchanged=True))
            pipe=s.execute(select(JourneyRecoveryForecastRefreshPipelineRow).where(JourneyRecoveryForecastRefreshPipelineRow.retraining_request_id==r.forecast_retraining_request_id)).scalars().first();pipe.challenger_model_version_id=m.risk_forecast_model_version_id;pipe.pipeline_state='CHALLENGER_GENERATED';pipe.governance_next_step='MODEL_APPROVAL_BACKTEST_SHADOW_4L_4M';pipe.updated_at=now();r.state='CHALLENGER_GENERATED';self._event(s,r.environment,'CHALLENGER_AUTO_GENERATED',actor,{'next_step':pipe.governance_next_step},r.source_drift_assessment_id,r.forecast_retraining_request_id,m.risk_forecast_model_version_id);s.commit();return {'challenger_model_version_id':m.risk_forecast_model_version_id,'state':m.state,'role':'CHALLENGER','governance_next_step':pipe.governance_next_step,'supplier_fact_unchanged':True}
    def status(self,environment):
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment);ass=s.execute(select(JourneyRecoveryForecastDriftAssessmentRow).where(JourneyRecoveryForecastDriftAssessmentRow.environment==environment).order_by(JourneyRecoveryForecastDriftAssessmentRow.evaluated_at.desc()).limit(20)).scalars().all();rr=s.execute(select(JourneyRecoveryForecastRetrainingRequestRow).where(JourneyRecoveryForecastRetrainingRequestRow.environment==environment).order_by(JourneyRecoveryForecastRetrainingRequestRow.requested_at.desc()).limit(20)).scalars().all();pipes=s.execute(select(JourneyRecoveryForecastRefreshPipelineRow).where(JourneyRecoveryForecastRefreshPipelineRow.environment==environment).order_by(JourneyRecoveryForecastRefreshPipelineRow.created_at.desc()).limit(20)).scalars().all();return {'active_policy':self._policy(p) if p else None,'drift_assessments':[self._assessment(x) for x in ass],'retraining_requests':[self._retraining(x) for x in rr],'refresh_pipelines':[{'forecast_refresh_pipeline_id':x.forecast_refresh_pipeline_id,'pipeline_state':x.pipeline_state,'challenger_model_version_id':x.challenger_model_version_id,'governance_next_step':x.governance_next_step,'supplier_fact_unchanged':True} for x in pipes]}
    def _event(self,s,e,t,actor,evidence,a=None,r=None,c=None): s.add(JourneyRecoveryForecastDriftEventRow(forecast_drift_event_id=nid('jfde'),environment=e,event_type=t,drift_assessment_id=a,retraining_request_id=r,challenger_model_version_id=c,evidence_json=evidence or {},actor=actor,created_at=now(),supplier_fact_unchanged=True))
    def policy(self,i):
        with SessionLocal() as s:return self._policy(s.get(JourneyRecoveryForecastDriftPolicyRow,i))
    def assessment(self,i):
        with SessionLocal() as s:return self._assessment(s.get(JourneyRecoveryForecastDriftAssessmentRow,i))
    def retraining(self,i):
        with SessionLocal() as s:return self._retraining(s.get(JourneyRecoveryForecastRetrainingRequestRow,i))
    def _policy(self,x): return {'forecast_drift_policy_id':x.forecast_drift_policy_id,'environment':x.environment,'version_no':x.version_no,'minimum_sample_count':x.minimum_sample_count,'max_population_psi':x.max_population_psi,'max_segment_psi':x.max_segment_psi,'max_residual_drift_pct':x.max_residual_drift_pct,'consecutive_breaches_required':x.consecutive_breaches_required,'state':x.state,'supplier_fact_unchanged':True}
    def _assessment(self,x): return {'forecast_drift_assessment_id':x.forecast_drift_assessment_id,'horizon_hours':x.horizon_hours,'sample_count':x.sample_count,'population_psi':x.population_psi,'max_segment_psi':x.max_segment_psi,'residual_drift_pct':x.residual_drift_pct,'drift_state':x.drift_state,'reason_codes':x.reason_codes_json,'supplier_fact_unchanged':True}
    def _retraining(self,x): return {'forecast_retraining_request_id':x.forecast_retraining_request_id,'state':x.state,'champion_model_version_id':x.champion_model_version_id,'refresh_reason_codes':x.refresh_reason_codes_json,'supplier_fact_unchanged':True}

recovery_forecast_drift_governance_service=RecoveryForecastDriftGovernanceService()
