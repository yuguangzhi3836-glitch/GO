from __future__ import annotations
from datetime import datetime,timezone
from math import sqrt
from hashlib import sha256
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoveryStrategyVersionRow,JourneyRecoveryStrategyEvaluationRow
from go_hotel.journey.recovery_data_governance import recovery_data_governance_service

def now():return datetime.now(timezone.utc)
def nid(p):return f'{p}_{uuid4().hex[:18]}'
BASE={'initial_poll_seconds':0,'max_poll_seconds':300,'max_attempts':8,'ack_multiplier':1.0,'resolution_multiplier':1.0}
BOUNDS={'initial_poll_seconds':[5,60],'max_poll_seconds':[60,900],'max_attempts':[6,15],'ack_multiplier':[0.5,1.2],'resolution_multiplier':[0.8,2.0]}
ROLLBACK={'timeout_upper':0.65,'manual_review_upper':0.55,'min_evaluations':5}
class RecoveryStrategyGovernanceService:
    def bootstrap(self,s):
        if not s.get(JourneyRecoveryStrategyVersionRow,'recovery_guardrail_v1'):
            t=now();s.add(JourneyRecoveryStrategyVersionRow(strategy_version_id='recovery_guardrail_v1',name='Recovery Guardrail V1',state='ACTIVE',min_sample_count=20,min_confidence=.8,confidence_level=.95,rollout_percent=100,parameter_bounds_json=BOUNDS,rollback_thresholds_json=ROLLBACK,requires_approval=False,approved_by='SYSTEM_BASELINE',approved_at=t,activated_at=t,created_at=t,updated_at=t))
            s.flush()
    def active(self,s):
        self.bootstrap(s);rows=s.execute(select(JourneyRecoveryStrategyVersionRow).where(JourneyRecoveryStrategyVersionRow.state.in_(['SHADOW','CANARY','ACTIVE'])).order_by(JourneyRecoveryStrategyVersionRow.created_at.desc())).scalars().all();return rows[0]
    def wilson(self,k,n,z=1.96):
        if not n:return [0.0,1.0]
        p=k/n;d=1+z*z/n;c=(p+z*z/(2*n))/d;m=z*sqrt((p*(1-p)+z*z/(4*n))/n)/d;return [max(0,c-m),min(1,c+m)]
    def _clamp(self,p,bounds):
        out={};events=[]
        for k,v in p.items():
            lo,hi=bounds.get(k,[v,v]);nv=max(lo,min(hi,v));out[k]=type(v)(nv) if isinstance(v,int) else float(nv)
            if nv!=v:events.append({'parameter':k,'proposed':v,'applied':nv,'bound':[lo,hi]})
        return out,events
    def evaluate(self,s,profile,execution_item_id=None):
        st=self.active(s);mode=st.state;reasons=[];eligible=bool(profile)
        kill_reason=recovery_data_governance_service.kill_switch_reason(s, getattr(profile,'vertical',None) if profile else None, getattr(profile,'adapter_key',None) if profile else None)
        quality=recovery_data_governance_service.latest_quality(s,getattr(profile,'vertical',None),getattr(profile,'adapter_key',None)) if profile else None
        if kill_reason:
            reasons.append(kill_reason);eligible=False
        if quality and quality.quality_state!='PASS':
            reasons.append('DATA_QUALITY_GATE_'+quality.quality_state);eligible=False
        if not profile:reasons.append('NO_RELIABILITY_PROFILE');eligible=False
        elif profile.sample_count<st.min_sample_count:reasons.append('MIN_SAMPLE_NOT_MET');eligible=False
        elif profile.confidence<st.min_confidence:reasons.append('MIN_CONFIDENCE_NOT_MET');eligible=False
        ci={}
        if profile:
            ci={'timeout_rate':self.wilson(profile.unknown_count,profile.sample_count),'manual_review_rate':self.wilson(profile.manual_review_count,profile.sample_count),'confirmation_rate':self.wilson(profile.confirmed_count,profile.sample_count)}
            proposed={'initial_poll_seconds':profile.recommended_initial_poll_seconds,'max_poll_seconds':profile.recommended_max_poll_seconds,'max_attempts':profile.recommended_max_attempts,'ack_multiplier':profile.recommended_ack_multiplier,'resolution_multiplier':profile.recommended_resolution_multiplier}
        else: proposed=dict(BASE)
        bounded,clamps=self._clamp(proposed,st.parameter_bounds_json or BOUNDS)
        bucket=int(sha256((execution_item_id or (profile.reliability_profile_id if profile else 'none')).encode()).hexdigest()[:8],16)%100
        apply_adaptive=eligible and mode=='ACTIVE'
        if mode=='SHADOW':reasons.append('SHADOW_NO_EFFECT')
        if mode=='CANARY':
            apply_adaptive=eligible and bucket<int(st.rollout_percent or 0)
            if not apply_adaptive:reasons.append('OUTSIDE_CANARY_COHORT')
        applied=bounded if apply_adaptive else dict(BASE)
        ev=JourneyRecoveryStrategyEvaluationRow(strategy_evaluation_id=nid('jrse'),strategy_version_id=st.strategy_version_id,reliability_profile_id=profile.reliability_profile_id if profile else None,execution_item_id=execution_item_id,mode=mode,eligible=eligible,cohort_bucket=bucket,confidence_intervals_json=ci,proposed_parameters_json=proposed,applied_parameters_json=applied,clamp_events_json=clamps,reason_codes_json=reasons,supplier_fact_unchanged=True,created_at=now());s.add(ev)
        return {'strategy_version_id':st.strategy_version_id,'mode':mode,'eligible':eligible,'confidence_intervals':ci,'applied':applied,'reasons':reasons,'cohort_bucket':bucket}
    def create(self,name,min_sample=20,min_confidence=.8,rollout=0,state='DRAFT'):
        with SessionLocal() as s:
            r=JourneyRecoveryStrategyVersionRow(strategy_version_id=nid('jrsv'),name=name,state=state,min_sample_count=min_sample,min_confidence=min_confidence,confidence_level=.95,rollout_percent=rollout,parameter_bounds_json=BOUNDS,rollback_thresholds_json=ROLLBACK,requires_approval=True,approved_by=None,approved_at=None,activated_at=None,rolled_back_at=None,rollback_reason=None,created_at=now(),updated_at=now());s.add(r);s.commit();return r.strategy_version_id
    def approve(self,id,actor):
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryStrategyVersionRow,id)
            if not r:raise ValueError('RECOVERY_STRATEGY_NOT_FOUND')
            r.approved_by=actor;r.approved_at=now();r.updated_at=now();s.commit();return id
    def activate(self,id,mode,actor):
        if mode not in {'SHADOW','CANARY','ACTIVE'}:raise ValueError('INVALID_STRATEGY_MODE')
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryStrategyVersionRow,id)
            if not r:raise ValueError('RECOVERY_STRATEGY_NOT_FOUND')
            if r.requires_approval and not r.approved_at:raise ValueError('RECOVERY_STRATEGY_APPROVAL_REQUIRED')
            for x in s.execute(select(JourneyRecoveryStrategyVersionRow).where(JourneyRecoveryStrategyVersionRow.state.in_(['SHADOW','CANARY','ACTIVE']))).scalars().all():
                if x.strategy_version_id!=id and x.strategy_version_id!='recovery_guardrail_v1':x.state='SUPERSEDED';x.updated_at=now()
            r.state=mode;r.activated_at=now();r.updated_at=now();s.commit();return id
    def rollback(self,id,actor,reason):
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryStrategyVersionRow,id)
            if not r:raise ValueError('RECOVERY_STRATEGY_NOT_FOUND')
            r.state='ROLLED_BACK';r.rolled_back_at=now();r.rollback_reason=f'{actor}: {reason}';r.updated_at=now();s.commit();return id
    def auto_guardrail(self):
        with SessionLocal() as s:
            st=self.active(s)
            if st.strategy_version_id=='recovery_guardrail_v1' or st.state not in {'CANARY','ACTIVE'}:return {'rolled_back':False}
            evs=s.execute(select(JourneyRecoveryStrategyEvaluationRow).where(JourneyRecoveryStrategyEvaluationRow.strategy_version_id==st.strategy_version_id).order_by(JourneyRecoveryStrategyEvaluationRow.created_at.desc()).limit(100)).scalars().all();thr=st.rollback_thresholds_json or ROLLBACK
            bad=[e for e in evs if (e.confidence_intervals_json.get('timeout_rate') or [0,0])[1]>thr['timeout_upper'] or (e.confidence_intervals_json.get('manual_review_rate') or [0,0])[1]>thr['manual_review_upper']]
            if len(evs)>=thr['min_evaluations'] and len(bad)/len(evs)>=.5:
                st.state='ROLLED_BACK';st.rolled_back_at=now();st.rollback_reason='AUTO_GUARDRAIL_CONFIDENCE_INTERVAL_BREACH';st.updated_at=now();s.commit();return {'rolled_back':True,'strategy_version_id':st.strategy_version_id}
            return {'rolled_back':False,'evaluations':len(evs)}
    def list_strategies(self):
        with SessionLocal() as s:
            self.bootstrap(s);s.commit();return [{'strategy_version_id':x.strategy_version_id,'name':x.name,'state':x.state,'min_sample_count':x.min_sample_count,'min_confidence':x.min_confidence,'rollout_percent':x.rollout_percent,'requires_approval':x.requires_approval,'approved_by':x.approved_by,'parameter_bounds':x.parameter_bounds_json,'rollback_thresholds':x.rollback_thresholds_json} for x in s.execute(select(JourneyRecoveryStrategyVersionRow).order_by(JourneyRecoveryStrategyVersionRow.created_at.desc())).scalars().all()]
    def evaluations(self,limit=100):
        with SessionLocal() as s:return [{'strategy_evaluation_id':x.strategy_evaluation_id,'strategy_version_id':x.strategy_version_id,'profile_id':x.reliability_profile_id,'execution_item_id':x.execution_item_id,'mode':x.mode,'eligible':x.eligible,'cohort_bucket':x.cohort_bucket,'confidence_intervals':x.confidence_intervals_json,'proposed':x.proposed_parameters_json,'applied':x.applied_parameters_json,'clamps':x.clamp_events_json,'reason_codes':x.reason_codes_json,'supplier_fact_unchanged':x.supplier_fact_unchanged} for x in s.execute(select(JourneyRecoveryStrategyEvaluationRow).order_by(JourneyRecoveryStrategyEvaluationRow.created_at.desc()).limit(limit)).scalars().all()]
recovery_strategy_governance_service=RecoveryStrategyGovernanceService()
