from datetime import datetime,timezone
from collections import defaultdict
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (JourneyRecoveryRiskAppetiteEnvelopeRow,JourneyRecoveryRiskStressScenarioRow,JourneyRecoveryRiskStressAssessmentRow,JourneyRecoveryRiskCapacityBufferRow,JourneyRecoveryStressPreemptiveFreezeRow,JourneyRecoveryRiskAppetiteEventRow,JourneyRecoveryExecutiveRiskPositionRow,JourneyRecoveryExecutiveRiskAcceptanceRow)
from go_hotel.journey.recovery_enterprise_risk_portfolio import recovery_enterprise_risk_portfolio_service as portfolio

def now(): return datetime.now(timezone.utc)
def aware(v): return v if v is None or v.tzinfo else v.replace(tzinfo=timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'

class RecoveryEnterpriseRiskAppetiteService:
    def active_appetite_in_session(self,s,environment):
        return s.execute(select(JourneyRecoveryRiskAppetiteEnvelopeRow).where(JourneyRecoveryRiskAppetiteEnvelopeRow.environment==environment,JourneyRecoveryRiskAppetiteEnvelopeRow.state=='ACTIVE').order_by(JourneyRecoveryRiskAppetiteEnvelopeRow.version_no.desc())).scalars().first()
    def create_appetite(self,key,environment,max_current,max_stressed,min_headroom,min_buffer_pct,max_sensitivity_pct,actor):
        if min(max_current,max_stressed,min_headroom,min_buffer_pct,max_sensitivity_pct)<=0 or min_buffer_pct>100: raise ValueError('INVALID_RISK_APPETITE_ENVELOPE')
        with SessionLocal() as s:
            prev=s.execute(select(JourneyRecoveryRiskAppetiteEnvelopeRow).where(JourneyRecoveryRiskAppetiteEnvelopeRow.appetite_key==key,JourneyRecoveryRiskAppetiteEnvelopeRow.environment==environment).order_by(JourneyRecoveryRiskAppetiteEnvelopeRow.version_no.desc())).scalars().first()
            x=JourneyRecoveryRiskAppetiteEnvelopeRow(risk_appetite_envelope_id=nid('jrra'),appetite_key=key,version_no=(prev.version_no+1 if prev else 1),environment=environment,max_current_exposure_points=max_current,max_stressed_exposure_points=max_stressed,min_headroom_points=min_headroom,min_capacity_buffer_pct=min_buffer_pct,max_sensitivity_pct=max_sensitivity_pct,requested_by=actor,board_approver_one=None,board_approver_two=None,state='PENDING_APPROVAL',created_at=now(),supplier_fact_unchanged=True)
            s.add(x);s.commit();return self.appetite(x.risk_appetite_envelope_id)
    def approve_appetite(self,i,actor):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryRiskAppetiteEnvelopeRow,i)
            if not x: raise ValueError('RISK_APPETITE_ENVELOPE_NOT_FOUND')
            if actor==x.requested_by: raise ValueError('RISK_APPETITE_MAKER_CHECKER_REQUIRED')
            if not x.board_approver_one: x.board_approver_one=actor
            elif x.board_approver_one==actor: raise ValueError('RISK_APPETITE_TWO_DISTINCT_APPROVERS_REQUIRED')
            elif not x.board_approver_two:
                x.board_approver_two=actor
                old=s.execute(select(JourneyRecoveryRiskAppetiteEnvelopeRow).where(JourneyRecoveryRiskAppetiteEnvelopeRow.environment==x.environment,JourneyRecoveryRiskAppetiteEnvelopeRow.state=='ACTIVE')).scalars().all()
                for y in old:y.state='SUPERSEDED'
                x.state='ACTIVE'
            s.commit();return self.appetite(i)
    def create_scenario(self,environment,key,scenario_type,shock_multiplier,correlation_amplifier,correlation_keys,risk_domains,actor):
        if scenario_type not in {'CLOUD_PROVIDER','IDENTITY_ROOT','REGION','RELEASE_CONTROL','COMBINED'}: raise ValueError('INVALID_STRESS_SCENARIO_TYPE')
        if shock_multiplier<1 or correlation_amplifier<1: raise ValueError('INVALID_STRESS_SHOCK')
        with SessionLocal() as s:
            x=JourneyRecoveryRiskStressScenarioRow(stress_scenario_id=nid('jrss'),environment=environment,scenario_key=key,scenario_type=scenario_type,shock_multiplier=shock_multiplier,correlation_amplifier=correlation_amplifier,affected_correlation_keys_json=correlation_keys or [],affected_risk_domains_json=risk_domains or [],state='ACTIVE',created_by=actor,created_at=now(),supplier_fact_unchanged=True);s.add(x);s.commit();return self.scenario(x.stress_scenario_id)
    def evaluate(self,environment,scenario_ids,actor='risk-stress-engine'):
        p=portfolio.evaluate(environment,actor)
        with SessionLocal() as s:
            appetite=self.active_appetite_in_session(s,environment)
            if not appetite: raise ValueError('ACTIVE_RISK_APPETITE_REQUIRED')
            scenarios=[s.get(JourneyRecoveryRiskStressScenarioRow,i) for i in scenario_ids]
            if not scenarios or any(x is None or x.state!='ACTIVE' or x.environment!=environment for x in scenarios): raise ValueError('ACTIVE_STRESS_SCENARIO_REQUIRED')
            positions=s.execute(select(JourneyRecoveryExecutiveRiskPositionRow).where(JourneyRecoveryExecutiveRiskPositionRow.environment==environment,JourneyRecoveryExecutiveRiskPositionRow.state=='ACTIVE')).scalars().all()
            accepts={x.executive_risk_acceptance_id:x for x in s.execute(select(JourneyRecoveryExecutiveRiskAcceptanceRow)).scalars().all()}
            effective=[]
            t=now()
            for pos in positions:
                a=accepts.get(pos.executive_risk_acceptance_id)
                if a and a.state=='APPROVED' and aware(a.starts_at)<=t<aware(a.expires_at): effective.append(pos)
            baseline=sum(x.exposure_points for x in effective)
            stressed_total=0.0; dims=[]; sensitivity_parts=[]
            for pos in effective:
                mult=1.0
                matched=[]
                for sc in scenarios:
                    hit_domain=not sc.affected_risk_domains_json or pos.risk_domain in sc.affected_risk_domains_json
                    hit_corr=not sc.affected_correlation_keys_json or bool(set(pos.correlation_keys_json or []) & set(sc.affected_correlation_keys_json or []))
                    if hit_domain and hit_corr:
                        mult=max(mult,sc.shock_multiplier*sc.correlation_amplifier);matched.append(sc.scenario_key)
                stressed=pos.exposure_points*mult;stressed_total+=stressed
                sens=0 if pos.exposure_points<=0 else (stressed-pos.exposure_points)/pos.exposure_points*100
                sensitivity_parts.append(sens)
                dims.append((pos,stressed,sens,matched))
            headroom=appetite.max_stressed_exposure_points-stressed_total
            buffer_pct=0 if appetite.max_stressed_exposure_points<=0 else max(0,headroom)/appetite.max_stressed_exposure_points*100
            sensitivity=0 if baseline<=0 else (stressed_total-baseline)/baseline*100
            reasons=[]
            if baseline>appetite.max_current_exposure_points: reasons.append('CURRENT_EXPOSURE_APPETITE_EXCEEDED')
            if stressed_total>appetite.max_stressed_exposure_points: reasons.append('STRESSED_EXPOSURE_APPETITE_EXCEEDED')
            if headroom<appetite.min_headroom_points: reasons.append('MINIMUM_HEADROOM_BREACHED')
            if buffer_pct<appetite.min_capacity_buffer_pct: reasons.append('CAPACITY_BUFFER_BELOW_MINIMUM')
            if sensitivity>appetite.max_sensitivity_pct: reasons.append('PORTFOLIO_SENSITIVITY_LIMIT_EXCEEDED')
            state='BREACH' if reasons else ('WATCH' if buffer_pct<appetite.min_capacity_buffer_pct*1.5 else 'PASS')
            a=JourneyRecoveryRiskStressAssessmentRow(stress_assessment_id=nid('jrsa'),environment=environment,risk_appetite_envelope_id=appetite.risk_appetite_envelope_id,portfolio_assessment_id=p['portfolio_assessment_id'],scenario_ids_json=scenario_ids,current_exposure_points=round(baseline,4),stressed_exposure_points=round(stressed_total,4),headroom_points=round(headroom,4),capacity_buffer_pct=round(buffer_pct,4),sensitivity_pct=round(sensitivity,4),assessment_state=state,reason_codes_json=reasons,metrics_json={'portfolio_state':p['portfolio_state'],'scenario_count':len(scenarios)},assessed_by=actor,assessed_at=now(),supplier_fact_unchanged=True);s.add(a);s.flush()
            for pos,stressed,sens,matched in dims:
                s.add(JourneyRecoveryRiskCapacityBufferRow(capacity_buffer_id=nid('jrcb'),stress_assessment_id=a.stress_assessment_id,dimension='POSITION',dimension_key=pos.risk_position_id,baseline_exposure_points=pos.exposure_points,stressed_exposure_points=round(stressed,4),sensitivity_pct=round(sens,4),headroom_points=round(max(0,appetite.max_stressed_exposure_points-stressed),4),created_at=now(),supplier_fact_unchanged=True))
            if state=='BREACH':
                f=s.execute(select(JourneyRecoveryStressPreemptiveFreezeRow).where(JourneyRecoveryStressPreemptiveFreezeRow.environment==environment,JourneyRecoveryStressPreemptiveFreezeRow.state=='ACTIVE')).scalars().first()
                if not f:
                    f=JourneyRecoveryStressPreemptiveFreezeRow(stress_freeze_id=nid('jrsf'),environment=environment,source_stress_assessment_id=a.stress_assessment_id,reason_codes_json=reasons,state='ACTIVE',activated_at=now(),released_at=None,released_by=None,release_evidence_reference=None,supplier_fact_unchanged=True);s.add(f);s.flush();self._event(s,environment,'STRESS_PREEMPTIVE_FREEZE_ACTIVATED',actor,{'reasons':reasons},a.stress_assessment_id,f.stress_freeze_id)
            s.commit();return self.assessment(a.stress_assessment_id)
    def assert_no_active_freeze(self,environment,code):
        with SessionLocal() as s:
            if not self.active_appetite_in_session(s,environment): return True
            f=s.execute(select(JourneyRecoveryStressPreemptiveFreezeRow).where(JourneyRecoveryStressPreemptiveFreezeRow.environment==environment,JourneyRecoveryStressPreemptiveFreezeRow.state=='ACTIVE')).scalars().first()
            if f: raise ValueError(code)
        return True
    def pre_request_waiver(self,environment): return self.assert_no_active_freeze(environment,'NEW_PRODUCTION_WAIVER_BLOCKED_BY_STRESS_PREEMPTIVE_FREEZE')
    def pre_request_executive_acceptance(self,environment): return self.assert_no_active_freeze(environment,'NEW_EXECUTIVE_RISK_ACCEPTANCE_BLOCKED_BY_STRESS_PREEMPTIVE_FREEZE')
    def assert_acceptance_eligible(self,environment): return self.assert_no_active_freeze(environment,'EXECUTIVE_RISK_ACCEPTANCE_BLOCKED_BY_STRESS_PREEMPTIVE_FREEZE')
    def release_freeze(self,environment,evidence_reference,actor):
        if not evidence_reference: raise ValueError('STRESS_FREEZE_RELEASE_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            f=s.execute(select(JourneyRecoveryStressPreemptiveFreezeRow).where(JourneyRecoveryStressPreemptiveFreezeRow.environment==environment,JourneyRecoveryStressPreemptiveFreezeRow.state=='ACTIVE').order_by(JourneyRecoveryStressPreemptiveFreezeRow.activated_at.desc())).scalars().first()
            if not f: raise ValueError('ACTIVE_STRESS_PREEMPTIVE_FREEZE_NOT_FOUND')
            latest=s.execute(select(JourneyRecoveryRiskStressAssessmentRow).where(JourneyRecoveryRiskStressAssessmentRow.environment==environment).order_by(JourneyRecoveryRiskStressAssessmentRow.assessed_at.desc())).scalars().first()
            if not latest or latest.assessment_state=='BREACH': raise ValueError('STRESS_FREEZE_RELEASE_CONDITIONS_NOT_MET')
            f.state='RELEASED';f.released_at=now();f.released_by=actor;f.release_evidence_reference=evidence_reference;self._event(s,environment,'STRESS_PREEMPTIVE_FREEZE_RELEASED',actor,{'evidence_reference':evidence_reference},latest.stress_assessment_id,f.stress_freeze_id);s.commit();return self.freeze(f.stress_freeze_id)
    def status(self,environment):
        with SessionLocal() as s:
            ap=self.active_appetite_in_session(s,environment)
            sc=s.execute(select(JourneyRecoveryRiskStressScenarioRow).where(JourneyRecoveryRiskStressScenarioRow.environment==environment).order_by(JourneyRecoveryRiskStressScenarioRow.created_at.desc())).scalars().all()
            ass=s.execute(select(JourneyRecoveryRiskStressAssessmentRow).where(JourneyRecoveryRiskStressAssessmentRow.environment==environment).order_by(JourneyRecoveryRiskStressAssessmentRow.assessed_at.desc())).scalars().first()
            fs=s.execute(select(JourneyRecoveryStressPreemptiveFreezeRow).where(JourneyRecoveryStressPreemptiveFreezeRow.environment==environment).order_by(JourneyRecoveryStressPreemptiveFreezeRow.activated_at.desc())).scalars().all()
            return {'environment':environment,'appetite':self._appetite(ap) if ap else None,'scenarios':[self._scenario(x) for x in sc[:50]],'latest_stress_assessment':self._assessment(ass) if ass else None,'stress_freezes':[self._freeze(x) for x in fs[:20]],'supplier_fact_unchanged':True}
    def _event(self,s,e,t,actor,evidence,assessment=None,freeze=None): s.add(JourneyRecoveryRiskAppetiteEventRow(risk_appetite_event_id=nid('jrrae'),environment=e,event_type=t,stress_assessment_id=assessment,stress_freeze_id=freeze,evidence_json=evidence or {},actor=actor,created_at=now(),supplier_fact_unchanged=True))
    def appetite(self,i):
        with SessionLocal() as s:return self._appetite(s.get(JourneyRecoveryRiskAppetiteEnvelopeRow,i))
    def scenario(self,i):
        with SessionLocal() as s:return self._scenario(s.get(JourneyRecoveryRiskStressScenarioRow,i))
    def assessment(self,i):
        with SessionLocal() as s:return self._assessment(s.get(JourneyRecoveryRiskStressAssessmentRow,i))
    def freeze(self,i):
        with SessionLocal() as s:return self._freeze(s.get(JourneyRecoveryStressPreemptiveFreezeRow,i))
    def _appetite(self,x): return {'risk_appetite_envelope_id':x.risk_appetite_envelope_id,'appetite_key':x.appetite_key,'version_no':x.version_no,'environment':x.environment,'max_current_exposure_points':x.max_current_exposure_points,'max_stressed_exposure_points':x.max_stressed_exposure_points,'min_headroom_points':x.min_headroom_points,'min_capacity_buffer_pct':x.min_capacity_buffer_pct,'max_sensitivity_pct':x.max_sensitivity_pct,'requested_by':x.requested_by,'board_approver_one':x.board_approver_one,'board_approver_two':x.board_approver_two,'state':x.state,'supplier_fact_unchanged':True}
    def _scenario(self,x): return {'stress_scenario_id':x.stress_scenario_id,'environment':x.environment,'scenario_key':x.scenario_key,'scenario_type':x.scenario_type,'shock_multiplier':x.shock_multiplier,'correlation_amplifier':x.correlation_amplifier,'affected_correlation_keys':x.affected_correlation_keys_json,'affected_risk_domains':x.affected_risk_domains_json,'state':x.state,'supplier_fact_unchanged':True}
    def _assessment(self,x): return {'stress_assessment_id':x.stress_assessment_id,'environment':x.environment,'risk_appetite_envelope_id':x.risk_appetite_envelope_id,'portfolio_assessment_id':x.portfolio_assessment_id,'scenario_ids':x.scenario_ids_json,'current_exposure_points':x.current_exposure_points,'stressed_exposure_points':x.stressed_exposure_points,'headroom_points':x.headroom_points,'capacity_buffer_pct':x.capacity_buffer_pct,'sensitivity_pct':x.sensitivity_pct,'assessment_state':x.assessment_state,'reason_codes':x.reason_codes_json,'metrics':x.metrics_json,'assessed_at':x.assessed_at.isoformat(),'supplier_fact_unchanged':True}
    def _freeze(self,x): return {'stress_freeze_id':x.stress_freeze_id,'environment':x.environment,'source_stress_assessment_id':x.source_stress_assessment_id,'reason_codes':x.reason_codes_json,'state':x.state,'activated_at':x.activated_at.isoformat(),'released_at':x.released_at.isoformat() if x.released_at else None,'release_evidence_reference':x.release_evidence_reference,'supplier_fact_unchanged':True}

recovery_enterprise_risk_appetite_service=RecoveryEnterpriseRiskAppetiteService()
