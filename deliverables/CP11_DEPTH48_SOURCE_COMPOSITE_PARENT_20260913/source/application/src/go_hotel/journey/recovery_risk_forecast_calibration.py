from datetime import datetime, timezone, timedelta
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import *

def now(): return datetime.now(timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'

def _prob(f):
    return 0.9 if f.forecast_state=='BREACH' else (0.55 if f.forecast_state=='WATCH' else 0.1)

class RecoveryRiskForecastCalibrationService:
    def active_model_in_session(self,s,environment):
        try:
            role=s.execute(select(JourneyRecoveryForecastModelRoleRow).where(JourneyRecoveryForecastModelRoleRow.environment==environment,JourneyRecoveryForecastModelRoleRow.role=='CHAMPION',JourneyRecoveryForecastModelRoleRow.state=='ACTIVE').order_by(JourneyRecoveryForecastModelRoleRow.assigned_at.desc())).scalars().first()
            if role:
                m=s.get(JourneyRecoveryRiskForecastModelVersionRow,role.model_version_id)
                if m:return m
        except Exception:
            pass
        return s.execute(select(JourneyRecoveryRiskForecastModelVersionRow).where(JourneyRecoveryRiskForecastModelVersionRow.environment==environment,JourneyRecoveryRiskForecastModelVersionRow.state.in_(['ACTIVE','DEGRADED'])).order_by(JourneyRecoveryRiskForecastModelVersionRow.version_no.desc())).scalars().first()
    def create_model(self,key,environment,algorithm,parameters,conservative_parameters,minimum_samples,max_mae,max_brier,max_fp,max_fn,max_drift,actor):
        if minimum_samples<2 or min(max_mae,max_brier,max_fp,max_fn,max_drift)<0: raise ValueError('INVALID_FORECAST_MODEL_GOVERNANCE')
        with SessionLocal() as s:
            prev=s.execute(select(JourneyRecoveryRiskForecastModelVersionRow).where(JourneyRecoveryRiskForecastModelVersionRow.model_key==key,JourneyRecoveryRiskForecastModelVersionRow.environment==environment).order_by(JourneyRecoveryRiskForecastModelVersionRow.version_no.desc())).scalars().first()
            x=JourneyRecoveryRiskForecastModelVersionRow(risk_forecast_model_version_id=nid('jrfm'),model_key=key,version_no=(prev.version_no+1 if prev else 1),environment=environment,algorithm_key=algorithm,parameters_json=parameters or {'growth_multiplier':1.0},conservative_parameters_json=conservative_parameters or {'growth_multiplier':1.5,'minimum_growth':0.08},minimum_samples=minimum_samples,max_mae_points=max_mae,max_brier_score=max_brier,max_false_positive_rate=max_fp,max_false_negative_rate=max_fn,max_capacity_drift_pct=max_drift,requested_by=actor,board_approver_one=None,board_approver_two=None,state='PENDING_APPROVAL',created_at=now(),supplier_fact_unchanged=True)
            s.add(x);self._event(s,environment,'MODEL_VERSION_CREATED',actor,{'model_key':key,'version_no':x.version_no},x.risk_forecast_model_version_id);s.commit();return self.model(x.risk_forecast_model_version_id)
    def approve_model(self,i,actor):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryRiskForecastModelVersionRow,i)
            if not x: raise ValueError('FORECAST_MODEL_VERSION_NOT_FOUND')
            if actor==x.requested_by: raise ValueError('FORECAST_MODEL_MAKER_CHECKER_REQUIRED')
            if not x.board_approver_one: x.board_approver_one=actor;x.state='AWAITING_SECOND_APPROVAL'
            elif x.board_approver_one==actor: raise ValueError('FORECAST_MODEL_TWO_DISTINCT_APPROVERS_REQUIRED')
            elif not x.board_approver_two:
                x.board_approver_two=actor
                for y in s.execute(select(JourneyRecoveryRiskForecastModelVersionRow).where(JourneyRecoveryRiskForecastModelVersionRow.environment==x.environment,JourneyRecoveryRiskForecastModelVersionRow.state.in_(['ACTIVE','DEGRADED']))).scalars().all(): y.state='SUPERSEDED'
                x.state='ACTIVE';self._event(s,x.environment,'MODEL_VERSION_ACTIVATED',actor,{},x.risk_forecast_model_version_id)
            s.commit();return self.model(i)
    def record_outcome(self,forecast_id,actual_exposure,evidence,observed_at=None):
        if actual_exposure<0 or not evidence: raise ValueError('INVALID_FORECAST_OUTCOME')
        with SessionLocal() as s:
            f=s.get(JourneyRecoveryRiskForecastRow,forecast_id)
            if not f: raise ValueError('RISK_FORECAST_NOT_FOUND')
            existing=s.execute(select(JourneyRecoveryRiskForecastOutcomeRow).where(JourneyRecoveryRiskForecastOutcomeRow.risk_forecast_id==forecast_id)).scalars().first()
            if existing: return self._outcome(existing)
            from go_hotel.journey.recovery_enterprise_risk_appetite import recovery_enterprise_risk_appetite_service as ap
            appetite=ap.active_appetite_in_session(s,f.environment)
            if not appetite: raise ValueError('ACTIVE_RISK_APPETITE_REQUIRED')
            p=_prob(f);actual_breach=actual_exposure>appetite.max_current_exposure_points
            model_version_id=(f.inputs_json or {}).get('forecast_model_version_id')
            o=JourneyRecoveryRiskForecastOutcomeRow(risk_forecast_outcome_id=nid('jrfo'),environment=f.environment,risk_forecast_id=f.risk_forecast_id,risk_forecast_model_version_id=model_version_id,horizon_hours=f.horizon_hours,predicted_exposure_points=f.projected_exposure_points,predicted_breach_probability=p,actual_exposure_points=actual_exposure,actual_breach=actual_breach,absolute_error_points=abs(f.projected_exposure_points-actual_exposure),squared_probability_error=(p-(1.0 if actual_breach else 0.0))**2,observed_at=observed_at or now(),evidence_json=evidence,supplier_fact_unchanged=True);s.add(o);s.flush()
            caps=s.execute(select(JourneyRecoveryDynamicRiskCapacityRow).where(JourneyRecoveryDynamicRiskCapacityRow.risk_forecast_id==forecast_id)).scalars().all()
            total_proj=sum(max(0,c.projected_exposure_points) for c in caps) or 1
            for c in caps:
                actual=actual_exposure*(max(0,c.projected_exposure_points)/total_proj)
                drift=abs(actual-c.projected_exposure_points)/max(c.allocated_capacity_points,1)*100
                s.add(JourneyRecoveryRiskCapacityAllocationDriftRow(risk_capacity_allocation_drift_id=nid('jrcd'),environment=f.environment,risk_forecast_id=forecast_id,dimension=c.dimension,dimension_key=c.dimension_key,allocated_capacity_points=c.allocated_capacity_points,projected_exposure_points=c.projected_exposure_points,actual_exposure_points=round(actual,4),allocation_drift_pct=round(drift,4),drift_state=('DRIFTED' if drift>=20 else 'STABLE'),observed_at=o.observed_at,supplier_fact_unchanged=True))
            self._event(s,f.environment,'FORECAST_OUTCOME_OBSERVED','forecast-outcome',{'actual_exposure_points':actual_exposure,'actual_breach':actual_breach},None,None)
            s.commit();return self.outcome(o.risk_forecast_outcome_id)
    def assess(self,environment,horizon_hours,actor='forecast-calibration-engine'):
        if horizon_hours not in (24,168): raise ValueError('UNSUPPORTED_FORECAST_HORIZON')
        with SessionLocal() as s:
            model=self.active_model_in_session(s,environment)
            if not model: raise ValueError('ACTIVE_FORECAST_MODEL_VERSION_REQUIRED')
            rows=s.execute(select(JourneyRecoveryRiskForecastOutcomeRow).where(JourneyRecoveryRiskForecastOutcomeRow.environment==environment,JourneyRecoveryRiskForecastOutcomeRow.horizon_hours==horizon_hours,JourneyRecoveryRiskForecastOutcomeRow.risk_forecast_model_version_id==model.risk_forecast_model_version_id)).scalars().all()
            n=len(rows)
            mae=sum(x.absolute_error_points for x in rows)/n if n else 0
            brier=sum(x.squared_probability_error for x in rows)/n if n else 0
            fp=sum(1 for x in rows if x.predicted_breach_probability>=0.5 and not x.actual_breach); pred_pos=sum(1 for x in rows if x.predicted_breach_probability>=0.5)
            fn=sum(1 for x in rows if x.predicted_breach_probability<0.5 and x.actual_breach); actual_pos=sum(1 for x in rows if x.actual_breach)
            fpr=fp/max(1,pred_pos);fnr=fn/max(1,actual_pos)
            pred_rate=sum(x.predicted_breach_probability for x in rows)/n if n else 0;actual_rate=sum(1 for x in rows if x.actual_breach)/n if n else 0;cal_err=abs(pred_rate-actual_rate)*100
            fids=[x.risk_forecast_id for x in rows]
            drift_rows=s.execute(select(JourneyRecoveryRiskCapacityAllocationDriftRow).where(JourneyRecoveryRiskCapacityAllocationDriftRow.risk_forecast_id.in_(fids))).scalars().all() if fids else []
            drift=sum(x.allocation_drift_pct for x in drift_rows)/len(drift_rows) if drift_rows else 0
            reasons=[]
            if n<model.minimum_samples:reasons.append('MINIMUM_CALIBRATION_SAMPLE_NOT_MET')
            if n>=model.minimum_samples:
                if mae>model.max_mae_points:reasons.append('FORECAST_MAE_LIMIT_EXCEEDED')
                if brier>model.max_brier_score:reasons.append('FORECAST_BRIER_LIMIT_EXCEEDED')
                if fpr>model.max_false_positive_rate:reasons.append('FORECAST_FALSE_POSITIVE_LIMIT_EXCEEDED')
                if fnr>model.max_false_negative_rate:reasons.append('FORECAST_FALSE_NEGATIVE_LIMIT_EXCEEDED')
                if drift>model.max_capacity_drift_pct:reasons.append('CAPACITY_ALLOCATION_DRIFT_LIMIT_EXCEEDED')
            state='INSUFFICIENT_DATA' if n<model.minimum_samples else ('DEGRADED' if reasons else 'PASS')
            a=JourneyRecoveryRiskForecastAccuracyAssessmentRow(risk_forecast_accuracy_assessment_id=nid('jrfa'),environment=environment,risk_forecast_model_version_id=model.risk_forecast_model_version_id,horizon_hours=horizon_hours,sample_count=n,mae_points=round(mae,4),brier_score=round(brier,6),false_positive_rate=round(fpr,6),false_negative_rate=round(fnr,6),mean_capacity_drift_pct=round(drift,4),calibration_error_pct=round(cal_err,4),accuracy_state=state,reason_codes_json=reasons,evaluated_at=now(),supplier_fact_unchanged=True);s.add(a);s.flush()
            cal=JourneyRecoveryRiskForecastCalibrationRow(risk_forecast_calibration_id=nid('jrcl'),environment=environment,risk_forecast_model_version_id=model.risk_forecast_model_version_id,horizon_hours=horizon_hours,sample_count=n,predicted_breach_rate=round(pred_rate,6),actual_breach_rate=round(actual_rate,6),calibration_error_pct=round(cal_err,4),calibration_state=('CALIBRATED' if state=='PASS' else state),valid_until=now()+timedelta(days=14),created_at=now(),supplier_fact_unchanged=True);s.add(cal)
            if state=='DEGRADED':
                model.state='DEGRADED'
                ctrl=s.execute(select(JourneyRecoveryRiskForecastSafetyControlRow).where(JourneyRecoveryRiskForecastSafetyControlRow.environment==environment,JourneyRecoveryRiskForecastSafetyControlRow.state=='ACTIVE')).scalars().first()
                if not ctrl:
                    ctrl=JourneyRecoveryRiskForecastSafetyControlRow(risk_forecast_safety_control_id=nid('jrsc'),environment=environment,risk_forecast_model_version_id=model.risk_forecast_model_version_id,control_mode='CONSERVATIVE_BASELINE',source_accuracy_assessment_id=a.risk_forecast_accuracy_assessment_id,reason_codes_json=reasons,state='ACTIVE',activated_at=now(),released_at=None,release_evidence_reference=None,supplier_fact_unchanged=True);s.add(ctrl)
                    self._event(s,environment,'CONSERVATIVE_BASELINE_ACTIVATED',actor,{'reason_codes':reasons},model.risk_forecast_model_version_id,a.risk_forecast_accuracy_assessment_id)
            self._event(s,environment,'FORECAST_ACCURACY_ASSESSED',actor,{'horizon_hours':horizon_hours,'state':state,'sample_count':n},model.risk_forecast_model_version_id,a.risk_forecast_accuracy_assessment_id)
            s.commit();return self.assessment(a.risk_forecast_accuracy_assessment_id)
    def runtime_governance(self,environment):
        with SessionLocal() as s:
            m=self.active_model_in_session(s,environment)
            if not m:return {'mode':'LEGACY','growth_multiplier':1.0,'minimum_growth':0.0,'model_version_id':None}
            ctrl=s.execute(select(JourneyRecoveryRiskForecastSafetyControlRow).where(JourneyRecoveryRiskForecastSafetyControlRow.environment==environment,JourneyRecoveryRiskForecastSafetyControlRow.state=='ACTIVE')).scalars().first()
            pars=m.conservative_parameters_json if ctrl else m.parameters_json
            return {'mode':'CONSERVATIVE_BASELINE' if ctrl else 'GOVERNED_MODEL','growth_multiplier':float(pars.get('growth_multiplier',1.0)),'minimum_growth':float(pars.get('minimum_growth',0.0)),'model_version_id':m.risk_forecast_model_version_id}
    def release_conservative(self,environment,evidence,actor):
        if not evidence: raise ValueError('FORECAST_BASELINE_RELEASE_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            m=self.active_model_in_session(s,environment);ctrl=s.execute(select(JourneyRecoveryRiskForecastSafetyControlRow).where(JourneyRecoveryRiskForecastSafetyControlRow.environment==environment,JourneyRecoveryRiskForecastSafetyControlRow.state=='ACTIVE')).scalars().first()
            if not m or not ctrl: raise ValueError('ACTIVE_CONSERVATIVE_BASELINE_NOT_FOUND')
            latest={}
            for h in (24,168): latest[h]=s.execute(select(JourneyRecoveryRiskForecastAccuracyAssessmentRow).where(JourneyRecoveryRiskForecastAccuracyAssessmentRow.environment==environment,JourneyRecoveryRiskForecastAccuracyAssessmentRow.horizon_hours==h).order_by(JourneyRecoveryRiskForecastAccuracyAssessmentRow.evaluated_at.desc())).scalars().first()
            if any(not x or x.accuracy_state!='PASS' for x in latest.values()): raise ValueError('FORECAST_BASELINE_RELEASE_ACCURACY_NOT_RECOVERED')
            ctrl.state='RELEASED';ctrl.released_at=now();ctrl.release_evidence_reference=evidence;m.state='ACTIVE';self._event(s,environment,'CONSERVATIVE_BASELINE_RELEASED',actor,{'evidence_reference':evidence},m.risk_forecast_model_version_id,None);s.commit();return {'state':'RELEASED','supplier_fact_unchanged':True}
    def status(self,environment):
        with SessionLocal() as s:
            ms=s.execute(select(JourneyRecoveryRiskForecastModelVersionRow).where(JourneyRecoveryRiskForecastModelVersionRow.environment==environment).order_by(JourneyRecoveryRiskForecastModelVersionRow.version_no.desc()).limit(10)).scalars().all();ass=s.execute(select(JourneyRecoveryRiskForecastAccuracyAssessmentRow).where(JourneyRecoveryRiskForecastAccuracyAssessmentRow.environment==environment).order_by(JourneyRecoveryRiskForecastAccuracyAssessmentRow.evaluated_at.desc()).limit(20)).scalars().all();cals=s.execute(select(JourneyRecoveryRiskForecastCalibrationRow).where(JourneyRecoveryRiskForecastCalibrationRow.environment==environment).order_by(JourneyRecoveryRiskForecastCalibrationRow.created_at.desc()).limit(20)).scalars().all();ctrl=s.execute(select(JourneyRecoveryRiskForecastSafetyControlRow).where(JourneyRecoveryRiskForecastSafetyControlRow.environment==environment).order_by(JourneyRecoveryRiskForecastSafetyControlRow.activated_at.desc()).limit(10)).scalars().all()
            return {'runtime_governance':self.runtime_governance(environment),'models':[self._model(x) for x in ms],'accuracy_assessments':[self._assessment(x) for x in ass],'calibrations':[self._cal(x) for x in cals],'safety_controls':[self._ctrl(x) for x in ctrl]}
    def _event(self,s,e,t,actor,evidence,model=None,assessment=None): s.add(JourneyRecoveryRiskForecastCalibrationEventRow(risk_forecast_calibration_event_id=nid('jrfce'),environment=e,event_type=t,model_version_id=model,accuracy_assessment_id=assessment,evidence_json=evidence or {},actor=actor,created_at=now(),supplier_fact_unchanged=True))
    def model(self,i):
        with SessionLocal() as s:return self._model(s.get(JourneyRecoveryRiskForecastModelVersionRow,i))
    def outcome(self,i):
        with SessionLocal() as s:return self._outcome(s.get(JourneyRecoveryRiskForecastOutcomeRow,i))
    def assessment(self,i):
        with SessionLocal() as s:return self._assessment(s.get(JourneyRecoveryRiskForecastAccuracyAssessmentRow,i))
    def _model(self,x):return {'risk_forecast_model_version_id':x.risk_forecast_model_version_id,'model_key':x.model_key,'version_no':x.version_no,'environment':x.environment,'algorithm_key':x.algorithm_key,'minimum_samples':x.minimum_samples,'state':x.state,'supplier_fact_unchanged':True}
    def _outcome(self,x):return {'risk_forecast_outcome_id':x.risk_forecast_outcome_id,'risk_forecast_id':x.risk_forecast_id,'horizon_hours':x.horizon_hours,'predicted_exposure_points':x.predicted_exposure_points,'actual_exposure_points':x.actual_exposure_points,'actual_breach':x.actual_breach,'absolute_error_points':x.absolute_error_points,'supplier_fact_unchanged':True}
    def _assessment(self,x):return {'risk_forecast_accuracy_assessment_id':x.risk_forecast_accuracy_assessment_id,'horizon_hours':x.horizon_hours,'sample_count':x.sample_count,'mae_points':x.mae_points,'brier_score':x.brier_score,'false_positive_rate':x.false_positive_rate,'false_negative_rate':x.false_negative_rate,'mean_capacity_drift_pct':x.mean_capacity_drift_pct,'calibration_error_pct':x.calibration_error_pct,'accuracy_state':x.accuracy_state,'reason_codes':x.reason_codes_json,'supplier_fact_unchanged':True}
    def _cal(self,x):return {'risk_forecast_calibration_id':x.risk_forecast_calibration_id,'horizon_hours':x.horizon_hours,'sample_count':x.sample_count,'predicted_breach_rate':x.predicted_breach_rate,'actual_breach_rate':x.actual_breach_rate,'calibration_error_pct':x.calibration_error_pct,'calibration_state':x.calibration_state,'valid_until':x.valid_until.isoformat(),'supplier_fact_unchanged':True}
    def _ctrl(self,x):return {'risk_forecast_safety_control_id':x.risk_forecast_safety_control_id,'control_mode':x.control_mode,'reason_codes':x.reason_codes_json,'state':x.state,'supplier_fact_unchanged':True}

recovery_risk_forecast_calibration_service=RecoveryRiskForecastCalibrationService()
