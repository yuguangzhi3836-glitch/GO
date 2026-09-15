from datetime import datetime, timezone
from collections import defaultdict
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    JourneyRecoveryEnterpriseRiskLimitRow,JourneyRecoveryExecutiveRiskPositionRow,
    JourneyRecoveryExecutiveRiskPortfolioAssessmentRow,JourneyRecoveryResidualRiskConcentrationRow,
    JourneyRecoveryPortfolioFreezeRow,JourneyRecoveryEnterpriseRiskEventRow,
    JourneyRecoveryExecutiveRiskAcceptanceRow,
)

def now(): return datetime.now(timezone.utc)
def aware(v): return v if v is None or v.tzinfo else v.replace(tzinfo=timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'

class RecoveryEnterpriseRiskPortfolioService:
    def active_limit_in_session(self,s,environment):
        return s.execute(select(JourneyRecoveryEnterpriseRiskLimitRow).where(JourneyRecoveryEnterpriseRiskLimitRow.environment==environment,JourneyRecoveryEnterpriseRiskLimitRow.state=='ACTIVE').order_by(JourneyRecoveryEnterpriseRiskLimitRow.version_no.desc())).scalars().first()

    def create_limit(self,limit_key,environment,max_aggregate_exposure_points,max_team_concentration_pct,max_risk_domain_concentration_pct,max_correlated_exposure_points,max_active_acceptances,actor):
        vals=[max_aggregate_exposure_points,max_correlated_exposure_points,max_active_acceptances]
        if min(vals)<=0 or not (0<max_team_concentration_pct<=100) or not (0<max_risk_domain_concentration_pct<=100): raise ValueError('INVALID_ENTERPRISE_RISK_LIMIT')
        with SessionLocal() as s:
            prev=s.execute(select(JourneyRecoveryEnterpriseRiskLimitRow).where(JourneyRecoveryEnterpriseRiskLimitRow.limit_key==limit_key,JourneyRecoveryEnterpriseRiskLimitRow.environment==environment).order_by(JourneyRecoveryEnterpriseRiskLimitRow.version_no.desc())).scalars().first()
            x=JourneyRecoveryEnterpriseRiskLimitRow(enterprise_risk_limit_id=nid('jrer'),limit_key=limit_key,version_no=(prev.version_no+1 if prev else 1),environment=environment,max_aggregate_exposure_points=max_aggregate_exposure_points,max_team_concentration_pct=max_team_concentration_pct,max_risk_domain_concentration_pct=max_risk_domain_concentration_pct,max_correlated_exposure_points=max_correlated_exposure_points,max_active_acceptances=max_active_acceptances,requested_by=actor,board_approver_one=None,board_approver_two=None,state='PENDING_APPROVAL',created_at=now(),supplier_fact_unchanged=True)
            s.add(x);s.commit();return self.limit(x.enterprise_risk_limit_id)

    def approve_limit(self,limit_id,actor):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryEnterpriseRiskLimitRow,limit_id)
            if not x: raise ValueError('ENTERPRISE_RISK_LIMIT_NOT_FOUND')
            if x.requested_by==actor: raise ValueError('BOARD_RISK_LIMIT_MAKER_CHECKER_REQUIRED')
            if x.state=='ACTIVE': return self._limit(x)
            if not x.board_approver_one:
                x.board_approver_one=actor;x.state='AWAITING_SECOND_APPROVAL'
            elif x.board_approver_one==actor: raise ValueError('TWO_DISTINCT_BOARD_APPROVERS_REQUIRED')
            elif not x.board_approver_two:
                x.board_approver_two=actor
                for p in s.execute(select(JourneyRecoveryEnterpriseRiskLimitRow).where(JourneyRecoveryEnterpriseRiskLimitRow.environment==x.environment,JourneyRecoveryEnterpriseRiskLimitRow.state=='ACTIVE')).scalars().all(): p.state='SUPERSEDED'
                x.state='ACTIVE'
            else: raise ValueError('ENTERPRISE_RISK_LIMIT_ALREADY_APPROVED')
            self._event(s,x.environment,'ENTERPRISE_RISK_LIMIT_APPROVED',actor,{'limit_id':limit_id,'state':x.state})
            s.commit();return self.limit(limit_id)

    def register_position(self,acceptance_id,team_key,risk_domain,exposure_points,correlation_keys,actor):
        if not team_key or not risk_domain or exposure_points<=0: raise ValueError('COMPLETE_RISK_POSITION_REQUIRED')
        with SessionLocal() as s:
            a=s.get(JourneyRecoveryExecutiveRiskAcceptanceRow,acceptance_id)
            if not a: raise ValueError('EXECUTIVE_RISK_ACCEPTANCE_NOT_FOUND')
            if a.state not in ('APPROVED','ACTIVE') or not (a.executive_approver_one and a.executive_approver_two): raise ValueError('APPROVED_EXECUTIVE_RISK_ACCEPTANCE_REQUIRED')
            existing=s.execute(select(JourneyRecoveryExecutiveRiskPositionRow).where(JourneyRecoveryExecutiveRiskPositionRow.executive_risk_acceptance_id==acceptance_id,JourneyRecoveryExecutiveRiskPositionRow.state=='ACTIVE')).scalars().first()
            if existing: raise ValueError('EXECUTIVE_RISK_POSITION_ALREADY_REGISTERED')
            x=JourneyRecoveryExecutiveRiskPositionRow(risk_position_id=nid('jrrp'),environment=a.environment,executive_risk_acceptance_id=acceptance_id,team_key=team_key,risk_domain=risk_domain,exposure_points=float(exposure_points),correlation_keys_json=list(dict.fromkeys(correlation_keys or [])),state='ACTIVE',registered_by=actor,registered_at=now(),supplier_fact_unchanged=True)
            s.add(x);self._event(s,a.environment,'RISK_POSITION_REGISTERED',actor,{'acceptance_id':acceptance_id,'team_key':team_key,'risk_domain':risk_domain,'exposure_points':exposure_points},risk_position=x.risk_position_id);s.commit()
        return self.position(x.risk_position_id)

    def _effective_positions(self,s,environment):
        out=[];t=now()
        for p in s.execute(select(JourneyRecoveryExecutiveRiskPositionRow).where(JourneyRecoveryExecutiveRiskPositionRow.environment==environment,JourneyRecoveryExecutiveRiskPositionRow.state=='ACTIVE')).scalars().all():
            a=s.get(JourneyRecoveryExecutiveRiskAcceptanceRow,p.executive_risk_acceptance_id)
            if a and a.state in ('APPROVED','ACTIVE') and a.executive_approver_one and a.executive_approver_two and aware(a.starts_at)<=t<aware(a.expires_at): out.append((p,a))
        return out

    def evaluate(self,environment,actor='system'):
        with SessionLocal() as s:
            lim=self.active_limit_in_session(s,environment)
            if not lim: raise ValueError('ACTIVE_ENTERPRISE_RISK_LIMIT_REQUIRED')
            pairs=self._effective_positions(s,environment);positions=[p for p,_ in pairs]
            agg=sum(p.exposure_points for p in positions)
            teams=defaultdict(float);domains=defaultdict(float);corr=defaultdict(float)
            for p in positions:
                teams[p.team_key]+=p.exposure_points;domains[p.risk_domain]+=p.exposure_points
                for k in p.correlation_keys_json or []: corr[k]+=p.exposure_points
            team_pct=max([v/agg*100 for v in teams.values()] or [0]);domain_pct=max([v/agg*100 for v in domains.values()] or [0]);corr_max=max(corr.values() or [0])
            reasons=[]
            if agg>lim.max_aggregate_exposure_points: reasons.append('AGGREGATE_EXPOSURE_LIMIT_EXCEEDED')
            if len(positions)>1 and team_pct>lim.max_team_concentration_pct: reasons.append('TEAM_CONCENTRATION_LIMIT_EXCEEDED')
            if len(positions)>1 and domain_pct>lim.max_risk_domain_concentration_pct: reasons.append('RISK_DOMAIN_CONCENTRATION_LIMIT_EXCEEDED')
            if corr_max>lim.max_correlated_exposure_points: reasons.append('CORRELATED_EXPOSURE_LIMIT_EXCEEDED')
            if len(positions)>lim.max_active_acceptances: reasons.append('ACTIVE_ACCEPTANCE_LIMIT_EXCEEDED')
            state='BREACH' if reasons else ('WATCH' if agg>=0.8*lim.max_aggregate_exposure_points else 'PASS')
            x=JourneyRecoveryExecutiveRiskPortfolioAssessmentRow(portfolio_assessment_id=nid('jrpa'),environment=environment,enterprise_risk_limit_id=lim.enterprise_risk_limit_id,active_acceptance_count=len(positions),aggregate_exposure_points=round(agg,4),max_team_concentration_pct=round(team_pct,4),max_risk_domain_concentration_pct=round(domain_pct,4),max_correlated_exposure_points=round(corr_max,4),portfolio_state=state,reason_codes_json=reasons,metrics_json={'team_exposure':dict(teams),'risk_domain_exposure':dict(domains),'correlated_exposure':dict(corr)},assessed_by=actor,assessed_at=now(),supplier_fact_unchanged=True)
            s.add(x);s.flush()
            for dim,data,limit in [('TEAM',teams,lim.max_team_concentration_pct),('RISK_DOMAIN',domains,lim.max_risk_domain_concentration_pct)]:
                for k,v in data.items():
                    pct=0 if agg<=0 else v/agg*100
                    s.add(JourneyRecoveryResidualRiskConcentrationRow(concentration_assessment_id=nid('jrrc'),portfolio_assessment_id=x.portfolio_assessment_id,dimension=dim,dimension_key=k,exposure_points=v,concentration_pct=round(pct,4),breached=pct>limit,created_at=now(),supplier_fact_unchanged=True))
            for k,v in corr.items(): s.add(JourneyRecoveryResidualRiskConcentrationRow(concentration_assessment_id=nid('jrrc'),portfolio_assessment_id=x.portfolio_assessment_id,dimension='CORRELATION',dimension_key=k,exposure_points=v,concentration_pct=(0 if agg<=0 else round(v/agg*100,4)),breached=v>lim.max_correlated_exposure_points,created_at=now(),supplier_fact_unchanged=True))
            freeze=None
            if state=='BREACH':
                freeze=s.execute(select(JourneyRecoveryPortfolioFreezeRow).where(JourneyRecoveryPortfolioFreezeRow.environment==environment,JourneyRecoveryPortfolioFreezeRow.state=='ACTIVE')).scalars().first()
                if not freeze:
                    freeze=JourneyRecoveryPortfolioFreezeRow(portfolio_freeze_id=nid('jrpf'),environment=environment,source_portfolio_assessment_id=x.portfolio_assessment_id,reason_codes_json=reasons,state='ACTIVE',activated_at=now(),released_at=None,released_by=None,release_evidence_reference=None,supplier_fact_unchanged=True)
                    s.add(freeze);self._event(s,environment,'PORTFOLIO_FREEZE_ACTIVATED',actor,{'reasons':reasons,'aggregate_exposure_points':agg},assessment=x.portfolio_assessment_id,freeze=freeze.portfolio_freeze_id)
            s.commit();return self.assessment(x.portfolio_assessment_id)

    def pre_request_waiver(self,environment,actor='system'):
        try:
            from go_hotel.journey.recovery_enterprise_risk_appetite import recovery_enterprise_risk_appetite_service as appetite
            appetite.pre_request_waiver(environment)
            from go_hotel.journey.recovery_enterprise_risk_forecast import recovery_enterprise_risk_forecast_service as forecast
            forecast.pre_request_waiver(environment)
        except ImportError:
            pass
        with SessionLocal() as s:
            if not self.active_limit_in_session(s,environment): return None
            f=s.execute(select(JourneyRecoveryPortfolioFreezeRow).where(JourneyRecoveryPortfolioFreezeRow.environment==environment,JourneyRecoveryPortfolioFreezeRow.state=='ACTIVE')).scalars().first()
            if f: raise ValueError('NEW_PRODUCTION_WAIVER_BLOCKED_BY_ENTERPRISE_RISK_PORTFOLIO_FREEZE')
        a=self.evaluate(environment,actor)
        if a['portfolio_state']=='BREACH': raise ValueError('NEW_PRODUCTION_WAIVER_BLOCKED_BY_ENTERPRISE_RISK_PORTFOLIO_FREEZE')
        return a

    def pre_request_executive_acceptance(self,environment,actor='system'):
        try:
            from go_hotel.journey.recovery_enterprise_risk_appetite import recovery_enterprise_risk_appetite_service as appetite
            appetite.pre_request_executive_acceptance(environment)
            from go_hotel.journey.recovery_enterprise_risk_forecast import recovery_enterprise_risk_forecast_service as forecast
            forecast.pre_request_executive_acceptance(environment)
        except ImportError:
            pass
        with SessionLocal() as s:
            if not self.active_limit_in_session(s,environment): return None
            f=s.execute(select(JourneyRecoveryPortfolioFreezeRow).where(JourneyRecoveryPortfolioFreezeRow.environment==environment,JourneyRecoveryPortfolioFreezeRow.state=='ACTIVE')).scalars().first()
            if f: raise ValueError('NEW_EXECUTIVE_RISK_ACCEPTANCE_BLOCKED_BY_PORTFOLIO_FREEZE')
        return self.evaluate(environment,actor)

    def assert_acceptance_eligible(self,acceptance_id,environment):
        try:
            from go_hotel.journey.recovery_enterprise_risk_appetite import recovery_enterprise_risk_appetite_service as appetite
            appetite.assert_acceptance_eligible(environment)
        except ImportError:
            pass
        with SessionLocal() as s:
            if not self.active_limit_in_session(s,environment): return True
            p=s.execute(select(JourneyRecoveryExecutiveRiskPositionRow).where(JourneyRecoveryExecutiveRiskPositionRow.executive_risk_acceptance_id==acceptance_id,JourneyRecoveryExecutiveRiskPositionRow.state=='ACTIVE')).scalars().first()
            if not p: raise ValueError('EXECUTIVE_RISK_POSITION_REGISTRATION_REQUIRED')
            f=s.execute(select(JourneyRecoveryPortfolioFreezeRow).where(JourneyRecoveryPortfolioFreezeRow.environment==environment,JourneyRecoveryPortfolioFreezeRow.state=='ACTIVE')).scalars().first()
            if f: raise ValueError('EXECUTIVE_RISK_ACCEPTANCE_BLOCKED_BY_PORTFOLIO_FREEZE')
        a=self.evaluate(environment,'portfolio-gate')
        if a['portfolio_state']=='BREACH': raise ValueError('EXECUTIVE_RISK_ACCEPTANCE_BLOCKED_BY_PORTFOLIO_FREEZE')
        return True

    def release_freeze(self,environment,evidence_reference,actor):
        if not evidence_reference: raise ValueError('PORTFOLIO_FREEZE_RELEASE_EVIDENCE_REQUIRED')
        a=self.evaluate(environment,actor)
        if a['portfolio_state']=='BREACH': raise ValueError('PORTFOLIO_FREEZE_RELEASE_CONDITIONS_NOT_MET')
        with SessionLocal() as s:
            f=s.execute(select(JourneyRecoveryPortfolioFreezeRow).where(JourneyRecoveryPortfolioFreezeRow.environment==environment,JourneyRecoveryPortfolioFreezeRow.state=='ACTIVE').order_by(JourneyRecoveryPortfolioFreezeRow.activated_at.desc())).scalars().first()
            if not f: raise ValueError('ACTIVE_PORTFOLIO_FREEZE_NOT_FOUND')
            f.state='RELEASED';f.released_at=now();f.released_by=actor;f.release_evidence_reference=evidence_reference
            self._event(s,environment,'PORTFOLIO_FREEZE_RELEASED',actor,{'evidence_reference':evidence_reference,'assessment_id':a['portfolio_assessment_id']},assessment=a['portfolio_assessment_id'],freeze=f.portfolio_freeze_id)
            s.commit();return self.freeze(f.portfolio_freeze_id)

    def status(self,environment):
        with SessionLocal() as s:
            lim=self.active_limit_in_session(s,environment)
            ass=s.execute(select(JourneyRecoveryExecutiveRiskPortfolioAssessmentRow).where(JourneyRecoveryExecutiveRiskPortfolioAssessmentRow.environment==environment).order_by(JourneyRecoveryExecutiveRiskPortfolioAssessmentRow.assessed_at.desc())).scalars().first()
            ps=s.execute(select(JourneyRecoveryExecutiveRiskPositionRow).where(JourneyRecoveryExecutiveRiskPositionRow.environment==environment).order_by(JourneyRecoveryExecutiveRiskPositionRow.registered_at.desc())).scalars().all()
            fs=s.execute(select(JourneyRecoveryPortfolioFreezeRow).where(JourneyRecoveryPortfolioFreezeRow.environment==environment).order_by(JourneyRecoveryPortfolioFreezeRow.activated_at.desc())).scalars().all()
            return {'environment':environment,'limit':self._limit(lim) if lim else None,'latest_assessment':self._assessment(ass) if ass else None,'positions':[self._position(x) for x in ps[:50]],'freezes':[self._freeze(x) for x in fs[:20]],'supplier_fact_unchanged':True}

    def _event(self,s,env,event,actor,evidence,risk_position=None,assessment=None,freeze=None): s.add(JourneyRecoveryEnterpriseRiskEventRow(enterprise_risk_event_id=nid('jrere'),environment=env,event_type=event,risk_position_id=risk_position,portfolio_assessment_id=assessment,portfolio_freeze_id=freeze,evidence_json=evidence or {},actor=actor,created_at=now(),supplier_fact_unchanged=True))
    def limit(self,i):
        with SessionLocal() as s:return self._limit(s.get(JourneyRecoveryEnterpriseRiskLimitRow,i))
    def position(self,i):
        with SessionLocal() as s:return self._position(s.get(JourneyRecoveryExecutiveRiskPositionRow,i))
    def assessment(self,i):
        with SessionLocal() as s:return self._assessment(s.get(JourneyRecoveryExecutiveRiskPortfolioAssessmentRow,i))
    def freeze(self,i):
        with SessionLocal() as s:return self._freeze(s.get(JourneyRecoveryPortfolioFreezeRow,i))
    def _limit(self,x): return {'enterprise_risk_limit_id':x.enterprise_risk_limit_id,'limit_key':x.limit_key,'version_no':x.version_no,'environment':x.environment,'max_aggregate_exposure_points':x.max_aggregate_exposure_points,'max_team_concentration_pct':x.max_team_concentration_pct,'max_risk_domain_concentration_pct':x.max_risk_domain_concentration_pct,'max_correlated_exposure_points':x.max_correlated_exposure_points,'max_active_acceptances':x.max_active_acceptances,'requested_by':x.requested_by,'board_approver_one':x.board_approver_one,'board_approver_two':x.board_approver_two,'state':x.state,'supplier_fact_unchanged':True}
    def _position(self,x): return {'risk_position_id':x.risk_position_id,'environment':x.environment,'executive_risk_acceptance_id':x.executive_risk_acceptance_id,'team_key':x.team_key,'risk_domain':x.risk_domain,'exposure_points':x.exposure_points,'correlation_keys':x.correlation_keys_json,'state':x.state,'supplier_fact_unchanged':True}
    def _assessment(self,x): return {'portfolio_assessment_id':x.portfolio_assessment_id,'environment':x.environment,'enterprise_risk_limit_id':x.enterprise_risk_limit_id,'active_acceptance_count':x.active_acceptance_count,'aggregate_exposure_points':x.aggregate_exposure_points,'max_team_concentration_pct':x.max_team_concentration_pct,'max_risk_domain_concentration_pct':x.max_risk_domain_concentration_pct,'max_correlated_exposure_points':x.max_correlated_exposure_points,'portfolio_state':x.portfolio_state,'reason_codes':x.reason_codes_json,'metrics':x.metrics_json,'assessed_at':x.assessed_at.isoformat(),'supplier_fact_unchanged':True}
    def _freeze(self,x): return {'portfolio_freeze_id':x.portfolio_freeze_id,'environment':x.environment,'source_portfolio_assessment_id':x.source_portfolio_assessment_id,'reason_codes':x.reason_codes_json,'state':x.state,'activated_at':x.activated_at.isoformat(),'released_at':x.released_at.isoformat() if x.released_at else None,'release_evidence_reference':x.release_evidence_reference,'supplier_fact_unchanged':True}

recovery_enterprise_risk_portfolio_service=RecoveryEnterpriseRiskPortfolioService()
