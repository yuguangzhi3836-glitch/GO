from datetime import datetime,timezone,timedelta
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoveryRuntimeObservationRow,JourneyRecoveryReleaseSafetyAssessmentRow,JourneyRecoveryReleaseSafetyControlRow,JourneyRecoveryRollbackRecommendationRow,JourneyRecoveryReleaseManifestRow,JourneyRecoveryReleaseVerificationRow

def now(): return datetime.now(timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'
def aware(x): return x.replace(tzinfo=timezone.utc) if x and x.tzinfo is None else x

class RecoveryRuntimeObservabilityService:
    SHORT_MINUTES=5; LONG_MINUTES=60; SHORT_BURN_THRESHOLD=14.4; LONG_BURN_THRESHOLD=6.0; WATCH_BURN_THRESHOLD=2.0
    def _latest_manifest(self,s,environment):
        return s.execute(select(JourneyRecoveryReleaseManifestRow).where(JourneyRecoveryReleaseManifestRow.target_environment==environment,JourneyRecoveryReleaseManifestRow.state=='PROMOTED').order_by(JourneyRecoveryReleaseManifestRow.promoted_at.desc())).scalars().first()
    def ingest(self,environment,runtime_instance,metrics,actor='runtime'):
        if environment not in {'DEV','STAGING','PROD'}: raise ValueError('INVALID_ENVIRONMENT')
        req=max(0,int(metrics.get('request_count',0)));err=max(0,int(metrics.get('error_count',0)));rate=float(metrics.get('error_rate',err/req if req else 0.0));avail=float(metrics.get('availability',max(0.0,1.0-rate)));slo=float(metrics.get('slo_target',0.999));lat=float(metrics.get('latency_p95_ms',0.0));window=max(1,int(metrics.get('window_seconds',60)))
        if not 0 < slo < 1: raise ValueError('INVALID_SLO_TARGET')
        with SessionLocal() as s:
            m=self._latest_manifest(s,environment)
            r=JourneyRecoveryRuntimeObservationRow(runtime_observation_id=nid('jrro'),release_manifest_id=m.release_manifest_id if m else None,environment=environment,runtime_instance=runtime_instance,window_seconds=window,request_count=req,error_count=err,error_rate=rate,availability=avail,latency_p95_ms=lat,slo_target=slo,payload_json=metrics,observed_at=now(),supplier_fact_unchanged=True);s.add(r);s.commit();return self.observation(r.runtime_observation_id)
    def _window(self,s,environment,minutes):
        cutoff=now()-timedelta(minutes=minutes);return s.execute(select(JourneyRecoveryRuntimeObservationRow).where(JourneyRecoveryRuntimeObservationRow.environment==environment,JourneyRecoveryRuntimeObservationRow.observed_at>=cutoff).order_by(JourneyRecoveryRuntimeObservationRow.observed_at.desc())).scalars().all()
    def _aggregate(self,rows):
        if not rows:return {'requests':0,'errors':0,'error_rate':0.0,'availability':1.0,'latency_p95_ms':0.0,'slo_target':0.999,'burn_rate':0.0}
        req=sum(x.request_count for x in rows);err=sum(x.error_count for x in rows);rate=(err/req) if req else sum(x.error_rate for x in rows)/len(rows);slo=rows[0].slo_target;budget=max(1e-9,1-slo);return {'requests':req,'errors':err,'error_rate':rate,'availability':max(0.0,1-rate),'latency_p95_ms':max(x.latency_p95_ms for x in rows),'slo_target':slo,'burn_rate':rate/budget}
    def assess(self,environment,actor='safety-controller'):
        with SessionLocal() as s:
            # Sprint 3U: once governed telemetry is configured, the legacy 3T assessment
            # cannot bypass telemetry provenance / quality gates.
            try:
                from go_hotel.db.models import JourneyRecoveryTelemetrySourceRow, JourneyRecoverySloPolicyRow
                governed_source=s.execute(select(JourneyRecoveryTelemetrySourceRow).where(JourneyRecoveryTelemetrySourceRow.environment==environment,JourneyRecoveryTelemetrySourceRow.state=='ACTIVE')).scalars().first()
                governed_policy=s.execute(select(JourneyRecoverySloPolicyRow).where(JourneyRecoverySloPolicyRow.environment==environment,JourneyRecoverySloPolicyRow.state=='ACTIVE')).scalars().first()
                if governed_source and governed_policy:
                    raise ValueError('GOVERNED_TELEMETRY_ASSESSMENT_REQUIRED')
            except ImportError:
                pass
            short=self._aggregate(self._window(s,environment,self.SHORT_MINUTES));long=self._aggregate(self._window(s,environment,self.LONG_MINUTES));m=self._latest_manifest(s,environment)
            verified=False
            if m: verified=bool(s.execute(select(JourneyRecoveryReleaseVerificationRow).where(JourneyRecoveryReleaseVerificationRow.release_manifest_id==m.release_manifest_id,JourneyRecoveryReleaseVerificationRow.state=='PASSED').order_by(JourneyRecoveryReleaseVerificationRow.verified_at.desc())).scalars().first())
            catastrophic=short['burn_rate']>=self.SHORT_BURN_THRESHOLD and long['burn_rate']>=self.LONG_BURN_THRESHOLD
            watch=max(short['burn_rate'],long['burn_rate'])>=self.WATCH_BURN_THRESHOLD
            correlated=bool(m and verified and watch)
            state='BREACH' if catastrophic else ('WATCH' if watch else 'HEALTHY')
            action='FREEZE_PROMOTION_AND_RECOMMEND_ROLLBACK' if catastrophic and environment=='PROD' else ('FREEZE_PROMOTION' if watch else 'NONE')
            remaining=max(0.0,1.0-long['burn_rate']/max(self.LONG_BURN_THRESHOLD,1.0))
            anomaly={'short_window_minutes':self.SHORT_MINUTES,'long_window_minutes':self.LONG_MINUTES,'short':short,'long':long,'verified_release':verified,'release_correlated':correlated,'thresholds':{'short':self.SHORT_BURN_THRESHOLD,'long':self.LONG_BURN_THRESHOLD,'watch':self.WATCH_BURN_THRESHOLD}}
            a=JourneyRecoveryReleaseSafetyAssessmentRow(safety_assessment_id=nid('jrrsa'),release_manifest_id=m.release_manifest_id if m else None,environment=environment,state=state,short_burn_rate=short['burn_rate'],long_burn_rate=long['burn_rate'],error_budget_remaining=remaining,release_correlated_anomaly=correlated,anomaly_json=anomaly,action=action,assessed_by=actor,assessed_at=now(),supplier_fact_unchanged=True);s.add(a);s.flush()
            if action!='NONE': self._set_freeze(s,environment,True,f'{state}: SLO burn-rate safety gate',a.safety_assessment_id,actor)
            rec=None
            if action=='FREEZE_PROMOTION_AND_RECOMMEND_ROLLBACK' and m:
                existing=s.execute(select(JourneyRecoveryRollbackRecommendationRow).where(JourneyRecoveryRollbackRecommendationRow.safety_assessment_id==a.safety_assessment_id)).scalars().first()
                if not existing:
                    rec=JourneyRecoveryRollbackRecommendationRow(rollback_recommendation_id=nid('jrrr'),safety_assessment_id=a.safety_assessment_id,release_manifest_id=m.release_manifest_id,rollback_target_manifest_id=m.rollback_target_manifest_id,environment=environment,state='OPEN',reason_json={'reason':'SLO_BURN_RATE_BREACH','short_burn_rate':a.short_burn_rate,'long_burn_rate':a.long_burn_rate,'release_correlated_anomaly':correlated},created_at=now(),supplier_fact_unchanged=True);s.add(rec)
            s.commit();return self.assessment(a.safety_assessment_id)
    def _set_freeze(self,s,environment,frozen,reason,assessment_id,actor):
        c=s.execute(select(JourneyRecoveryReleaseSafetyControlRow).where(JourneyRecoveryReleaseSafetyControlRow.environment==environment)).scalars().first()
        if not c:c=JourneyRecoveryReleaseSafetyControlRow(release_safety_control_id=nid('jrrsc'),environment=environment,promotion_frozen=frozen,freeze_reason=reason,source_assessment_id=assessment_id,updated_by=actor,updated_at=now(),supplier_fact_unchanged=True);s.add(c)
        else:c.promotion_frozen=frozen;c.freeze_reason=reason;c.source_assessment_id=assessment_id;c.updated_by=actor;c.updated_at=now()
        return c
    def unfreeze(self,environment,actor,evidence_reference):
        if not evidence_reference: raise ValueError('RECOVERY_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            c=s.execute(select(JourneyRecoveryReleaseSafetyControlRow).where(JourneyRecoveryReleaseSafetyControlRow.environment==environment)).scalars().first()
            if not c: raise ValueError('SAFETY_CONTROL_NOT_FOUND')
            latest=s.execute(select(JourneyRecoveryReleaseSafetyAssessmentRow).where(JourneyRecoveryReleaseSafetyAssessmentRow.environment==environment).order_by(JourneyRecoveryReleaseSafetyAssessmentRow.assessed_at.desc())).scalars().first()
            if not latest or latest.state!='HEALTHY': raise ValueError('HEALTHY_ASSESSMENT_REQUIRED')
            self._set_freeze(s,environment,False,f'UNFROZEN_WITH_EVIDENCE:{evidence_reference}',latest.safety_assessment_id,actor);s.commit();return self.control(environment)
    def promotion_allowed(self,environment):
        with SessionLocal() as s:
            c=s.execute(select(JourneyRecoveryReleaseSafetyControlRow).where(JourneyRecoveryReleaseSafetyControlRow.environment==environment)).scalars().first()
            base=not bool(c and c.promotion_frozen)
        if environment=='PROD':
            try:
                from go_hotel.services.production_connector_runtime import production_connector_runtime_service
                if production_connector_runtime_service.has_release_blocking_incident(): return False
            except Exception:
                return False
        return base
    def acknowledge_recommendation(self,recommendation_id,actor):
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryRollbackRecommendationRow,recommendation_id)
            if not r: raise ValueError('ROLLBACK_RECOMMENDATION_NOT_FOUND')
            if r.state!='OPEN': raise ValueError('OPEN_RECOMMENDATION_REQUIRED')
            r.state='ACKNOWLEDGED';r.acknowledged_by=actor;r.acknowledged_at=now();s.commit();return self.recommendation(recommendation_id)
    def observation(self,id):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryRuntimeObservationRow,id)
            if not x: raise ValueError('OBSERVATION_NOT_FOUND')
            return {'runtime_observation_id':x.runtime_observation_id,'release_manifest_id':x.release_manifest_id,'environment':x.environment,'runtime_instance':x.runtime_instance,'request_count':x.request_count,'error_count':x.error_count,'error_rate':x.error_rate,'availability':x.availability,'latency_p95_ms':x.latency_p95_ms,'slo_target':x.slo_target,'observed_at':aware(x.observed_at).isoformat(),'supplier_fact_unchanged':True}
    def assessment(self,id):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryReleaseSafetyAssessmentRow,id)
            if not x: raise ValueError('ASSESSMENT_NOT_FOUND')
            rec=s.execute(select(JourneyRecoveryRollbackRecommendationRow).where(JourneyRecoveryRollbackRecommendationRow.safety_assessment_id==id)).scalars().first()
            return {'safety_assessment_id':x.safety_assessment_id,'release_manifest_id':x.release_manifest_id,'environment':x.environment,'state':x.state,'short_burn_rate':x.short_burn_rate,'long_burn_rate':x.long_burn_rate,'error_budget_remaining':x.error_budget_remaining,'release_correlated_anomaly':x.release_correlated_anomaly,'anomaly':x.anomaly_json,'action':x.action,'rollback_recommendation':self.recommendation(rec.rollback_recommendation_id) if rec else None,'supplier_fact_unchanged':True}
    def recommendation(self,id):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryRollbackRecommendationRow,id)
            if not x: raise ValueError('ROLLBACK_RECOMMENDATION_NOT_FOUND')
            return {'rollback_recommendation_id':x.rollback_recommendation_id,'safety_assessment_id':x.safety_assessment_id,'release_manifest_id':x.release_manifest_id,'rollback_target_manifest_id':x.rollback_target_manifest_id,'environment':x.environment,'state':x.state,'reason':x.reason_json,'acknowledged_by':x.acknowledged_by,'supplier_fact_unchanged':True}
    def control(self,environment):
        with SessionLocal() as s:
            c=s.execute(select(JourneyRecoveryReleaseSafetyControlRow).where(JourneyRecoveryReleaseSafetyControlRow.environment==environment)).scalars().first()
            return {'environment':environment,'promotion_frozen':bool(c and c.promotion_frozen),'freeze_reason':c.freeze_reason if c else None,'source_assessment_id':c.source_assessment_id if c else None,'supplier_fact_unchanged':True}
    def status(self,environment='PROD'):
        with SessionLocal() as s:
            a=s.execute(select(JourneyRecoveryReleaseSafetyAssessmentRow).where(JourneyRecoveryReleaseSafetyAssessmentRow.environment==environment).order_by(JourneyRecoveryReleaseSafetyAssessmentRow.assessed_at.desc())).scalars().first();recs=s.execute(select(JourneyRecoveryRollbackRecommendationRow).where(JourneyRecoveryRollbackRecommendationRow.environment==environment).order_by(JourneyRecoveryRollbackRecommendationRow.created_at.desc()).limit(10)).scalars().all()
            incident_blocked=False
            try:
                from go_hotel.services.production_connector_runtime import production_connector_runtime_service
                incident_blocked=production_connector_runtime_service.has_release_blocking_incident()
            except Exception:
                incident_blocked=True if environment=='PROD' else False
            return {'environment':environment,'control':self.control(environment),'latest_assessment':self.assessment(a.safety_assessment_id) if a else None,'rollback_recommendations':[self.recommendation(x.rollback_recommendation_id) for x in recs],'external_truth_incident_blocked':incident_blocked,'promotion_allowed':self.promotion_allowed(environment)}

recovery_runtime_observability_service=RecoveryRuntimeObservabilityService()
