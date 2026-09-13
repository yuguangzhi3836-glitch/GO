from datetime import datetime,timezone
from uuid import uuid4
from math import sqrt
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import *
def now():return datetime.now(timezone.utc)
def nid(p):return f'{p}_{uuid4().hex[:20]}'
class RecoveryForecastOnlineSegmentGovernanceService:
 def create_policy(self,environment='PROD',minimum_segment_samples=5,max_segment_mae=15,max_segment_rmse=20,max_segment_brier=.25,consecutive_breaches_required=2,actor='model-risk-governance'):
  if minimum_segment_samples<2 or consecutive_breaches_required<1:raise ValueError('INVALID_ONLINE_SEGMENT_POLICY')
  with SessionLocal() as s:
   prev=s.execute(select(JourneyRecoveryForecastOnlineSegmentPolicyRow).where(JourneyRecoveryForecastOnlineSegmentPolicyRow.environment==environment).order_by(JourneyRecoveryForecastOnlineSegmentPolicyRow.version_no.desc())).scalars().first()
   x=JourneyRecoveryForecastOnlineSegmentPolicyRow(forecast_online_segment_policy_id=nid('jfosp'),environment=environment,version_no=(prev.version_no+1 if prev else 1),minimum_segment_samples=minimum_segment_samples,max_segment_mae=max_segment_mae,max_segment_rmse=max_segment_rmse,max_segment_brier=max_segment_brier,consecutive_breaches_required=consecutive_breaches_required,requested_by=actor,approver_one=None,approver_two=None,state='PENDING_APPROVAL',created_at=now(),supplier_fact_unchanged=True);s.add(x);s.commit();return self.policy(x.forecast_online_segment_policy_id)
 def approve_policy(self,i,actor):
  with SessionLocal() as s:
   x=s.get(JourneyRecoveryForecastOnlineSegmentPolicyRow,i)
   if not x:raise ValueError('ONLINE_SEGMENT_POLICY_NOT_FOUND')
   if actor==x.requested_by:raise ValueError('ONLINE_SEGMENT_MAKER_CHECKER_REQUIRED')
   if not x.approver_one:x.approver_one=actor;x.state='AWAITING_SECOND_APPROVAL'
   elif x.approver_one==actor:raise ValueError('TWO_DISTINCT_SEGMENT_APPROVERS_REQUIRED')
   elif not x.approver_two:
    x.approver_two=actor
    for y in s.execute(select(JourneyRecoveryForecastOnlineSegmentPolicyRow).where(JourneyRecoveryForecastOnlineSegmentPolicyRow.environment==x.environment,JourneyRecoveryForecastOnlineSegmentPolicyRow.state=='ACTIVE')).scalars().all():y.state='SUPERSEDED'
    x.state='ACTIVE'
   s.commit();return self.policy(i)
 def register_attribution_segment(self,attribution_id,team_key,risk_domain):
  with SessionLocal() as s:
   a=s.get(JourneyRecoveryForecastOutcomeAttributionRow,attribution_id)
   if not a:raise ValueError('OUTCOME_ATTRIBUTION_NOT_FOUND')
   if s.execute(select(JourneyRecoveryForecastSegmentPerformanceObservationRow).where(JourneyRecoveryForecastSegmentPerformanceObservationRow.forecast_outcome_attribution_id==attribution_id)).scalars().first():raise ValueError('SEGMENT_OBSERVATION_ALREADY_REGISTERED')
   x=JourneyRecoveryForecastSegmentPerformanceObservationRow(forecast_segment_performance_observation_id=nid('jfsgo'),forecast_outcome_attribution_id=attribution_id,environment=a.environment,deployment_key=a.deployment_key,model_version_id=a.model_version_id,team_key=team_key,risk_domain=risk_domain,horizon_hours=a.horizon_hours,absolute_error=a.absolute_error,squared_error=a.squared_error,brier_score=a.brier_score,observed_at=a.observed_at,supplier_fact_unchanged=True);s.add(x);s.commit();return {'observation_id':x.forecast_segment_performance_observation_id,'team_key':team_key,'risk_domain':risk_domain,'horizon_hours':a.horizon_hours,'supplier_fact_unchanged':True}
 def assess_segment(self,environment,deployment_key,team_key,risk_domain,horizon_hours,auto_refresh=True,evidence_reference='segment://live'):
  with SessionLocal() as s:
   p=s.execute(select(JourneyRecoveryForecastOnlineSegmentPolicyRow).where(JourneyRecoveryForecastOnlineSegmentPolicyRow.environment==environment,JourneyRecoveryForecastOnlineSegmentPolicyRow.state=='ACTIVE').order_by(JourneyRecoveryForecastOnlineSegmentPolicyRow.version_no.desc())).scalars().first()
   if not p:raise ValueError('ACTIVE_ONLINE_SEGMENT_POLICY_REQUIRED')
   rows=s.execute(select(JourneyRecoveryForecastSegmentPerformanceObservationRow).where(JourneyRecoveryForecastSegmentPerformanceObservationRow.environment==environment,JourneyRecoveryForecastSegmentPerformanceObservationRow.deployment_key==deployment_key,JourneyRecoveryForecastSegmentPerformanceObservationRow.team_key==team_key,JourneyRecoveryForecastSegmentPerformanceObservationRow.risk_domain==risk_domain,JourneyRecoveryForecastSegmentPerformanceObservationRow.horizon_hours==horizon_hours)).scalars().all()
   if not rows:raise ValueError('NO_SEGMENT_OUTCOMES')
   n=len(rows);mae=sum(x.absolute_error for x in rows)/n;rmse=sqrt(sum(x.squared_error for x in rows)/n);bs=[x.brier_score for x in rows if x.brier_score is not None];mb=sum(bs)/len(bs) if bs else None;reasons=[]
   if n<p.minimum_segment_samples:state='INSUFFICIENT_SAMPLE';reasons=['MINIMUM_SEGMENT_SAMPLE_NOT_MET']
   else:
    if mae>p.max_segment_mae:reasons.append('SEGMENT_MAE_BREACH')
    if rmse>p.max_segment_rmse:reasons.append('SEGMENT_RMSE_BREACH')
    if mb is not None and mb>p.max_segment_brier:reasons.append('SEGMENT_BRIER_BREACH')
    state='DEGRADED' if reasons else 'PASS'
   a=JourneyRecoveryForecastSegmentPerformanceAssessmentRow(forecast_segment_performance_assessment_id=nid('jfspa'),environment=environment,deployment_key=deployment_key,model_version_id=rows[0].model_version_id,team_key=team_key,risk_domain=risk_domain,horizon_hours=horizon_hours,sample_count=n,mae=mae,rmse=rmse,mean_brier_score=mb,performance_state=state,reason_codes_json=reasons,assessed_at=now(),supplier_fact_unchanged=True);s.add(a);self._event(s,environment,'SEGMENT_PERFORMANCE_ASSESSED',a.forecast_segment_performance_assessment_id,None,{'state':state,'team_key':team_key,'risk_domain':risk_domain,'horizon_hours':horizon_hours},'segment-performance-engine');s.commit();aid=a.forecast_segment_performance_assessment_id
  if state=='DEGRADED' and auto_refresh:self.trigger_refresh(aid,evidence_reference)
  return self.assessment(aid)
 def trigger_refresh(self,assessment_id,evidence_reference,actor='automatic-challenger-refresh'):
  with SessionLocal() as s:
   a=s.get(JourneyRecoveryForecastSegmentPerformanceAssessmentRow,assessment_id)
   if not a or a.performance_state!='DEGRADED':raise ValueError('DEGRADED_SEGMENT_ASSESSMENT_REQUIRED')
   p=s.execute(select(JourneyRecoveryForecastOnlineSegmentPolicyRow).where(JourneyRecoveryForecastOnlineSegmentPolicyRow.environment==a.environment,JourneyRecoveryForecastOnlineSegmentPolicyRow.state=='ACTIVE').order_by(JourneyRecoveryForecastOnlineSegmentPolicyRow.version_no.desc())).scalars().first()
   recent=s.execute(select(JourneyRecoveryForecastSegmentPerformanceAssessmentRow).where(JourneyRecoveryForecastSegmentPerformanceAssessmentRow.environment==a.environment,JourneyRecoveryForecastSegmentPerformanceAssessmentRow.deployment_key==a.deployment_key,JourneyRecoveryForecastSegmentPerformanceAssessmentRow.team_key==a.team_key,JourneyRecoveryForecastSegmentPerformanceAssessmentRow.risk_domain==a.risk_domain,JourneyRecoveryForecastSegmentPerformanceAssessmentRow.horizon_hours==a.horizon_hours,JourneyRecoveryForecastSegmentPerformanceAssessmentRow.performance_state=='DEGRADED').order_by(JourneyRecoveryForecastSegmentPerformanceAssessmentRow.assessed_at.desc()).limit(p.consecutive_breaches_required)).scalars().all()
   if len(recent)<p.consecutive_breaches_required:raise ValueError('CONSECUTIVE_SEGMENT_BREACHES_REQUIRED')
   existing=s.execute(select(JourneyRecoveryForecastAutomaticRefreshTriggerRow).where(JourneyRecoveryForecastAutomaticRefreshTriggerRow.environment==a.environment,JourneyRecoveryForecastAutomaticRefreshTriggerRow.source_segment_assessment_id==assessment_id)).scalars().first()
   if existing:return {'trigger_id':existing.forecast_automatic_refresh_trigger_id,'retraining_request_id':existing.retraining_request_id,'trigger_state':existing.trigger_state,'supplier_fact_unchanged':True}
   m=s.get(JourneyRecoveryRiskForecastModelVersionRow,a.model_version_id)
   r=JourneyRecoveryForecastRetrainingRequestRow(forecast_retraining_request_id=nid('jfrr'),environment=a.environment,source_drift_assessment_id=assessment_id,champion_model_version_id=a.model_version_id,requested_model_key=m.model_key,refresh_reason_codes_json=['ONLINE_SEGMENT_DEGRADATION']+list(a.reason_codes_json or []),state='APPROVED_FOR_REFRESH',requested_at=now(),requested_by=actor,evidence_json={'segment':{'team_key':a.team_key,'risk_domain':a.risk_domain,'horizon_hours':a.horizon_hours},'evidence_reference':evidence_reference},supplier_fact_unchanged=True);s.add(r);s.flush()
   pipe=JourneyRecoveryForecastRefreshPipelineRow(forecast_refresh_pipeline_id=nid('jfrp'),environment=a.environment,retraining_request_id=r.forecast_retraining_request_id,source_champion_model_version_id=a.model_version_id,challenger_model_version_id=None,pipeline_state='REFRESH_REQUESTED',governance_next_step='GENERATE_CHALLENGER',created_at=now(),updated_at=now(),supplier_fact_unchanged=True);s.add(pipe)
   t=JourneyRecoveryForecastAutomaticRefreshTriggerRow(forecast_automatic_refresh_trigger_id=nid('jfart'),environment=a.environment,source_segment_assessment_id=assessment_id,retraining_request_id=r.forecast_retraining_request_id,trigger_state='RETRAINING_REQUESTED',reason_codes_json=r.refresh_reason_codes_json,evidence_reference=evidence_reference,created_at=now(),supplier_fact_unchanged=True);s.add(t);self._event(s,a.environment,'AUTOMATIC_CHALLENGER_REFRESH_TRIGGERED',assessment_id,r.forecast_retraining_request_id,{'team_key':a.team_key,'risk_domain':a.risk_domain,'horizon_hours':a.horizon_hours},actor);s.commit();return {'trigger_id':t.forecast_automatic_refresh_trigger_id,'retraining_request_id':r.forecast_retraining_request_id,'trigger_state':'RETRAINING_REQUESTED','governance_next_step':'GENERATE_CHALLENGER','supplier_fact_unchanged':True}
 def policy(self,i):
  with SessionLocal() as s:
   x=s.get(JourneyRecoveryForecastOnlineSegmentPolicyRow,i);return {'policy_id':x.forecast_online_segment_policy_id,'environment':x.environment,'version_no':x.version_no,'minimum_segment_samples':x.minimum_segment_samples,'state':x.state,'supplier_fact_unchanged':True}
 def assessment(self,i):
  with SessionLocal() as s:
   x=s.get(JourneyRecoveryForecastSegmentPerformanceAssessmentRow,i);return {'assessment_id':x.forecast_segment_performance_assessment_id,'team_key':x.team_key,'risk_domain':x.risk_domain,'horizon_hours':x.horizon_hours,'sample_count':x.sample_count,'mae':x.mae,'rmse':x.rmse,'performance_state':x.performance_state,'reason_codes':x.reason_codes_json,'supplier_fact_unchanged':True}
 def status(self,environment='PROD'):
  with SessionLocal() as s:
   a=s.execute(select(JourneyRecoveryForecastSegmentPerformanceAssessmentRow).where(JourneyRecoveryForecastSegmentPerformanceAssessmentRow.environment==environment).order_by(JourneyRecoveryForecastSegmentPerformanceAssessmentRow.assessed_at.desc()).limit(20)).scalars().all();t=s.execute(select(JourneyRecoveryForecastAutomaticRefreshTriggerRow).where(JourneyRecoveryForecastAutomaticRefreshTriggerRow.environment==environment).order_by(JourneyRecoveryForecastAutomaticRefreshTriggerRow.created_at.desc()).limit(20)).scalars().all();return {'segment_assessments':[{'assessment_id':x.forecast_segment_performance_assessment_id,'team_key':x.team_key,'risk_domain':x.risk_domain,'horizon_hours':x.horizon_hours,'state':x.performance_state,'mae':x.mae} for x in a],'automatic_refresh_triggers':[{'trigger_id':x.forecast_automatic_refresh_trigger_id,'retraining_request_id':x.retraining_request_id,'state':x.trigger_state} for x in t],'supplier_fact_unchanged':True}
 def _event(self,s,e,t,a,r,ev,actor):s.add(JourneyRecoveryForecastOnlineSegmentEventRow(forecast_online_segment_event_id=nid('jfose'),environment=e,event_type=t,segment_assessment_id=a,retraining_request_id=r,evidence_json=ev or {},actor=actor,created_at=now(),supplier_fact_unchanged=True))
recovery_forecast_online_segment_governance_service=RecoveryForecastOnlineSegmentGovernanceService()
