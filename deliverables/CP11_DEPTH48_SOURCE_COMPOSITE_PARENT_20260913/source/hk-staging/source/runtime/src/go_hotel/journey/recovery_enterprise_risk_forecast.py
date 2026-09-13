from datetime import datetime,timezone,timedelta
from collections import defaultdict
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import *

def now(): return datetime.now(timezone.utc)
def aware(v): return v if v is None or v.tzinfo else v.replace(tzinfo=timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'

class RecoveryEnterpriseRiskForecastService:
    def active_policy_in_session(self,s,environment):
        return s.execute(select(JourneyRecoveryRiskForecastPolicyRow).where(JourneyRecoveryRiskForecastPolicyRow.environment==environment,JourneyRecoveryRiskForecastPolicyRow.state=='ACTIVE').order_by(JourneyRecoveryRiskForecastPolicyRow.version_no.desc())).scalars().first()
    def create_policy(self,key,environment,warning_pct,restrict_pct,reserve_pct,actor):
        if not (0<warning_pct<restrict_pct<=100) or not (0<=reserve_pct<100): raise ValueError('INVALID_RISK_FORECAST_POLICY')
        with SessionLocal() as s:
            prev=s.execute(select(JourneyRecoveryRiskForecastPolicyRow).where(JourneyRecoveryRiskForecastPolicyRow.policy_key==key,JourneyRecoveryRiskForecastPolicyRow.environment==environment).order_by(JourneyRecoveryRiskForecastPolicyRow.version_no.desc())).scalars().first()
            x=JourneyRecoveryRiskForecastPolicyRow(risk_forecast_policy_id=nid('jrfp'),policy_key=key,version_no=(prev.version_no+1 if prev else 1),environment=environment,warning_capacity_utilization_pct=warning_pct,restrict_capacity_utilization_pct=restrict_pct,reserve_capacity_pct=reserve_pct,requested_by=actor,board_approver_one=None,board_approver_two=None,state='PENDING_APPROVAL',created_at=now(),supplier_fact_unchanged=True);s.add(x);s.commit();return self.policy(x.risk_forecast_policy_id)
    def approve_policy(self,i,actor):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryRiskForecastPolicyRow,i)
            if not x: raise ValueError('RISK_FORECAST_POLICY_NOT_FOUND')
            if actor==x.requested_by: raise ValueError('RISK_FORECAST_MAKER_CHECKER_REQUIRED')
            if not x.board_approver_one: x.board_approver_one=actor;x.state='AWAITING_SECOND_APPROVAL'
            elif x.board_approver_one==actor: raise ValueError('RISK_FORECAST_TWO_DISTINCT_APPROVERS_REQUIRED')
            elif not x.board_approver_two:
                x.board_approver_two=actor
                for y in s.execute(select(JourneyRecoveryRiskForecastPolicyRow).where(JourneyRecoveryRiskForecastPolicyRow.environment==x.environment,JourneyRecoveryRiskForecastPolicyRow.state=='ACTIVE')).scalars().all():y.state='SUPERSEDED'
                x.state='ACTIVE'
            s.commit();return self.policy(i)
    def observe_indicator(self,environment,key,indicator_type,dimension,dimension_key,value,threshold,direction,weight,evidence):
        if direction not in {'HIGH_BAD','LOW_BAD'} or threshold<=0 or weight<=0: raise ValueError('INVALID_RISK_INDICATOR')
        ratio=(value/threshold) if direction=='HIGH_BAD' else (threshold/max(value,0.0001))
        state='BREACH' if ratio>=1.15 else ('WATCH' if ratio>=0.9 else 'NORMAL')
        with SessionLocal() as s:
            x=JourneyRecoveryRiskIndicatorRow(risk_indicator_id=nid('jrki'),environment=environment,indicator_key=key,indicator_type=indicator_type,dimension=dimension,dimension_key=dimension_key,observed_value=value,threshold_value=threshold,direction=direction,weight=weight,signal_state=state,evidence_json=evidence or {},observed_at=now(),supplier_fact_unchanged=True);s.add(x);s.commit();return self.indicator(x.risk_indicator_id)
    def _active_positions(self,s,environment):
        t=now();out=[]
        for p in s.execute(select(JourneyRecoveryExecutiveRiskPositionRow).where(JourneyRecoveryExecutiveRiskPositionRow.environment==environment,JourneyRecoveryExecutiveRiskPositionRow.state=='ACTIVE')).scalars().all():
            a=s.get(JourneyRecoveryExecutiveRiskAcceptanceRow,p.executive_risk_acceptance_id)
            if a and a.state in ('APPROVED','ACTIVE') and aware(a.starts_at)<=t<aware(a.expires_at):out.append(p)
        return out
    def forecast(self,environment,horizon_hours,actor='risk-forecast-engine'):
        if horizon_hours not in {24,168}: raise ValueError('FORECAST_HORIZON_MUST_BE_24_OR_168_HOURS')
        with SessionLocal() as s:
            pol=self.active_policy_in_session(s,environment)
            if not pol: raise ValueError('ACTIVE_RISK_FORECAST_POLICY_REQUIRED')
            appetite=s.execute(select(JourneyRecoveryRiskAppetiteEnvelopeRow).where(JourneyRecoveryRiskAppetiteEnvelopeRow.environment==environment,JourneyRecoveryRiskAppetiteEnvelopeRow.state=='ACTIVE').order_by(JourneyRecoveryRiskAppetiteEnvelopeRow.version_no.desc())).scalars().first()
            if not appetite: raise ValueError('ACTIVE_RISK_APPETITE_REQUIRED')
            positions=self._active_positions(s,environment);current=sum(p.exposure_points for p in positions)
            cutoff=now()-timedelta(hours=24)
            inds=s.execute(select(JourneyRecoveryRiskIndicatorRow).where(JourneyRecoveryRiskIndicatorRow.environment==environment,JourneyRecoveryRiskIndicatorRow.observed_at>=cutoff).order_by(JourneyRecoveryRiskIndicatorRow.observed_at.desc())).scalars().all()
            latest={}
            for i in inds: latest.setdefault((i.indicator_key,i.dimension,i.dimension_key),i)
            weighted=0;weights=0
            for i in latest.values():
                ratio=(i.observed_value/i.threshold_value) if i.direction=='HIGH_BAD' else (i.threshold_value/max(i.observed_value,0.0001))
                weighted+=max(0,ratio-0.5)*i.weight;weights+=i.weight
            signal=0 if weights==0 else weighted/weights
            governance={'mode':'LEGACY','growth_multiplier':1.0,'minimum_growth':0.0,'model_version_id':None}
            try:
                from go_hotel.journey.recovery_risk_forecast_calibration import recovery_risk_forecast_calibration_service as calibration
                governance=calibration.runtime_governance(environment)
            except Exception:
                pass
            try:
                from go_hotel.journey.recovery_forecast_serving_governance import recovery_forecast_serving_governance_service as serving
                serving.assert_runtime_model_eligible_in_session(s,environment,governance.get('model_version_id'))
            except ImportError:
                pass
            growth=max(0,signal)*0.12*(horizon_hours/24)*float(governance.get('growth_multiplier',1.0))
            growth=max(growth,float(governance.get('minimum_growth',0.0))*(horizon_hours/24))
            projected=current*(1+growth)
            usable=appetite.max_current_exposure_points*(1-pol.reserve_capacity_pct/100)
            util=0 if usable<=0 else projected/usable*100
            headroom=usable-projected
            reasons=[]
            if projected>appetite.max_current_exposure_points:reasons.append('FORECAST_CURRENT_APPETITE_BREACH')
            if util>=pol.restrict_capacity_utilization_pct:reasons.append('FORECAST_CAPACITY_RESTRICTION_THRESHOLD')
            elif util>=pol.warning_capacity_utilization_pct:reasons.append('FORECAST_CAPACITY_WARNING_THRESHOLD')
            state='BREACH' if any(r in reasons for r in ['FORECAST_CURRENT_APPETITE_BREACH','FORECAST_CAPACITY_RESTRICTION_THRESHOLD']) else ('WATCH' if reasons else 'PASS')
            x=JourneyRecoveryRiskForecastRow(risk_forecast_id=nid('jrfc'),environment=environment,risk_forecast_policy_id=pol.risk_forecast_policy_id,horizon_hours=horizon_hours,current_exposure_points=round(current,4),projected_exposure_points=round(projected,4),projected_capacity_consumption_pct=round(util,4),projected_headroom_points=round(headroom,4),weighted_risk_signal=round(signal,4),forecast_state=state,reason_codes_json=reasons,inputs_json={'indicator_count':len(latest),'reserve_capacity_pct':pol.reserve_capacity_pct,'forecast_model_mode':governance.get('mode'),'forecast_model_version_id':governance.get('model_version_id')},forecasted_at=now(),valid_until=now()+timedelta(hours=6),supplier_fact_unchanged=True);s.add(x);s.flush()
            teams=defaultdict(float);domains=defaultdict(float)
            for p in positions:teams[p.team_key]+=p.exposure_points;domains[p.risk_domain]+=p.exposure_points
            for dim,data in [('TEAM',teams),('RISK_DOMAIN',domains)]:
                total=sum(data.values())
                for k,v in data.items():
                    share=(v/total if total else 1/max(1,len(data)));alloc=max(usable*0.1,usable*share);proj=v*(1+growth);u=0 if alloc<=0 else proj/alloc*100
                    s.add(JourneyRecoveryDynamicRiskCapacityRow(risk_capacity_id=nid('jrca'),environment=environment,risk_forecast_id=x.risk_forecast_id,dimension=dim,dimension_key=k,allocated_capacity_points=round(alloc,4),current_exposure_points=round(v,4),projected_exposure_points=round(proj,4),capacity_utilization_pct=round(u,4),available_capacity_points=round(max(0,alloc-proj),4),allocation_state=('RESTRICTED' if u>=pol.restrict_capacity_utilization_pct else ('WATCH' if u>=pol.warning_capacity_utilization_pct else 'AVAILABLE')),created_at=now(),supplier_fact_unchanged=True))
            restriction=None
            if state in {'WATCH','BREACH'}:
                sev='HIGH' if state=='BREACH' else 'MEDIUM';s.add(JourneyRecoveryRiskEarlyWarningRow(early_warning_id=nid('jrew'),environment=environment,risk_forecast_id=x.risk_forecast_id,warning_type='RISK_APPETITE_FORECAST',severity=sev,reason_codes_json=reasons,state='OPEN',created_at=now(),acknowledged_at=None,acknowledged_by=None,supplier_fact_unchanged=True))
            if state=='BREACH':
                restriction=s.execute(select(JourneyRecoveryForecastRiskRestrictionRow).where(JourneyRecoveryForecastRiskRestrictionRow.environment==environment,JourneyRecoveryForecastRiskRestrictionRow.state=='ACTIVE')).scalars().first()
                if not restriction:
                    restriction=JourneyRecoveryForecastRiskRestrictionRow(forecast_restriction_id=nid('jrrx'),environment=environment,source_risk_forecast_id=x.risk_forecast_id,restriction_scope='NEW_RESIDUAL_RISK',reason_codes_json=reasons,state='ACTIVE',activated_at=now(),released_at=None,released_by=None,release_evidence_reference=None,supplier_fact_unchanged=True);s.add(restriction);s.flush();self._event(s,environment,'FORECAST_RESTRICTION_ACTIVATED',actor,{'horizon_hours':horizon_hours,'reasons':reasons},x.risk_forecast_id,restriction.forecast_restriction_id)
            s.commit();return self.forecast_get(x.risk_forecast_id)
    def assert_no_active_restriction(self,environment,code):
        with SessionLocal() as s:
            if not self.active_policy_in_session(s,environment):return True
            x=s.execute(select(JourneyRecoveryForecastRiskRestrictionRow).where(JourneyRecoveryForecastRiskRestrictionRow.environment==environment,JourneyRecoveryForecastRiskRestrictionRow.state=='ACTIVE')).scalars().first()
            if x: raise ValueError(code)
        return True
    def pre_request_waiver(self,e): return self.assert_no_active_restriction(e,'NEW_PRODUCTION_WAIVER_BLOCKED_BY_FORECAST_RISK_RESTRICTION')
    def pre_request_executive_acceptance(self,e): return self.assert_no_active_restriction(e,'NEW_EXECUTIVE_RISK_ACCEPTANCE_BLOCKED_BY_FORECAST_RISK_RESTRICTION')
    def release_restriction(self,environment,evidence,actor):
        if not evidence: raise ValueError('RELEASE_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            x=s.execute(select(JourneyRecoveryForecastRiskRestrictionRow).where(JourneyRecoveryForecastRiskRestrictionRow.environment==environment,JourneyRecoveryForecastRiskRestrictionRow.state=='ACTIVE')).scalars().first()
            if not x: raise ValueError('ACTIVE_FORECAST_RESTRICTION_NOT_FOUND')
            latest=s.execute(select(JourneyRecoveryRiskForecastRow).where(JourneyRecoveryRiskForecastRow.environment==environment).order_by(JourneyRecoveryRiskForecastRow.forecasted_at.desc())).scalars().first()
            if not latest or latest.forecast_state=='BREACH': raise ValueError('FORECAST_RESTRICTION_RELEASE_CONDITIONS_NOT_MET')
            x.state='RELEASED';x.released_at=now();x.released_by=actor;x.release_evidence_reference=evidence;self._event(s,environment,'FORECAST_RESTRICTION_RELEASED',actor,{'evidence_reference':evidence},latest.risk_forecast_id,x.forecast_restriction_id);s.commit();return self.restriction(x.forecast_restriction_id)
    def status(self,environment):
        with SessionLocal() as s:
            fs=s.execute(select(JourneyRecoveryRiskForecastRow).where(JourneyRecoveryRiskForecastRow.environment==environment).order_by(JourneyRecoveryRiskForecastRow.forecasted_at.desc()).limit(10)).scalars().all();rs=s.execute(select(JourneyRecoveryForecastRiskRestrictionRow).where(JourneyRecoveryForecastRiskRestrictionRow.environment==environment)).scalars().all();ws=s.execute(select(JourneyRecoveryRiskEarlyWarningRow).where(JourneyRecoveryRiskEarlyWarningRow.environment==environment).order_by(JourneyRecoveryRiskEarlyWarningRow.created_at.desc()).limit(20)).scalars().all()
            return {'forecasts':[self._forecast(x) for x in fs],'restrictions':[self._restriction(x) for x in rs],'warnings':[{'early_warning_id':x.early_warning_id,'severity':x.severity,'state':x.state,'reason_codes':x.reason_codes_json} for x in ws]}
    def _event(self,s,e,t,actor,evidence,forecast=None,restriction=None):s.add(JourneyRecoveryRiskForecastEventRow(risk_forecast_event_id=nid('jrfe'),environment=e,event_type=t,risk_forecast_id=forecast,forecast_restriction_id=restriction,evidence_json=evidence or {},actor=actor,created_at=now(),supplier_fact_unchanged=True))
    def policy(self,i):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryRiskForecastPolicyRow,i);return self._policy(x)
    def indicator(self,i):
        with SessionLocal() as s:return self._indicator(s.get(JourneyRecoveryRiskIndicatorRow,i))
    def forecast_get(self,i):
        with SessionLocal() as s:return self._forecast(s.get(JourneyRecoveryRiskForecastRow,i))
    def restriction(self,i):
        with SessionLocal() as s:return self._restriction(s.get(JourneyRecoveryForecastRiskRestrictionRow,i))
    def _policy(self,x):return {'risk_forecast_policy_id':x.risk_forecast_policy_id,'policy_key':x.policy_key,'version_no':x.version_no,'environment':x.environment,'warning_capacity_utilization_pct':x.warning_capacity_utilization_pct,'restrict_capacity_utilization_pct':x.restrict_capacity_utilization_pct,'reserve_capacity_pct':x.reserve_capacity_pct,'state':x.state,'supplier_fact_unchanged':True}
    def _indicator(self,x):return {'risk_indicator_id':x.risk_indicator_id,'indicator_key':x.indicator_key,'indicator_type':x.indicator_type,'dimension':x.dimension,'dimension_key':x.dimension_key,'observed_value':x.observed_value,'threshold_value':x.threshold_value,'signal_state':x.signal_state,'supplier_fact_unchanged':True}
    def _forecast(self,x):return {'risk_forecast_id':x.risk_forecast_id,'environment':x.environment,'horizon_hours':x.horizon_hours,'current_exposure_points':x.current_exposure_points,'projected_exposure_points':x.projected_exposure_points,'projected_capacity_consumption_pct':x.projected_capacity_consumption_pct,'projected_headroom_points':x.projected_headroom_points,'weighted_risk_signal':x.weighted_risk_signal,'forecast_state':x.forecast_state,'reason_codes':x.reason_codes_json,'valid_until':x.valid_until.isoformat(),'supplier_fact_unchanged':True}
    def _restriction(self,x):return {'forecast_restriction_id':x.forecast_restriction_id,'environment':x.environment,'source_risk_forecast_id':x.source_risk_forecast_id,'restriction_scope':x.restriction_scope,'reason_codes':x.reason_codes_json,'state':x.state,'supplier_fact_unchanged':True}
recovery_enterprise_risk_forecast_service=RecoveryEnterpriseRiskForecastService()
