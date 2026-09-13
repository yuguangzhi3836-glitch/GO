from datetime import datetime, timezone, timedelta
from uuid import uuid4
import hashlib, json
from sqlalchemy import select, func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    JourneyRecoveryChaosPolicyRow,JourneyRecoveryChaosCampaignRow,JourneyRecoveryChaosExecutionRow,
    JourneyRecoveryReadinessAssessmentRow,JourneyRecoveryProductionReadinessGateRow,
    JourneyRecoveryTrustPlaneDisasterIncidentRow,
)

SUPPORTED_SCENARIOS=['WITNESS_LOSS','REGION_LOSS','PROVIDER_LOSS','STALE_CHECKPOINT','ARCHIVE_CORRUPTION','QUORUM_DEGRADATION']
def now(): return datetime.now(timezone.utc)
def aware(v): return v if v is None or v.tzinfo else v.replace(tzinfo=timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'
def canon(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def sha(v): return hashlib.sha256(canon(v).encode()).hexdigest()

def active_policy_in_session(s,environment):
    return s.execute(select(JourneyRecoveryChaosPolicyRow).where(JourneyRecoveryChaosPolicyRow.environment==environment,JourneyRecoveryChaosPolicyRow.state=='ACTIVE').order_by(JourneyRecoveryChaosPolicyRow.version_no.desc(),JourneyRecoveryChaosPolicyRow.created_at.desc())).scalars().first()

def production_readiness_allows(environment):
    if environment!='PROD': return True
    with SessionLocal() as s:
        p=active_policy_in_session(s,environment)
        if not p:return True
        g=s.execute(select(JourneyRecoveryProductionReadinessGateRow).where(JourneyRecoveryProductionReadinessGateRow.environment==environment).order_by(JourneyRecoveryProductionReadinessGateRow.evaluated_at.desc())).scalars().first()
        return bool(g and g.gate_state=='PASS' and aware(g.valid_until)>=now())

class RecoveryTrustPlaneChaosService:
    def create_policy(self,policy_key,environment,required_scenarios,minimum_readiness_score,max_rto_seconds,max_rpo_seconds,evidence_ttl_seconds,actor):
        req=list(dict.fromkeys(required_scenarios))
        if not req or any(x not in SUPPORTED_SCENARIOS for x in req):raise ValueError('INVALID_CHAOS_SCENARIO_POLICY')
        if minimum_readiness_score<0 or minimum_readiness_score>100 or min(max_rto_seconds,max_rpo_seconds,evidence_ttl_seconds)<0:raise ValueError('INVALID_READINESS_POLICY')
        with SessionLocal() as s:
            ver=(s.execute(select(func.max(JourneyRecoveryChaosPolicyRow.version_no)).where(JourneyRecoveryChaosPolicyRow.policy_key==policy_key)).scalar() or 0)+1
            for x in s.execute(select(JourneyRecoveryChaosPolicyRow).where(JourneyRecoveryChaosPolicyRow.policy_key==policy_key,JourneyRecoveryChaosPolicyRow.state=='ACTIVE')).scalars().all():x.state='SUPERSEDED'
            x=JourneyRecoveryChaosPolicyRow(chaos_policy_id=nid('jrcp'),policy_key=policy_key,version_no=ver,environment=environment,required_scenarios_json=req,minimum_readiness_score=minimum_readiness_score,max_rto_seconds=max_rto_seconds,max_rpo_seconds=max_rpo_seconds,evidence_ttl_seconds=evidence_ttl_seconds,state='ACTIVE',created_by=actor,created_at=now(),supplier_fact_unchanged=True)
            s.add(x);s.commit();return self.policy(x.chaos_policy_id)

    def create_campaign(self,environment,campaign_key,scenarios,actor):
        with SessionLocal() as s:
            p=active_policy_in_session(s,environment)
            if not p:raise ValueError('ACTIVE_CHAOS_POLICY_REQUIRED')
            defs=[]
            for item in scenarios:
                st=item.get('scenario_type') if isinstance(item,dict) else str(item)
                if st not in SUPPORTED_SCENARIOS:raise ValueError('UNSUPPORTED_CHAOS_SCENARIO')
                defs.append({'scenario_type':st,'fault_parameters':(item.get('fault_parameters') or {}) if isinstance(item,dict) else {}})
            x=JourneyRecoveryChaosCampaignRow(chaos_campaign_id=nid('jrcc'),environment=environment,chaos_policy_id=p.chaos_policy_id,campaign_key=campaign_key,scenarios_json=defs,state='READY',requested_by=actor,requested_at=now(),completed_at=None,supplier_fact_unchanged=True)
            s.add(x);s.commit();return self.campaign(x.chaos_campaign_id)

    def _simulate(self,scenario,params,policy):
        rto=int(params.get('rto_seconds',min(60,policy.max_rto_seconds)))
        rpo=int(params.get('rpo_seconds',0))
        if scenario in {'WITNESS_LOSS','QUORUM_DEGRADATION'}:
            required=int(params.get('required_quorum',2));remaining=int(params.get('remaining_independent_quorum',required-1));recovered=int(params.get('post_recovery_quorum',required))
            action='FAIL_SAFE_DENY' if remaining<required else 'DEGRADED_ALLOW'
            ok=recovered>=required
        elif scenario in {'REGION_LOSS','PROVIDER_LOSS'}:
            action='FAIL_SAFE_DENY';ok=bool(params.get('region_recovered',True))
        elif scenario=='STALE_CHECKPOINT':
            action='FAIL_SAFE_DENY';ok=bool(params.get('fresh_checkpoint_after',True))
        elif scenario=='ARCHIVE_CORRUPTION':
            action='ARCHIVE_REJECTED';ok=bool(params.get('alternate_verified_archive',True))
        else: raise ValueError('UNSUPPORTED_CHAOS_SCENARIO')
        if params.get('force_recovery_failure'):ok=False
        return action,'RECOVERED' if ok else 'RECOVERY_FAILED',rto,rpo

    def run_campaign(self,campaign_id,actor,evidence_prefix='chaos://'):
        with SessionLocal() as s:
            c=s.get(JourneyRecoveryChaosCampaignRow,campaign_id)
            if not c:raise ValueError('CHAOS_CAMPAIGN_NOT_FOUND')
            if c.state not in {'READY','FAILED'}:raise ValueError('CHAOS_CAMPAIGN_NOT_RUNNABLE')
            p=s.get(JourneyRecoveryChaosPolicyRow,c.chaos_policy_id);c.state='RUNNING';s.flush()
            ids=[]
            for d in c.scenarios_json:
                st=d['scenario_type'];params=d.get('fault_parameters') or {};start=now();action,state,rto,rpo=self._simulate(st,params,p);end=start+timedelta(seconds=rto)
                body={'campaign_id':campaign_id,'scenario_type':st,'params':params,'observed_safety_action':action,'recovery_state':state,'rto_seconds':rto,'rpo_seconds':rpo}
                x=JourneyRecoveryChaosExecutionRow(chaos_execution_id=nid('jrce'),chaos_campaign_id=campaign_id,environment=c.environment,scenario_type=st,fault_parameters_json=params,expected_safety_action='ARCHIVE_REJECTED' if st=='ARCHIVE_CORRUPTION' else ('DEGRADED_ALLOW' if params.get('remaining_independent_quorum',0)>=params.get('required_quorum',2) and st in {'WITNESS_LOSS','QUORUM_DEGRADATION'} else 'FAIL_SAFE_DENY'),observed_safety_action=action,recovery_state=state,rto_seconds=rto,rpo_seconds=rpo,evidence_hash=sha(body),evidence_reference=f'{evidence_prefix}{campaign_id}/{st.lower()}',executed_by=actor,started_at=start,completed_at=end,supplier_fact_unchanged=True)
                s.add(x);ids.append(x.chaos_execution_id)
            c.state='COMPLETED';c.completed_at=now();s.commit();return {'campaign':self.campaign(campaign_id),'execution_ids':ids,'supplier_fact_unchanged':True}

    def assess_readiness(self,campaign_id,actor):
        with SessionLocal() as s:
            c=s.get(JourneyRecoveryChaosCampaignRow,campaign_id)
            if not c or c.state!='COMPLETED':raise ValueError('COMPLETED_CHAOS_CAMPAIGN_REQUIRED')
            p=s.get(JourneyRecoveryChaosPolicyRow,c.chaos_policy_id)
            xs=s.execute(select(JourneyRecoveryChaosExecutionRow).where(JourneyRecoveryChaosExecutionRow.chaos_campaign_id==campaign_id)).scalars().all()
            latest={x.scenario_type:x for x in xs};required=set(p.required_scenarios_json);covered=required & set(latest);missing=sorted(required-covered)
            failed=sorted(k for k in covered if latest[k].recovery_state!='RECOVERED' or latest[k].observed_safety_action!=latest[k].expected_safety_action)
            maxrto=max([x.rto_seconds for x in xs] or [0]);maxrpo=max([x.rpo_seconds for x in xs] or [0])
            freshness=all((now()-aware(x.completed_at)).total_seconds()<=p.evidence_ttl_seconds for x in xs) if xs else False
            reasons=[]
            if missing:reasons.append('REQUIRED_CHAOS_SCENARIO_COVERAGE_MISSING')
            if failed:reasons.append('CHAOS_RECOVERY_OR_SAFETY_ACTION_FAILED')
            if maxrto>p.max_rto_seconds:reasons.append('RTO_TARGET_BREACHED')
            if maxrpo>p.max_rpo_seconds:reasons.append('RPO_TARGET_BREACHED')
            if not freshness:reasons.append('CHAOS_EVIDENCE_STALE')
            coverage=len(covered)/max(1,len(required));success=(len(covered)-len(failed))/max(1,len(required))
            score=max(0.0,min(100.0,round(50*coverage+30*success+10*(maxrto<=p.max_rto_seconds)+5*(maxrpo<=p.max_rpo_seconds)+5*freshness,2)))
            if score<p.minimum_readiness_score:reasons.append('MINIMUM_READINESS_SCORE_NOT_MET')
            state='PASS' if not reasons else 'FAIL'
            cov={'required':sorted(required),'covered':sorted(covered),'missing':missing,'failed':failed}
            a=JourneyRecoveryReadinessAssessmentRow(readiness_assessment_id=nid('jrra'),environment=c.environment,chaos_policy_id=p.chaos_policy_id,chaos_campaign_id=campaign_id,scenario_coverage_json=cov,readiness_score=score,max_observed_rto_seconds=maxrto,max_observed_rpo_seconds=maxrpo,evidence_fresh=freshness,state=state,reason_codes_json=sorted(set(reasons)),assessed_by=actor,assessed_at=now(),supplier_fact_unchanged=True)
            s.add(a);s.commit();return self.assessment(a.readiness_assessment_id)

    def evaluate_gate(self,assessment_id,evidence_reference,actor):
        with SessionLocal() as s:
            a=s.get(JourneyRecoveryReadinessAssessmentRow,assessment_id)
            if not a:raise ValueError('READINESS_ASSESSMENT_NOT_FOUND')
            p=s.get(JourneyRecoveryChaosPolicyRow,a.chaos_policy_id);reasons=list(a.reason_codes_json or [])
            open_real=s.execute(select(JourneyRecoveryTrustPlaneDisasterIncidentRow).where(JourneyRecoveryTrustPlaneDisasterIncidentRow.environment==a.environment,JourneyRecoveryTrustPlaneDisasterIncidentRow.state=='OPEN',JourneyRecoveryTrustPlaneDisasterIncidentRow.drill_mode==False)).scalars().first()
            if open_real:reasons.append('OPEN_TRUST_PLANE_DISASTER')
            state='PASS' if a.state=='PASS' and not reasons else 'BLOCKED'
            t=now();g=JourneyRecoveryProductionReadinessGateRow(production_readiness_gate_id=nid('jrpg'),environment=a.environment,readiness_assessment_id=assessment_id,gate_state=state,readiness_score=a.readiness_score,reason_codes_json=sorted(set(reasons)),evidence_reference=evidence_reference,evaluated_by=actor,evaluated_at=t,valid_until=t+timedelta(seconds=p.evidence_ttl_seconds),supplier_fact_unchanged=True)
            s.add(g);s.commit();return self.gate(g.production_readiness_gate_id)

    def policy(self,id):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryChaosPolicyRow,id)
            if not x:raise ValueError('CHAOS_POLICY_NOT_FOUND')
            return {'chaos_policy_id':x.chaos_policy_id,'policy_key':x.policy_key,'version_no':x.version_no,'environment':x.environment,'required_scenarios':x.required_scenarios_json,'minimum_readiness_score':x.minimum_readiness_score,'max_rto_seconds':x.max_rto_seconds,'max_rpo_seconds':x.max_rpo_seconds,'evidence_ttl_seconds':x.evidence_ttl_seconds,'state':x.state}
    def campaign(self,id):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryChaosCampaignRow,id)
            if not x:raise ValueError('CHAOS_CAMPAIGN_NOT_FOUND')
            return {'chaos_campaign_id':x.chaos_campaign_id,'environment':x.environment,'chaos_policy_id':x.chaos_policy_id,'campaign_key':x.campaign_key,'scenarios':x.scenarios_json,'state':x.state,'requested_by':x.requested_by,'requested_at':x.requested_at.isoformat(),'completed_at':x.completed_at.isoformat() if x.completed_at else None}
    def assessment(self,id):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryReadinessAssessmentRow,id)
            if not x:raise ValueError('READINESS_ASSESSMENT_NOT_FOUND')
            return {'readiness_assessment_id':x.readiness_assessment_id,'environment':x.environment,'chaos_campaign_id':x.chaos_campaign_id,'scenario_coverage':x.scenario_coverage_json,'readiness_score':x.readiness_score,'max_observed_rto_seconds':x.max_observed_rto_seconds,'max_observed_rpo_seconds':x.max_observed_rpo_seconds,'evidence_fresh':x.evidence_fresh,'state':x.state,'reason_codes':x.reason_codes_json,'assessed_at':x.assessed_at.isoformat(),'supplier_fact_unchanged':x.supplier_fact_unchanged}
    def gate(self,id):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryProductionReadinessGateRow,id)
            if not x:raise ValueError('PRODUCTION_READINESS_GATE_NOT_FOUND')
            return {'production_readiness_gate_id':x.production_readiness_gate_id,'environment':x.environment,'readiness_assessment_id':x.readiness_assessment_id,'gate_state':x.gate_state,'readiness_score':x.readiness_score,'reason_codes':x.reason_codes_json,'evidence_reference':x.evidence_reference,'evaluated_at':x.evaluated_at.isoformat(),'valid_until':x.valid_until.isoformat(),'supplier_fact_unchanged':x.supplier_fact_unchanged}
    def status(self,environment='PROD'):
        with SessionLocal() as s:
            p=active_policy_in_session(s,environment)
            camps=s.execute(select(JourneyRecoveryChaosCampaignRow).where(JourneyRecoveryChaosCampaignRow.environment==environment).order_by(JourneyRecoveryChaosCampaignRow.requested_at.desc()).limit(20)).scalars().all()
            ass=s.execute(select(JourneyRecoveryReadinessAssessmentRow).where(JourneyRecoveryReadinessAssessmentRow.environment==environment).order_by(JourneyRecoveryReadinessAssessmentRow.assessed_at.desc()).limit(20)).scalars().all()
            gates=s.execute(select(JourneyRecoveryProductionReadinessGateRow).where(JourneyRecoveryProductionReadinessGateRow.environment==environment).order_by(JourneyRecoveryProductionReadinessGateRow.evaluated_at.desc()).limit(20)).scalars().all()
            return {'environment':environment,'active_policy':self.policy(p.chaos_policy_id) if p else None,'campaigns':[{'chaos_campaign_id':x.chaos_campaign_id,'campaign_key':x.campaign_key,'state':x.state,'requested_at':x.requested_at.isoformat()} for x in camps],'assessments':[{'readiness_assessment_id':x.readiness_assessment_id,'readiness_score':x.readiness_score,'state':x.state,'reason_codes':x.reason_codes_json,'assessed_at':x.assessed_at.isoformat()} for x in ass],'gates':[{'production_readiness_gate_id':x.production_readiness_gate_id,'gate_state':x.gate_state,'readiness_score':x.readiness_score,'valid_until':x.valid_until.isoformat()} for x in gates],'promotion_allowed':production_readiness_allows(environment),'supplier_fact_unchanged':True}

recovery_trust_plane_chaos_service=RecoveryTrustPlaneChaosService()
