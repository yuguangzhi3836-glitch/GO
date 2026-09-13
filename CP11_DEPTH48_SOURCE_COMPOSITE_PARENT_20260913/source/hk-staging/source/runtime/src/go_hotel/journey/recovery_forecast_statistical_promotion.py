from datetime import datetime, timezone, timedelta
from uuid import uuid4
from math import sqrt, erfc
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import *

def now(): return datetime.now(timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'
def aware(x): return x if not x or x.tzinfo else x.replace(tzinfo=timezone.utc)

class RecoveryForecastStatisticalPromotionService:
    def active_policy_in_session(self,s,environment):
        return s.execute(select(JourneyRecoveryForecastPromotionPolicyRow).where(JourneyRecoveryForecastPromotionPolicyRow.environment==environment,JourneyRecoveryForecastPromotionPolicyRow.state=='ACTIVE').order_by(JourneyRecoveryForecastPromotionPolicyRow.version_no.desc())).scalars().first()
    def create_policy(self,environment,minimum_sample_count=30,significance_alpha=.05,minimum_effect_size_pct=5,stability_evaluations_required=2,required_segments=None,probation_seconds=86400,max_mae_regression_pct=10,max_brier_regression_pct=10,max_safety_regression_pct=5,actor='model-risk-governance'):
        if minimum_sample_count<2 or not (0<significance_alpha<1) or minimum_effect_size_pct<0 or stability_evaluations_required<1 or probation_seconds<1: raise ValueError('INVALID_STATISTICAL_PROMOTION_POLICY')
        with SessionLocal() as s:
            prev=s.execute(select(JourneyRecoveryForecastPromotionPolicyRow).where(JourneyRecoveryForecastPromotionPolicyRow.environment==environment).order_by(JourneyRecoveryForecastPromotionPolicyRow.version_no.desc())).scalars().first()
            x=JourneyRecoveryForecastPromotionPolicyRow(forecast_promotion_policy_id=nid('jfpp'),environment=environment,version_no=(prev.version_no+1 if prev else 1),minimum_sample_count=minimum_sample_count,significance_alpha=significance_alpha,minimum_effect_size_pct=minimum_effect_size_pct,stability_evaluations_required=stability_evaluations_required,required_segments_json=required_segments or ['ALL'],probation_seconds=probation_seconds,max_mae_regression_pct=max_mae_regression_pct,max_brier_regression_pct=max_brier_regression_pct,max_safety_regression_pct=max_safety_regression_pct,requested_by=actor,approver_one=None,approver_two=None,state='PENDING_APPROVAL',created_at=now(),supplier_fact_unchanged=True);s.add(x);s.commit();return self.policy(x.forecast_promotion_policy_id)
    def approve_policy(self,i,actor):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryForecastPromotionPolicyRow,i)
            if not x: raise ValueError('STATISTICAL_PROMOTION_POLICY_NOT_FOUND')
            if actor==x.requested_by: raise ValueError('STATISTICAL_PROMOTION_MAKER_CHECKER_REQUIRED')
            if not x.approver_one: x.approver_one=actor;x.state='AWAITING_SECOND_APPROVAL'
            elif x.approver_one==actor: raise ValueError('TWO_DISTINCT_PROMOTION_APPROVERS_REQUIRED')
            elif not x.approver_two:
                x.approver_two=actor
                for y in s.execute(select(JourneyRecoveryForecastPromotionPolicyRow).where(JourneyRecoveryForecastPromotionPolicyRow.environment==x.environment,JourneyRecoveryForecastPromotionPolicyRow.state=='ACTIVE')).scalars().all(): y.state='SUPERSEDED'
                x.state='ACTIVE'
            s.commit();return self.policy(i)
    def _latest_metric(self,s,environment,model,horizon,segment):
        run=s.execute(select(JourneyRecoveryForecastBacktestRunRow).where(JourneyRecoveryForecastBacktestRunRow.environment==environment).order_by(JourneyRecoveryForecastBacktestRunRow.created_at.desc())).scalars().first()
        if run:
            m=s.execute(select(JourneyRecoveryForecastBacktestMetricRow).where(JourneyRecoveryForecastBacktestMetricRow.forecast_backtest_run_id==run.forecast_backtest_run_id,JourneyRecoveryForecastBacktestMetricRow.model_version_id==model,JourneyRecoveryForecastBacktestMetricRow.horizon_hours==horizon,JourneyRecoveryForecastBacktestMetricRow.segment_key==segment)).scalars().first()
            if m:return m
        return None
    def assess(self,environment,challenger_id):
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment)
            if not p: raise ValueError('ACTIVE_STATISTICAL_PROMOTION_POLICY_REQUIRED')
            champ=s.execute(select(JourneyRecoveryForecastModelRoleRow).where(JourneyRecoveryForecastModelRoleRow.environment==environment,JourneyRecoveryForecastModelRoleRow.role=='CHAMPION',JourneyRecoveryForecastModelRoleRow.state=='ACTIVE').order_by(JourneyRecoveryForecastModelRoleRow.assigned_at.desc())).scalars().first()
            if not champ: raise ValueError('ACTIVE_CHAMPION_REQUIRED')
            out=[]
            for h in (24,168):
                for seg in p.required_segments_json:
                    cm=self._latest_metric(s,environment,champ.model_version_id,h,seg); qm=self._latest_metric(s,environment,challenger_id,h,seg)
                    if not cm or not qm:
                        ca=s.execute(select(JourneyRecoveryRiskForecastAccuracyAssessmentRow).where(JourneyRecoveryRiskForecastAccuracyAssessmentRow.environment==environment,JourneyRecoveryRiskForecastAccuracyAssessmentRow.risk_forecast_model_version_id==champ.model_version_id,JourneyRecoveryRiskForecastAccuracyAssessmentRow.horizon_hours==h).order_by(JourneyRecoveryRiskForecastAccuracyAssessmentRow.evaluated_at.desc())).scalars().first()
                        qa=s.execute(select(JourneyRecoveryRiskForecastAccuracyAssessmentRow).where(JourneyRecoveryRiskForecastAccuracyAssessmentRow.environment==environment,JourneyRecoveryRiskForecastAccuracyAssessmentRow.risk_forecast_model_version_id==challenger_id,JourneyRecoveryRiskForecastAccuracyAssessmentRow.horizon_hours==h).order_by(JourneyRecoveryRiskForecastAccuracyAssessmentRow.evaluated_at.desc())).scalars().first()
                        if not ca or not qa: raise ValueError('BACKTEST_OR_ACCURACY_EVIDENCE_REQUIRED')
                        n=min(ca.sample_count,qa.sample_count); cmae=ca.mae_points;qmae=qa.mae_points; cfp=ca.false_positive_rate;cfn=ca.false_negative_rate;cd=ca.mean_capacity_drift_pct;qfp=qa.false_positive_rate;qfn=qa.false_negative_rate;qd=qa.mean_capacity_drift_pct
                    else:
                        n=min(cm.sample_count,qm.sample_count);cmae=cm.mae_points;qmae=qm.mae_points;cfp=cm.false_positive_rate;cfn=cm.false_negative_rate;cd=cm.capacity_drift_pct;qfp=qm.false_positive_rate;qfn=qm.false_negative_rate;qd=qm.capacity_drift_pct
                    effect=((cmae-qmae)/max(abs(cmae),.0001))*100
                    se=sqrt((cmae*cmae/max(n,1))+(qmae*qmae/max(n,1))) or .0001
                    z=(cmae-qmae)/se;pval=erfc(abs(z)/sqrt(2))
                    reasons=[]
                    if n<p.minimum_sample_count:reasons.append('MINIMUM_SAMPLE_NOT_MET')
                    if effect<p.minimum_effect_size_pct:reasons.append('MINIMUM_EFFECT_SIZE_NOT_MET')
                    if pval>p.significance_alpha:reasons.append('STATISTICAL_SIGNIFICANCE_NOT_MET')
                    if max(qfp-cfp,qfn-cfn,qd-cd)>0:reasons.append('SEGMENT_SAFETY_DEGRADED')
                    state='PASS' if not reasons else 'FAIL'
                    a=JourneyRecoveryForecastStatisticalAssessmentRow(forecast_statistical_assessment_id=nid('jfsa'),environment=environment,policy_id=p.forecast_promotion_policy_id,champion_model_version_id=champ.model_version_id,challenger_model_version_id=challenger_id,horizon_hours=h,segment_key=seg,sample_count=n,effect_size_pct=round(effect,4),z_score=round(z,6),p_value=round(pval,8),significance_state=state,reason_codes_json=reasons,evaluated_at=now(),supplier_fact_unchanged=True);s.add(a);s.flush();out.append(self._assessment(a))
            s.commit();return {'assessments':out,'supplier_fact_unchanged':True}
    def promote(self,environment,challenger_id,evidence):
        if not evidence: raise ValueError('MODEL_PROMOTION_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment)
            if not p: raise ValueError('ACTIVE_STATISTICAL_PROMOTION_POLICY_REQUIRED')
            try:
                from go_hotel.journey.recovery_forecast_segment_remediation import recovery_forecast_segment_remediation_service as remediation
                remediation.assert_promotion_eligible_in_session(s,environment,challenger_id)
            except ImportError:
                pass
            try:
                from go_hotel.journey.recovery_forecast_artifact_governance import recovery_forecast_artifact_governance_service as artifacts
                artifacts.assert_artifact_eligible_in_session(s,environment,challenger_id)
            except ImportError:
                pass
            try:
                from go_hotel.journey.recovery_forecast_generalization import recovery_forecast_generalization_service as generalization
                generalization.assert_pre_promotion_eligible_in_session(s,environment,challenger_id)
            except ImportError:
                pass
            try:
                from go_hotel.journey.recovery_forecast_portfolio_governance import recovery_forecast_portfolio_governance_service as portfolio_governance
                portfolio_governance.assert_promotion_eligible_in_session(s,environment,challenger_id)
            except ImportError:
                pass
            champ=s.execute(select(JourneyRecoveryForecastModelRoleRow).where(JourneyRecoveryForecastModelRoleRow.environment==environment,JourneyRecoveryForecastModelRoleRow.role=='CHAMPION',JourneyRecoveryForecastModelRoleRow.state=='ACTIVE').order_by(JourneyRecoveryForecastModelRoleRow.assigned_at.desc())).scalars().first()
            if not champ: raise ValueError('ACTIVE_CHAMPION_REQUIRED')
            reasons=[]
            for h in (24,168):
                for seg in p.required_segments_json:
                    a=s.execute(select(JourneyRecoveryForecastStatisticalAssessmentRow).where(JourneyRecoveryForecastStatisticalAssessmentRow.environment==environment,JourneyRecoveryForecastStatisticalAssessmentRow.policy_id==p.forecast_promotion_policy_id,JourneyRecoveryForecastStatisticalAssessmentRow.challenger_model_version_id==challenger_id,JourneyRecoveryForecastStatisticalAssessmentRow.horizon_hours==h,JourneyRecoveryForecastStatisticalAssessmentRow.segment_key==seg).order_by(JourneyRecoveryForecastStatisticalAssessmentRow.evaluated_at.desc())).scalars().first()
                    if not a or a.significance_state!='PASS': reasons.append(f'STATISTICAL_GATE_REQUIRED_{h}_{seg}')
                    stable=s.execute(select(JourneyRecoveryForecastShadowEvaluationRow).where(JourneyRecoveryForecastShadowEvaluationRow.environment==environment,JourneyRecoveryForecastShadowEvaluationRow.challenger_model_version_id==challenger_id,JourneyRecoveryForecastShadowEvaluationRow.horizon_hours==h,JourneyRecoveryForecastShadowEvaluationRow.segment_key==seg,JourneyRecoveryForecastShadowEvaluationRow.evaluation_state=='PASS')).scalars().all()
                    if len(stable)<p.stability_evaluations_required: reasons.append(f'STABILITY_WINDOW_NOT_MET_{h}_{seg}')
            d=JourneyRecoveryForecastPromotionDecisionRow(forecast_promotion_decision_id=nid('jfpd'),environment=environment,champion_model_version_id=champ.model_version_id,challenger_model_version_id=challenger_id,decision=('BLOCKED' if reasons else 'PROMOTED_PROBATION'),reason_codes_json=reasons,evidence_json=evidence,decided_at=now(),supplier_fact_unchanged=True);s.add(d);s.flush()
            if not reasons:
                champ.state='SUPERSEDED'
                s.add(JourneyRecoveryForecastModelRoleRow(forecast_model_role_id=nid('jfmr'),environment=environment,model_version_id=challenger_id,role='CHAMPION',state='ACTIVE',assigned_at=now(),supplier_fact_unchanged=True))
                pr=JourneyRecoveryForecastPromotionProbationRow(forecast_promotion_probation_id=nid('jfpr'),environment=environment,policy_id=p.forecast_promotion_policy_id,promotion_decision_id=d.forecast_promotion_decision_id,previous_champion_model_version_id=champ.model_version_id,promoted_model_version_id=challenger_id,started_at=now(),probation_until=now()+timedelta(seconds=p.probation_seconds),state='PROBATION',latest_evaluation_json={},rollback_reason_codes_json=[],completed_at=None,supplier_fact_unchanged=True);s.add(pr)
            s.commit();return {'decision':d.decision,'reason_codes':reasons,'supplier_fact_unchanged':True}
    def probation_tick(self,environment,evidence=None,actor='model-risk-controller'):
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment)
            pr=s.execute(select(JourneyRecoveryForecastPromotionProbationRow).where(JourneyRecoveryForecastPromotionProbationRow.environment==environment,JourneyRecoveryForecastPromotionProbationRow.state=='PROBATION').order_by(JourneyRecoveryForecastPromotionProbationRow.started_at.desc())).scalars().first()
            if not p or not pr: raise ValueError('ACTIVE_MODEL_PROBATION_NOT_FOUND')
            reasons=[];detail={}
            for h in (24,168):
                old=s.execute(select(JourneyRecoveryRiskForecastAccuracyAssessmentRow).where(JourneyRecoveryRiskForecastAccuracyAssessmentRow.environment==environment,JourneyRecoveryRiskForecastAccuracyAssessmentRow.risk_forecast_model_version_id==pr.previous_champion_model_version_id,JourneyRecoveryRiskForecastAccuracyAssessmentRow.horizon_hours==h).order_by(JourneyRecoveryRiskForecastAccuracyAssessmentRow.evaluated_at.desc())).scalars().first()
                new=s.execute(select(JourneyRecoveryRiskForecastAccuracyAssessmentRow).where(JourneyRecoveryRiskForecastAccuracyAssessmentRow.environment==environment,JourneyRecoveryRiskForecastAccuracyAssessmentRow.risk_forecast_model_version_id==pr.promoted_model_version_id,JourneyRecoveryRiskForecastAccuracyAssessmentRow.horizon_hours==h).order_by(JourneyRecoveryRiskForecastAccuracyAssessmentRow.evaluated_at.desc())).scalars().first()
                if not old or not new: reasons.append(f'PROBATION_ACCURACY_EVIDENCE_REQUIRED_{h}');continue
                mae=((new.mae_points-old.mae_points)/max(old.mae_points,.0001))*100;brier=((new.brier_score-old.brier_score)/max(old.brier_score,.0001))*100
                safety=max((new.false_positive_rate-old.false_positive_rate)*100,(new.false_negative_rate-old.false_negative_rate)*100,(new.mean_capacity_drift_pct-old.mean_capacity_drift_pct))
                detail[str(h)]={'mae_regression_pct':round(mae,4),'brier_regression_pct':round(brier,4),'safety_regression_pct':round(safety,4)}
                if mae>p.max_mae_regression_pct:reasons.append(f'PROBATION_MAE_REGRESSION_{h}')
                if brier>p.max_brier_regression_pct:reasons.append(f'PROBATION_BRIER_REGRESSION_{h}')
                if safety>p.max_safety_regression_pct:reasons.append(f'PROBATION_SAFETY_REGRESSION_{h}')
            try:
                from go_hotel.journey.recovery_forecast_generalization import recovery_forecast_generalization_service as generalization
                r4v=generalization.probation_reason_in_session(s,environment,pr.promoted_model_version_id)
                if r4v: reasons.append(r4v)
            except ImportError:
                pass
            pr.latest_evaluation_json=detail
            if any(x.startswith('PROBATION_') and 'EVIDENCE_REQUIRED' not in x for x in reasons):
                for r in s.execute(select(JourneyRecoveryForecastModelRoleRow).where(JourneyRecoveryForecastModelRoleRow.environment==environment,JourneyRecoveryForecastModelRoleRow.role=='CHAMPION',JourneyRecoveryForecastModelRoleRow.state=='ACTIVE')).scalars().all(): r.state='ROLLED_BACK'
                s.add(JourneyRecoveryForecastModelRoleRow(forecast_model_role_id=nid('jfmr'),environment=environment,model_version_id=pr.previous_champion_model_version_id,role='CHAMPION',state='ACTIVE',assigned_at=now(),supplier_fact_unchanged=True))
                pr.state='ROLLED_BACK';pr.rollback_reason_codes_json=reasons;pr.completed_at=now()
                s.add(JourneyRecoveryForecastModelRollbackEventRow(forecast_model_rollback_event_id=nid('jfmre'),environment=environment,probation_id=pr.forecast_promotion_probation_id,from_model_version_id=pr.promoted_model_version_id,to_model_version_id=pr.previous_champion_model_version_id,reason_codes_json=reasons,evidence_json=evidence or {'source':'automated-probation'},rolled_back_at=now(),supplier_fact_unchanged=True))
            elif now()>=aware(pr.probation_until) and not reasons:
                pr.state='STABLE';pr.completed_at=now()
            s.commit();return {'probation_id':pr.forecast_promotion_probation_id,'state':pr.state,'reason_codes':pr.rollback_reason_codes_json,'evaluation':detail,'supplier_fact_unchanged':True}
    def status(self,environment):
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment);probs=s.execute(select(JourneyRecoveryForecastPromotionProbationRow).where(JourneyRecoveryForecastPromotionProbationRow.environment==environment).order_by(JourneyRecoveryForecastPromotionProbationRow.started_at.desc()).limit(10)).scalars().all();roll=s.execute(select(JourneyRecoveryForecastModelRollbackEventRow).where(JourneyRecoveryForecastModelRollbackEventRow.environment==environment).order_by(JourneyRecoveryForecastModelRollbackEventRow.rolled_back_at.desc()).limit(10)).scalars().all()
            return {'active_policy':self._policy(p) if p else None,'probations':[self._prob(x) for x in probs],'rollback_events':[{'from_model_version_id':x.from_model_version_id,'to_model_version_id':x.to_model_version_id,'reason_codes':x.reason_codes_json,'supplier_fact_unchanged':True} for x in roll]}
    def policy(self,i):
        with SessionLocal() as s:return self._policy(s.get(JourneyRecoveryForecastPromotionPolicyRow,i))
    def _policy(self,x): return {'forecast_promotion_policy_id':x.forecast_promotion_policy_id,'environment':x.environment,'version_no':x.version_no,'minimum_sample_count':x.minimum_sample_count,'significance_alpha':x.significance_alpha,'minimum_effect_size_pct':x.minimum_effect_size_pct,'stability_evaluations_required':x.stability_evaluations_required,'required_segments':x.required_segments_json,'probation_seconds':x.probation_seconds,'state':x.state,'supplier_fact_unchanged':True}
    def _assessment(self,x): return {'forecast_statistical_assessment_id':x.forecast_statistical_assessment_id,'horizon_hours':x.horizon_hours,'segment_key':x.segment_key,'sample_count':x.sample_count,'effect_size_pct':x.effect_size_pct,'z_score':x.z_score,'p_value':x.p_value,'significance_state':x.significance_state,'reason_codes':x.reason_codes_json,'supplier_fact_unchanged':True}
    def _prob(self,x): return {'forecast_promotion_probation_id':x.forecast_promotion_probation_id,'promoted_model_version_id':x.promoted_model_version_id,'previous_champion_model_version_id':x.previous_champion_model_version_id,'state':x.state,'probation_until':x.probation_until.isoformat(),'rollback_reason_codes':x.rollback_reason_codes_json,'supplier_fact_unchanged':True}

recovery_forecast_statistical_promotion_service=RecoveryForecastStatisticalPromotionService()
