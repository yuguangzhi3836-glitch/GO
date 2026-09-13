from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import *

def now(): return datetime.now(timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'

class RecoveryForecastModelPromotionService:
    def assign_role(self,environment,model_id,role,actor='risk-model-governance'):
        if role not in ('CHAMPION','CHALLENGER'): raise ValueError('INVALID_MODEL_ROLE')
        with SessionLocal() as s:
            m=s.get(JourneyRecoveryRiskForecastModelVersionRow,model_id)
            if not m or m.environment!=environment: raise ValueError('FORECAST_MODEL_VERSION_NOT_FOUND')
            if role=='CHAMPION':
                for r in s.execute(select(JourneyRecoveryForecastModelRoleRow).where(JourneyRecoveryForecastModelRoleRow.environment==environment,JourneyRecoveryForecastModelRoleRow.role=='CHAMPION',JourneyRecoveryForecastModelRoleRow.state=='ACTIVE')).scalars().all(): r.state='SUPERSEDED'
            x=JourneyRecoveryForecastModelRoleRow(forecast_model_role_id=nid('jfmr'),environment=environment,model_version_id=model_id,role=role,state='ACTIVE',assigned_at=now(),supplier_fact_unchanged=True);s.add(x);s.commit();return self.role(x.forecast_model_role_id)
    def backtest(self,environment,champion_id,challenger_id,window_key='ROLLING_30D',segments=None):
        segments=segments or ['ALL']; horizons=[24,168]
        with SessionLocal() as s:
            try:
                from go_hotel.journey.recovery_forecast_training_governance import recovery_forecast_training_governance_service as training
                training.assert_challenger_eligible_in_session(s,environment,challenger_id)
            except ImportError:
                pass
            try:
                from go_hotel.journey.recovery_forecast_artifact_governance import recovery_forecast_artifact_governance_service as artifacts
                artifacts.assert_artifact_eligible_in_session(s,environment,challenger_id)
            except ImportError:
                pass
            run=JourneyRecoveryForecastBacktestRunRow(forecast_backtest_run_id=nid('jfbr'),environment=environment,champion_model_version_id=champion_id,challenger_model_version_id=challenger_id,window_key=window_key,horizons_json=horizons,segments_json=segments,state='COMPLETED',created_at=now(),supplier_fact_unchanged=True);s.add(run);s.flush()
            for mid in (champion_id,challenger_id):
                for h in horizons:
                    rows=s.execute(select(JourneyRecoveryRiskForecastOutcomeRow).where(JourneyRecoveryRiskForecastOutcomeRow.environment==environment,JourneyRecoveryRiskForecastOutcomeRow.risk_forecast_model_version_id==mid,JourneyRecoveryRiskForecastOutcomeRow.horizon_hours==h)).scalars().all()
                    n=len(rows); mae=sum(x.absolute_error_points for x in rows)/n if n else 999; brier=sum(x.squared_probability_error for x in rows)/n if n else 1
                    fp=sum(1 for x in rows if x.predicted_breach_probability>=.5 and not x.actual_breach); pp=sum(1 for x in rows if x.predicted_breach_probability>=.5)
                    fn=sum(1 for x in rows if x.predicted_breach_probability<.5 and x.actual_breach); ap=sum(1 for x in rows if x.actual_breach)
                    fpr=fp/max(1,pp); fnr=fn/max(1,ap)
                    fids=[x.risk_forecast_id for x in rows]; dr=s.execute(select(JourneyRecoveryRiskCapacityAllocationDriftRow).where(JourneyRecoveryRiskCapacityAllocationDriftRow.risk_forecast_id.in_(fids))).scalars().all() if fids else []
                    drift=sum(x.allocation_drift_pct for x in dr)/len(dr) if dr else 0
                    for seg in segments:s.add(JourneyRecoveryForecastBacktestMetricRow(forecast_backtest_metric_id=nid('jfbm'),forecast_backtest_run_id=run.forecast_backtest_run_id,model_version_id=mid,horizon_hours=h,segment_key=seg,sample_count=n,mae_points=round(mae,4),brier_score=round(brier,6),false_positive_rate=round(fpr,6),false_negative_rate=round(fnr,6),capacity_drift_pct=round(drift,4),supplier_fact_unchanged=True))
            s.commit();return self.run(run.forecast_backtest_run_id)
    def shadow(self,environment,challenger_id,horizon,segment='ALL'):
        with SessionLocal() as s:
            champ=s.execute(select(JourneyRecoveryForecastModelRoleRow).where(JourneyRecoveryForecastModelRoleRow.environment==environment,JourneyRecoveryForecastModelRoleRow.role=='CHAMPION',JourneyRecoveryForecastModelRoleRow.state=='ACTIVE')).scalars().first()
            if not champ: raise ValueError('ACTIVE_CHAMPION_REQUIRED')
            def metric(mid):
                a=s.execute(select(JourneyRecoveryRiskForecastAccuracyAssessmentRow).where(JourneyRecoveryRiskForecastAccuracyAssessmentRow.environment==environment,JourneyRecoveryRiskForecastAccuracyAssessmentRow.risk_forecast_model_version_id==mid,JourneyRecoveryRiskForecastAccuracyAssessmentRow.horizon_hours==horizon).order_by(JourneyRecoveryRiskForecastAccuracyAssessmentRow.evaluated_at.desc())).scalars().first();return a
            c=metric(champ.model_version_id); q=metric(challenger_id)
            if not c or not q: raise ValueError('ACCURACY_EVIDENCE_REQUIRED')
            improvement=((c.mae_points-q.mae_points)/max(c.mae_points,0.0001))*100; safety=max(q.false_positive_rate-c.false_positive_rate,q.false_negative_rate-c.false_negative_rate,q.mean_capacity_drift_pct-c.mean_capacity_drift_pct)
            st='PASS' if improvement>0 and safety<=0 else 'FAIL'
            x=JourneyRecoveryForecastShadowEvaluationRow(forecast_shadow_evaluation_id=nid('jfse'),environment=environment,challenger_model_version_id=challenger_id,horizon_hours=horizon,segment_key=segment,sample_count=min(c.sample_count,q.sample_count),improvement_pct=round(improvement,4),safety_delta_pct=round(safety,4),evaluation_state=st,created_at=now(),supplier_fact_unchanged=True);s.add(x);s.commit();return self.shadow_get(x.forecast_shadow_evaluation_id)
    def promote(self,environment,challenger_id,evidence):
        if not evidence: raise ValueError('MODEL_PROMOTION_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            try:
                from go_hotel.journey.recovery_forecast_statistical_promotion import recovery_forecast_statistical_promotion_service as stat
                if stat.active_policy_in_session(s,environment): raise ValueError('STATISTICAL_PROMOTION_GOVERNANCE_REQUIRED')
            except ImportError:
                pass
            try:
                from go_hotel.journey.recovery_forecast_artifact_governance import recovery_forecast_artifact_governance_service as artifacts
                artifacts.assert_artifact_eligible_in_session(s,environment,challenger_id)
            except ImportError:
                pass
            champ=s.execute(select(JourneyRecoveryForecastModelRoleRow).where(JourneyRecoveryForecastModelRoleRow.environment==environment,JourneyRecoveryForecastModelRoleRow.role=='CHAMPION',JourneyRecoveryForecastModelRoleRow.state=='ACTIVE')).scalars().first()
            if not champ: raise ValueError('ACTIVE_CHAMPION_REQUIRED')
            evals=s.execute(select(JourneyRecoveryForecastShadowEvaluationRow).where(JourneyRecoveryForecastShadowEvaluationRow.environment==environment,JourneyRecoveryForecastShadowEvaluationRow.challenger_model_version_id==challenger_id)).scalars().all()
            reasons=[]
            for h in (24,168):
                e=[x for x in evals if x.horizon_hours==h and x.evaluation_state=='PASS']
                if not e: reasons.append(f'HORIZON_{h}_SHADOW_PASS_REQUIRED')
            if any(x.safety_delta_pct>0 for x in evals): reasons.append('SAFETY_METRIC_DEGRADED')
            decision='BLOCKED' if reasons else 'PROMOTED'
            d=JourneyRecoveryForecastPromotionDecisionRow(forecast_promotion_decision_id=nid('jfpd'),environment=environment,champion_model_version_id=champ.model_version_id,challenger_model_version_id=challenger_id,decision=decision,reason_codes_json=reasons,evidence_json=evidence,decided_at=now(),supplier_fact_unchanged=True);s.add(d)
            if not reasons:
                champ.state='SUPERSEDED'
                s.add(JourneyRecoveryForecastModelRoleRow(forecast_model_role_id=nid('jfmr'),environment=environment,model_version_id=challenger_id,role='CHAMPION',state='ACTIVE',assigned_at=now(),supplier_fact_unchanged=True))
            s.commit();return self.decision(d.forecast_promotion_decision_id)
    def status(self,environment):
        with SessionLocal() as s:
            return {'roles':[self._role(x) for x in s.execute(select(JourneyRecoveryForecastModelRoleRow).where(JourneyRecoveryForecastModelRoleRow.environment==environment)).scalars().all()],'decisions':[self._decision(x) for x in s.execute(select(JourneyRecoveryForecastPromotionDecisionRow).where(JourneyRecoveryForecastPromotionDecisionRow.environment==environment).order_by(JourneyRecoveryForecastPromotionDecisionRow.decided_at.desc())).scalars().all()]}
    def role(self,i):
        with SessionLocal() as s:return self._role(s.get(JourneyRecoveryForecastModelRoleRow,i))
    def run(self,i):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryForecastBacktestRunRow,i);ms=s.execute(select(JourneyRecoveryForecastBacktestMetricRow).where(JourneyRecoveryForecastBacktestMetricRow.forecast_backtest_run_id==i)).scalars().all();return {'forecast_backtest_run_id':i,'state':x.state,'metrics':[{'model_version_id':m.model_version_id,'horizon_hours':m.horizon_hours,'segment_key':m.segment_key,'sample_count':m.sample_count,'mae_points':m.mae_points,'brier_score':m.brier_score} for m in ms],'supplier_fact_unchanged':True}
    def shadow_get(self,i):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryForecastShadowEvaluationRow,i);return {'forecast_shadow_evaluation_id':i,'horizon_hours':x.horizon_hours,'segment_key':x.segment_key,'sample_count':x.sample_count,'improvement_pct':x.improvement_pct,'safety_delta_pct':x.safety_delta_pct,'evaluation_state':x.evaluation_state,'supplier_fact_unchanged':True}
    def decision(self,i):
        with SessionLocal() as s:return self._decision(s.get(JourneyRecoveryForecastPromotionDecisionRow,i))
    def _role(self,x):return {'forecast_model_role_id':x.forecast_model_role_id,'model_version_id':x.model_version_id,'role':x.role,'state':x.state,'supplier_fact_unchanged':True}
    def _decision(self,x):return {'forecast_promotion_decision_id':x.forecast_promotion_decision_id,'decision':x.decision,'reason_codes':x.reason_codes_json,'challenger_model_version_id':x.challenger_model_version_id,'supplier_fact_unchanged':True}
recovery_forecast_model_promotion_service=RecoveryForecastModelPromotionService()
