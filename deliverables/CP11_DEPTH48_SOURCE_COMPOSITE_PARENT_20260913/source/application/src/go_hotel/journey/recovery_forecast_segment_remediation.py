from datetime import datetime,timezone
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import *
def now():return datetime.now(timezone.utc)
def nid(p):return f'{p}_{uuid4().hex[:20]}'
class RecoveryForecastSegmentRemediationService:
 def active_policy(self,s,e):return s.execute(select(JourneyRecoveryForecastRemediationPolicyRow).where(JourneyRecoveryForecastRemediationPolicyRow.environment==e,JourneyRecoveryForecastRemediationPolicyRow.state=='ACTIVE').order_by(JourneyRecoveryForecastRemediationPolicyRow.version_no.desc())).scalars().first()
 def create_policy(self,environment='PROD',minimum_target_improvement_pct=15,max_cross_segment_regression_pct=10,minimum_validation_samples=3,actor='model-risk-governance'):
  if minimum_target_improvement_pct<=0 or max_cross_segment_regression_pct<0 or minimum_validation_samples<2:raise ValueError('INVALID_REMEDIATION_POLICY')
  with SessionLocal() as s:
   prev=s.execute(select(JourneyRecoveryForecastRemediationPolicyRow).where(JourneyRecoveryForecastRemediationPolicyRow.environment==environment).order_by(JourneyRecoveryForecastRemediationPolicyRow.version_no.desc())).scalars().first();x=JourneyRecoveryForecastRemediationPolicyRow(forecast_remediation_policy_id=nid('jfrmp'),environment=environment,version_no=(prev.version_no+1 if prev else 1),minimum_target_improvement_pct=minimum_target_improvement_pct,max_cross_segment_regression_pct=max_cross_segment_regression_pct,minimum_validation_samples=minimum_validation_samples,requested_by=actor,approver_one=None,approver_two=None,state='PENDING_APPROVAL',created_at=now(),supplier_fact_unchanged=True);s.add(x);s.commit();return self._policy(x)
 def approve_policy(self,i,actor):
  with SessionLocal() as s:
   x=s.get(JourneyRecoveryForecastRemediationPolicyRow,i)
   if not x:raise ValueError('REMEDIATION_POLICY_NOT_FOUND')
   if actor==x.requested_by:raise ValueError('REMEDIATION_MAKER_CHECKER_REQUIRED')
   if not x.approver_one:x.approver_one=actor;x.state='AWAITING_SECOND_APPROVAL'
   elif x.approver_one==actor:raise ValueError('TWO_DISTINCT_REMEDIATION_APPROVERS_REQUIRED')
   elif not x.approver_two:
    x.approver_two=actor
    for y in s.execute(select(JourneyRecoveryForecastRemediationPolicyRow).where(JourneyRecoveryForecastRemediationPolicyRow.environment==x.environment,JourneyRecoveryForecastRemediationPolicyRow.state=='ACTIVE')).scalars().all():y.state='SUPERSEDED'
    x.state='ACTIVE'
   s.commit();return self._policy(x)
 def create_target(self,retraining_request_id,actor='remediation-controller'):
  with SessionLocal() as s:
   r=s.get(JourneyRecoveryForecastRetrainingRequestRow,retraining_request_id)
   if not r:raise ValueError('RETRAINING_REQUEST_NOT_FOUND')
   p=self.active_policy(s,r.environment)
   if not p:raise ValueError('ACTIVE_REMEDIATION_POLICY_REQUIRED')
   old=s.execute(select(JourneyRecoveryForecastRemediationTargetRow).where(JourneyRecoveryForecastRemediationTargetRow.retraining_request_id==retraining_request_id)).scalars().first()
   if old:return self._target(old)
   a=s.get(JourneyRecoveryForecastSegmentPerformanceAssessmentRow,r.source_drift_assessment_id)
   if not a or a.performance_state!='DEGRADED':raise ValueError('SOURCE_DEGRADED_SEGMENT_REQUIRED')
   x=JourneyRecoveryForecastRemediationTargetRow(forecast_remediation_target_id=nid('jfrmt'),environment=r.environment,retraining_request_id=retraining_request_id,source_segment_assessment_id=a.forecast_segment_performance_assessment_id,champion_model_version_id=r.champion_model_version_id,team_key=a.team_key,risk_domain=a.risk_domain,horizon_hours=a.horizon_hours,baseline_mae=a.mae,baseline_rmse=a.rmse,baseline_brier=a.mean_brier_score,required_improvement_pct=p.minimum_target_improvement_pct,created_at=now(),supplier_fact_unchanged=True);s.add(x);self._event(s,r.environment,'REMEDIATION_TARGET_CREATED',x.forecast_remediation_target_id,None,{'source_assessment_id':a.forecast_segment_performance_assessment_id},actor);s.commit();return self._target(x)
 def validate_target(self,target_id,challenger_model_version_id,sample_count,challenger_mae,actor='remediation-validator'):
  with SessionLocal() as s:
   t=s.get(JourneyRecoveryForecastRemediationTargetRow,target_id);p=self.active_policy(s,t.environment) if t else None
   if not t:raise ValueError('REMEDIATION_TARGET_NOT_FOUND')
   if sample_count<p.minimum_validation_samples:state='FAIL';reasons=['MINIMUM_VALIDATION_SAMPLE_NOT_MET']
   else:
    imp=((t.baseline_mae-challenger_mae)/max(abs(t.baseline_mae),.0001))*100;reasons=[]
    if imp<t.required_improvement_pct:reasons.append('TARGET_SEGMENT_IMPROVEMENT_NOT_MET')
    state='PASS' if not reasons else 'FAIL'
   imp=((t.baseline_mae-challenger_mae)/max(abs(t.baseline_mae),.0001))*100
   x=JourneyRecoveryForecastSegmentValidationRow(forecast_segment_validation_id=nid('jfrsv'),environment=t.environment,remediation_target_id=target_id,challenger_model_version_id=challenger_model_version_id,team_key=t.team_key,risk_domain=t.risk_domain,horizon_hours=t.horizon_hours,sample_count=sample_count,challenger_mae=challenger_mae,improvement_pct=round(imp,4),validation_state=state,reason_codes_json=reasons,evaluated_at=now(),supplier_fact_unchanged=True);s.add(x);self._event(s,t.environment,'TARGET_SEGMENT_VALIDATED',target_id,challenger_model_version_id,{'state':state,'improvement_pct':x.improvement_pct},actor);s.commit();return self._validation(x)
 def register_cross_segment(self,target_id,challenger_model_version_id,segment_key,baseline_mae,challenger_mae):
  with SessionLocal() as s:
   t=s.get(JourneyRecoveryForecastRemediationTargetRow,target_id);p=self.active_policy(s,t.environment) if t else None
   if not t:raise ValueError('REMEDIATION_TARGET_NOT_FOUND')
   reg=((challenger_mae-baseline_mae)/max(abs(baseline_mae),.0001))*100;state='REGRESSED' if reg>p.max_cross_segment_regression_pct else 'PASS';x=JourneyRecoveryForecastCrossSegmentRegressionRow(forecast_cross_segment_regression_id=nid('jfrcr'),environment=t.environment,remediation_target_id=target_id,challenger_model_version_id=challenger_model_version_id,segment_key=segment_key,baseline_mae=baseline_mae,challenger_mae=challenger_mae,regression_pct=round(reg,4),regression_state=state,evaluated_at=now(),supplier_fact_unchanged=True);s.add(x);s.commit();return {'cross_segment_regression_id':x.forecast_cross_segment_regression_id,'segment_key':segment_key,'regression_pct':x.regression_pct,'state':state,'supplier_fact_unchanged':True}
 def assess(self,target_id,challenger_model_version_id,evidence=None,actor='remediation-controller'):
  with SessionLocal() as s:
   t=s.get(JourneyRecoveryForecastRemediationTargetRow,target_id)
   if not t:raise ValueError('REMEDIATION_TARGET_NOT_FOUND')
   v=s.execute(select(JourneyRecoveryForecastSegmentValidationRow).where(JourneyRecoveryForecastSegmentValidationRow.remediation_target_id==target_id,JourneyRecoveryForecastSegmentValidationRow.challenger_model_version_id==challenger_model_version_id).order_by(JourneyRecoveryForecastSegmentValidationRow.evaluated_at.desc())).scalars().first()
   if not v:raise ValueError('TARGET_SEGMENT_VALIDATION_REQUIRED')
   cr=s.execute(select(JourneyRecoveryForecastCrossSegmentRegressionRow).where(JourneyRecoveryForecastCrossSegmentRegressionRow.remediation_target_id==target_id,JourneyRecoveryForecastCrossSegmentRegressionRow.challenger_model_version_id==challenger_model_version_id)).scalars().all();maxreg=max([x.regression_pct for x in cr],default=0);reasons=list(v.reason_codes_json or [])
   if any(x.regression_state=='REGRESSED' for x in cr):reasons.append('CROSS_SEGMENT_REGRESSION_DETECTED')
   if v.validation_state!='PASS':state='REMEDIATION_INEFFECTIVE'
   elif any(x.regression_state=='REGRESSED' and x.regression_pct>=50 for x in cr):state='REMEDIATION_HARMFUL'
   elif any(x.regression_state=='REGRESSED' for x in cr):state='REMEDIATION_PARTIALLY_EFFECTIVE'
   else:state='REMEDIATION_EFFECTIVE'
   eligible=state=='REMEDIATION_EFFECTIVE';x=JourneyRecoveryForecastRemediationAssessmentRow(forecast_remediation_assessment_id=nid('jfra'),environment=t.environment,remediation_target_id=target_id,challenger_model_version_id=challenger_model_version_id,effectiveness_state=state,target_improvement_pct=v.improvement_pct,max_cross_segment_regression_pct=maxreg,reason_codes_json=reasons,promotion_eligible=eligible,evidence_json=evidence or {},evaluated_at=now(),supplier_fact_unchanged=True);s.add(x);self._event(s,t.environment,'REMEDIATION_ASSESSED',target_id,challenger_model_version_id,{'state':state,'promotion_eligible':eligible},actor);s.commit();return self._assessment(x)
 def assert_promotion_eligible_in_session(self,s,environment,challenger_id):
  pipe=s.execute(select(JourneyRecoveryForecastRefreshPipelineRow).where(JourneyRecoveryForecastRefreshPipelineRow.environment==environment,JourneyRecoveryForecastRefreshPipelineRow.challenger_model_version_id==challenger_id).order_by(JourneyRecoveryForecastRefreshPipelineRow.created_at.desc())).scalars().first()
  if not pipe:return True
  target=s.execute(select(JourneyRecoveryForecastRemediationTargetRow).where(JourneyRecoveryForecastRemediationTargetRow.retraining_request_id==pipe.retraining_request_id)).scalars().first()
  if not target:raise ValueError('SEGMENT_REMEDIATION_TARGET_REQUIRED')
  a=s.execute(select(JourneyRecoveryForecastRemediationAssessmentRow).where(JourneyRecoveryForecastRemediationAssessmentRow.remediation_target_id==target.forecast_remediation_target_id,JourneyRecoveryForecastRemediationAssessmentRow.challenger_model_version_id==challenger_id).order_by(JourneyRecoveryForecastRemediationAssessmentRow.evaluated_at.desc())).scalars().first()
  if not a or not a.promotion_eligible:raise ValueError('SEGMENT_REMEDIATION_PROMOTION_GATE_REQUIRED')
  return True
 def status(self,environment='PROD'):
  with SessionLocal() as s:
   a=s.execute(select(JourneyRecoveryForecastRemediationAssessmentRow).where(JourneyRecoveryForecastRemediationAssessmentRow.environment==environment).order_by(JourneyRecoveryForecastRemediationAssessmentRow.evaluated_at.desc()).limit(20)).scalars().all();return {'assessments':[self._assessment(x) for x in a],'supplier_fact_unchanged':True}
 def _event(self,s,e,typ,t,c,ev,actor):s.add(JourneyRecoveryForecastRemediationEventRow(forecast_remediation_event_id=nid('jfre'),environment=e,event_type=typ,remediation_target_id=t,challenger_model_version_id=c,evidence_json=ev or {},actor=actor,created_at=now(),supplier_fact_unchanged=True))
 def _policy(self,x):return {'policy_id':x.forecast_remediation_policy_id,'environment':x.environment,'version_no':x.version_no,'minimum_target_improvement_pct':x.minimum_target_improvement_pct,'max_cross_segment_regression_pct':x.max_cross_segment_regression_pct,'minimum_validation_samples':x.minimum_validation_samples,'state':x.state,'supplier_fact_unchanged':True}
 def _target(self,x):return {'target_id':x.forecast_remediation_target_id,'retraining_request_id':x.retraining_request_id,'team_key':x.team_key,'risk_domain':x.risk_domain,'horizon_hours':x.horizon_hours,'baseline_mae':x.baseline_mae,'required_improvement_pct':x.required_improvement_pct,'supplier_fact_unchanged':True}
 def _validation(self,x):return {'validation_id':x.forecast_segment_validation_id,'improvement_pct':x.improvement_pct,'validation_state':x.validation_state,'reason_codes':x.reason_codes_json,'supplier_fact_unchanged':True}
 def _assessment(self,x):return {'assessment_id':x.forecast_remediation_assessment_id,'effectiveness_state':x.effectiveness_state,'target_improvement_pct':x.target_improvement_pct,'max_cross_segment_regression_pct':x.max_cross_segment_regression_pct,'promotion_eligible':x.promotion_eligible,'reason_codes':x.reason_codes_json,'supplier_fact_unchanged':True}
recovery_forecast_segment_remediation_service=RecoveryForecastSegmentRemediationService()
