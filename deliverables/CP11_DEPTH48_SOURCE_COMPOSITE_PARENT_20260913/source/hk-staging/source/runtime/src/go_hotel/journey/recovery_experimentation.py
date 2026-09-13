from __future__ import annotations
from datetime import datetime,timezone
from hashlib import sha256
from math import erf,sqrt
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoveryExperimentRow,JourneyRecoveryExperimentObservationRow,JourneyRecoveryExperimentDecisionRow,JourneyRecoveryCalibrationProfileRow,JourneyRecoveryStrategyVersionRow

def now(): return datetime.now(timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'
DEFAULT_GATE={'min_confirmation_lift':0.0,'max_timeout_delta':0.05,'max_manual_review_delta':0.05,'require_significance':True,'require_strata_coverage':True}

class RecoveryExperimentationService:
    def create(self,name,control_strategy_version_id,candidate_strategy_version_id,allocation_percent=10,min_sample_per_arm=30,alpha=.05,primary_metric='confirmation_rate',stratification=None,promotion_gate=None):
        with SessionLocal() as s:
            if not s.get(JourneyRecoveryStrategyVersionRow,control_strategy_version_id): raise ValueError('CONTROL_STRATEGY_NOT_FOUND')
            if not s.get(JourneyRecoveryStrategyVersionRow,candidate_strategy_version_id): raise ValueError('CANDIDATE_STRATEGY_NOT_FOUND')
            t=now();r=JourneyRecoveryExperimentRow(experiment_id=nid('jrex'),name=name,state='DRAFT',control_strategy_version_id=control_strategy_version_id,candidate_strategy_version_id=candidate_strategy_version_id,allocation_percent=max(1,min(50,allocation_percent)),min_sample_per_arm=max(5,min_sample_per_arm),significance_alpha=alpha,primary_metric=primary_metric,stratification_json=stratification or {'dimensions':['vertical','adapter_key']},promotion_gate_json={**DEFAULT_GATE,**(promotion_gate or {})},created_at=t,updated_at=t);s.add(r);s.commit();return r.experiment_id
    def approve(self,id,actor):
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryExperimentRow,id)
            if not r: raise ValueError('EXPERIMENT_NOT_FOUND')
            r.approved_by=actor;r.approved_at=now();r.updated_at=now();s.commit();return id
    def start(self,id,actor):
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryExperimentRow,id)
            if not r: raise ValueError('EXPERIMENT_NOT_FOUND')
            if not r.approved_at: raise ValueError('EXPERIMENT_APPROVAL_REQUIRED')
            cand=s.get(JourneyRecoveryStrategyVersionRow,r.candidate_strategy_version_id)
            if not cand or not cand.approved_at: raise ValueError('CANDIDATE_STRATEGY_APPROVAL_REQUIRED')
            r.state='RUNNING';r.started_at=now();r.updated_at=now();s.commit();return id
    def assign(self,id,execution_item_id):
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryExperimentRow,id)
            if not r or r.state!='RUNNING': return 'CONTROL'
            bucket=int(sha256(f'{id}:{execution_item_id}'.encode()).hexdigest()[:8],16)%100
            return 'CANDIDATE' if bucket<r.allocation_percent else 'CONTROL'
    def observe(self,id,execution_item_id,arm,vertical=None,adapter_key=None,confirmed=False,timeout=False,manual_review=False,confirmation_seconds=None,metrics=None):
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryExperimentRow,id)
            if not r or r.state!='RUNNING': raise ValueError('EXPERIMENT_NOT_RUNNING')
            existing=s.execute(select(JourneyRecoveryExperimentObservationRow).where(JourneyRecoveryExperimentObservationRow.experiment_id==id,JourneyRecoveryExperimentObservationRow.execution_item_id==execution_item_id)).scalars().first()
            if existing:return existing.observation_id
            x=JourneyRecoveryExperimentObservationRow(observation_id=nid('jreo'),experiment_id=id,execution_item_id=execution_item_id,arm=arm,vertical=vertical,adapter_key=adapter_key,confirmed=confirmed,timeout=timeout,manual_review=manual_review,confirmation_seconds=confirmation_seconds,metrics_json=metrics or {},created_at=now());s.add(x);s.commit();return x.observation_id
    def _arm(self,obs,arm):
        xs=[x for x in obs if x.arm==arm];n=len(xs);return {'n':n,'confirmation_rate':sum(x.confirmed for x in xs)/n if n else 0.0,'timeout_rate':sum(x.timeout for x in xs)/n if n else 0.0,'manual_review_rate':sum(x.manual_review for x in xs)/n if n else 0.0,'avg_confirmation_seconds':sum(x.confirmation_seconds or 0 for x in xs if x.confirmation_seconds is not None)/max(1,sum(x.confirmation_seconds is not None for x in xs))}
    def _pvalue(self,a_success,a_n,b_success,b_n):
        if not a_n or not b_n:return 1.0
        p=(a_success+b_success)/(a_n+b_n);se=sqrt(max(1e-12,p*(1-p)*(1/a_n+1/b_n)));z=((b_success/b_n)-(a_success/a_n))/se
        return max(0.0,min(1.0,1-erf(abs(z)/sqrt(2))))
    def evaluate(self,id):
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryExperimentRow,id)
            if not r: raise ValueError('EXPERIMENT_NOT_FOUND')
            obs=s.execute(select(JourneyRecoveryExperimentObservationRow).where(JourneyRecoveryExperimentObservationRow.experiment_id==id)).scalars().all();c=self._arm(obs,'CONTROL');k=self._arm(obs,'CANDIDATE')
            p=self._pvalue(round(c['confirmation_rate']*c['n']),c['n'],round(k['confirmation_rate']*k['n']),k['n'])
            strata={}
            for x in obs:
                key=f'{x.vertical or "UNKNOWN"}|{x.adapter_key or "UNKNOWN"}';strata.setdefault(key,{'CONTROL':0,'CANDIDATE':0});strata[key][x.arm]=strata[key].get(x.arm,0)+1
            gate=r.promotion_gate_json or DEFAULT_GATE;reasons=[]
            enough=c['n']>=r.min_sample_per_arm and k['n']>=r.min_sample_per_arm
            if not enough:reasons.append('MIN_SAMPLE_PER_ARM_NOT_MET')
            significant=p<=r.significance_alpha
            if gate.get('require_significance') and not significant:reasons.append('SIGNIFICANCE_NOT_MET')
            if k['confirmation_rate']-c['confirmation_rate']<gate.get('min_confirmation_lift',0):reasons.append('CONFIRMATION_LIFT_NOT_MET')
            safety_bad=(k['timeout_rate']-c['timeout_rate']>gate.get('max_timeout_delta',.05) or k['manual_review_rate']-c['manual_review_rate']>gate.get('max_manual_review_delta',.05))
            if safety_bad:reasons.append('SAFETY_GUARDRAIL_BREACH')
            coverage=all(v.get('CONTROL',0)>0 and v.get('CANDIDATE',0)>0 for v in strata.values()) if strata else False
            if gate.get('require_strata_coverage') and not coverage:reasons.append('STRATA_COVERAGE_NOT_MET')
            decision='DEGRADE' if safety_bad else ('PROMOTE' if not reasons else 'CONTINUE')
            d=JourneyRecoveryExperimentDecisionRow(decision_id=nid('jred'),experiment_id=id,decision=decision,metrics_json={'control':c,'candidate':k},significance_json={'primary_metric':r.primary_metric,'p_value':p,'alpha':r.significance_alpha,'significant':significant},strata_json=strata,gate_results_json={'sample_ok':enough,'significance_ok':significant,'strata_coverage_ok':coverage,'safety_ok':not safety_bad},reason_codes_json=reasons,supplier_fact_unchanged=True,created_at=now());s.add(d)
            if decision=='DEGRADE':
                cand=s.get(JourneyRecoveryStrategyVersionRow,r.candidate_strategy_version_id)
                if cand and cand.state in {'CANARY','ACTIVE'}:cand.state='ROLLED_BACK';cand.rolled_back_at=now();cand.rollback_reason='EXPERIMENT_SAFETY_GUARDRAIL_BREACH';cand.updated_at=now()
                r.state='DEGRADED';r.ended_at=now();r.updated_at=now()
            elif decision=='PROMOTE':
                cand=s.get(JourneyRecoveryStrategyVersionRow,r.candidate_strategy_version_id)
                if cand:cand.state='ACTIVE';cand.rollout_percent=100;cand.activated_at=now();cand.updated_at=now()
                r.state='PROMOTED';r.ended_at=now();r.updated_at=now()
            s.commit();return {'decision':decision,'metrics':{'control':c,'candidate':k},'p_value':p,'strata':strata,'reasons':reasons,'supplier_fact_unchanged':True}
    def calibrate(self,id):
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryExperimentRow,id)
            if not r or r.state!='PROMOTED':raise ValueError('EXPERIMENT_NOT_PROMOTED')
            obs=s.execute(select(JourneyRecoveryExperimentObservationRow).where(JourneyRecoveryExperimentObservationRow.experiment_id==id,JourneyRecoveryExperimentObservationRow.arm=='CANDIDATE')).scalars().all();groups={}
            for x in obs:groups.setdefault((x.vertical or 'UNKNOWN',x.adapter_key or 'UNKNOWN'),[]).append(x)
            out=[]
            for (v,a),xs in groups.items():
                n=len(xs);confirmed=sum(x.confirmed for x in xs);timeout=sum(x.timeout for x in xs);manual=sum(x.manual_review for x in xs);cpid=f'cal_{sha256((v+"|"+a).encode()).hexdigest()[:24]}';row=s.get(JourneyRecoveryCalibrationProfileRow,cpid);t=now();params={'observed_confirmation_rate':confirmed/n,'observed_timeout_rate':timeout/n,'observed_manual_review_rate':manual/n}
                if not row:row=JourneyRecoveryCalibrationProfileRow(calibration_profile_id=cpid,vertical=v,adapter_key=a,sample_count=n,source_experiment_id=id,calibrated_parameters_json=params,confidence_json={'sample_count':n,'production_calibrated':n>=r.min_sample_per_arm},state='CALIBRATED' if n>=r.min_sample_per_arm else 'PROVISIONAL',created_at=t,updated_at=t);s.add(row)
                else:row.sample_count=n;row.source_experiment_id=id;row.calibrated_parameters_json=params;row.confidence_json={'sample_count':n,'production_calibrated':n>=r.min_sample_per_arm};row.state='CALIBRATED' if n>=r.min_sample_per_arm else 'PROVISIONAL';row.updated_at=t
                out.append({'vertical':v,'adapter_key':a,'sample_count':n,'state':row.state,'parameters':params})
            s.commit();return out
    def list_experiments(self):
        with SessionLocal() as s:return [{'experiment_id':x.experiment_id,'name':x.name,'state':x.state,'control_strategy_version_id':x.control_strategy_version_id,'candidate_strategy_version_id':x.candidate_strategy_version_id,'allocation_percent':x.allocation_percent,'min_sample_per_arm':x.min_sample_per_arm,'primary_metric':x.primary_metric,'approved_by':x.approved_by} for x in s.execute(select(JourneyRecoveryExperimentRow).order_by(JourneyRecoveryExperimentRow.created_at.desc())).scalars().all()]
    def decisions(self,limit=100):
        with SessionLocal() as s:return [{'decision_id':x.decision_id,'experiment_id':x.experiment_id,'decision':x.decision,'metrics':x.metrics_json,'significance':x.significance_json,'strata':x.strata_json,'gate_results':x.gate_results_json,'reason_codes':x.reason_codes_json,'supplier_fact_unchanged':x.supplier_fact_unchanged} for x in s.execute(select(JourneyRecoveryExperimentDecisionRow).order_by(JourneyRecoveryExperimentDecisionRow.created_at.desc()).limit(limit)).scalars().all()]
    def calibrations(self):
        with SessionLocal() as s:return [{'calibration_profile_id':x.calibration_profile_id,'vertical':x.vertical,'adapter_key':x.adapter_key,'sample_count':x.sample_count,'source_experiment_id':x.source_experiment_id,'state':x.state,'parameters':x.calibrated_parameters_json,'confidence':x.confidence_json} for x in s.execute(select(JourneyRecoveryCalibrationProfileRow).order_by(JourneyRecoveryCalibrationProfileRow.updated_at.desc())).scalars().all()]
recovery_experimentation_service=RecoveryExperimentationService()
