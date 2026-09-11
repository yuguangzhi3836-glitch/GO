from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
from json import dumps
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    JourneyRecoveryConfigVersionRow, JourneyRecoveryEnvironmentBindingRow,
    JourneyRecoveryReleaseManifestRow, JourneyRecoveryConfigDriftAssessmentRow,
    JourneyRecoveryReleaseEventRow, JourneyRecoveryStrategyVersionRow,
    JourneyRecoveryCalibrationProfileRow, JourneyRecoveryLearningChangeRequestRow,
)

def now(): return datetime.now(timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'
def h(obj): return sha256(dumps(obj,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()

class RecoveryReleaseGovernanceService:
    ENVS=('DEV','STAGING','PROD')
    TYPES={'STRATEGY','CALIBRATION','INCIDENT_CHANGE','GENERIC'}

    def _event(self,s,manifest_id,event_type,actor,payload=None):
        s.add(JourneyRecoveryReleaseEventRow(release_event_id=nid('jrre'),release_manifest_id=manifest_id,event_type=event_type,actor_id=actor,payload_json=payload or {},supplier_fact_unchanged=True,created_at=now()))

    def _source_payload(self,s,kind,source_id):
        if kind=='STRATEGY':
            x=s.get(JourneyRecoveryStrategyVersionRow,source_id)
            if not x: raise ValueError('SOURCE_STRATEGY_NOT_FOUND')
            return {'strategy_version_id':x.strategy_version_id,'name':x.name,'state':x.state,'min_sample_count':x.min_sample_count,'min_confidence':x.min_confidence,'confidence_level':x.confidence_level,'rollout_percent':x.rollout_percent,'parameter_bounds':x.parameter_bounds_json,'rollback_thresholds':x.rollback_thresholds_json,'requires_approval':x.requires_approval,'approved_by':x.approved_by}
        if kind=='CALIBRATION':
            x=s.get(JourneyRecoveryCalibrationProfileRow,source_id)
            if not x: raise ValueError('SOURCE_CALIBRATION_NOT_FOUND')
            return {'calibration_profile_id':x.calibration_profile_id,'vertical':x.vertical,'adapter_key':x.adapter_key,'sample_count':x.sample_count,'source_experiment_id':x.source_experiment_id,'parameters':x.calibrated_parameters_json,'confidence':x.confidence_json,'state':x.state}
        if kind=='INCIDENT_CHANGE':
            x=s.get(JourneyRecoveryLearningChangeRequestRow,source_id)
            if not x: raise ValueError('SOURCE_CHANGE_REQUEST_NOT_FOUND')
            if x.state!='EXECUTED': raise ValueError('SOURCE_CHANGE_REQUEST_NOT_EXECUTED')
            return {'change_request_id':x.change_request_id,'incident_id':x.incident_id,'change_type':x.change_type,'requested_scope':x.requested_scope_json,'resume_plan':x.resume_plan_json,'execution_result':x.execution_result_json,'executed_by':x.executed_by,'executed_at':x.executed_at.isoformat() if x.executed_at else None}
        raise ValueError('UNSUPPORTED_SOURCE_KIND')

    def create_config_version(self,config_key,config_type,scope_type,scope_key,actor,payload=None,source_ref_kind=None,source_ref_id=None):
        if config_type not in self.TYPES: raise ValueError('INVALID_CONFIG_TYPE')
        if not config_key: raise ValueError('CONFIG_KEY_REQUIRED')
        with SessionLocal() as s:
            body=payload or {}
            if source_ref_kind and source_ref_id: body=self._source_payload(s,source_ref_kind,source_ref_id)
            latest=s.execute(select(JourneyRecoveryConfigVersionRow).where(JourneyRecoveryConfigVersionRow.config_key==config_key).order_by(JourneyRecoveryConfigVersionRow.version_number.desc())).scalars().first()
            ver=(latest.version_number+1) if latest else 1
            t=now();digest=h({'config_key':config_key,'version_number':ver,'config_type':config_type,'scope_type':scope_type,'scope_key':scope_key,'payload':body,'source_ref_kind':source_ref_kind,'source_ref_id':source_ref_id})
            row=JourneyRecoveryConfigVersionRow(config_version_id=nid('jrcv'),config_key=config_key,version_number=ver,config_type=config_type,scope_type=scope_type,scope_key=scope_key,source_ref_kind=source_ref_kind,source_ref_id=source_ref_id,payload_json=body,content_hash=digest,created_by=actor,created_at=t,supplier_fact_unchanged=True);s.add(row);s.flush()
            self._bind(s,'DEV',row,None,actor,None)
            s.commit();return self.config(row.config_version_id)

    def _bind(self,s,environment,row,manifest_id,actor,previous_override=None):
        b=s.execute(select(JourneyRecoveryEnvironmentBindingRow).where(JourneyRecoveryEnvironmentBindingRow.environment==environment,JourneyRecoveryEnvironmentBindingRow.config_key==row.config_key)).scalars().first()
        t=now();bh=h({'environment':environment,'config_key':row.config_key,'config_version_id':row.config_version_id,'content_hash':row.content_hash})
        if not b:
            b=JourneyRecoveryEnvironmentBindingRow(environment_binding_id=nid('jreb'),environment=environment,config_key=row.config_key,active_config_version_id=row.config_version_id,previous_config_version_id=previous_override,release_manifest_id=manifest_id,binding_hash=bh,drift_status='IN_SYNC',promoted_by=actor,promoted_at=t,last_verified_at=t,updated_at=t,supplier_fact_unchanged=True);s.add(b)
        else:
            prev=previous_override if previous_override is not None else b.active_config_version_id
            b.previous_config_version_id=prev;b.active_config_version_id=row.config_version_id;b.release_manifest_id=manifest_id;b.binding_hash=bh;b.drift_status='IN_SYNC';b.promoted_by=actor;b.promoted_at=t;b.last_verified_at=t;b.updated_at=t
        return b

    def create_manifest(self,source_environment,target_environment,config_version_ids,actor,rollback_target_manifest_id=None):
        if (source_environment,target_environment) not in {('DEV','STAGING'),('STAGING','PROD')}: raise ValueError('INVALID_ENVIRONMENT_PROMOTION')
        if not config_version_ids: raise ValueError('RELEASE_ENTRIES_REQUIRED')
        with SessionLocal() as s:
            entries=[]
            for vid in config_version_ids:
                v=s.get(JourneyRecoveryConfigVersionRow,vid)
                if not v: raise ValueError('CONFIG_VERSION_NOT_FOUND')
                entries.append({'config_key':v.config_key,'config_version_id':v.config_version_id,'content_hash':v.content_hash,'config_type':v.config_type,'scope_type':v.scope_type,'scope_key':v.scope_key})
            if len({x['config_key'] for x in entries})!=len(entries): raise ValueError('DUPLICATE_CONFIG_KEY_IN_RELEASE')
            if rollback_target_manifest_id and not s.get(JourneyRecoveryReleaseManifestRow,rollback_target_manifest_id): raise ValueError('ROLLBACK_TARGET_NOT_FOUND')
            body={'source_environment':source_environment,'target_environment':target_environment,'entries':entries,'rollback_target_manifest_id':rollback_target_manifest_id}
            row=JourneyRecoveryReleaseManifestRow(release_manifest_id=nid('jrrm'),source_environment=source_environment,target_environment=target_environment,state='DRAFT',entries_json=entries,manifest_hash=h(body),dry_run_json={},staging_evidence_json={},rollback_target_manifest_id=rollback_target_manifest_id,requested_by=actor,requested_at=now(),promotion_result_json={},supplier_fact_unchanged=True);s.add(row);self._event(s,row.release_manifest_id,'RELEASE_MANIFEST_CREATED',actor,body);s.commit();return self.manifest(row.release_manifest_id)

    def dry_run(self,manifest_id,actor):
        with SessionLocal() as s:
            m=s.get(JourneyRecoveryReleaseManifestRow,manifest_id)
            if not m: raise ValueError('RELEASE_MANIFEST_NOT_FOUND')
            checks=[];ok=True
            for e in m.entries_json:
                v=s.get(JourneyRecoveryConfigVersionRow,e['config_version_id']);valid=bool(v and v.content_hash==e['content_hash'])
                b=s.execute(select(JourneyRecoveryEnvironmentBindingRow).where(JourneyRecoveryEnvironmentBindingRow.environment==m.source_environment,JourneyRecoveryEnvironmentBindingRow.config_key==e['config_key'])).scalars().first()
                bound=bool(b and b.active_config_version_id==e['config_version_id'])
                checks.append({'config_key':e['config_key'],'immutable_hash_ok':valid,'source_binding_ok':bound});ok=ok and valid and bound
            result={'passed':ok,'checks':checks,'source_environment':m.source_environment,'target_environment':m.target_environment,'checked_at':now().isoformat()}
            m.dry_run_json=result;m.state='DRY_RUN_PASSED' if ok else 'DRY_RUN_FAILED';self._event(s,m.release_manifest_id,'DRY_RUN_COMPLETED',actor,result);s.commit()
            if not ok: raise ValueError('RELEASE_DRY_RUN_FAILED')
            return result

    def attach_staging_evidence(self,manifest_id,evidence_reference,summary,actor):
        if not evidence_reference: raise ValueError('STAGING_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            m=s.get(JourneyRecoveryReleaseManifestRow,manifest_id)
            if not m: raise ValueError('RELEASE_MANIFEST_NOT_FOUND')
            if m.target_environment!='PROD': raise ValueError('STAGING_EVIDENCE_ONLY_FOR_PROD_PROMOTION')
            m.staging_evidence_json={'evidence_reference':evidence_reference,'summary':summary,'attached_by':actor,'attached_at':now().isoformat()};self._event(s,m.release_manifest_id,'STAGING_EVIDENCE_ATTACHED',actor,m.staging_evidence_json);s.commit();return self.manifest(manifest_id)

    def approve(self,manifest_id,actor):
        with SessionLocal() as s:
            m=s.get(JourneyRecoveryReleaseManifestRow,manifest_id)
            if not m: raise ValueError('RELEASE_MANIFEST_NOT_FOUND')
            if m.requested_by==actor: raise ValueError('MAKER_CHECKER_REQUIRED')
            if not (m.dry_run_json or {}).get('passed'): raise ValueError('DRY_RUN_REQUIRED')
            if m.target_environment=='PROD' and not m.staging_evidence_json: raise ValueError('STAGING_EVIDENCE_REQUIRED')
            m.approved_by=actor;m.approved_at=now();m.state='APPROVED';self._event(s,m.release_manifest_id,'RELEASE_APPROVED',actor,{'manifest_hash':m.manifest_hash});s.commit();return self.manifest(manifest_id)

    def promote(self,manifest_id,actor):
        with SessionLocal() as s:
            m=s.get(JourneyRecoveryReleaseManifestRow,manifest_id)
            if not m: raise ValueError('RELEASE_MANIFEST_NOT_FOUND')
            if m.state!='APPROVED': raise ValueError('RELEASE_APPROVAL_REQUIRED')
            from go_hotel.journey.recovery_runtime_observability import recovery_runtime_observability_service as safety
            if not safety.promotion_allowed(m.target_environment): raise ValueError('PROMOTION_FROZEN_BY_RUNTIME_SAFETY')
            if m.target_environment=='PROD':
                from go_hotel.journey.recovery_continuous_chaos import recovery_continuous_chaos_service as continuous_readiness
                auth=continuous_readiness.authorize_release('PROD',m.release_manifest_id,actor)
                if not auth['allowed']: raise ValueError('PRODUCTION_READINESS_GATE_REQUIRED_OR_APPROVED_WAIVER')
            promoted=[]
            for e in m.entries_json:
                v=s.get(JourneyRecoveryConfigVersionRow,e['config_version_id'])
                if not v or v.content_hash!=e['content_hash']: raise ValueError('CONFIG_HASH_MISMATCH')
                self._bind(s,m.target_environment,v,m.release_manifest_id,actor)
                promoted.append({'config_key':v.config_key,'config_version_id':v.config_version_id})
            m.state='PROMOTED';m.promoted_by=actor;m.promoted_at=now();m.promotion_result_json={'environment':m.target_environment,'bindings':promoted,'supplier_fact_unchanged':True};self._event(s,m.release_manifest_id,'RELEASE_PROMOTED',actor,m.promotion_result_json);s.commit();return self.manifest(manifest_id)

    def rollback(self,manifest_id,actor):
        with SessionLocal() as s:
            m=s.get(JourneyRecoveryReleaseManifestRow,manifest_id)
            if not m: raise ValueError('RELEASE_MANIFEST_NOT_FOUND')
            if m.state!='PROMOTED': raise ValueError('ONLY_PROMOTED_RELEASE_CAN_ROLLBACK')
            target=s.get(JourneyRecoveryReleaseManifestRow,m.rollback_target_manifest_id) if m.rollback_target_manifest_id else None
            restored=[]
            if target:
                if target.target_environment!=m.target_environment or target.state not in {'PROMOTED','ROLLED_BACK'}: raise ValueError('INVALID_ROLLBACK_TARGET')
                target_map={e['config_key']:e for e in target.entries_json}
                for e in m.entries_json:
                    te=target_map.get(e['config_key'])
                    if not te: raise ValueError('ROLLBACK_TARGET_ENTRY_MISSING')
                    v=s.get(JourneyRecoveryConfigVersionRow,te['config_version_id']);self._bind(s,m.target_environment,v,m.release_manifest_id,actor);restored.append({'config_key':v.config_key,'config_version_id':v.config_version_id})
            else:
                for e in m.entries_json:
                    b=s.execute(select(JourneyRecoveryEnvironmentBindingRow).where(JourneyRecoveryEnvironmentBindingRow.environment==m.target_environment,JourneyRecoveryEnvironmentBindingRow.config_key==e['config_key'])).scalars().first()
                    if not b or not b.previous_config_version_id: raise ValueError('ROLLBACK_TARGET_REQUIRED')
                    v=s.get(JourneyRecoveryConfigVersionRow,b.previous_config_version_id);self._bind(s,m.target_environment,v,m.release_manifest_id,actor,previous_override=b.active_config_version_id);restored.append({'config_key':v.config_key,'config_version_id':v.config_version_id})
            m.state='ROLLED_BACK';m.rolled_back_by=actor;m.rolled_back_at=now();m.promotion_result_json={**(m.promotion_result_json or {}),'rollback':{'restored_bindings':restored,'rollback_target_manifest_id':m.rollback_target_manifest_id,'supplier_fact_unchanged':True}};self._event(s,m.release_manifest_id,'RELEASE_ROLLED_BACK',actor,m.promotion_result_json['rollback']);s.commit();return self.manifest(manifest_id)

    def check_drift(self,environment,observed_bindings,actor):
        if environment not in self.ENVS: raise ValueError('INVALID_ENVIRONMENT')
        with SessionLocal() as s:
            rows=s.execute(select(JourneyRecoveryEnvironmentBindingRow).where(JourneyRecoveryEnvironmentBindingRow.environment==environment)).scalars().all();expected={x.config_key:{'config_version_id':x.active_config_version_id,'binding_hash':x.binding_hash} for x in rows};drift={}
            for key,exp in expected.items():
                obs=(observed_bindings or {}).get(key)
                if not obs or obs.get('config_version_id')!=exp['config_version_id'] or (obs.get('binding_hash') and obs.get('binding_hash')!=exp['binding_hash']):drift[key]={'expected':exp,'observed':obs}
            for key,obs in (observed_bindings or {}).items():
                if key not in expected:drift[key]={'expected':None,'observed':obs}
            detected=bool(drift);t=now();row=JourneyRecoveryConfigDriftAssessmentRow(drift_assessment_id=nid('jrcda'),environment=environment,observed_bindings_json=observed_bindings or {},expected_bindings_json=expected,drift_json=drift,drift_detected=detected,action='BLOCK_PROMOTION_AND_RECONCILE' if detected else 'NONE',created_by=actor,created_at=t,supplier_fact_unchanged=True);s.add(row)
            for b in rows:b.drift_status='DRIFTED' if b.config_key in drift else 'IN_SYNC';b.last_verified_at=t;b.updated_at=t
            self._event(s,None,'CONFIG_DRIFT_DETECTED' if detected else 'CONFIG_DRIFT_CHECK_PASSED',actor,{'environment':environment,'drift':drift});s.commit();return {'drift_assessment_id':row.drift_assessment_id,'environment':environment,'drift_detected':detected,'drift':drift,'action':row.action,'supplier_fact_unchanged':True}

    def config(self,id):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryConfigVersionRow,id)
            if not x: raise ValueError('CONFIG_VERSION_NOT_FOUND')
            return {'config_version_id':x.config_version_id,'config_key':x.config_key,'version_number':x.version_number,'config_type':x.config_type,'scope_type':x.scope_type,'scope_key':x.scope_key,'source_ref_kind':x.source_ref_kind,'source_ref_id':x.source_ref_id,'payload':x.payload_json,'content_hash':x.content_hash,'created_by':x.created_by,'created_at':x.created_at.isoformat(),'supplier_fact_unchanged':x.supplier_fact_unchanged}

    def configs(self):
        with SessionLocal() as s:return [self._config_obj(x) for x in s.execute(select(JourneyRecoveryConfigVersionRow).order_by(JourneyRecoveryConfigVersionRow.created_at.desc())).scalars().all()]
    def _config_obj(self,x):return {'config_version_id':x.config_version_id,'config_key':x.config_key,'version_number':x.version_number,'config_type':x.config_type,'scope_type':x.scope_type,'scope_key':x.scope_key,'content_hash':x.content_hash,'source_ref_kind':x.source_ref_kind,'source_ref_id':x.source_ref_id,'created_by':x.created_by}
    def bindings(self,environment=None):
        with SessionLocal() as s:
            q=select(JourneyRecoveryEnvironmentBindingRow)
            if environment:q=q.where(JourneyRecoveryEnvironmentBindingRow.environment==environment)
            return [{'environment':x.environment,'config_key':x.config_key,'active_config_version_id':x.active_config_version_id,'previous_config_version_id':x.previous_config_version_id,'release_manifest_id':x.release_manifest_id,'binding_hash':x.binding_hash,'drift_status':x.drift_status,'last_verified_at':x.last_verified_at.isoformat() if x.last_verified_at else None} for x in s.execute(q.order_by(JourneyRecoveryEnvironmentBindingRow.environment,JourneyRecoveryEnvironmentBindingRow.config_key)).scalars().all()]
    def manifest(self,id):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryReleaseManifestRow,id)
            if not x: raise ValueError('RELEASE_MANIFEST_NOT_FOUND')
            ev=s.execute(select(JourneyRecoveryReleaseEventRow).where(JourneyRecoveryReleaseEventRow.release_manifest_id==id).order_by(JourneyRecoveryReleaseEventRow.created_at)).scalars().all()
            return {'release_manifest_id':x.release_manifest_id,'source_environment':x.source_environment,'target_environment':x.target_environment,'state':x.state,'entries':x.entries_json,'manifest_hash':x.manifest_hash,'dry_run':x.dry_run_json,'staging_evidence':x.staging_evidence_json,'rollback_target_manifest_id':x.rollback_target_manifest_id,'requested_by':x.requested_by,'approved_by':x.approved_by,'promoted_by':x.promoted_by,'rolled_back_by':x.rolled_back_by,'promotion_result':x.promotion_result_json,'supplier_fact_unchanged':x.supplier_fact_unchanged,'events':[{'event_type':e.event_type,'actor_id':e.actor_id,'payload':e.payload_json,'created_at':e.created_at.isoformat()} for e in ev]}
    def manifests(self):
        with SessionLocal() as s:return [{'release_manifest_id':x.release_manifest_id,'source_environment':x.source_environment,'target_environment':x.target_environment,'state':x.state,'manifest_hash':x.manifest_hash,'rollback_target_manifest_id':x.rollback_target_manifest_id,'requested_by':x.requested_by,'approved_by':x.approved_by,'promoted_by':x.promoted_by} for x in s.execute(select(JourneyRecoveryReleaseManifestRow).order_by(JourneyRecoveryReleaseManifestRow.requested_at.desc())).scalars().all()]
    def drift_assessments(self,limit=100):
        with SessionLocal() as s:return [{'drift_assessment_id':x.drift_assessment_id,'environment':x.environment,'drift_detected':x.drift_detected,'drift':x.drift_json,'action':x.action,'created_by':x.created_by,'created_at':x.created_at.isoformat(),'supplier_fact_unchanged':x.supplier_fact_unchanged} for x in s.execute(select(JourneyRecoveryConfigDriftAssessmentRow).order_by(JourneyRecoveryConfigDriftAssessmentRow.created_at.desc()).limit(limit)).scalars().all()]

recovery_release_governance_service=RecoveryReleaseGovernanceService()
