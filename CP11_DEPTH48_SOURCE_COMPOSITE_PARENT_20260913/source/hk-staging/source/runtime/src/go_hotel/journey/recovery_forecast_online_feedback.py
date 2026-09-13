from datetime import datetime,timezone
from uuid import uuid4
from math import sqrt
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import *
from go_hotel.journey.recovery_forecast_traffic_governance import recovery_forecast_traffic_governance_service as traffic
def now(): return datetime.now(timezone.utc)
def nid(p): return f'{p}_{uuid4().hex}'
class RecoveryForecastOnlineFeedbackService:
 def attribute_outcome(self,prediction_request_id,actual_value,horizon_hours,evidence_reference,observed_at=None,outcome_state='FINAL'):
  if outcome_state!='FINAL': raise ValueError('FINAL_OUTCOME_REQUIRED')
  with SessionLocal() as s:
   pr=s.get(JourneyRecoveryForecastPredictionProvenanceRow,prediction_request_id)
   if not pr: raise ValueError('PREDICTION_PROVENANCE_NOT_FOUND')
   if s.execute(select(JourneyRecoveryForecastOutcomeAttributionRow).where(JourneyRecoveryForecastOutcomeAttributionRow.prediction_request_id==prediction_request_id)).scalars().first(): raise ValueError('OUTCOME_ALREADY_ATTRIBUTED')
   pv=float(pr.prediction_json.get('value',0)); av=float(actual_value); ae=abs(av-pv); se=(av-pv)**2
   prob=pr.prediction_json.get('probability'); brier=None if prob is None else (float(prob)-(1.0 if av>=0.5 else 0.0))**2
   x=JourneyRecoveryForecastOutcomeAttributionRow(forecast_outcome_attribution_id=nid('jfoa'),prediction_request_id=prediction_request_id,environment=pr.environment,serving_role=pr.serving_role,deployment_key=pr.deployment_key,model_version_id=pr.model_version_id,predicted_value=pv,actual_value=av,absolute_error=ae,squared_error=se,brier_score=brier,horizon_hours=horizon_hours,outcome_state='FINAL',evidence_reference=evidence_reference,observed_at=observed_at or now(),attributed_at=now(),supplier_fact_unchanged=True);s.add(x);self._event(s,pr.environment,'OUTCOME_ATTRIBUTED',prediction_request_id,pr.deployment_key,{'actual_value':av,'absolute_error':ae},'outcome-attribution');s.commit();return self.attribution(x.forecast_outcome_attribution_id)
 def assess_live_performance(self,environment,deployment_key,min_samples=5,max_mae=15,max_rmse=20,max_brier=.25,auto_degrade=True,evidence_reference='live://assessment'):
  with SessionLocal() as s:
   rows=s.execute(select(JourneyRecoveryForecastOutcomeAttributionRow).where(JourneyRecoveryForecastOutcomeAttributionRow.environment==environment,JourneyRecoveryForecastOutcomeAttributionRow.deployment_key==deployment_key).order_by(JourneyRecoveryForecastOutcomeAttributionRow.attributed_at.desc())).scalars().all()
   if not rows: raise ValueError('NO_ATTRIBUTED_OUTCOMES')
   n=len(rows); mae=sum(x.absolute_error for x in rows)/n; rmse=sqrt(sum(x.squared_error for x in rows)/n); bs=[x.brier_score for x in rows if x.brier_score is not None]; mb=(sum(bs)/len(bs) if bs else None); reasons=[]
   if n<min_samples: state='INSUFFICIENT_SAMPLE';reasons.append('MINIMUM_LIVE_SAMPLE_NOT_MET')
   else:
    if mae>max_mae:reasons.append('LIVE_MAE_THRESHOLD_EXCEEDED')
    if rmse>max_rmse:reasons.append('LIVE_RMSE_THRESHOLD_EXCEEDED')
    if mb is not None and mb>max_brier:reasons.append('LIVE_BRIER_THRESHOLD_EXCEEDED')
    state='DEGRADED' if reasons else 'PASS'
   r0=rows[0];a=JourneyRecoveryForecastLivePerformanceAssessmentRow(forecast_live_performance_assessment_id=nid('jflp'),environment=environment,deployment_key=deployment_key,model_version_id=r0.model_version_id,serving_role=r0.serving_role,sample_count=n,mae=mae,rmse=rmse,mean_brier_score=mb,performance_state=state,reason_codes_json=reasons,assessed_at=now(),supplier_fact_unchanged=True);s.add(a);self._event(s,environment,'LIVE_PERFORMANCE_ASSESSED',None,deployment_key,{'state':state,'sample_count':n,'mae':mae,'rmse':rmse},'performance-engine');s.commit();aid=a.forecast_live_performance_assessment_id
  if state=='DEGRADED' and auto_degrade:self.auto_degrade(environment,deployment_key,aid,reasons,evidence_reference)
  return self.assessment(aid)
 def auto_degrade(self,environment,deployment_key,assessment_id,reasons,evidence_reference):
  st=traffic.status(environment)
  if st.get('state')=='NO_ACTIVE_POLICY': raise ValueError('ACTIVE_TRAFFIC_POLICY_REQUIRED')
  if deployment_key!=st['candidate_deployment_key']: raise ValueError('AUTO_DEGRADE_ONLY_CANARY_CANDIDATE')
  previous=st['canary_percentage']
  if previous>0: traffic.rollback(environment,evidence_reference,'online-feedback-controller')
  with SessionLocal() as s:
   existing=s.execute(select(JourneyRecoveryForecastServingAutoDegradeControlRow).where(JourneyRecoveryForecastServingAutoDegradeControlRow.environment==environment,JourneyRecoveryForecastServingAutoDegradeControlRow.deployment_key==deployment_key,JourneyRecoveryForecastServingAutoDegradeControlRow.control_state=='ACTIVE')).scalars().first()
   if existing:return {'control_id':existing.forecast_serving_auto_degrade_control_id,'control_state':'ACTIVE','applied_canary_percentage':0,'supplier_fact_unchanged':True}
   c=JourneyRecoveryForecastServingAutoDegradeControlRow(forecast_serving_auto_degrade_control_id=nid('jfadc'),environment=environment,deployment_key=deployment_key,control_state='ACTIVE',trigger_assessment_id=assessment_id,reason_codes_json=reasons,previous_canary_percentage=previous,applied_canary_percentage=0,evidence_reference=evidence_reference,activated_at=now(),released_at=None,release_evidence_reference=None,supplier_fact_unchanged=True);s.add(c);self._event(s,environment,'SERVING_AUTO_DEGRADED',None,deployment_key,{'previous_canary_percentage':previous,'applied_canary_percentage':0,'reasons':reasons},'online-feedback-controller');s.commit();return {'control_id':c.forecast_serving_auto_degrade_control_id,'control_state':'ACTIVE','applied_canary_percentage':0,'supplier_fact_unchanged':True}
 def release_degrade(self,environment,deployment_key,evidence_reference,actor):
  with SessionLocal() as s:
   c=s.execute(select(JourneyRecoveryForecastServingAutoDegradeControlRow).where(JourneyRecoveryForecastServingAutoDegradeControlRow.environment==environment,JourneyRecoveryForecastServingAutoDegradeControlRow.deployment_key==deployment_key,JourneyRecoveryForecastServingAutoDegradeControlRow.control_state=='ACTIVE').order_by(JourneyRecoveryForecastServingAutoDegradeControlRow.activated_at.desc())).scalars().first()
   if not c: raise ValueError('ACTIVE_AUTO_DEGRADE_CONTROL_NOT_FOUND')
   latest=s.execute(select(JourneyRecoveryForecastLivePerformanceAssessmentRow).where(JourneyRecoveryForecastLivePerformanceAssessmentRow.environment==environment,JourneyRecoveryForecastLivePerformanceAssessmentRow.deployment_key==deployment_key).order_by(JourneyRecoveryForecastLivePerformanceAssessmentRow.assessed_at.desc())).scalars().first()
   if not latest or latest.performance_state!='PASS' or latest.assessed_at<=c.activated_at: raise ValueError('FRESH_LIVE_PERFORMANCE_PASS_REQUIRED')
   c.control_state='RELEASED';c.released_at=now();c.release_evidence_reference=evidence_reference;self._event(s,environment,'AUTO_DEGRADE_RELEASED',None,deployment_key,{'evidence_reference':evidence_reference},actor);s.commit();return {'control_state':'RELEASED','supplier_fact_unchanged':True}
 def attribution(self,aid):
  with SessionLocal() as s:
   x=s.get(JourneyRecoveryForecastOutcomeAttributionRow,aid);return {'forecast_outcome_attribution_id':x.forecast_outcome_attribution_id,'prediction_request_id':x.prediction_request_id,'deployment_key':x.deployment_key,'model_version_id':x.model_version_id,'predicted_value':x.predicted_value,'actual_value':x.actual_value,'absolute_error':x.absolute_error,'brier_score':x.brier_score,'supplier_fact_unchanged':True}
 def assessment(self,aid):
  with SessionLocal() as s:
   x=s.get(JourneyRecoveryForecastLivePerformanceAssessmentRow,aid);return {'forecast_live_performance_assessment_id':x.forecast_live_performance_assessment_id,'deployment_key':x.deployment_key,'sample_count':x.sample_count,'mae':x.mae,'rmse':x.rmse,'mean_brier_score':x.mean_brier_score,'performance_state':x.performance_state,'reason_codes':x.reason_codes_json,'supplier_fact_unchanged':True}
 def status(self,environment):
  with SessionLocal() as s:
   a=s.execute(select(JourneyRecoveryForecastLivePerformanceAssessmentRow).where(JourneyRecoveryForecastLivePerformanceAssessmentRow.environment==environment).order_by(JourneyRecoveryForecastLivePerformanceAssessmentRow.assessed_at.desc())).scalars().first();c=s.execute(select(JourneyRecoveryForecastServingAutoDegradeControlRow).where(JourneyRecoveryForecastServingAutoDegradeControlRow.environment==environment,JourneyRecoveryForecastServingAutoDegradeControlRow.control_state=='ACTIVE').order_by(JourneyRecoveryForecastServingAutoDegradeControlRow.activated_at.desc())).scalars().first();return {'latest_performance_state':a.performance_state if a else None,'active_auto_degrade':bool(c),'deployment_key':c.deployment_key if c else (a.deployment_key if a else None),'supplier_fact_unchanged':True}
 def _event(self,s,e,t,pid,dkey,evidence,actor):s.add(JourneyRecoveryForecastOnlineFeedbackEventRow(forecast_online_feedback_event_id=nid('jfof'),environment=e,event_type=t,prediction_request_id=pid,deployment_key=dkey,evidence_json=evidence or {},actor=actor,created_at=now(),supplier_fact_unchanged=True))
recovery_forecast_online_feedback_service=RecoveryForecastOnlineFeedbackService()
