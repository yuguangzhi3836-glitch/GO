from datetime import datetime, timezone, timedelta
from uuid import uuid4
import hashlib, json
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    JourneyRecoveryTelemetrySourceRow, JourneyRecoveryTelemetryQualityAssessmentRow,
    JourneyRecoverySloPolicyRow, JourneyRecoveryRuntimeIncidentCorrelationRow,
    JourneyRecoveryRuntimeObservationRow, JourneyRecoveryReleaseSafetyAssessmentRow,
    JourneyRecoveryRollbackRecommendationRow, JourneyRecoveryReleaseManifestRow,
    JourneyRecoveryDeploymentAttestationRow, JourneyRecoveryReleaseVerificationRow,
    JourneyRecoveryLearningIncidentRow,
)
from go_hotel.journey.recovery_runtime_observability import recovery_runtime_observability_service as runtime_safety


def now(): return datetime.now(timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'
def aware(x): return x.replace(tzinfo=timezone.utc) if x and x.tzinfo is None else x
def canon(v): return json.dumps(v, sort_keys=True, separators=(',',':'), default=str)
def sha(v): return hashlib.sha256(canon(v).encode()).hexdigest()

class RecoveryRuntimeTelemetryGovernanceService:
    ALLOWED_SOURCE_TYPES={'PROMETHEUS','OTEL','CLOUD_PROVIDER','MANAGED_METRICS','ENGINEERING'}
    def register_source(self,source_key,source_type,environment,actor,config=None,trust_level='GOVERNED',endpoint_ref=None):
        if source_type not in self.ALLOWED_SOURCE_TYPES: raise ValueError('INVALID_TELEMETRY_SOURCE_TYPE')
        if environment not in {'DEV','STAGING','PROD'}: raise ValueError('INVALID_ENVIRONMENT')
        cfg=config or {}
        fp=sha({'source_key':source_key,'source_type':source_type,'environment':environment,'endpoint_ref':endpoint_ref,'config':cfg})
        with SessionLocal() as s:
            old=s.execute(select(JourneyRecoveryTelemetrySourceRow).where(JourneyRecoveryTelemetrySourceRow.source_key==source_key)).scalars().first()
            if old: raise ValueError('TELEMETRY_SOURCE_KEY_EXISTS')
            r=JourneyRecoveryTelemetrySourceRow(telemetry_source_id=nid('jrts'),source_key=source_key,source_type=source_type,environment=environment,state='ACTIVE',trust_level=trust_level,endpoint_ref=endpoint_ref,config_json=cfg,source_fingerprint=fp,created_by=actor,created_at=now(),updated_at=now(),supplier_fact_unchanged=True)
            s.add(r);s.commit();return self.source(r.telemetry_source_id)
    def set_source_state(self,source_id,state,actor):
        if state not in {'ACTIVE','SUSPENDED','REVOKED'}: raise ValueError('INVALID_TELEMETRY_SOURCE_STATE')
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryTelemetrySourceRow,source_id)
            if not r: raise ValueError('TELEMETRY_SOURCE_NOT_FOUND')
            r.state=state;r.updated_at=now();s.commit();return self.source(source_id)
    def source(self,source_id):
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryTelemetrySourceRow,source_id)
            if not r: raise ValueError('TELEMETRY_SOURCE_NOT_FOUND')
            return {'telemetry_source_id':r.telemetry_source_id,'source_key':r.source_key,'source_type':r.source_type,'environment':r.environment,'state':r.state,'trust_level':r.trust_level,'endpoint_ref':r.endpoint_ref,'config':r.config_json,'source_fingerprint':r.source_fingerprint,'supplier_fact_unchanged':True}
    def list_sources(self,environment=None):
        with SessionLocal() as s:
            q=select(JourneyRecoveryTelemetrySourceRow)
            if environment:q=q.where(JourneyRecoveryTelemetrySourceRow.environment==environment)
            rows=s.execute(q.order_by(JourneyRecoveryTelemetrySourceRow.created_at.desc())).scalars().all()
            return [self.source(x.telemetry_source_id) for x in rows]
    def ingest(self,source_id,runtime_instance,metrics,actor='telemetry'):
        with SessionLocal() as s:
            src=s.get(JourneyRecoveryTelemetrySourceRow,source_id)
            if not src: raise ValueError('TELEMETRY_SOURCE_NOT_FOUND')
            if src.state!='ACTIVE': raise ValueError('TELEMETRY_SOURCE_NOT_ACTIVE')
            env=src.environment
        obs=runtime_safety.ingest(env,runtime_instance,metrics,actor)
        qa=self.assess_quality(obs['runtime_observation_id'],source_id)
        return {'observation':obs,'telemetry_source':self.source(source_id),'quality':qa}
    def assess_quality(self,observation_id,source_id):
        with SessionLocal() as s:
            obs=s.get(JourneyRecoveryRuntimeObservationRow,observation_id);src=s.get(JourneyRecoveryTelemetrySourceRow,source_id)
            if not obs: raise ValueError('OBSERVATION_NOT_FOUND')
            if not src: raise ValueError('TELEMETRY_SOURCE_NOT_FOUND')
            cfg=src.config_json or {};fresh=max(0.0,(now()-aware(obs.observed_at)).total_seconds());max_fresh=float(cfg.get('max_freshness_seconds',300));min_req=int(cfg.get('min_request_count',1));required=list(cfg.get('required_metric_fields',[]));payload=obs.payload_json or {}
            checks={'source_active':src.state=='ACTIVE','environment_match':src.environment==obs.environment,'fresh':fresh<=max_fresh,'minimum_volume':obs.request_count>=min_req,'required_fields':all(k in payload for k in required),'fingerprint_present':bool(src.source_fingerprint),'trust_level':src.trust_level}
            hard=['source_active','environment_match','fresh','minimum_volume','required_fields','fingerprint_present'];score=sum(1 for k in hard if checks[k])/len(hard);state='PASS' if all(checks[k] for k in hard) else 'FAIL'
            q=JourneyRecoveryTelemetryQualityAssessmentRow(telemetry_quality_assessment_id=nid('jrtqa'),runtime_observation_id=observation_id,telemetry_source_id=source_id,environment=obs.environment,state=state,freshness_seconds=fresh,quality_score=score,checks_json=checks,assessed_at=now(),supplier_fact_unchanged=True);s.add(q);s.commit();return self.quality(q.telemetry_quality_assessment_id)
    def quality(self,id):
        with SessionLocal() as s:
            q=s.get(JourneyRecoveryTelemetryQualityAssessmentRow,id)
            if not q: raise ValueError('TELEMETRY_QUALITY_NOT_FOUND')
            return {'telemetry_quality_assessment_id':q.telemetry_quality_assessment_id,'runtime_observation_id':q.runtime_observation_id,'telemetry_source_id':q.telemetry_source_id,'environment':q.environment,'state':q.state,'freshness_seconds':q.freshness_seconds,'quality_score':q.quality_score,'checks':q.checks_json,'supplier_fact_unchanged':True}
    def create_slo_policy(self,policy_key,environment,actor,slo_target=.999,windows=None,min_quality_score=.8,min_sources=1):
        if not 0<slo_target<1: raise ValueError('INVALID_SLO_TARGET')
        ws=windows or [{'minutes':5,'burn_threshold':14.4,'watch_threshold':2.0},{'minutes':30,'burn_threshold':6.0,'watch_threshold':2.0},{'minutes':60,'burn_threshold':3.0,'watch_threshold':1.5}]
        if len(ws)<2 or any(int(w.get('minutes',0))<=0 or float(w.get('burn_threshold',0))<=0 for w in ws): raise ValueError('INVALID_SLO_WINDOWS')
        with SessionLocal() as s:
            old=s.execute(select(JourneyRecoverySloPolicyRow).where(JourneyRecoverySloPolicyRow.policy_key==policy_key)).scalars().first()
            if old: raise ValueError('SLO_POLICY_KEY_EXISTS')
            p=JourneyRecoverySloPolicyRow(slo_policy_id=nid('jrslo'),policy_key=policy_key,environment=environment,state='ACTIVE',slo_target=slo_target,windows_json=ws,min_quality_score=min_quality_score,min_sources=min_sources,created_by=actor,created_at=now(),updated_at=now(),supplier_fact_unchanged=True);s.add(p);s.commit();return self.policy(p.slo_policy_id)
    def policy(self,id):
        with SessionLocal() as s:
            p=s.get(JourneyRecoverySloPolicyRow,id)
            if not p: raise ValueError('SLO_POLICY_NOT_FOUND')
            return {'slo_policy_id':p.slo_policy_id,'policy_key':p.policy_key,'environment':p.environment,'state':p.state,'slo_target':p.slo_target,'windows':p.windows_json,'min_quality_score':p.min_quality_score,'min_sources':p.min_sources,'supplier_fact_unchanged':True}
    def _active_policy(self,s,environment):
        p=s.execute(select(JourneyRecoverySloPolicyRow).where(JourneyRecoverySloPolicyRow.environment==environment,JourneyRecoverySloPolicyRow.state=='ACTIVE').order_by(JourneyRecoverySloPolicyRow.created_at.desc())).scalars().first()
        return p
    def _window_rows(self,s,environment,minutes):
        cutoff=now()-timedelta(minutes=int(minutes));return s.execute(select(JourneyRecoveryRuntimeObservationRow).where(JourneyRecoveryRuntimeObservationRow.environment==environment,JourneyRecoveryRuntimeObservationRow.observed_at>=cutoff).order_by(JourneyRecoveryRuntimeObservationRow.observed_at.desc())).scalars().all()
    def _quality_gate(self,s,rows,policy):
        if not rows:return {'state':'FAIL','reason':'NO_TELEMETRY','quality_score':0.0,'source_count':0,'pass_count':0}
        obsids=[r.runtime_observation_id for r in rows]
        qs=s.execute(select(JourneyRecoveryTelemetryQualityAssessmentRow).where(JourneyRecoveryTelemetryQualityAssessmentRow.runtime_observation_id.in_(obsids)).order_by(JourneyRecoveryTelemetryQualityAssessmentRow.assessed_at.desc())).scalars().all()
        latest={}
        for q in qs:
            latest.setdefault(q.runtime_observation_id,q)
        passed=[q for q in latest.values() if q.state=='PASS' and q.quality_score>=policy.min_quality_score]
        sources={q.telemetry_source_id for q in passed};score=(sum(q.quality_score for q in passed)/len(passed)) if passed else 0.0
        ok=len(passed)==len(rows) and len(sources)>=policy.min_sources and score>=policy.min_quality_score
        return {'state':'PASS' if ok else 'FAIL','reason':'QUALITY_GATE_PASS' if ok else 'QUALITY_OR_SOURCE_COVERAGE_INSUFFICIENT','quality_score':score,'source_count':len(sources),'pass_count':len(passed),'observation_count':len(rows)}
    def _aggregate(self,rows,slo):
        if not rows:return {'requests':0,'errors':0,'error_rate':0.0,'availability':1.0,'latency_p95_ms':0.0,'burn_rate':0.0}
        req=sum(r.request_count for r in rows);err=sum(r.error_count for r in rows);rate=(err/req) if req else sum(r.error_rate for r in rows)/len(rows);budget=max(1e-9,1-slo)
        return {'requests':req,'errors':err,'error_rate':rate,'availability':max(0.0,1-rate),'latency_p95_ms':max(r.latency_p95_ms for r in rows),'burn_rate':rate/budget}
    def assess(self,environment='PROD',actor='telemetry-safety-controller'):
        with SessionLocal() as s:
            p=self._active_policy(s,environment)
            if not p: raise ValueError('ACTIVE_SLO_POLICY_REQUIRED')
            windows=[];all_rows={}
            for w in p.windows_json:
                rows=self._window_rows(s,environment,w['minutes']);all_rows.update({r.runtime_observation_id:r for r in rows});agg=self._aggregate(rows,p.slo_target);windows.append({**w,**agg,'breach':agg['burn_rate']>=float(w['burn_threshold']),'watch':agg['burn_rate']>=float(w.get('watch_threshold',2.0))})
            gate=self._quality_gate(s,list(all_rows.values()),p)
            breaches=sum(1 for w in windows if w['breach']);watch=any(w['watch'] for w in windows)
            telemetry_ok=gate['state']=='PASS'
            state='INSUFFICIENT_TELEMETRY' if not telemetry_ok else ('BREACH' if breaches>=2 else ('WATCH' if watch else 'HEALTHY'))
            action='OBSERVE_ONLY' if not telemetry_ok else ('FREEZE_PROMOTION_AND_RECOMMEND_ROLLBACK' if state=='BREACH' and environment=='PROD' else ('FREEZE_PROMOTION' if state=='WATCH' else 'NONE'))
            m=runtime_safety._latest_manifest(s,environment);verified=None;att=None
            if m:
                verified=s.execute(select(JourneyRecoveryReleaseVerificationRow).where(JourneyRecoveryReleaseVerificationRow.release_manifest_id==m.release_manifest_id,JourneyRecoveryReleaseVerificationRow.state=='PASSED').order_by(JourneyRecoveryReleaseVerificationRow.verified_at.desc())).scalars().first()
                att=s.execute(select(JourneyRecoveryDeploymentAttestationRow).where(JourneyRecoveryDeploymentAttestationRow.release_manifest_id==m.release_manifest_id).order_by(JourneyRecoveryDeploymentAttestationRow.attested_at.desc())).scalars().first()
            correlated=bool(m and verified and telemetry_ok and state in {'WATCH','BREACH'})
            worst=max([w['burn_rate'] for w in windows] or [0.0]);remaining=max(0.0,1.0-worst/max(max(float(w['burn_threshold']) for w in windows),1.0))
            anomaly={'policy':self.policy(p.slo_policy_id),'windows':windows,'telemetry_quality_gate':gate,'release_verified':bool(verified),'deployment_attested':bool(att),'release_correlated':correlated}
            a=JourneyRecoveryReleaseSafetyAssessmentRow(safety_assessment_id=nid('jrrsa'),release_manifest_id=m.release_manifest_id if m else None,environment=environment,state=state,short_burn_rate=windows[0]['burn_rate'] if windows else 0.0,long_burn_rate=windows[-1]['burn_rate'] if windows else 0.0,error_budget_remaining=remaining,release_correlated_anomaly=correlated,anomaly_json=anomaly,action=action,assessed_by=actor,assessed_at=now(),supplier_fact_unchanged=True);s.add(a);s.flush()
            if action not in {'NONE','OBSERVE_ONLY'}: runtime_safety._set_freeze(s,environment,True,f'{state}: governed multi-window SLO safety gate',a.safety_assessment_id,actor)
            if action=='FREEZE_PROMOTION_AND_RECOMMEND_ROLLBACK' and m:
                r=JourneyRecoveryRollbackRecommendationRow(rollback_recommendation_id=nid('jrrr'),safety_assessment_id=a.safety_assessment_id,release_manifest_id=m.release_manifest_id,rollback_target_manifest_id=m.rollback_target_manifest_id,environment=environment,state='OPEN',reason_json={'reason':'GOVERNED_MULTI_WINDOW_SLO_BREACH','windows':windows,'telemetry_quality_gate':gate},created_at=now(),supplier_fact_unchanged=True);s.add(r)
            s.commit()
        corr=self.correlate(a.safety_assessment_id,actor)
        out=runtime_safety.assessment(a.safety_assessment_id);out['telemetry_quality_gate']=gate;out['incident_correlation']=corr;return out
    def correlate(self,safety_assessment_id,actor='correlator'):
        with SessionLocal() as s:
            a=s.get(JourneyRecoveryReleaseSafetyAssessmentRow,safety_assessment_id)
            if not a: raise ValueError('ASSESSMENT_NOT_FOUND')
            m=s.get(JourneyRecoveryReleaseManifestRow,a.release_manifest_id) if a.release_manifest_id else None
            att=ver=None
            if m:
                att=s.execute(select(JourneyRecoveryDeploymentAttestationRow).where(JourneyRecoveryDeploymentAttestationRow.release_manifest_id==m.release_manifest_id).order_by(JourneyRecoveryDeploymentAttestationRow.attested_at.desc())).scalars().first()
                ver=s.execute(select(JourneyRecoveryReleaseVerificationRow).where(JourneyRecoveryReleaseVerificationRow.release_manifest_id==m.release_manifest_id).order_by(JourneyRecoveryReleaseVerificationRow.verified_at.desc())).scalars().first()
            inc=s.execute(select(JourneyRecoveryLearningIncidentRow).where(JourneyRecoveryLearningIncidentRow.state!='CLOSED').order_by(JourneyRecoveryLearningIncidentRow.opened_at.desc())).scalars().first()
            q=(a.anomaly_json or {}).get('telemetry_quality_gate',{});quality_ok=q.get('state')=='PASS';signals=sum([bool(m),bool(att),bool(ver),bool(inc)])
            confidence='HIGH' if quality_ok and signals>=3 else ('MEDIUM' if quality_ok and signals>=2 else 'LOW')
            state='RELEASE_AND_INCIDENT_CORRELATED' if m and inc and a.release_correlated_anomaly else ('RELEASE_CORRELATED' if m and a.release_correlated_anomaly else ('NO_STRONG_CORRELATION' if quality_ok else 'INSUFFICIENT_EVIDENCE'))
            evidence={'release_manifest_id':m.release_manifest_id if m else None,'deployment_attestation_id':att.deployment_attestation_id if att else None,'release_verification_id':ver.release_verification_id if ver else None,'learning_incident_id':inc.incident_id if inc else None,'telemetry_quality_gate':q,'safety_state':a.state,'safety_action':a.action,'correlation_does_not_mutate_supplier_fact':True}
            c=JourneyRecoveryRuntimeIncidentCorrelationRow(runtime_incident_correlation_id=nid('jrric'),safety_assessment_id=a.safety_assessment_id,release_manifest_id=m.release_manifest_id if m else None,deployment_attestation_id=att.deployment_attestation_id if att else None,release_verification_id=ver.release_verification_id if ver else None,learning_incident_id=inc.incident_id if inc else None,environment=a.environment,correlation_state=state,confidence=confidence,evidence_json=evidence,correlated_at=now(),supplier_fact_unchanged=True);s.add(c);s.commit();return self.correlation(c.runtime_incident_correlation_id)
    def correlation(self,id):
        with SessionLocal() as s:
            c=s.get(JourneyRecoveryRuntimeIncidentCorrelationRow,id)
            if not c: raise ValueError('INCIDENT_CORRELATION_NOT_FOUND')
            return {'runtime_incident_correlation_id':c.runtime_incident_correlation_id,'safety_assessment_id':c.safety_assessment_id,'release_manifest_id':c.release_manifest_id,'deployment_attestation_id':c.deployment_attestation_id,'release_verification_id':c.release_verification_id,'learning_incident_id':c.learning_incident_id,'environment':c.environment,'correlation_state':c.correlation_state,'confidence':c.confidence,'evidence':c.evidence_json,'supplier_fact_unchanged':True}
    def status(self,environment='PROD'):
        with SessionLocal() as s:
            p=self._active_policy(s,environment);src=s.execute(select(JourneyRecoveryTelemetrySourceRow).where(JourneyRecoveryTelemetrySourceRow.environment==environment).order_by(JourneyRecoveryTelemetrySourceRow.created_at.desc())).scalars().all();q=s.execute(select(JourneyRecoveryTelemetryQualityAssessmentRow).where(JourneyRecoveryTelemetryQualityAssessmentRow.environment==environment).order_by(JourneyRecoveryTelemetryQualityAssessmentRow.assessed_at.desc())).scalars().first();c=s.execute(select(JourneyRecoveryRuntimeIncidentCorrelationRow).where(JourneyRecoveryRuntimeIncidentCorrelationRow.environment==environment).order_by(JourneyRecoveryRuntimeIncidentCorrelationRow.correlated_at.desc())).scalars().first()
            return {'environment':environment,'active_policy':self.policy(p.slo_policy_id) if p else None,'sources':[self.source(x.telemetry_source_id) for x in src],'latest_quality':self.quality(q.telemetry_quality_assessment_id) if q else None,'latest_correlation':self.correlation(c.runtime_incident_correlation_id) if c else None,'release_safety':runtime_safety.status(environment)}

recovery_runtime_telemetry_governance_service=RecoveryRuntimeTelemetryGovernanceService()
