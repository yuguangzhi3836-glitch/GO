from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import *

def now(): return datetime.now(timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:20]}'
CANARY_STEPS=[0,1,5,10,25,50,100]

class RecoveryForecastChampionGovernanceService:
    def register_champion(self,portfolio_id,champion_model_version_id=None,previous_stable_champion_model_version_id=None,actor='champion-governance'):
        with SessionLocal() as s:
            p=s.get(JourneyRecoveryForecastRemediationPortfolioRow,portfolio_id)
            if not p: raise ValueError('REMEDIATION_PORTFOLIO_NOT_FOUND')
            model=champion_model_version_id or p.champion_model_version_id
            if not s.get(JourneyRecoveryRiskForecastModelVersionRow,model): raise ValueError('CHAMPION_MODEL_VERSION_NOT_FOUND')
            active=s.execute(select(JourneyRecoveryForecastPortfolioChampionStateRow).where(JourneyRecoveryForecastPortfolioChampionStateRow.environment==p.environment,JourneyRecoveryForecastPortfolioChampionStateRow.portfolio_id==portfolio_id,JourneyRecoveryForecastPortfolioChampionStateRow.champion_state.in_(['CHAMPION_HEALTHY','CHAMPION_DEGRADING','CHAMPION_NO_LONGER_OPTIMAL','CHAMPION_UNSAFE']))).scalars().first()
            if active: raise ValueError('ACTIVE_PORTFOLIO_CHAMPION_ALREADY_EXISTS')
            x=JourneyRecoveryForecastPortfolioChampionStateRow(forecast_portfolio_champion_state_id=nid('jfpcs'),environment=p.environment,portfolio_id=portfolio_id,champion_model_version_id=model,previous_stable_champion_model_version_id=previous_stable_champion_model_version_id,objective_snapshot_json={'objectives':p.objectives_json or [],'protected_segment_keys':p.protected_segment_keys_json or []},champion_state='CHAMPION_HEALTHY',assigned_at=now(),supplier_fact_unchanged=True)
            s.add(x);self._event(s,p.environment,'CHAMPION_REGISTERED',x.forecast_portfolio_champion_state_id,None,{'model_version_id':model},actor);s.commit();return self._state(x)

    def assess_continuity(self,champion_state_id,portfolio_objective_score,target_health_state='PASS',protected_segment_state='PASS',serving_health_state='PASS',holdout_state='PASS',evidence=None,actor='champion-assessor'):
        with SessionLocal() as s:
            cs=s.get(JourneyRecoveryForecastPortfolioChampionStateRow,champion_state_id)
            if not cs: raise ValueError('PORTFOLIO_CHAMPION_STATE_NOT_FOUND')
            valid={'PASS','WATCH','FAIL'}
            if any(x not in valid for x in [target_health_state,protected_segment_state,serving_health_state,holdout_state]): raise ValueError('INVALID_CONTINUITY_HEALTH_STATE')
            reasons=[]
            if protected_segment_state=='FAIL': reasons.append('PROTECTED_SEGMENT_UNSAFE')
            if serving_health_state=='FAIL': reasons.append('SERVING_HEALTH_UNSAFE')
            if holdout_state=='FAIL': reasons.append('HOLDOUT_UNSAFE')
            if target_health_state=='FAIL': reasons.append('TARGET_HEALTH_FAILED')
            if reasons: state='CHAMPION_UNSAFE'
            elif portfolio_objective_score<70: state='CHAMPION_NO_LONGER_OPTIMAL'
            elif portfolio_objective_score<85 or 'WATCH' in [target_health_state,protected_segment_state,serving_health_state,holdout_state]: state='CHAMPION_DEGRADING'
            else: state='CHAMPION_HEALTHY'
            a=JourneyRecoveryForecastChampionContinuityAssessmentRow(forecast_champion_continuity_assessment_id=nid('jfcca'),environment=cs.environment,champion_state_id=champion_state_id,champion_model_version_id=cs.champion_model_version_id,portfolio_objective_score=portfolio_objective_score,target_health_state=target_health_state,protected_segment_state=protected_segment_state,serving_health_state=serving_health_state,holdout_state=holdout_state,continuity_state=state,reason_codes_json=reasons,evidence_json=evidence or {},assessed_at=now(),supplier_fact_unchanged=True)
            s.add(a);cs.champion_state=state;self._event(s,cs.environment,'CHAMPION_CONTINUITY_ASSESSED',champion_state_id,None,{'continuity_state':state,'score':portfolio_objective_score,'reason_codes':reasons},actor);s.commit();return self._continuity(a)

    def open_challenge(self,champion_state_id,portfolio_candidate_id,actor='champion-governance'):
        with SessionLocal() as s:
            cs=s.get(JourneyRecoveryForecastPortfolioChampionStateRow,champion_state_id); c=s.get(JourneyRecoveryForecastPortfolioCandidateRow,portfolio_candidate_id)
            if not cs: raise ValueError('PORTFOLIO_CHAMPION_STATE_NOT_FOUND')
            if not c or c.portfolio_id!=cs.portfolio_id: raise ValueError('PORTFOLIO_CANDIDATE_NOT_FOUND')
            if c.challenger_model_version_id==cs.champion_model_version_id: raise ValueError('CHAMPION_CANNOT_CHALLENGE_ITSELF')
            gate=s.execute(select(JourneyRecoveryForecastPortfolioPromotionGateRow).where(JourneyRecoveryForecastPortfolioPromotionGateRow.portfolio_candidate_id==portfolio_candidate_id,JourneyRecoveryForecastPortfolioPromotionGateRow.promotion_eligible==True).order_by(JourneyRecoveryForecastPortfolioPromotionGateRow.evaluated_at.desc())).scalars().first()
            if not gate: raise ValueError('4W_PORTFOLIO_WINNER_PROMOTION_GATE_REQUIRED')
            x=JourneyRecoveryForecastChampionChallengeRow(forecast_champion_challenge_id=nid('jfch'),environment=cs.environment,portfolio_id=cs.portfolio_id,champion_state_id=champion_state_id,current_champion_model_version_id=cs.champion_model_version_id,portfolio_candidate_id=portfolio_candidate_id,candidate_model_version_id=c.challenger_model_version_id,challenge_state='CHALLENGE_OPEN',opened_by=actor,opened_at=now(),supplier_fact_unchanged=True)
            s.add(x);self._event(s,cs.environment,'CHAMPION_CHALLENGE_OPENED',champion_state_id,x.forecast_champion_challenge_id,{'candidate_model_version_id':x.candidate_model_version_id},actor);s.commit();return self._challenge(x)

    def compare_candidate(self,challenge_id,champion_portfolio_score,candidate_portfolio_score,protected_segment_safe=True,generalization_pass=True,serving_health_pass=True,statistical_confidence_pass=True,evidence=None,actor='champion-assessor'):
        with SessionLocal() as s:
            ch=s.get(JourneyRecoveryForecastChampionChallengeRow,challenge_id)
            if not ch: raise ValueError('CHAMPION_CHALLENGE_NOT_FOUND')
            improvement=((candidate_portfolio_score-champion_portfolio_score)/max(abs(champion_portfolio_score),.0001))*100
            reasons=[]
            if not protected_segment_safe: reasons.append('PROTECTED_SEGMENT_REGRESSION')
            if not generalization_pass: reasons.append('GENERALIZATION_NOT_PROVEN')
            if not serving_health_pass: reasons.append('SERVING_HEALTH_NOT_PROVEN')
            if not statistical_confidence_pass: reasons.append('STATISTICAL_CONFIDENCE_NOT_PROVEN')
            if reasons: state='CANDIDATE_UNSAFE'
            elif improvement>=5: state='CANDIDATE_SUPERIOR'
            elif improvement>=0: state='CANDIDATE_NON_INFERIOR'
            else: state='NO_MATERIAL_GAIN'
            x=JourneyRecoveryForecastChampionCandidateComparisonRow(forecast_champion_candidate_comparison_id=nid('jfccc'),environment=ch.environment,challenge_id=challenge_id,champion_model_version_id=ch.current_champion_model_version_id,candidate_model_version_id=ch.candidate_model_version_id,champion_portfolio_score=champion_portfolio_score,candidate_portfolio_score=candidate_portfolio_score,improvement_pct=round(improvement,4),protected_segment_safe=protected_segment_safe,generalization_pass=generalization_pass,serving_health_pass=serving_health_pass,statistical_confidence_pass=statistical_confidence_pass,comparison_state=state,reason_codes_json=reasons,evidence_json=evidence or {},compared_at=now(),supplier_fact_unchanged=True)
            s.add(x);ch.challenge_state=state;self._event(s,ch.environment,'CHAMPION_CANDIDATE_COMPARED',ch.champion_state_id,challenge_id,{'comparison_state':state,'improvement_pct':x.improvement_pct,'reason_codes':reasons},actor);s.commit();return self._comparison(x)

    def decide_replacement(self,challenge_id,evidence,actor='champion-governance'):
        if not evidence: raise ValueError('CHAMPION_REPLACEMENT_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            ch=s.get(JourneyRecoveryForecastChampionChallengeRow,challenge_id)
            if not ch: raise ValueError('CHAMPION_CHALLENGE_NOT_FOUND')
            cmp=s.execute(select(JourneyRecoveryForecastChampionCandidateComparisonRow).where(JourneyRecoveryForecastChampionCandidateComparisonRow.challenge_id==challenge_id).order_by(JourneyRecoveryForecastChampionCandidateComparisonRow.compared_at.desc())).scalars().first()
            reasons=[]
            if not cmp or cmp.comparison_state!='CANDIDATE_SUPERIOR': reasons.append('CANDIDATE_SUPERIOR_COMPARISON_REQUIRED')
            approved=not reasons; state='REPLACEMENT_APPROVED' if approved else 'REPLACEMENT_BLOCKED'
            x=JourneyRecoveryForecastChampionReplacementDecisionRow(forecast_champion_replacement_decision_id=nid('jfcrd'),environment=ch.environment,challenge_id=challenge_id,comparison_id=(cmp.forecast_champion_candidate_comparison_id if cmp else 'missing'),from_model_version_id=ch.current_champion_model_version_id,to_model_version_id=ch.candidate_model_version_id,decision_state=state,approved=approved,reason_codes_json=reasons,evidence_json=evidence,decided_by=actor,decided_at=now(),supplier_fact_unchanged=True)
            s.add(x)
            if approved:
                ch.challenge_state='REPLACEMENT_APPROVED'
                s.add(JourneyRecoveryForecastChampionTransitionRow(forecast_champion_transition_id=nid('jfct'),environment=ch.environment,replacement_decision_id=x.forecast_champion_replacement_decision_id,from_model_version_id=x.from_model_version_id,to_model_version_id=x.to_model_version_id,transition_state='REPLACEMENT_CANARY',canary_percentage=0,previous_stable_champion_model_version_id=x.from_model_version_id,evidence_json={'source':'4X','decision_id':x.forecast_champion_replacement_decision_id},transitioned_at=now(),supplier_fact_unchanged=True))
            self._event(s,ch.environment,'CHAMPION_REPLACEMENT_DECIDED',ch.champion_state_id,challenge_id,{'decision_state':state,'reason_codes':reasons},actor);s.commit();return self._decision(x)

    def sync_transition(self,replacement_decision_id,action='SYNC',evidence=None,actor='champion-controller'):
        with SessionLocal() as s:
            d=s.get(JourneyRecoveryForecastChampionReplacementDecisionRow,replacement_decision_id)
            if not d or not d.approved: raise ValueError('APPROVED_CHAMPION_REPLACEMENT_REQUIRED')
            ch=s.get(JourneyRecoveryForecastChampionChallengeRow,d.challenge_id); cs=s.get(JourneyRecoveryForecastPortfolioChampionStateRow,ch.champion_state_id)
            t=s.execute(select(JourneyRecoveryForecastChampionTransitionRow).where(JourneyRecoveryForecastChampionTransitionRow.replacement_decision_id==replacement_decision_id).order_by(JourneyRecoveryForecastChampionTransitionRow.transitioned_at.desc())).scalars().first()
            if action=='ROLLBACK':
                nt=JourneyRecoveryForecastChampionTransitionRow(forecast_champion_transition_id=nid('jfct'),environment=d.environment,replacement_decision_id=d.forecast_champion_replacement_decision_id,from_model_version_id=d.to_model_version_id,to_model_version_id=d.from_model_version_id,transition_state='REPLACEMENT_ROLLED_BACK',canary_percentage=0,previous_stable_champion_model_version_id=d.from_model_version_id,evidence_json=evidence or {},transitioned_at=now(),supplier_fact_unchanged=True);s.add(nt);ch.challenge_state='REPLACEMENT_ROLLED_BACK';self._event(s,d.environment,'CHAMPION_REPLACEMENT_ROLLED_BACK',cs.forecast_portfolio_champion_state_id,ch.forecast_champion_challenge_id,evidence or {},actor);s.commit();return self._transition(nt)
            policy=s.execute(select(JourneyRecoveryForecastTrafficPolicyRow).where(JourneyRecoveryForecastTrafficPolicyRow.environment==d.environment,JourneyRecoveryForecastTrafficPolicyRow.state=='ACTIVE').order_by(JourneyRecoveryForecastTrafficPolicyRow.version_no.desc())).scalars().first()
            if not policy: raise ValueError('ACTIVE_4R_TRAFFIC_POLICY_REQUIRED')
            cb=s.execute(select(JourneyRecoveryForecastArtifactDeploymentBindingRow).where(JourneyRecoveryForecastArtifactDeploymentBindingRow.environment==d.environment,JourneyRecoveryForecastArtifactDeploymentBindingRow.model_version_id==d.from_model_version_id,JourneyRecoveryForecastArtifactDeploymentBindingRow.deployment_key==policy.champion_deployment_key,JourneyRecoveryForecastArtifactDeploymentBindingRow.state=='ACTIVE')).scalars().first()
            qb=s.execute(select(JourneyRecoveryForecastArtifactDeploymentBindingRow).where(JourneyRecoveryForecastArtifactDeploymentBindingRow.environment==d.environment,JourneyRecoveryForecastArtifactDeploymentBindingRow.model_version_id==d.to_model_version_id,JourneyRecoveryForecastArtifactDeploymentBindingRow.deployment_key==policy.candidate_deployment_key,JourneyRecoveryForecastArtifactDeploymentBindingRow.state=='ACTIVE')).scalars().first()
            if not cb or not qb: raise ValueError('4R_TRAFFIC_MODEL_BINDING_MISMATCH')
            alloc=s.execute(select(JourneyRecoveryForecastTrafficAllocationRow).where(JourneyRecoveryForecastTrafficAllocationRow.forecast_traffic_policy_id==policy.forecast_traffic_policy_id,JourneyRecoveryForecastTrafficAllocationRow.state=='ACTIVE').order_by(JourneyRecoveryForecastTrafficAllocationRow.allocation_version.desc())).scalars().first()
            if not alloc: raise ValueError('ACTIVE_4R_TRAFFIC_ALLOCATION_REQUIRED')
            pct=alloc.canary_percentage
            if pct not in CANARY_STEPS: raise ValueError('UNAPPROVED_4R_CANARY_PERCENTAGE')
            state='NEW_CHAMPION_PROBATION' if pct==100 else 'REPLACEMENT_CANARY'
            if action=='FINALIZE':
                if pct!=100: raise ValueError('FULL_CANARY_REQUIRED_BEFORE_CHAMPION_REPLACEMENT')
                p=s.get(JourneyRecoveryForecastRemediationPortfolioRow,ch.portfolio_id); must=[o['target_id'] for o in (p.objectives_json or []) if o.get('role')=='MUST_FIX']
                for tid in must:
                    proof=s.execute(select(JourneyRecoveryForecastPostPromotionProofRow).where(JourneyRecoveryForecastPostPromotionProofRow.environment==d.environment,JourneyRecoveryForecastPostPromotionProofRow.remediation_target_id==tid,JourneyRecoveryForecastPostPromotionProofRow.promoted_model_version_id==d.to_model_version_id,JourneyRecoveryForecastPostPromotionProofRow.proof_state=='REMEDIATION_PROVEN_IN_PRODUCTION').order_by(JourneyRecoveryForecastPostPromotionProofRow.evaluated_at.desc())).scalars().first()
                    if not proof: raise ValueError(f'4V_PRODUCTION_PROOF_REQUIRED_{tid}')
                cs.champion_state='SUPERSEDED';
                ns=JourneyRecoveryForecastPortfolioChampionStateRow(forecast_portfolio_champion_state_id=nid('jfpcs'),environment=d.environment,portfolio_id=ch.portfolio_id,champion_model_version_id=d.to_model_version_id,previous_stable_champion_model_version_id=d.from_model_version_id,objective_snapshot_json=cs.objective_snapshot_json,champion_state='CHAMPION_HEALTHY',assigned_at=now(),supplier_fact_unchanged=True);s.add(ns)
                state='CHAMPION_REPLACED';ch.challenge_state='CHAMPION_REPLACED'
            nt=JourneyRecoveryForecastChampionTransitionRow(forecast_champion_transition_id=nid('jfct'),environment=d.environment,replacement_decision_id=d.forecast_champion_replacement_decision_id,from_model_version_id=d.from_model_version_id,to_model_version_id=d.to_model_version_id,transition_state=state,canary_percentage=pct,previous_stable_champion_model_version_id=d.from_model_version_id,evidence_json=evidence or {'traffic_policy_id':policy.forecast_traffic_policy_id,'allocation_id':alloc.forecast_traffic_allocation_id},transitioned_at=now(),supplier_fact_unchanged=True);s.add(nt);self._event(s,d.environment,'CHAMPION_TRANSITION_SYNCED',cs.forecast_portfolio_champion_state_id,ch.forecast_champion_challenge_id,{'transition_state':state,'canary_percentage':pct},actor);s.commit();return self._transition(nt)

    def status(self,environment='PROD'):
        with SessionLocal() as s:
            states=s.execute(select(JourneyRecoveryForecastPortfolioChampionStateRow).where(JourneyRecoveryForecastPortfolioChampionStateRow.environment==environment).order_by(JourneyRecoveryForecastPortfolioChampionStateRow.assigned_at.desc()).limit(20)).scalars().all()
            challenges=s.execute(select(JourneyRecoveryForecastChampionChallengeRow).where(JourneyRecoveryForecastChampionChallengeRow.environment==environment).order_by(JourneyRecoveryForecastChampionChallengeRow.opened_at.desc()).limit(20)).scalars().all()
            return {'champions':[self._state(x) for x in states],'challenges':[self._challenge(x) for x in challenges],'supplier_fact_unchanged':True}

    def _event(self,s,e,t,state_id,challenge_id,evidence,actor): s.add(JourneyRecoveryForecastChampionGovernanceEventRow(forecast_champion_governance_event_id=nid('jfcge'),environment=e,event_type=t,champion_state_id=state_id,challenge_id=challenge_id,evidence_json=evidence or {},actor=actor,created_at=now(),supplier_fact_unchanged=True))
    def _state(self,x): return {'champion_state_id':x.forecast_portfolio_champion_state_id,'environment':x.environment,'portfolio_id':x.portfolio_id,'champion_model_version_id':x.champion_model_version_id,'previous_stable_champion_model_version_id':x.previous_stable_champion_model_version_id,'champion_state':x.champion_state,'supplier_fact_unchanged':True}
    def _continuity(self,x): return {'continuity_assessment_id':x.forecast_champion_continuity_assessment_id,'champion_model_version_id':x.champion_model_version_id,'portfolio_objective_score':x.portfolio_objective_score,'continuity_state':x.continuity_state,'reason_codes':x.reason_codes_json,'supplier_fact_unchanged':True}
    def _challenge(self,x): return {'challenge_id':x.forecast_champion_challenge_id,'portfolio_id':x.portfolio_id,'current_champion_model_version_id':x.current_champion_model_version_id,'candidate_model_version_id':x.candidate_model_version_id,'challenge_state':x.challenge_state,'supplier_fact_unchanged':True}
    def _comparison(self,x): return {'comparison_id':x.forecast_champion_candidate_comparison_id,'comparison_state':x.comparison_state,'improvement_pct':x.improvement_pct,'reason_codes':x.reason_codes_json,'supplier_fact_unchanged':True}
    def _decision(self,x): return {'replacement_decision_id':x.forecast_champion_replacement_decision_id,'decision_state':x.decision_state,'approved':x.approved,'from_model_version_id':x.from_model_version_id,'to_model_version_id':x.to_model_version_id,'reason_codes':x.reason_codes_json,'supplier_fact_unchanged':True}
    def _transition(self,x): return {'transition_id':x.forecast_champion_transition_id,'transition_state':x.transition_state,'canary_percentage':x.canary_percentage,'from_model_version_id':x.from_model_version_id,'to_model_version_id':x.to_model_version_id,'previous_stable_champion_model_version_id':x.previous_stable_champion_model_version_id,'supplier_fact_unchanged':True}

recovery_forecast_champion_governance_service=RecoveryForecastChampionGovernanceService()
