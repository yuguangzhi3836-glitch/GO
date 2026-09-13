from datetime import datetime,timezone
from uuid import uuid4
from hashlib import sha256
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import *
from go_hotel.journey.recovery_forecast_serving_governance import recovery_forecast_serving_governance_service as serving

def now(): return datetime.now(timezone.utc)
def nid(p): return f'{p}_{uuid4().hex}'
def h(v): return sha256(str(v).encode()).hexdigest()

class RecoveryForecastTrafficGovernanceService:
    STEPS=[0,1,5,10,25,50,100]
    def create_policy(self,environment,champion_deployment_key,candidate_deployment_key,min_requests_per_step=100,max_error_rate=.02,max_timeout_rate=.01,max_p95_latency_ms=1000,max_shadow_divergence=.25,actor='traffic-governance'):
        if champion_deployment_key==candidate_deployment_key: raise ValueError('DISTINCT_CHAMPION_AND_CANDIDATE_REQUIRED')
        with SessionLocal() as s:
            prev=s.execute(select(JourneyRecoveryForecastTrafficPolicyRow).where(JourneyRecoveryForecastTrafficPolicyRow.environment==environment).order_by(JourneyRecoveryForecastTrafficPolicyRow.version_no.desc())).scalars().first()
            x=JourneyRecoveryForecastTrafficPolicyRow(forecast_traffic_policy_id=nid('jftp'),environment=environment,version_no=(prev.version_no+1 if prev else 1),champion_deployment_key=champion_deployment_key,candidate_deployment_key=candidate_deployment_key,allowed_canary_steps_json=self.STEPS,min_requests_per_step=min_requests_per_step,max_error_rate=max_error_rate,max_timeout_rate=max_timeout_rate,max_p95_latency_ms=max_p95_latency_ms,max_shadow_divergence=max_shadow_divergence,requested_by=actor,approver_one=None,approver_two=None,state='PENDING_APPROVAL',created_at=now(),supplier_fact_unchanged=True);s.add(x);s.commit();return self.policy(x.forecast_traffic_policy_id)
    def approve_policy(self,pid,actor):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryForecastTrafficPolicyRow,pid)
            if not x: raise ValueError('TRAFFIC_POLICY_NOT_FOUND')
            if actor==x.requested_by or actor in (x.approver_one,x.approver_two): raise ValueError('TRAFFIC_POLICY_MAKER_CHECKER_REQUIRED')
            if not x.approver_one:x.approver_one=actor
            elif not x.approver_two:
                x.approver_two=actor;x.state='ACTIVE'
                for old in s.execute(select(JourneyRecoveryForecastTrafficPolicyRow).where(JourneyRecoveryForecastTrafficPolicyRow.environment==x.environment,JourneyRecoveryForecastTrafficPolicyRow.state=='ACTIVE',JourneyRecoveryForecastTrafficPolicyRow.forecast_traffic_policy_id!=x.forecast_traffic_policy_id)).scalars().all():old.state='SUPERSEDED'
                a=JourneyRecoveryForecastTrafficAllocationRow(forecast_traffic_allocation_id=nid('jfta'),forecast_traffic_policy_id=x.forecast_traffic_policy_id,environment=x.environment,champion_percentage=100,canary_percentage=0,allocation_version=1,state='ACTIVE',reason_codes_json=[],activated_at=now(),supplier_fact_unchanged=True);s.add(a)
            self._event(s,x.environment,'TRAFFIC_POLICY_APPROVAL',x.forecast_traffic_policy_id,{'state':x.state},actor);s.commit();return self.policy(pid)
    def active_policy_in_session(self,s,environment):return s.execute(select(JourneyRecoveryForecastTrafficPolicyRow).where(JourneyRecoveryForecastTrafficPolicyRow.environment==environment,JourneyRecoveryForecastTrafficPolicyRow.state=='ACTIVE').order_by(JourneyRecoveryForecastTrafficPolicyRow.version_no.desc())).scalars().first()
    def _allocation(self,s,pid):return s.execute(select(JourneyRecoveryForecastTrafficAllocationRow).where(JourneyRecoveryForecastTrafficAllocationRow.forecast_traffic_policy_id==pid,JourneyRecoveryForecastTrafficAllocationRow.state=='ACTIVE').order_by(JourneyRecoveryForecastTrafficAllocationRow.allocation_version.desc())).scalars().first()
    def _eligible(self,s,environment,deployment_key):
        b=s.execute(select(JourneyRecoveryForecastArtifactDeploymentBindingRow).where(JourneyRecoveryForecastArtifactDeploymentBindingRow.environment==environment,JourneyRecoveryForecastArtifactDeploymentBindingRow.deployment_key==deployment_key,JourneyRecoveryForecastArtifactDeploymentBindingRow.state=='ACTIVE').order_by(JourneyRecoveryForecastArtifactDeploymentBindingRow.bound_at.desc())).scalars().first()
        if not b: raise ValueError('RUNTIME_MODEL_DEPLOYMENT_BINDING_REQUIRED')
        ctrl=s.execute(select(JourneyRecoveryForecastServingSafetyControlRow).where(JourneyRecoveryForecastServingSafetyControlRow.environment==environment,JourneyRecoveryForecastServingSafetyControlRow.deployment_key==deployment_key,JourneyRecoveryForecastServingSafetyControlRow.control_state=='BLOCKED')).scalars().first()
        if ctrl: raise ValueError('RUNTIME_MODEL_SERVING_BLOCKED_BY_ATTESTATION_MISMATCH')
        r=s.execute(select(JourneyRecoveryForecastRuntimeModelIdentityRow).where(JourneyRecoveryForecastRuntimeModelIdentityRow.environment==environment,JourneyRecoveryForecastRuntimeModelIdentityRow.deployment_key==deployment_key,JourneyRecoveryForecastRuntimeModelIdentityRow.model_version_id==b.model_version_id,JourneyRecoveryForecastRuntimeModelIdentityRow.state=='ACTIVE').order_by(JourneyRecoveryForecastRuntimeModelIdentityRow.registered_at.desc())).scalars().first()
        if not r: raise ValueError('RUNTIME_MODEL_IDENTITY_REQUIRED')
        at=s.execute(select(JourneyRecoveryForecastModelServingAttestationRow).where(JourneyRecoveryForecastModelServingAttestationRow.forecast_artifact_deployment_binding_id==b.forecast_artifact_deployment_binding_id,JourneyRecoveryForecastModelServingAttestationRow.forecast_runtime_model_identity_id==r.forecast_runtime_model_identity_id).order_by(JourneyRecoveryForecastModelServingAttestationRow.attested_at.desc())).scalars().first()
        if not at or at.attestation_state!='VERIFIED': raise ValueError('VERIFIED_MODEL_SERVING_ATTESTATION_REQUIRED')
        return b,r
    def route(self,environment,subject_key):
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment)
            if not p: raise ValueError('GOVERNED_MODEL_TRAFFIC_ROUTING_REQUIRED')
            a=self._allocation(s,p.forecast_traffic_policy_id);bucket=int(h(subject_key+str(p.version_no))[:8],16)%100
            role='CANARY' if bucket<a.canary_percentage else 'CHAMPION';key=p.candidate_deployment_key if role=='CANARY' else p.champion_deployment_key;b,r=self._eligible(s,environment,key)
            return {'forecast_traffic_policy_id':p.forecast_traffic_policy_id,'forecast_traffic_allocation_id':a.forecast_traffic_allocation_id,'serving_role':role,'deployment_key':key,'model_version_id':b.model_version_id,'runtime_model_identity_id':r.forecast_runtime_model_identity_id,'artifact_id':b.forecast_model_artifact_id,'artifact_digest':b.expected_artifact_digest,'supplier_fact_unchanged':True}
    def record_prediction(self,environment,subject_key,prediction,latency_ms,serving_status='OK'):
        route=self.route(environment,subject_key)
        with SessionLocal() as s:
            b=s.execute(select(JourneyRecoveryForecastArtifactDeploymentBindingRow).where(JourneyRecoveryForecastArtifactDeploymentBindingRow.environment==environment,JourneyRecoveryForecastArtifactDeploymentBindingRow.deployment_key==route['deployment_key'],JourneyRecoveryForecastArtifactDeploymentBindingRow.state=='ACTIVE').order_by(JourneyRecoveryForecastArtifactDeploymentBindingRow.bound_at.desc())).scalars().first()
            x=JourneyRecoveryForecastPredictionProvenanceRow(prediction_request_id=nid('pred'),environment=environment,forecast_traffic_policy_id=route['forecast_traffic_policy_id'],forecast_traffic_allocation_id=route['forecast_traffic_allocation_id'],subject_key_hash=h(subject_key),serving_role=route['serving_role'],deployment_key=route['deployment_key'],forecast_artifact_deployment_binding_id=b.forecast_artifact_deployment_binding_id,forecast_runtime_model_identity_id=route['runtime_model_identity_id'],model_version_id=route['model_version_id'],forecast_model_artifact_id=route['artifact_id'],artifact_digest=route['artifact_digest'],prediction_json=prediction,latency_ms=latency_ms,serving_status=serving_status,created_at=now(),supplier_fact_unchanged=True);s.add(x);s.commit();return self.provenance(x.prediction_request_id)
    def compare_shadow(self,prediction_request_id,shadow_value,evidence=None):
        with SessionLocal() as s:
            pr=s.get(JourneyRecoveryForecastPredictionProvenanceRow,prediction_request_id);p=s.get(JourneyRecoveryForecastTrafficPolicyRow,pr.forecast_traffic_policy_id);b,r=self._eligible(s,pr.environment,p.candidate_deployment_key)
            cv=float(pr.prediction_json.get('value',0));d=abs(shadow_value-cv)/max(abs(cv),1.0);state='PASS' if d<=p.max_shadow_divergence else 'DIVERGED'
            x=JourneyRecoveryForecastShadowComparisonRow(forecast_shadow_comparison_id=nid('jfsh'),environment=pr.environment,champion_prediction_request_id=prediction_request_id,candidate_model_version_id=b.model_version_id,candidate_deployment_key=p.candidate_deployment_key,champion_value=cv,shadow_value=shadow_value,divergence=d,comparison_state=state,evidence_json=evidence or {},created_at=now(),supplier_fact_unchanged=True);s.add(x);s.commit();return {'forecast_shadow_comparison_id':x.forecast_shadow_comparison_id,'comparison_state':state,'divergence':d,'supplier_fact_unchanged':True}
    def assess_budget(self,environment,request_count,error_rate,timeout_rate,p95_latency_ms,invalid_prediction_rate=0,fallback_rate=0,availability=1,attestation_mismatch_rate=0):
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment);a=self._allocation(s,p.forecast_traffic_policy_id);reasons=[]
            if error_rate>p.max_error_rate:reasons.append('SERVING_ERROR_BUDGET_BREACH')
            if timeout_rate>p.max_timeout_rate:reasons.append('SERVING_TIMEOUT_BUDGET_BREACH')
            if p95_latency_ms>p.max_p95_latency_ms:reasons.append('SERVING_LATENCY_BUDGET_BREACH')
            if attestation_mismatch_rate>0:reasons.append('SERVING_ATTESTATION_MISMATCH')
            state='BREACH' if reasons else 'PASS';x=JourneyRecoveryForecastServingBudgetAssessmentRow(forecast_serving_budget_assessment_id=nid('jfba'),environment=environment,forecast_traffic_policy_id=p.forecast_traffic_policy_id,canary_percentage=a.canary_percentage,request_count=request_count,error_rate=error_rate,timeout_rate=timeout_rate,p95_latency_ms=p95_latency_ms,invalid_prediction_rate=invalid_prediction_rate,fallback_rate=fallback_rate,availability=availability,attestation_mismatch_rate=attestation_mismatch_rate,assessment_state=state,reason_codes_json=reasons,assessed_at=now(),supplier_fact_unchanged=True);s.add(x);self._event(s,environment,'CANARY_FROZEN' if reasons else 'SERVING_BUDGET_PASS',p.forecast_traffic_policy_id,{'reason_codes':reasons},'traffic-controller');s.commit();return {'forecast_serving_budget_assessment_id':x.forecast_serving_budget_assessment_id,'assessment_state':state,'reason_codes':reasons,'supplier_fact_unchanged':True}
    def progress_canary(self,environment,to_percentage,evidence_reference,actor='traffic-controller'):
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment);a=self._allocation(s,p.forecast_traffic_policy_id)
            if to_percentage not in p.allowed_canary_steps_json or to_percentage<=a.canary_percentage:raise ValueError('INVALID_CANARY_PROGRESSION_STEP')
            idx=p.allowed_canary_steps_json.index(a.canary_percentage)
            if idx+1>=len(p.allowed_canary_steps_json) or p.allowed_canary_steps_json[idx+1]!=to_percentage:raise ValueError('CANARY_STEP_MUST_BE_SEQUENTIAL')
            self._eligible(s,environment,p.candidate_deployment_key)
            budget=s.execute(select(JourneyRecoveryForecastServingBudgetAssessmentRow).where(JourneyRecoveryForecastServingBudgetAssessmentRow.forecast_traffic_policy_id==p.forecast_traffic_policy_id,JourneyRecoveryForecastServingBudgetAssessmentRow.canary_percentage==a.canary_percentage).order_by(JourneyRecoveryForecastServingBudgetAssessmentRow.assessed_at.desc())).scalars().first()
            if not budget or budget.assessment_state!='PASS' or budget.request_count<p.min_requests_per_step:raise ValueError('CANARY_TRAFFIC_HEALTH_GATE_NOT_PASSED')
            div=s.execute(select(JourneyRecoveryForecastShadowComparisonRow).where(JourneyRecoveryForecastShadowComparisonRow.environment==environment,JourneyRecoveryForecastShadowComparisonRow.comparison_state=='DIVERGED').order_by(JourneyRecoveryForecastShadowComparisonRow.created_at.desc())).scalars().first()
            if div:raise ValueError('SHADOW_CONSISTENCY_GATE_NOT_PASSED')
            a.state='SUPERSEDED';n=JourneyRecoveryForecastTrafficAllocationRow(forecast_traffic_allocation_id=nid('jfta'),forecast_traffic_policy_id=p.forecast_traffic_policy_id,environment=environment,champion_percentage=100-to_percentage,canary_percentage=to_percentage,allocation_version=a.allocation_version+1,state='ACTIVE',reason_codes_json=[],activated_at=now(),supplier_fact_unchanged=True);s.add(n);g=JourneyRecoveryForecastCanaryProgressionRow(forecast_canary_progression_id=nid('jfcp'),environment=environment,forecast_traffic_policy_id=p.forecast_traffic_policy_id,from_percentage=a.canary_percentage,to_percentage=to_percentage,gate_state='PASSED',reason_codes_json=[],evidence_reference=evidence_reference,created_at=now(),supplier_fact_unchanged=True);s.add(g);self._event(s,environment,'CANARY_PROGRESSING',p.forecast_traffic_policy_id,{'from':a.canary_percentage,'to':to_percentage},actor);s.commit();return {'canary_percentage':to_percentage,'champion_percentage':100-to_percentage,'gate_state':'PASSED','supplier_fact_unchanged':True}
    def rollback(self,environment,evidence_reference,actor='traffic-controller'):
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment);a=self._allocation(s,p.forecast_traffic_policy_id);a.state='SUPERSEDED';n=JourneyRecoveryForecastTrafficAllocationRow(forecast_traffic_allocation_id=nid('jfta'),forecast_traffic_policy_id=p.forecast_traffic_policy_id,environment=environment,champion_percentage=100,canary_percentage=0,allocation_version=a.allocation_version+1,state='ACTIVE',reason_codes_json=['CANARY_ROLLBACK'],activated_at=now(),supplier_fact_unchanged=True);s.add(n);self._event(s,environment,'CANARY_ROLLED_BACK',p.forecast_traffic_policy_id,{'evidence_reference':evidence_reference},actor);s.commit();return {'champion_percentage':100,'canary_percentage':0,'supplier_fact_unchanged':True}
    def policy(self,pid):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryForecastTrafficPolicyRow,pid);return {'forecast_traffic_policy_id':x.forecast_traffic_policy_id,'environment':x.environment,'version_no':x.version_no,'state':x.state,'allowed_canary_steps':x.allowed_canary_steps_json,'supplier_fact_unchanged':True}
    def provenance(self,pid):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryForecastPredictionProvenanceRow,pid);return {'prediction_request_id':x.prediction_request_id,'serving_role':x.serving_role,'deployment_key':x.deployment_key,'model_version_id':x.model_version_id,'forecast_runtime_model_identity_id':x.forecast_runtime_model_identity_id,'artifact_digest':x.artifact_digest,'prediction':x.prediction_json,'supplier_fact_unchanged':True}
    def status(self,environment):
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment)
            if not p:return {'state':'NO_ACTIVE_POLICY'}
            a=self._allocation(s,p.forecast_traffic_policy_id);return {'policy_id':p.forecast_traffic_policy_id,'champion_deployment_key':p.champion_deployment_key,'candidate_deployment_key':p.candidate_deployment_key,'champion_percentage':a.champion_percentage,'canary_percentage':a.canary_percentage,'supplier_fact_unchanged':True}
    def _event(self,s,e,t,pid,evidence,actor):s.add(JourneyRecoveryForecastTrafficGovernanceEventRow(forecast_traffic_governance_event_id=nid('jftg'),environment=e,event_type=t,forecast_traffic_policy_id=pid,evidence_json=evidence or {},actor=actor,created_at=now(),supplier_fact_unchanged=True))

recovery_forecast_traffic_governance_service=RecoveryForecastTrafficGovernanceService()
