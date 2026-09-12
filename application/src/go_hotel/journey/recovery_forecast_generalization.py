from datetime import datetime,timezone
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import *
def now():return datetime.now(timezone.utc)
def nid(p):return f'{p}_{uuid4().hex[:20]}'
class RecoveryForecastGeneralizationService:
 def active_policy(self,s,e):return s.execute(select(JourneyRecoveryForecastGeneralizationPolicyRow).where(JourneyRecoveryForecastGeneralizationPolicyRow.environment==e,JourneyRecoveryForecastGeneralizationPolicyRow.state=='ACTIVE').order_by(JourneyRecoveryForecastGeneralizationPolicyRow.version_no.desc())).scalars().first()
 def create_policy(self,environment='PROD',minimum_adjacent_samples=3,max_adjacent_regression_pct=10,max_holdout_regression_pct=8,minimum_target_sustain_improvement_pct=10,actor='model-risk-governance'):
  if minimum_adjacent_samples<2 or min(max_adjacent_regression_pct,max_holdout_regression_pct,minimum_target_sustain_improvement_pct)<0:raise ValueError('INVALID_GENERALIZATION_POLICY')
  with SessionLocal() as s:
   prev=s.execute(select(JourneyRecoveryForecastGeneralizationPolicyRow).where(JourneyRecoveryForecastGeneralizationPolicyRow.environment==environment).order_by(JourneyRecoveryForecastGeneralizationPolicyRow.version_no.desc())).scalars().first();x=JourneyRecoveryForecastGeneralizationPolicyRow(forecast_generalization_policy_id=nid('jfgp'),environment=environment,version_no=(prev.version_no+1 if prev else 1),minimum_adjacent_samples=minimum_adjacent_samples,max_adjacent_regression_pct=max_adjacent_regression_pct,max_holdout_regression_pct=max_holdout_regression_pct,minimum_target_sustain_improvement_pct=minimum_target_sustain_improvement_pct,requested_by=actor,approver_one=None,approver_two=None,state='PENDING_APPROVAL',created_at=now(),supplier_fact_unchanged=True);s.add(x);s.commit();return self._policy(x)
 def approve_policy(self,i,actor):
  with SessionLocal() as s:
   x=s.get(JourneyRecoveryForecastGeneralizationPolicyRow,i)
   if not x:raise ValueError('GENERALIZATION_POLICY_NOT_FOUND')
   if actor==x.requested_by:raise ValueError('GENERALIZATION_MAKER_CHECKER_REQUIRED')
   if not x.approver_one:x.approver_one=actor;x.state='AWAITING_SECOND_APPROVAL'
   elif x.approver_one==actor:raise ValueError('TWO_DISTINCT_GENERALIZATION_APPROVERS_REQUIRED')
   elif not x.approver_two:
    x.approver_two=actor
    for y in s.execute(select(JourneyRecoveryForecastGeneralizationPolicyRow).where(JourneyRecoveryForecastGeneralizationPolicyRow.environment==x.environment,JourneyRecoveryForecastGeneralizationPolicyRow.state=='ACTIVE')).scalars().all():y.state='SUPERSEDED'
    x.state='ACTIVE'
   s.commit();return self._policy(x)
 def _target(self,s,target_id):
  t=s.get(JourneyRecoveryForecastRemediationTargetRow,target_id)
  if not t:raise ValueError('REMEDIATION_TARGET_NOT_FOUND')
  p=self.active_policy(s,t.environment)
  if not p:raise ValueError('ACTIVE_GENERALIZATION_POLICY_REQUIRED')
  return t,p
 def validate_adjacent(self,target_id,challenger_model_version_id,segment_key,sample_count,baseline_mae,challenger_mae,actor='generalization-validator'):
  with SessionLocal() as s:
   t,p=self._target(s,target_id);reg=((challenger_mae-baseline_mae)/max(abs(baseline_mae),.0001))*100;reasons=[]
   if sample_count<p.minimum_adjacent_samples:reasons.append('ADJACENT_MINIMUM_SAMPLE_NOT_MET')
   if reg>p.max_adjacent_regression_pct:reasons.append('ADJACENT_SEGMENT_REGRESSION')
   state='PASS' if not reasons else 'FAIL';x=JourneyRecoveryForecastGeneralizationValidationRow(forecast_generalization_validation_id=nid('jfgv'),environment=t.environment,remediation_target_id=target_id,challenger_model_version_id=challenger_model_version_id,segment_key=segment_key,sample_count=sample_count,baseline_mae=baseline_mae,challenger_mae=challenger_mae,regression_pct=round(reg,4),validation_state=state,reason_codes_json=reasons,evaluated_at=now(),supplier_fact_unchanged=True);s.add(x);self._event(s,t.environment,'ADJACENT_GENERALIZATION_VALIDATED',target_id,challenger_model_version_id,{'segment_key':segment_key,'state':state},actor);s.commit();return self._validation(x)
 def validate_holdout(self,target_id,challenger_model_version_id,segment_key,sample_count,baseline_mae,challenger_mae,actor='holdout-validator'):
  with SessionLocal() as s:
   t,p=self._target(s,target_id);reg=((challenger_mae-baseline_mae)/max(abs(baseline_mae),.0001))*100;reasons=[]
   if sample_count<p.minimum_adjacent_samples:reasons.append('HOLDOUT_MINIMUM_SAMPLE_NOT_MET')
   if reg>p.max_holdout_regression_pct:reasons.append('HOLDOUT_SEGMENT_REGRESSION')
   state='PASS' if not reasons else 'FAIL';x=JourneyRecoveryForecastHoldoutValidationRow(forecast_holdout_validation_id=nid('jfhv'),environment=t.environment,remediation_target_id=target_id,challenger_model_version_id=challenger_model_version_id,holdout_segment_key=segment_key,sample_count=sample_count,baseline_mae=baseline_mae,challenger_mae=challenger_mae,regression_pct=round(reg,4),validation_state=state,reason_codes_json=reasons,evaluated_at=now(),supplier_fact_unchanged=True);s.add(x);self._event(s,t.environment,'HOLDOUT_VALIDATED',target_id,challenger_model_version_id,{'segment_key':segment_key,'state':state},actor);s.commit();return {'holdout_validation_id':x.forecast_holdout_validation_id,'state':state,'regression_pct':x.regression_pct,'reason_codes':reasons,'supplier_fact_unchanged':True}
 def assert_pre_promotion_eligible_in_session(self,s,environment,challenger_id):
  p=self.active_policy(s,environment)
  if not p:return True
  pipe=s.execute(select(JourneyRecoveryForecastRefreshPipelineRow).where(JourneyRecoveryForecastRefreshPipelineRow.environment==environment,JourneyRecoveryForecastRefreshPipelineRow.challenger_model_version_id==challenger_id).order_by(JourneyRecoveryForecastRefreshPipelineRow.created_at.desc())).scalars().first()
  if not pipe:return True
  t=s.execute(select(JourneyRecoveryForecastRemediationTargetRow).where(JourneyRecoveryForecastRemediationTargetRow.retraining_request_id==pipe.retraining_request_id)).scalars().first()
  if not t:return True
  a=s.execute(select(JourneyRecoveryForecastRemediationAssessmentRow).where(JourneyRecoveryForecastRemediationAssessmentRow.remediation_target_id==t.forecast_remediation_target_id,JourneyRecoveryForecastRemediationAssessmentRow.challenger_model_version_id==challenger_id).order_by(JourneyRecoveryForecastRemediationAssessmentRow.evaluated_at.desc())).scalars().first()
  if not a or a.effectiveness_state!='REMEDIATION_EFFECTIVE':raise ValueError('4U_EFFECTIVE_REMEDIATION_REQUIRED')
  g=s.execute(select(JourneyRecoveryForecastGeneralizationValidationRow).where(JourneyRecoveryForecastGeneralizationValidationRow.remediation_target_id==t.forecast_remediation_target_id,JourneyRecoveryForecastGeneralizationValidationRow.challenger_model_version_id==challenger_id)).scalars().all()
  h=s.execute(select(JourneyRecoveryForecastHoldoutValidationRow).where(JourneyRecoveryForecastHoldoutValidationRow.remediation_target_id==t.forecast_remediation_target_id,JourneyRecoveryForecastHoldoutValidationRow.challenger_model_version_id==challenger_id)).scalars().all()
  if not g or any(x.validation_state!='PASS' for x in g):raise ValueError('REMEDIATION_GENERALIZATION_GATE_REQUIRED')
  if not h or any(x.validation_state!='PASS' for x in h):raise ValueError('REMEDIATION_HOLDOUT_SAFETY_GATE_REQUIRED')
  return True
 def post_promotion_proof(self,target_id,promoted_model_version_id,target_live_improvement_pct,max_adjacent_regression_pct,max_holdout_regression_pct,global_performance_state='PASS',evidence=None,actor='production-proof-controller'):
  with SessionLocal() as s:
   t,p=self._target(s,target_id);reasons=[]
   if target_live_improvement_pct<p.minimum_target_sustain_improvement_pct:reasons.append('TARGET_REMEDIATION_NOT_SUSTAINED')
   if max_adjacent_regression_pct>p.max_adjacent_regression_pct:reasons.append('ADJACENT_PRODUCTION_REGRESSION')
   if max_holdout_regression_pct>p.max_holdout_regression_pct:reasons.append('HOLDOUT_PRODUCTION_REGRESSION')
   if global_performance_state!='PASS':reasons.append('GLOBAL_PRODUCTION_PERFORMANCE_REGRESSION')
   if not reasons:state='REMEDIATION_PROVEN_IN_PRODUCTION'
   elif 'TARGET_REMEDIATION_NOT_SUSTAINED' in reasons and len(reasons)==1:state='REMEDIATION_NOT_GENERALIZED'
   else:state='POST_PROMOTION_REGRESSION'
   rollback=state!='REMEDIATION_PROVEN_IN_PRODUCTION';x=JourneyRecoveryForecastPostPromotionProofRow(forecast_post_promotion_proof_id=nid('jfppp'),environment=t.environment,remediation_target_id=target_id,promoted_model_version_id=promoted_model_version_id,target_live_improvement_pct=target_live_improvement_pct,max_adjacent_regression_pct=max_adjacent_regression_pct,max_holdout_regression_pct=max_holdout_regression_pct,global_performance_state=global_performance_state,proof_state=state,rollback_required=rollback,reason_codes_json=reasons,evidence_json=evidence or {},evaluated_at=now(),supplier_fact_unchanged=True);s.add(x);self._event(s,t.environment,'POST_PROMOTION_PROOF_ASSESSED',target_id,promoted_model_version_id,{'proof_state':state,'rollback_required':rollback},actor);s.commit();return self._proof(x)
 def probation_reason_in_session(self,s,environment,promoted_model_version_id):
  p=self.active_policy(s,environment)
  if not p:return None
  pipe=s.execute(select(JourneyRecoveryForecastRefreshPipelineRow).where(JourneyRecoveryForecastRefreshPipelineRow.environment==environment,JourneyRecoveryForecastRefreshPipelineRow.challenger_model_version_id==promoted_model_version_id).order_by(JourneyRecoveryForecastRefreshPipelineRow.created_at.desc())).scalars().first()
  if not pipe:return None
  t=s.execute(select(JourneyRecoveryForecastRemediationTargetRow).where(JourneyRecoveryForecastRemediationTargetRow.retraining_request_id==pipe.retraining_request_id)).scalars().first()
  if not t:return None
  x=s.execute(select(JourneyRecoveryForecastPostPromotionProofRow).where(JourneyRecoveryForecastPostPromotionProofRow.remediation_target_id==t.forecast_remediation_target_id,JourneyRecoveryForecastPostPromotionProofRow.promoted_model_version_id==promoted_model_version_id).order_by(JourneyRecoveryForecastPostPromotionProofRow.evaluated_at.desc())).scalars().first()
  if not x:return 'PROBATION_4V_PROOF_EVIDENCE_REQUIRED'
  if x.proof_state!='REMEDIATION_PROVEN_IN_PRODUCTION':return 'PROBATION_POST_PROMOTION_REGRESSION_4V'
  return None
 def status(self,environment='PROD'):
  with SessionLocal() as s:
   rows=s.execute(select(JourneyRecoveryForecastPostPromotionProofRow).where(JourneyRecoveryForecastPostPromotionProofRow.environment==environment).order_by(JourneyRecoveryForecastPostPromotionProofRow.evaluated_at.desc()).limit(20)).scalars().all();return {'proofs':[self._proof(x) for x in rows],'supplier_fact_unchanged':True}
 def _event(self,s,e,typ,t,m,ev,actor):s.add(JourneyRecoveryForecastGeneralizationEventRow(forecast_generalization_event_id=nid('jfge'),environment=e,event_type=typ,remediation_target_id=t,model_version_id=m,evidence_json=ev or {},actor=actor,created_at=now(),supplier_fact_unchanged=True))
 def _policy(self,x):return {'policy_id':x.forecast_generalization_policy_id,'environment':x.environment,'version_no':x.version_no,'minimum_adjacent_samples':x.minimum_adjacent_samples,'max_adjacent_regression_pct':x.max_adjacent_regression_pct,'max_holdout_regression_pct':x.max_holdout_regression_pct,'minimum_target_sustain_improvement_pct':x.minimum_target_sustain_improvement_pct,'state':x.state,'supplier_fact_unchanged':True}
 def _validation(self,x):return {'validation_id':x.forecast_generalization_validation_id,'segment_key':x.segment_key,'state':x.validation_state,'regression_pct':x.regression_pct,'reason_codes':x.reason_codes_json,'supplier_fact_unchanged':True}
 def _proof(self,x):return {'proof_id':x.forecast_post_promotion_proof_id,'proof_state':x.proof_state,'rollback_required':x.rollback_required,'reason_codes':x.reason_codes_json,'supplier_fact_unchanged':True}
recovery_forecast_generalization_service=RecoveryForecastGeneralizationService()
