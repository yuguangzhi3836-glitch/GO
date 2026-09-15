from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import *

def now(): return datetime.now(timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:20]}'

ALLOWED_ROLES={'MUST_FIX','IMPROVE_IF_SAFE'}
ALLOWED_CONFLICTS={'COMPATIBLE','PARTIALLY_CONFLICTING','MUTUALLY_CONFLICTING'}
ALLOWED_STRATEGIES={'UNIFIED','SPECIALIZED'}

class RecoveryForecastPortfolioGovernanceService:
    def create_portfolio(self,target_ids,objectives=None,protected_segment_keys=None,actor='portfolio-controller'):
        target_ids=list(dict.fromkeys(target_ids or []))
        if len(target_ids)<2: raise ValueError('MULTI_SEGMENT_PORTFOLIO_REQUIRES_AT_LEAST_TWO_TARGETS')
        with SessionLocal() as s:
            targets=[s.get(JourneyRecoveryForecastRemediationTargetRow,t) for t in target_ids]
            if any(t is None for t in targets): raise ValueError('REMEDIATION_TARGET_NOT_FOUND')
            envs={t.environment for t in targets}; champs={t.champion_model_version_id for t in targets}
            if len(envs)!=1: raise ValueError('PORTFOLIO_TARGET_ENVIRONMENT_MISMATCH')
            if len(champs)!=1: raise ValueError('PORTFOLIO_TARGET_CHAMPION_MISMATCH')
            objective_map=objectives or {t:'MUST_FIX' for t in target_ids}
            obj=[]
            for tid in target_ids:
                role=objective_map.get(tid,'MUST_FIX') if isinstance(objective_map,dict) else 'MUST_FIX'
                if role not in ALLOWED_ROLES: raise ValueError('INVALID_PORTFOLIO_OBJECTIVE_ROLE')
                obj.append({'target_id':tid,'role':role})
            x=JourneyRecoveryForecastRemediationPortfolioRow(
                forecast_remediation_portfolio_id=nid('jfrpf'),environment=targets[0].environment,
                champion_model_version_id=targets[0].champion_model_version_id,target_ids_json=target_ids,
                objectives_json=obj,protected_segment_keys_json=list(protected_segment_keys or []),
                portfolio_state='OPEN',created_by=actor,created_at=now(),supplier_fact_unchanged=True)
            s.add(x);self._event(s,x.forecast_remediation_portfolio_id,None,'PORTFOLIO_CREATED',{'target_ids':target_ids,'objectives':obj},actor,x.environment);s.commit();return self._portfolio(x)

    def register_conflict(self,portfolio_id,target_a_id,target_b_id,conflict_state,resolution_state='OPEN',conflict_penalty_pct=0,shared_root_cause=None,evidence=None,actor='portfolio-controller'):
        if conflict_state not in ALLOWED_CONFLICTS: raise ValueError('INVALID_SEGMENT_CONFLICT_STATE')
        if resolution_state not in {'OPEN','RESOLVED','ACCEPTED_TRADEOFF'}: raise ValueError('INVALID_CONFLICT_RESOLUTION_STATE')
        if conflict_penalty_pct<0: raise ValueError('INVALID_CONFLICT_PENALTY')
        with SessionLocal() as s:
            p=s.get(JourneyRecoveryForecastRemediationPortfolioRow,portfolio_id)
            if not p: raise ValueError('REMEDIATION_PORTFOLIO_NOT_FOUND')
            ids=set(p.target_ids_json or [])
            if target_a_id not in ids or target_b_id not in ids or target_a_id==target_b_id: raise ValueError('CONFLICT_TARGET_NOT_IN_PORTFOLIO')
            x=JourneyRecoveryForecastSegmentConflictRow(
                forecast_segment_conflict_id=nid('jfrsc'),environment=p.environment,portfolio_id=portfolio_id,
                target_a_id=target_a_id,target_b_id=target_b_id,conflict_state=conflict_state,
                resolution_state=resolution_state,conflict_penalty_pct=conflict_penalty_pct,
                shared_root_cause_json=shared_root_cause or {},evidence_json=evidence or {},assessed_at=now(),supplier_fact_unchanged=True)
            s.add(x);self._event(s,portfolio_id,None,'SEGMENT_CONFLICT_REGISTERED',{'conflict_state':conflict_state,'resolution_state':resolution_state},actor,p.environment);s.commit();return self._conflict(x)

    def register_candidate(self,portfolio_id,challenger_model_version_id,strategy='UNIFIED',covered_target_ids=None,actor='portfolio-controller'):
        if strategy not in ALLOWED_STRATEGIES: raise ValueError('INVALID_PORTFOLIO_CANDIDATE_STRATEGY')
        with SessionLocal() as s:
            p=s.get(JourneyRecoveryForecastRemediationPortfolioRow,portfolio_id)
            if not p: raise ValueError('REMEDIATION_PORTFOLIO_NOT_FOUND')
            if not s.get(JourneyRecoveryRiskForecastModelVersionRow,challenger_model_version_id): raise ValueError('CHALLENGER_MODEL_VERSION_NOT_FOUND')
            covered=list(dict.fromkeys(covered_target_ids or p.target_ids_json or []))
            if not covered or not set(covered).issubset(set(p.target_ids_json or [])): raise ValueError('INVALID_PORTFOLIO_CANDIDATE_COVERAGE')
            x=JourneyRecoveryForecastPortfolioCandidateRow(
                forecast_portfolio_candidate_id=nid('jfrpc'),environment=p.environment,portfolio_id=portfolio_id,
                challenger_model_version_id=challenger_model_version_id,strategy=strategy,covered_target_ids_json=covered,
                candidate_state='REGISTERED',registered_by=actor,created_at=now(),supplier_fact_unchanged=True)
            s.add(x);self._event(s,portfolio_id,x.forecast_portfolio_candidate_id,'PORTFOLIO_CANDIDATE_REGISTERED',{'model_version_id':challenger_model_version_id,'strategy':strategy},actor,p.environment);s.commit();return self._candidate(x)

    def assess_candidate(self,candidate_id,evidence=None,actor='portfolio-assessor'):
        with SessionLocal() as s:
            c=s.get(JourneyRecoveryForecastPortfolioCandidateRow,candidate_id)
            if not c: raise ValueError('PORTFOLIO_CANDIDATE_NOT_FOUND')
            p=s.get(JourneyRecoveryForecastRemediationPortfolioRow,c.portfolio_id)
            objective_by_target={x['target_id']:x['role'] for x in (p.objectives_json or [])}
            reasons=[];improvements=[];maxreg=0.0;must_total=0;must_pass=0
            for tid in c.covered_target_ids_json or []:
                role=objective_by_target.get(tid,'MUST_FIX')
                if role=='MUST_FIX': must_total+=1
                a=s.execute(select(JourneyRecoveryForecastRemediationAssessmentRow).where(
                    JourneyRecoveryForecastRemediationAssessmentRow.remediation_target_id==tid,
                    JourneyRecoveryForecastRemediationAssessmentRow.challenger_model_version_id==c.challenger_model_version_id
                ).order_by(JourneyRecoveryForecastRemediationAssessmentRow.evaluated_at.desc())).scalars().first()
                if not a:
                    reasons.append(f'4U_REMEDIATION_EVIDENCE_REQUIRED_{tid}');continue
                improvements.append(a.target_improvement_pct);maxreg=max(maxreg,a.max_cross_segment_regression_pct or 0)
                if role=='MUST_FIX':
                    if a.effectiveness_state=='REMEDIATION_EFFECTIVE' and a.promotion_eligible: must_pass+=1
                    else: reasons.append(f'MUST_FIX_TARGET_NOT_REPAIRED_{tid}')
                elif a.effectiveness_state in {'REMEDIATION_HARMFUL','REMEDIATION_INEFFECTIVE'}:
                    reasons.append(f'IMPROVE_IF_SAFE_TARGET_UNSAFE_{tid}')
                gv=s.execute(select(JourneyRecoveryForecastGeneralizationValidationRow).where(
                    JourneyRecoveryForecastGeneralizationValidationRow.remediation_target_id==tid,
                    JourneyRecoveryForecastGeneralizationValidationRow.challenger_model_version_id==c.challenger_model_version_id
                )).scalars().all()
                hv=s.execute(select(JourneyRecoveryForecastHoldoutValidationRow).where(
                    JourneyRecoveryForecastHoldoutValidationRow.remediation_target_id==tid,
                    JourneyRecoveryForecastHoldoutValidationRow.challenger_model_version_id==c.challenger_model_version_id
                )).scalars().all()
                if role=='MUST_FIX':
                    if not gv or any(x.validation_state!='PASS' for x in gv): reasons.append(f'4V_GENERALIZATION_GATE_REQUIRED_{tid}')
                    if not hv or any(x.validation_state!='PASS' for x in hv): reasons.append(f'4V_HOLDOUT_GATE_REQUIRED_{tid}')
            uncovered_must=[tid for tid,role in objective_by_target.items() if role=='MUST_FIX' and tid not in set(c.covered_target_ids_json or [])]
            for tid in uncovered_must: reasons.append(f'MUST_FIX_TARGET_NOT_COVERED_{tid}');must_total+=1
            protected=set(p.protected_segment_keys_json or [])
            if protected:
                regs=s.execute(select(JourneyRecoveryForecastCrossSegmentRegressionRow).where(
                    JourneyRecoveryForecastCrossSegmentRegressionRow.challenger_model_version_id==c.challenger_model_version_id,
                    JourneyRecoveryForecastCrossSegmentRegressionRow.environment==p.environment
                )).scalars().all()
                for r in regs:
                    if r.segment_key in protected and r.regression_state=='REGRESSED': reasons.append(f'PROTECTED_SEGMENT_REGRESSION_{r.segment_key}')
            conflicts=s.execute(select(JourneyRecoveryForecastSegmentConflictRow).where(JourneyRecoveryForecastSegmentConflictRow.portfolio_id==p.forecast_remediation_portfolio_id)).scalars().all()
            conflict_penalty=sum((x.conflict_penalty_pct or 0) for x in conflicts if x.conflict_state!='COMPATIBLE')
            for x in conflicts:
                if x.conflict_state=='MUTUALLY_CONFLICTING' and x.resolution_state=='OPEN': reasons.append('UNRESOLVED_MUTUAL_SEGMENT_CONFLICT')
            avg=sum(improvements)/len(improvements) if improvements else 0.0
            score=round(avg-maxreg-conflict_penalty,4)
            if 'UNRESOLVED_MUTUAL_SEGMENT_CONFLICT' in reasons: state='REJECTED_CONFLICT'
            elif not reasons and must_total==must_pass: state='PORTFOLIO_PASS'
            elif must_pass>0: state='PORTFOLIO_PARTIAL'
            else: state='PORTFOLIO_FAIL'
            x=JourneyRecoveryForecastPortfolioAssessmentRow(
                forecast_portfolio_assessment_id=nid('jfrpa'),environment=p.environment,portfolio_id=p.forecast_remediation_portfolio_id,
                portfolio_candidate_id=c.forecast_portfolio_candidate_id,challenger_model_version_id=c.challenger_model_version_id,
                must_fix_total=must_total,must_fix_passed=must_pass,average_target_improvement_pct=round(avg,4),
                max_cross_segment_regression_pct=round(maxreg,4),conflict_penalty_pct=round(conflict_penalty,4),portfolio_score=score,
                assessment_state=state,reason_codes_json=reasons,evidence_json=evidence or {},evaluated_at=now(),supplier_fact_unchanged=True)
            s.add(x);c.candidate_state='ASSESSED';self._event(s,p.forecast_remediation_portfolio_id,c.forecast_portfolio_candidate_id,'PORTFOLIO_CANDIDATE_ASSESSED',{'state':state,'score':score,'reason_codes':reasons},actor,p.environment);s.commit();return self._assessment(x)

    def arbitrate(self,portfolio_id,evidence=None,actor='portfolio-arbitrator'):
        with SessionLocal() as s:
            p=s.get(JourneyRecoveryForecastRemediationPortfolioRow,portfolio_id)
            if not p: raise ValueError('REMEDIATION_PORTFOLIO_NOT_FOUND')
            candidates=s.execute(select(JourneyRecoveryForecastPortfolioCandidateRow).where(JourneyRecoveryForecastPortfolioCandidateRow.portfolio_id==portfolio_id)).scalars().all()
            if not candidates: raise ValueError('PORTFOLIO_CANDIDATE_REQUIRED')
            ranked=[]
            for c in candidates:
                a=s.execute(select(JourneyRecoveryForecastPortfolioAssessmentRow).where(JourneyRecoveryForecastPortfolioAssessmentRow.portfolio_candidate_id==c.forecast_portfolio_candidate_id).order_by(JourneyRecoveryForecastPortfolioAssessmentRow.evaluated_at.desc())).scalars().first()
                if a: ranked.append((c,a))
            if not ranked: raise ValueError('PORTFOLIO_ASSESSMENT_REQUIRED')
            eligible=[(c,a) for c,a in ranked if a.assessment_state=='PORTFOLIO_PASS']
            reasons=[];winner=None
            if eligible:
                eligible.sort(key=lambda z:z[1].portfolio_score,reverse=True);winner=eligible[0]
                decision='PORTFOLIO_WINNER_SELECTED'
            elif any(a.assessment_state=='REJECTED_CONFLICT' for _,a in ranked):
                decision='REJECTED_CONFLICT';reasons=['NO_CONFLICT_SAFE_PORTFOLIO_CANDIDATE']
            else:
                decision='RETRAIN_REQUIRED';reasons=['NO_PORTFOLIO_PASS_CANDIDATE']
            rankings=[]
            for c,a in sorted(ranked,key=lambda z:z[1].portfolio_score,reverse=True):
                state='PORTFOLIO_WINNER' if winner and c.forecast_portfolio_candidate_id==winner[0].forecast_portfolio_candidate_id else ('KEEP_IN_SHADOW' if a.assessment_state=='PORTFOLIO_PASS' else a.assessment_state)
                c.candidate_state=state
                rankings.append({'candidate_id':c.forecast_portfolio_candidate_id,'model_version_id':c.challenger_model_version_id,'score':a.portfolio_score,'state':state})
            x=JourneyRecoveryForecastCandidateArbitrationRow(
                forecast_candidate_arbitration_id=nid('jfrar'),environment=p.environment,portfolio_id=portfolio_id,
                winner_candidate_id=(winner[0].forecast_portfolio_candidate_id if winner else None),winner_model_version_id=(winner[0].challenger_model_version_id if winner else None),
                decision_state=decision,rankings_json=rankings,reason_codes_json=reasons,evidence_json=evidence or {},decided_at=now(),supplier_fact_unchanged=True)
            s.add(x);p.portfolio_state='ARBITRATED' if winner else 'RETRAIN_REQUIRED';self._event(s,portfolio_id,(winner[0].forecast_portfolio_candidate_id if winner else None),'PORTFOLIO_ARBITRATED',{'decision':decision,'rankings':rankings},actor,p.environment);s.commit();return self._arbitration(x)

    def create_promotion_gate(self,portfolio_id,candidate_id,evidence=None,actor='portfolio-promotion-controller'):
        with SessionLocal() as s:
            p=s.get(JourneyRecoveryForecastRemediationPortfolioRow,portfolio_id);c=s.get(JourneyRecoveryForecastPortfolioCandidateRow,candidate_id)
            if not p or not c or c.portfolio_id!=portfolio_id: raise ValueError('PORTFOLIO_CANDIDATE_NOT_FOUND')
            arb=s.execute(select(JourneyRecoveryForecastCandidateArbitrationRow).where(JourneyRecoveryForecastCandidateArbitrationRow.portfolio_id==portfolio_id).order_by(JourneyRecoveryForecastCandidateArbitrationRow.decided_at.desc())).scalars().first()
            reasons=[]
            if not arb or arb.winner_candidate_id!=candidate_id: reasons.append('PORTFOLIO_WINNER_REQUIRED')
            ass=s.execute(select(JourneyRecoveryForecastPortfolioAssessmentRow).where(JourneyRecoveryForecastPortfolioAssessmentRow.portfolio_candidate_id==candidate_id).order_by(JourneyRecoveryForecastPortfolioAssessmentRow.evaluated_at.desc())).scalars().first()
            if not ass or ass.assessment_state!='PORTFOLIO_PASS': reasons.append('PORTFOLIO_PASS_ASSESSMENT_REQUIRED')
            state='PASS' if not reasons else 'BLOCKED';x=JourneyRecoveryForecastPortfolioPromotionGateRow(
                forecast_portfolio_promotion_gate_id=nid('jfrpg'),environment=p.environment,portfolio_id=portfolio_id,
                portfolio_candidate_id=candidate_id,challenger_model_version_id=c.challenger_model_version_id,
                arbitration_id=(arb.forecast_candidate_arbitration_id if arb else 'missing'),gate_state=state,promotion_eligible=not reasons,
                reason_codes_json=reasons,evidence_json=evidence or {},evaluated_at=now(),supplier_fact_unchanged=True)
            s.add(x);self._event(s,portfolio_id,candidate_id,'PORTFOLIO_PROMOTION_GATE_EVALUATED',{'gate_state':state,'reason_codes':reasons},actor,p.environment);s.commit();return self._gate(x)

    def assert_promotion_eligible_in_session(self,s,environment,challenger_model_version_id):
        candidates=s.execute(select(JourneyRecoveryForecastPortfolioCandidateRow).where(
            JourneyRecoveryForecastPortfolioCandidateRow.environment==environment,
            JourneyRecoveryForecastPortfolioCandidateRow.challenger_model_version_id==challenger_model_version_id
        ).order_by(JourneyRecoveryForecastPortfolioCandidateRow.created_at.desc())).scalars().all()
        if not candidates: return True
        for c in candidates:
            g=s.execute(select(JourneyRecoveryForecastPortfolioPromotionGateRow).where(
                JourneyRecoveryForecastPortfolioPromotionGateRow.portfolio_candidate_id==c.forecast_portfolio_candidate_id,
                JourneyRecoveryForecastPortfolioPromotionGateRow.challenger_model_version_id==challenger_model_version_id
            ).order_by(JourneyRecoveryForecastPortfolioPromotionGateRow.evaluated_at.desc())).scalars().first()
            if not g or not g.promotion_eligible: raise ValueError('MULTI_SEGMENT_PORTFOLIO_PROMOTION_GATE_REQUIRED')
        return True

    def status(self,environment='PROD'):
        with SessionLocal() as s:
            ps=s.execute(select(JourneyRecoveryForecastRemediationPortfolioRow).where(JourneyRecoveryForecastRemediationPortfolioRow.environment==environment).order_by(JourneyRecoveryForecastRemediationPortfolioRow.created_at.desc()).limit(20)).scalars().all()
            ar=s.execute(select(JourneyRecoveryForecastCandidateArbitrationRow).where(JourneyRecoveryForecastCandidateArbitrationRow.environment==environment).order_by(JourneyRecoveryForecastCandidateArbitrationRow.decided_at.desc()).limit(20)).scalars().all()
            return {'portfolios':[self._portfolio(x) for x in ps],'arbitrations':[self._arbitration(x) for x in ar],'supplier_fact_unchanged':True}

    def _event(self,s,pid,cid,typ,evidence,actor,environment):
        s.add(JourneyRecoveryForecastPortfolioEventRow(forecast_portfolio_event_id=nid('jfrpe'),environment=environment,portfolio_id=pid,portfolio_candidate_id=cid,event_type=typ,evidence_json=evidence or {},actor=actor,created_at=now(),supplier_fact_unchanged=True))
    def _portfolio(self,x): return {'portfolio_id':x.forecast_remediation_portfolio_id,'environment':x.environment,'champion_model_version_id':x.champion_model_version_id,'target_ids':x.target_ids_json,'objectives':x.objectives_json,'protected_segment_keys':x.protected_segment_keys_json,'state':x.portfolio_state,'supplier_fact_unchanged':True}
    def _conflict(self,x): return {'conflict_id':x.forecast_segment_conflict_id,'conflict_state':x.conflict_state,'resolution_state':x.resolution_state,'conflict_penalty_pct':x.conflict_penalty_pct,'supplier_fact_unchanged':True}
    def _candidate(self,x): return {'candidate_id':x.forecast_portfolio_candidate_id,'portfolio_id':x.portfolio_id,'model_version_id':x.challenger_model_version_id,'strategy':x.strategy,'covered_target_ids':x.covered_target_ids_json,'state':x.candidate_state,'supplier_fact_unchanged':True}
    def _assessment(self,x): return {'assessment_id':x.forecast_portfolio_assessment_id,'candidate_id':x.portfolio_candidate_id,'model_version_id':x.challenger_model_version_id,'must_fix_total':x.must_fix_total,'must_fix_passed':x.must_fix_passed,'portfolio_score':x.portfolio_score,'assessment_state':x.assessment_state,'reason_codes':x.reason_codes_json,'supplier_fact_unchanged':True}
    def _arbitration(self,x): return {'arbitration_id':x.forecast_candidate_arbitration_id,'portfolio_id':x.portfolio_id,'winner_candidate_id':x.winner_candidate_id,'winner_model_version_id':x.winner_model_version_id,'decision_state':x.decision_state,'rankings':x.rankings_json,'reason_codes':x.reason_codes_json,'supplier_fact_unchanged':True}
    def _gate(self,x): return {'promotion_gate_id':x.forecast_portfolio_promotion_gate_id,'candidate_id':x.portfolio_candidate_id,'model_version_id':x.challenger_model_version_id,'gate_state':x.gate_state,'promotion_eligible':x.promotion_eligible,'reason_codes':x.reason_codes_json,'supplier_fact_unchanged':True}

recovery_forecast_portfolio_governance_service=RecoveryForecastPortfolioGovernanceService()
