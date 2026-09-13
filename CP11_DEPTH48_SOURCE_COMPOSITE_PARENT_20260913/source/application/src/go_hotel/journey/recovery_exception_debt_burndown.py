from datetime import datetime, timezone, timedelta
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    JourneyRecoveryDebtBurnDownPolicyRow,JourneyRecoveryDebtAgingAssessmentRow,
    JourneyRecoveryDebtBurnDownPlanRow,JourneyRecoveryDebtBurnDownMilestoneRow,
    JourneyRecoveryDebtResponsibilityRow,JourneyRecoveryWaiverFreezeRow,
    JourneyRecoveryExecutiveRiskAcceptanceRow,JourneyRecoveryDebtGovernanceEventRow,
    JourneyRecoveryExceptionDebtRow,
)

def now(): return datetime.now(timezone.utc)
def aware(v): return v if v is None or v.tzinfo else v.replace(tzinfo=timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'

class RecoveryExceptionDebtBurnDownService:
    def active_policy_in_session(self,s,environment):
        return s.execute(select(JourneyRecoveryDebtBurnDownPolicyRow).where(JourneyRecoveryDebtBurnDownPolicyRow.environment==environment,JourneyRecoveryDebtBurnDownPolicyRow.state=='ACTIVE').order_by(JourneyRecoveryDebtBurnDownPolicyRow.version_no.desc())).scalars().first()

    def _active_residual_acceptance_in_session(self,s,environment):
        t=now()
        xs=s.execute(select(JourneyRecoveryExecutiveRiskAcceptanceRow).where(JourneyRecoveryExecutiveRiskAcceptanceRow.environment==environment,JourneyRecoveryExecutiveRiskAcceptanceRow.state.in_(['APPROVED','ACTIVE'])).order_by(JourneyRecoveryExecutiveRiskAcceptanceRow.expires_at.desc())).scalars().all()
        for x in xs:
            if not (x.executive_approver_one and x.executive_approver_two and aware(x.starts_at)<=t<aware(x.expires_at)):
                continue
            plan=s.get(JourneyRecoveryDebtBurnDownPlanRow,x.debt_burn_down_plan_id)
            if plan and plan.progress_percent>=100 and plan.state=='ACTIVE':
                return x
        return None

    def create_policy(self,policy_key,environment,freeze_trigger_debt_points,release_threshold_debt_points,max_debt_age_seconds,plan_due_seconds,milestone_overdue_escalation_seconds,executive_acceptance_max_seconds,actor):
        if freeze_trigger_debt_points<=0 or release_threshold_debt_points<0 or release_threshold_debt_points>=freeze_trigger_debt_points: raise ValueError('INVALID_DEBT_BURN_DOWN_THRESHOLDS')
        if min(max_debt_age_seconds,plan_due_seconds,milestone_overdue_escalation_seconds,executive_acceptance_max_seconds)<=0: raise ValueError('INVALID_DEBT_BURN_DOWN_POLICY')
        with SessionLocal() as s:
            prev=s.execute(select(JourneyRecoveryDebtBurnDownPolicyRow).where(JourneyRecoveryDebtBurnDownPolicyRow.policy_key==policy_key,JourneyRecoveryDebtBurnDownPolicyRow.environment==environment).order_by(JourneyRecoveryDebtBurnDownPolicyRow.version_no.desc())).scalars().first()
            for p in s.execute(select(JourneyRecoveryDebtBurnDownPolicyRow).where(JourneyRecoveryDebtBurnDownPolicyRow.environment==environment,JourneyRecoveryDebtBurnDownPolicyRow.state=='ACTIVE')).scalars().all(): p.state='SUPERSEDED'
            x=JourneyRecoveryDebtBurnDownPolicyRow(debt_burn_down_policy_id=nid('jrbdp'),policy_key=policy_key,version_no=(prev.version_no+1 if prev else 1),environment=environment,freeze_trigger_debt_points=freeze_trigger_debt_points,release_threshold_debt_points=release_threshold_debt_points,max_debt_age_seconds=max_debt_age_seconds,plan_due_seconds=plan_due_seconds,milestone_overdue_escalation_seconds=milestone_overdue_escalation_seconds,executive_acceptance_max_seconds=executive_acceptance_max_seconds,state='ACTIVE',created_by=actor,created_at=now(),supplier_fact_unchanged=True)
            s.add(x);s.commit();return self.policy(x.debt_burn_down_policy_id)

    def evaluate_aging(self,environment,actor='system'):
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment)
            if not p:return {'environment':environment,'policy_active':False,'supplier_fact_unchanged':True}
            debt=s.execute(select(JourneyRecoveryExceptionDebtRow).where(JourneyRecoveryExceptionDebtRow.environment==environment).order_by(JourneyRecoveryExceptionDebtRow.evaluated_at.desc())).scalars().first()
            if not debt: raise ValueError('EXCEPTION_DEBT_ASSESSMENT_REQUIRED')
            age=max(0,int((now()-aware(debt.evaluated_at)).total_seconds()))
            reasons=[]
            if debt.debt_points>=p.freeze_trigger_debt_points: reasons.append('DEBT_POINTS_FREEZE_THRESHOLD_EXCEEDED')
            if age>=p.max_debt_age_seconds and debt.debt_state!='HEALTHY': reasons.append('EXCEPTION_DEBT_AGED_OUT')
            residual_acceptance=self._active_residual_acceptance_in_session(s,environment)
            if reasons and residual_acceptance:
                reasons.append('TIME_BOUND_EXECUTIVE_RESIDUAL_RISK_ACCEPTANCE_ACTIVE')
                aging_state='ACCEPTED_RESIDUAL_RISK'
            else:
                aging_state='CRITICAL' if reasons else ('WATCH' if debt.debt_state!='HEALTHY' else 'HEALTHY')
            x=JourneyRecoveryDebtAgingAssessmentRow(debt_aging_assessment_id=nid('jrdaa'),environment=environment,exception_debt_id=debt.exception_debt_id,debt_burn_down_policy_id=p.debt_burn_down_policy_id,debt_points=debt.debt_points,debt_state=debt.debt_state,debt_age_seconds=age,aging_state=aging_state,reason_codes_json=reasons,assessed_by=actor,assessed_at=now(),supplier_fact_unchanged=True)
            s.add(x)
            freeze=None
            if reasons and not residual_acceptance:
                freeze=s.execute(select(JourneyRecoveryWaiverFreezeRow).where(JourneyRecoveryWaiverFreezeRow.environment==environment,JourneyRecoveryWaiverFreezeRow.state=='ACTIVE').order_by(JourneyRecoveryWaiverFreezeRow.activated_at.desc())).scalars().first()
                if not freeze:
                    freeze=JourneyRecoveryWaiverFreezeRow(waiver_freeze_id=nid('jrwf'),environment=environment,source_exception_debt_id=debt.exception_debt_id,source_aging_assessment_id=x.debt_aging_assessment_id,reason_codes_json=reasons,state='ACTIVE',activated_at=now(),released_at=None,released_by=None,release_evidence_reference=None,supplier_fact_unchanged=True)
                    s.add(freeze);self._event(s,environment,None,freeze.waiver_freeze_id,None,'WAIVER_FREEZE_ACTIVATED',actor,{'reason_codes':reasons,'debt_points':debt.debt_points})
            s.commit();return self.aging(x.debt_aging_assessment_id)

    def pre_request_waiver(self,environment,actor='system'):
        try:
            from go_hotel.journey.recovery_enterprise_risk_portfolio import recovery_enterprise_risk_portfolio_service as portfolio
            portfolio.pre_request_waiver(environment,actor)
        except ImportError:
            pass
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment)
            if not p:return None
            freeze=s.execute(select(JourneyRecoveryWaiverFreezeRow).where(JourneyRecoveryWaiverFreezeRow.environment==environment,JourneyRecoveryWaiverFreezeRow.state=='ACTIVE')).scalars().first()
            if freeze: raise ValueError('NEW_PRODUCTION_WAIVER_BLOCKED_BY_ACTIVE_DEBT_FREEZE')
        a=self.evaluate_aging(environment,actor)
        if a.get('aging_state')=='CRITICAL': raise ValueError('NEW_PRODUCTION_WAIVER_BLOCKED_BY_ACTIVE_DEBT_FREEZE')
        return a

    def create_plan(self,environment,plan_owner,executive_sponsor,objective,target_debt_points,milestones,responsibilities,actor):
        if not plan_owner or not executive_sponsor or not objective: raise ValueError('BURN_DOWN_PLAN_OWNERSHIP_REQUIRED')
        if not milestones: raise ValueError('BURN_DOWN_MILESTONES_REQUIRED')
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment)
            if not p: raise ValueError('ACTIVE_DEBT_BURN_DOWN_POLICY_REQUIRED')
            debt=s.execute(select(JourneyRecoveryExceptionDebtRow).where(JourneyRecoveryExceptionDebtRow.environment==environment).order_by(JourneyRecoveryExceptionDebtRow.evaluated_at.desc())).scalars().first()
            if not debt: raise ValueError('EXCEPTION_DEBT_ASSESSMENT_REQUIRED')
            if target_debt_points<0 or target_debt_points>=debt.debt_points: raise ValueError('BURN_DOWN_TARGET_MUST_REDUCE_DEBT')
            x=JourneyRecoveryDebtBurnDownPlanRow(debt_burn_down_plan_id=nid('jrbd'),environment=environment,source_exception_debt_id=debt.exception_debt_id,plan_owner=plan_owner,executive_sponsor=executive_sponsor,objective=objective,starting_debt_points=debt.debt_points,target_debt_points=target_debt_points,opened_at=now(),due_at=now()+timedelta(seconds=p.plan_due_seconds),progress_percent=0,state='ACTIVE',closure_evidence_reference=None,supplier_fact_unchanged=True)
            s.add(x);s.flush()
            for i,m in enumerate(milestones,1):
                due=aware(m.get('due_at')) if m.get('due_at') else now()+timedelta(seconds=min(p.plan_due_seconds,i*max(60,p.plan_due_seconds//max(1,len(milestones)))))
                s.add(JourneyRecoveryDebtBurnDownMilestoneRow(debt_burn_down_milestone_id=nid('jrbm'),debt_burn_down_plan_id=x.debt_burn_down_plan_id,sequence_no=i,title=m['title'],owner_team=m['owner_team'],accountable_owner=m['accountable_owner'],target_debt_reduction_points=float(m.get('target_debt_reduction_points',0)),due_at=due,completed_at=None,evidence_reference=None,escalation_level=0,state='OPEN',supplier_fact_unchanged=True))
            for r in responsibilities or []:
                s.add(JourneyRecoveryDebtResponsibilityRow(debt_responsibility_id=nid('jrrs'),debt_burn_down_plan_id=x.debt_burn_down_plan_id,team_key=r['team_key'],responsible_owner=r['responsible_owner'],accountable_executive=r['accountable_executive'],consulted_json=r.get('consulted',[]),informed_json=r.get('informed',[]),created_at=now(),supplier_fact_unchanged=True))
            self._event(s,environment,x.debt_burn_down_plan_id,None,None,'BURN_DOWN_PLAN_OPENED',actor,{'starting_debt_points':debt.debt_points,'target_debt_points':target_debt_points})
            s.commit();return self.plan(x.debt_burn_down_plan_id)

    def complete_milestone(self,milestone_id,evidence_reference,actor):
        if not evidence_reference: raise ValueError('MILESTONE_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            m=s.get(JourneyRecoveryDebtBurnDownMilestoneRow,milestone_id)
            if not m: raise ValueError('BURN_DOWN_MILESTONE_NOT_FOUND')
            if m.state=='COMPLETED': return self._milestone(m)
            m.state='COMPLETED';m.completed_at=now();m.evidence_reference=evidence_reference
            plan=s.get(JourneyRecoveryDebtBurnDownPlanRow,m.debt_burn_down_plan_id)
            allm=s.execute(select(JourneyRecoveryDebtBurnDownMilestoneRow).where(JourneyRecoveryDebtBurnDownMilestoneRow.debt_burn_down_plan_id==plan.debt_burn_down_plan_id)).scalars().all()
            done=sum(1 for x in allm if x.state=='COMPLETED')
            plan.progress_percent=round(done/max(1,len(allm))*100,2)
            self._event(s,plan.environment,plan.debt_burn_down_plan_id,None,None,'BURN_DOWN_MILESTONE_COMPLETED',actor,{'milestone_id':m.milestone_id if hasattr(m,'milestone_id') else milestone_id,'evidence_reference':evidence_reference})
            s.commit();return self._milestone(m)

    def governance_tick(self,environment,actor='system'):
        escalated=[];t=now()
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment)
            if not p:return {'environment':environment,'escalated':[],'supplier_fact_unchanged':True}
            plans=s.execute(select(JourneyRecoveryDebtBurnDownPlanRow).where(JourneyRecoveryDebtBurnDownPlanRow.environment==environment,JourneyRecoveryDebtBurnDownPlanRow.state=='ACTIVE')).scalars().all()
            for plan in plans:
                ms=s.execute(select(JourneyRecoveryDebtBurnDownMilestoneRow).where(JourneyRecoveryDebtBurnDownMilestoneRow.debt_burn_down_plan_id==plan.debt_burn_down_plan_id,JourneyRecoveryDebtBurnDownMilestoneRow.state.in_(['OPEN','OVERDUE','ESCALATED']))).scalars().all()
                for m in ms:
                    if aware(m.due_at)<t:
                        m.state='OVERDUE'
                        overdue=(t-aware(m.due_at)).total_seconds()
                        level=max(1,int(overdue//p.milestone_overdue_escalation_seconds)+1)
                        if level>m.escalation_level:
                            m.escalation_level=level;m.state='ESCALATED';escalated.append(m.debt_burn_down_milestone_id)
                            self._event(s,environment,plan.debt_burn_down_plan_id,None,None,'BURN_DOWN_MILESTONE_ESCALATED',actor,{'milestone_id':m.debt_burn_down_milestone_id,'level':level,'owner_team':m.owner_team})
            s.commit()
        try:self.evaluate_aging(environment,actor)
        except ValueError:pass
        return {'environment':environment,'escalated':escalated,'supplier_fact_unchanged':True}

    def request_executive_acceptance(self,plan_id,residual_risk_summary,evidence_reference,starts_at,expires_at,actor):
        st=aware(starts_at);ex=aware(expires_at)
        if not residual_risk_summary or not evidence_reference: raise ValueError('EXECUTIVE_RISK_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            plan=s.get(JourneyRecoveryDebtBurnDownPlanRow,plan_id)
            if not plan: raise ValueError('BURN_DOWN_PLAN_NOT_FOUND')
            p=self.active_policy_in_session(s,plan.environment)
            if not p: raise ValueError('ACTIVE_DEBT_BURN_DOWN_POLICY_REQUIRED')
            try:
                from go_hotel.journey.recovery_enterprise_risk_portfolio import recovery_enterprise_risk_portfolio_service as portfolio
                portfolio.pre_request_executive_acceptance(plan.environment,actor)
            except ImportError:
                pass
            if ex<=st or ex<=now() or (ex-st).total_seconds()>p.executive_acceptance_max_seconds: raise ValueError('INVALID_EXECUTIVE_RISK_ACCEPTANCE_WINDOW')
            x=JourneyRecoveryExecutiveRiskAcceptanceRow(executive_risk_acceptance_id=nid('jrera'),environment=plan.environment,debt_burn_down_plan_id=plan_id,residual_risk_summary=residual_risk_summary,evidence_reference=evidence_reference,requested_by=actor,requested_at=now(),executive_approver_one=None,executive_approver_two=None,starts_at=st,expires_at=ex,state='PENDING_APPROVAL',supplier_fact_unchanged=True)
            s.add(x);self._event(s,plan.environment,plan_id,None,x.executive_risk_acceptance_id,'EXECUTIVE_RISK_ACCEPTANCE_REQUESTED',actor,{});s.commit();return self.acceptance(x.executive_risk_acceptance_id)

    def approve_executive_acceptance(self,acceptance_id,actor):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryExecutiveRiskAcceptanceRow,acceptance_id)
            if not x: raise ValueError('EXECUTIVE_RISK_ACCEPTANCE_NOT_FOUND')
            if x.requested_by==actor: raise ValueError('EXECUTIVE_RISK_MAKER_CHECKER_REQUIRED')
            if aware(x.expires_at)<=now(): x.state='EXPIRED';s.commit();raise ValueError('EXECUTIVE_RISK_ACCEPTANCE_EXPIRED')
            if not x.executive_approver_one:x.executive_approver_one=actor;x.state='AWAITING_SECOND_APPROVAL'
            elif x.executive_approver_one==actor: raise ValueError('TWO_DISTINCT_EXECUTIVE_APPROVERS_REQUIRED')
            elif not x.executive_approver_two:x.executive_approver_two=actor;x.state='APPROVED'
            else: raise ValueError('EXECUTIVE_RISK_ACCEPTANCE_ALREADY_APPROVED')
            self._event(s,x.environment,x.debt_burn_down_plan_id,None,x.executive_risk_acceptance_id,'EXECUTIVE_RISK_ACCEPTANCE_APPROVED',actor,{'state':x.state});s.commit();return self.acceptance(acceptance_id)

    def release_freeze(self,environment,evidence_reference,actor):
        if not evidence_reference: raise ValueError('WAIVER_FREEZE_RELEASE_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment)
            if not p: raise ValueError('ACTIVE_DEBT_BURN_DOWN_POLICY_REQUIRED')
            f=s.execute(select(JourneyRecoveryWaiverFreezeRow).where(JourneyRecoveryWaiverFreezeRow.environment==environment,JourneyRecoveryWaiverFreezeRow.state=='ACTIVE').order_by(JourneyRecoveryWaiverFreezeRow.activated_at.desc())).scalars().first()
            if not f: raise ValueError('ACTIVE_WAIVER_FREEZE_NOT_FOUND')
            debt=s.execute(select(JourneyRecoveryExceptionDebtRow).where(JourneyRecoveryExceptionDebtRow.environment==environment).order_by(JourneyRecoveryExceptionDebtRow.evaluated_at.desc())).scalars().first()
            plans=s.execute(select(JourneyRecoveryDebtBurnDownPlanRow).where(JourneyRecoveryDebtBurnDownPlanRow.environment==environment,JourneyRecoveryDebtBurnDownPlanRow.state=='ACTIVE').order_by(JourneyRecoveryDebtBurnDownPlanRow.opened_at.desc())).scalars().all()
            active_accept=s.execute(select(JourneyRecoveryExecutiveRiskAcceptanceRow).where(JourneyRecoveryExecutiveRiskAcceptanceRow.environment==environment,JourneyRecoveryExecutiveRiskAcceptanceRow.state.in_(['APPROVED','ACTIVE'])).order_by(JourneyRecoveryExecutiveRiskAcceptanceRow.expires_at.desc())).scalars().first()
            accepted=bool(active_accept and active_accept.executive_approver_one and active_accept.executive_approver_two and aware(active_accept.starts_at)<=now()<aware(active_accept.expires_at))
            debt_ok=bool(debt and debt.debt_points<=p.release_threshold_debt_points)
            plan_progress_ok=bool(plans and max(x.progress_percent for x in plans)>=100)
            if accepted and plan_progress_ok and not debt_ok:
                try:
                    from go_hotel.journey.recovery_enterprise_risk_portfolio import recovery_enterprise_risk_portfolio_service as portfolio
                    portfolio.assert_acceptance_eligible(active_accept.executive_risk_acceptance_id,environment)
                except ImportError:
                    pass
            if not debt_ok and not (accepted and plan_progress_ok): raise ValueError('WAIVER_FREEZE_RELEASE_CONDITIONS_NOT_MET')
            f.state='RELEASED';f.released_at=now();f.released_by=actor;f.release_evidence_reference=evidence_reference
            if active_accept and accepted:active_accept.state='ACTIVE'
            self._event(s,environment,plans[0].debt_burn_down_plan_id if plans else None,f.waiver_freeze_id,active_accept.executive_risk_acceptance_id if active_accept else None,'WAIVER_FREEZE_RELEASED',actor,{'debt_ok':debt_ok,'executive_acceptance_used':accepted,'evidence_reference':evidence_reference})
            s.commit();return self.freeze(f.waiver_freeze_id)

    def status(self,environment):
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment)
            aging=s.execute(select(JourneyRecoveryDebtAgingAssessmentRow).where(JourneyRecoveryDebtAgingAssessmentRow.environment==environment).order_by(JourneyRecoveryDebtAgingAssessmentRow.assessed_at.desc())).scalars().first()
            plans=s.execute(select(JourneyRecoveryDebtBurnDownPlanRow).where(JourneyRecoveryDebtBurnDownPlanRow.environment==environment).order_by(JourneyRecoveryDebtBurnDownPlanRow.opened_at.desc())).scalars().all()
            freezes=s.execute(select(JourneyRecoveryWaiverFreezeRow).where(JourneyRecoveryWaiverFreezeRow.environment==environment).order_by(JourneyRecoveryWaiverFreezeRow.activated_at.desc())).scalars().all()
            acc=s.execute(select(JourneyRecoveryExecutiveRiskAcceptanceRow).where(JourneyRecoveryExecutiveRiskAcceptanceRow.environment==environment).order_by(JourneyRecoveryExecutiveRiskAcceptanceRow.requested_at.desc())).scalars().all()
            events=s.execute(select(JourneyRecoveryDebtGovernanceEventRow).where(JourneyRecoveryDebtGovernanceEventRow.environment==environment).order_by(JourneyRecoveryDebtGovernanceEventRow.created_at.desc())).scalars().all()
            return {'environment':environment,'policy':self._policy(p) if p else None,'aging':self._aging(aging) if aging else None,'plans':[self._plan(s,x) for x in plans[:20]],'freezes':[self._freeze(x) for x in freezes[:20]],'executive_acceptances':[self._acceptance(x) for x in acc[:20]],'events':[{'event_type':x.event_type,'evidence':x.evidence_json,'created_at':x.created_at.isoformat()} for x in events[:50]],'supplier_fact_unchanged':True}

    def _event(self,s,env,plan,freeze,acc,event_type,actor,evidence):
        s.add(JourneyRecoveryDebtGovernanceEventRow(debt_governance_event_id=nid('jrdge'),environment=env,plan_id=plan,freeze_id=freeze,executive_acceptance_id=acc,event_type=event_type,evidence_json=evidence or {},actor=actor,created_at=now(),supplier_fact_unchanged=True))
    def policy(self,i):
        with SessionLocal() as s:return self._policy(s.get(JourneyRecoveryDebtBurnDownPolicyRow,i))
    def aging(self,i):
        with SessionLocal() as s:return self._aging(s.get(JourneyRecoveryDebtAgingAssessmentRow,i))
    def plan(self,i):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryDebtBurnDownPlanRow,i);return self._plan(s,x)
    def freeze(self,i):
        with SessionLocal() as s:return self._freeze(s.get(JourneyRecoveryWaiverFreezeRow,i))
    def acceptance(self,i):
        with SessionLocal() as s:return self._acceptance(s.get(JourneyRecoveryExecutiveRiskAcceptanceRow,i))
    def _policy(self,x):return {'debt_burn_down_policy_id':x.debt_burn_down_policy_id,'policy_key':x.policy_key,'version_no':x.version_no,'environment':x.environment,'freeze_trigger_debt_points':x.freeze_trigger_debt_points,'release_threshold_debt_points':x.release_threshold_debt_points,'max_debt_age_seconds':x.max_debt_age_seconds,'plan_due_seconds':x.plan_due_seconds,'milestone_overdue_escalation_seconds':x.milestone_overdue_escalation_seconds,'executive_acceptance_max_seconds':x.executive_acceptance_max_seconds,'state':x.state,'supplier_fact_unchanged':True}
    def _aging(self,x):return {'debt_aging_assessment_id':x.debt_aging_assessment_id,'environment':x.environment,'exception_debt_id':x.exception_debt_id,'debt_points':x.debt_points,'debt_state':x.debt_state,'debt_age_seconds':x.debt_age_seconds,'aging_state':x.aging_state,'reason_codes':x.reason_codes_json,'assessed_at':x.assessed_at.isoformat(),'supplier_fact_unchanged':True}
    def _milestone(self,x):return {'debt_burn_down_milestone_id':x.debt_burn_down_milestone_id,'sequence_no':x.sequence_no,'title':x.title,'owner_team':x.owner_team,'accountable_owner':x.accountable_owner,'target_debt_reduction_points':x.target_debt_reduction_points,'due_at':x.due_at.isoformat(),'completed_at':x.completed_at.isoformat() if x.completed_at else None,'evidence_reference':x.evidence_reference,'escalation_level':x.escalation_level,'state':x.state,'supplier_fact_unchanged':True}
    def _plan(self,s,x):
        ms=s.execute(select(JourneyRecoveryDebtBurnDownMilestoneRow).where(JourneyRecoveryDebtBurnDownMilestoneRow.debt_burn_down_plan_id==x.debt_burn_down_plan_id).order_by(JourneyRecoveryDebtBurnDownMilestoneRow.sequence_no)).scalars().all();rs=s.execute(select(JourneyRecoveryDebtResponsibilityRow).where(JourneyRecoveryDebtResponsibilityRow.debt_burn_down_plan_id==x.debt_burn_down_plan_id)).scalars().all()
        return {'debt_burn_down_plan_id':x.debt_burn_down_plan_id,'environment':x.environment,'source_exception_debt_id':x.source_exception_debt_id,'plan_owner':x.plan_owner,'executive_sponsor':x.executive_sponsor,'objective':x.objective,'starting_debt_points':x.starting_debt_points,'target_debt_points':x.target_debt_points,'opened_at':x.opened_at.isoformat(),'due_at':x.due_at.isoformat(),'progress_percent':x.progress_percent,'state':x.state,'milestones':[self._milestone(m) for m in ms],'responsibility_matrix':[{'team_key':r.team_key,'responsible_owner':r.responsible_owner,'accountable_executive':r.accountable_executive,'consulted':r.consulted_json,'informed':r.informed_json} for r in rs],'supplier_fact_unchanged':True}
    def _freeze(self,x):return {'waiver_freeze_id':x.waiver_freeze_id,'environment':x.environment,'source_exception_debt_id':x.source_exception_debt_id,'reason_codes':x.reason_codes_json,'state':x.state,'activated_at':x.activated_at.isoformat(),'released_at':x.released_at.isoformat() if x.released_at else None,'release_evidence_reference':x.release_evidence_reference,'supplier_fact_unchanged':True}
    def _acceptance(self,x):return {'executive_risk_acceptance_id':x.executive_risk_acceptance_id,'environment':x.environment,'debt_burn_down_plan_id':x.debt_burn_down_plan_id,'residual_risk_summary':x.residual_risk_summary,'evidence_reference':x.evidence_reference,'requested_by':x.requested_by,'executive_approver_one':x.executive_approver_one,'executive_approver_two':x.executive_approver_two,'starts_at':x.starts_at.isoformat(),'expires_at':x.expires_at.isoformat(),'state':x.state,'supplier_fact_unchanged':True}

recovery_exception_debt_burndown_service=RecoveryExceptionDebtBurnDownService()
