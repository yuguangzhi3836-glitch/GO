from datetime import datetime, timezone
from uuid import uuid4
from hashlib import sha256
import json
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import *

def now(): return datetime.now(timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'
def canon(v): return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=True,default=str)
def h(v): return sha256(canon(v).encode()).hexdigest()

class RecoveryForecastTrainingGovernanceService:
    def active_policy_in_session(self,s,environment):
        return s.execute(select(JourneyRecoveryForecastTrainingPolicyRow).where(JourneyRecoveryForecastTrainingPolicyRow.environment==environment,JourneyRecoveryForecastTrainingPolicyRow.state=='ACTIVE').order_by(JourneyRecoveryForecastTrainingPolicyRow.version_no.desc())).scalars().first()
    def create_policy(self,environment,minimum_training_rows=20,max_missing_rate=.05,max_duplicate_rate=.02,max_invalid_rate=.01,reproducibility_required=True,actor='model-risk-governance'):
        if minimum_training_rows<2 or min(max_missing_rate,max_duplicate_rate,max_invalid_rate)<0 or max(max_missing_rate,max_duplicate_rate,max_invalid_rate)>1: raise ValueError('INVALID_FORECAST_TRAINING_POLICY')
        with SessionLocal() as s:
            prev=s.execute(select(JourneyRecoveryForecastTrainingPolicyRow).where(JourneyRecoveryForecastTrainingPolicyRow.environment==environment).order_by(JourneyRecoveryForecastTrainingPolicyRow.version_no.desc())).scalars().first()
            x=JourneyRecoveryForecastTrainingPolicyRow(forecast_training_policy_id=nid('jftp'),environment=environment,version_no=(prev.version_no+1 if prev else 1),minimum_training_rows=minimum_training_rows,max_missing_rate=max_missing_rate,max_duplicate_rate=max_duplicate_rate,max_invalid_rate=max_invalid_rate,reproducibility_required=reproducibility_required,requested_by=actor,approver_one=None,approver_two=None,state='PENDING_APPROVAL',created_at=now(),supplier_fact_unchanged=True);s.add(x);s.commit();return self.policy(x.forecast_training_policy_id)
    def approve_policy(self,policy_id,actor):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryForecastTrainingPolicyRow,policy_id)
            if not x: raise ValueError('FORECAST_TRAINING_POLICY_NOT_FOUND')
            if actor==x.requested_by: raise ValueError('FORECAST_TRAINING_MAKER_CHECKER_REQUIRED')
            if not x.approver_one: x.approver_one=actor;x.state='AWAITING_SECOND_APPROVAL'
            elif x.approver_one==actor: raise ValueError('TWO_DISTINCT_TRAINING_APPROVERS_REQUIRED')
            elif not x.approver_two:
                x.approver_two=actor
                for y in s.execute(select(JourneyRecoveryForecastTrainingPolicyRow).where(JourneyRecoveryForecastTrainingPolicyRow.environment==x.environment,JourneyRecoveryForecastTrainingPolicyRow.state=='ACTIVE')).scalars().all(): y.state='SUPERSEDED'
                x.state='ACTIVE'
            s.commit();return self.policy(policy_id)
    def register_feature(self,environment,feature_key,data_type,definition,actor='feature-governance'):
        if not feature_key or not data_type: raise ValueError('FEATURE_DEFINITION_REQUIRED')
        transform_hash=h({'feature_key':feature_key,'data_type':data_type,'definition':definition or {}})
        with SessionLocal() as s:
            prev=s.execute(select(JourneyRecoveryForecastFeatureVersionRow).where(JourneyRecoveryForecastFeatureVersionRow.environment==environment,JourneyRecoveryForecastFeatureVersionRow.feature_key==feature_key).order_by(JourneyRecoveryForecastFeatureVersionRow.version_no.desc())).scalars().first()
            x=JourneyRecoveryForecastFeatureVersionRow(forecast_feature_version_id=nid('jffv'),environment=environment,feature_key=feature_key,version_no=(prev.version_no+1 if prev else 1),data_type=data_type,definition_json=definition or {},transform_hash=transform_hash,state='ACTIVE',created_by=actor,created_at=now(),supplier_fact_unchanged=True);s.add(x);s.commit();return self.feature(x.forecast_feature_version_id)
    def snapshot_dataset(self,environment,dataset_key,records,feature_version_ids,source_refs=None):
        records=records or []; feature_version_ids=feature_version_ids or []
        if not dataset_key or not feature_version_ids: raise ValueError('DATASET_AND_FEATURE_VERSIONS_REQUIRED')
        with SessionLocal() as s:
            feats=[s.get(JourneyRecoveryForecastFeatureVersionRow,i) for i in feature_version_ids]
            if any(not f or f.environment!=environment or f.state!='ACTIVE' for f in feats): raise ValueError('ACTIVE_FEATURE_VERSION_REQUIRED')
            prev=s.execute(select(JourneyRecoveryForecastTrainingDatasetSnapshotRow).where(JourneyRecoveryForecastTrainingDatasetSnapshotRow.environment==environment,JourneyRecoveryForecastTrainingDatasetSnapshotRow.dataset_key==dataset_key).order_by(JourneyRecoveryForecastTrainingDatasetSnapshotRow.snapshot_version.desc())).scalars().first()
            keys=sorted({k for r in records if isinstance(r,dict) for k in r.keys()}); schema={'keys':keys,'feature_versions':sorted(feature_version_ids)}
            x=JourneyRecoveryForecastTrainingDatasetSnapshotRow(training_dataset_snapshot_id=nid('jtds'),environment=environment,dataset_key=dataset_key,snapshot_version=(prev.snapshot_version+1 if prev else 1),row_count=len(records),schema_hash=h(schema),content_hash=h(records),source_refs_json=source_refs or [],feature_version_ids_json=feature_version_ids,created_at=now(),supplier_fact_unchanged=True);s.add(x);self._event(s,environment,'TRAINING_DATASET_SNAPSHOTTED',None,{'dataset_key':dataset_key,'content_hash':x.content_hash},'training-data-governance');s.commit();return self.dataset(x.training_dataset_snapshot_id)
    def assess_data_quality(self,snapshot_id,missing_rate,duplicate_rate,invalid_rate,evidence,actor='training-data-quality'):
        if not evidence: raise ValueError('TRAINING_DATA_QUALITY_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            ds=s.get(JourneyRecoveryForecastTrainingDatasetSnapshotRow,snapshot_id)
            if not ds: raise ValueError('TRAINING_DATASET_SNAPSHOT_NOT_FOUND')
            p=self.active_policy_in_session(s,ds.environment)
            if not p: raise ValueError('ACTIVE_FORECAST_TRAINING_POLICY_REQUIRED')
            reasons=[]
            if ds.row_count<p.minimum_training_rows: reasons.append('MINIMUM_TRAINING_ROWS_NOT_MET')
            if missing_rate>p.max_missing_rate: reasons.append('MISSING_RATE_EXCEEDED')
            if duplicate_rate>p.max_duplicate_rate: reasons.append('DUPLICATE_RATE_EXCEEDED')
            if invalid_rate>p.max_invalid_rate: reasons.append('INVALID_RATE_EXCEEDED')
            state='FAIL' if reasons else 'PASS'
            x=JourneyRecoveryForecastTrainingDataQualityRow(training_data_quality_id=nid('jtdq'),environment=ds.environment,training_dataset_snapshot_id=ds.training_dataset_snapshot_id,policy_id=p.forecast_training_policy_id,row_count=ds.row_count,missing_rate=missing_rate,duplicate_rate=duplicate_rate,invalid_rate=invalid_rate,quality_state=state,reason_codes_json=reasons,evidence_json=evidence,assessed_at=now(),supplier_fact_unchanged=True);s.add(x);self._event(s,ds.environment,'TRAINING_DATA_QUALITY_ASSESSED',None,{'state':state,'reason_codes':reasons},actor);s.commit();return self.quality(x.training_data_quality_id)
    def create_lineage(self,environment,challenger_model_version_id,snapshot_id,source_retraining_request_id=None):
        with SessionLocal() as s:
            m=s.get(JourneyRecoveryRiskForecastModelVersionRow,challenger_model_version_id);ds=s.get(JourneyRecoveryForecastTrainingDatasetSnapshotRow,snapshot_id)
            if not m or m.environment!=environment: raise ValueError('CHALLENGER_MODEL_VERSION_NOT_FOUND')
            role=s.execute(select(JourneyRecoveryForecastModelRoleRow).where(JourneyRecoveryForecastModelRoleRow.environment==environment,JourneyRecoveryForecastModelRoleRow.model_version_id==challenger_model_version_id,JourneyRecoveryForecastModelRoleRow.role=='CHALLENGER',JourneyRecoveryForecastModelRoleRow.state=='ACTIVE')).scalars().first()
            if not role: raise ValueError('ACTIVE_CHALLENGER_ROLE_REQUIRED')
            if not ds or ds.environment!=environment: raise ValueError('TRAINING_DATASET_SNAPSHOT_NOT_FOUND')
            payload={'model_version_id':challenger_model_version_id,'dataset_snapshot_id':snapshot_id,'dataset_hash':ds.content_hash,'feature_versions':sorted(ds.feature_version_ids_json or []),'source_retraining_request_id':source_retraining_request_id}
            x=JourneyRecoveryForecastTrainingLineageRow(forecast_training_lineage_id=nid('jftl'),environment=environment,challenger_model_version_id=challenger_model_version_id,training_dataset_snapshot_id=snapshot_id,feature_version_ids_json=ds.feature_version_ids_json or [],source_retraining_request_id=source_retraining_request_id,lineage_hash=h(payload),lineage_state='COMPLETE',created_at=now(),supplier_fact_unchanged=True);s.add(x);self._event(s,environment,'TRAINING_LINEAGE_CREATED',challenger_model_version_id,{'lineage_hash':x.lineage_hash},'model-build-governance');s.commit();return self.lineage(x.forecast_training_lineage_id)
    def create_manifest(self,lineage_id,code_ref,code_hash,hyperparameters=None,random_seed=42,actor='model-build-governance'):
        if not code_ref or not code_hash: raise ValueError('TRAINING_CODE_PROVENANCE_REQUIRED')
        with SessionLocal() as s:
            l=s.get(JourneyRecoveryForecastTrainingLineageRow,lineage_id)
            if not l or l.lineage_state!='COMPLETE': raise ValueError('COMPLETE_TRAINING_LINEAGE_REQUIRED')
            m=s.get(JourneyRecoveryRiskForecastModelVersionRow,l.challenger_model_version_id);ds=s.get(JourneyRecoveryForecastTrainingDatasetSnapshotRow,l.training_dataset_snapshot_id)
            feats=[s.get(JourneyRecoveryForecastFeatureVersionRow,i) for i in l.feature_version_ids_json or []]
            payload={'lineage_hash':l.lineage_hash,'dataset_hash':ds.content_hash,'feature_hashes':sorted(f.transform_hash for f in feats),'code_ref':code_ref,'code_hash':code_hash,'algorithm_key':m.algorithm_key,'hyperparameters':hyperparameters or dict(m.parameters_json or {}),'random_seed':random_seed}
            x=JourneyRecoveryForecastTrainingManifestRow(forecast_training_manifest_id=nid('jftm'),environment=l.environment,challenger_model_version_id=l.challenger_model_version_id,training_lineage_id=l.forecast_training_lineage_id,code_ref=code_ref,code_hash=code_hash,algorithm_key=m.algorithm_key,hyperparameters_json=payload['hyperparameters'],random_seed=random_seed,build_hash=h(payload),manifest_state='READY_FOR_REPRODUCTION',created_at=now(),supplier_fact_unchanged=True);s.add(x);self._event(s,l.environment,'TRAINING_MANIFEST_CREATED',l.challenger_model_version_id,{'build_hash':x.build_hash},actor);s.commit();return self.manifest(x.forecast_training_manifest_id)
    def check_reproducibility(self,manifest_id,reproduced_code_hash,reproduced_hyperparameters,reproduced_seed,evidence_reference,actor='independent-reproducer'):
        if not evidence_reference: raise ValueError('REPRODUCIBILITY_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            m=s.get(JourneyRecoveryForecastTrainingManifestRow,manifest_id)
            if not m: raise ValueError('TRAINING_MANIFEST_NOT_FOUND')
            l=s.get(JourneyRecoveryForecastTrainingLineageRow,m.training_lineage_id);ds=s.get(JourneyRecoveryForecastTrainingDatasetSnapshotRow,l.training_dataset_snapshot_id);feats=[s.get(JourneyRecoveryForecastFeatureVersionRow,i) for i in l.feature_version_ids_json or []]
            payload={'lineage_hash':l.lineage_hash,'dataset_hash':ds.content_hash,'feature_hashes':sorted(f.transform_hash for f in feats),'code_ref':m.code_ref,'code_hash':reproduced_code_hash,'algorithm_key':m.algorithm_key,'hyperparameters':reproduced_hyperparameters,'random_seed':reproduced_seed}
            rh=h(payload);state='MATCHED' if rh==m.build_hash else 'MISMATCH'
            x=JourneyRecoveryForecastReproducibilityCheckRow(forecast_reproducibility_check_id=nid('jfrc'),environment=m.environment,challenger_model_version_id=m.challenger_model_version_id,training_manifest_id=m.forecast_training_manifest_id,expected_build_hash=m.build_hash,reproduced_build_hash=rh,reproducibility_state=state,evidence_reference=evidence_reference,checked_by=actor,checked_at=now(),supplier_fact_unchanged=True);s.add(x);self._event(s,m.environment,'REPRODUCIBILITY_CHECKED',m.challenger_model_version_id,{'state':state,'expected':m.build_hash,'reproduced':rh},actor);s.commit();return self.repro(x.forecast_reproducibility_check_id)
    def evaluate_build(self,challenger_model_version_id,actor='model-build-gate'):
        with SessionLocal() as s:
            m=s.get(JourneyRecoveryRiskForecastModelVersionRow,challenger_model_version_id)
            if not m: raise ValueError('CHALLENGER_MODEL_VERSION_NOT_FOUND')
            p=self.active_policy_in_session(s,m.environment)
            if not p: raise ValueError('ACTIVE_FORECAST_TRAINING_POLICY_REQUIRED')
            manifest=s.execute(select(JourneyRecoveryForecastTrainingManifestRow).where(JourneyRecoveryForecastTrainingManifestRow.challenger_model_version_id==challenger_model_version_id).order_by(JourneyRecoveryForecastTrainingManifestRow.created_at.desc())).scalars().first()
            if not manifest: raise ValueError('TRAINING_MANIFEST_REQUIRED')
            lineage=s.get(JourneyRecoveryForecastTrainingLineageRow,manifest.training_lineage_id)
            quality=s.execute(select(JourneyRecoveryForecastTrainingDataQualityRow).join(JourneyRecoveryForecastTrainingDatasetSnapshotRow,JourneyRecoveryForecastTrainingDataQualityRow.training_dataset_snapshot_id==JourneyRecoveryForecastTrainingDatasetSnapshotRow.training_dataset_snapshot_id).where(JourneyRecoveryForecastTrainingDatasetSnapshotRow.training_dataset_snapshot_id==lineage.training_dataset_snapshot_id).order_by(JourneyRecoveryForecastTrainingDataQualityRow.assessed_at.desc())).scalars().first()
            repro=s.execute(select(JourneyRecoveryForecastReproducibilityCheckRow).where(JourneyRecoveryForecastReproducibilityCheckRow.training_manifest_id==manifest.forecast_training_manifest_id).order_by(JourneyRecoveryForecastReproducibilityCheckRow.checked_at.desc())).scalars().first()
            reasons=[]
            if not quality or quality.quality_state!='PASS': reasons.append('TRAINING_DATA_QUALITY_PASS_REQUIRED')
            if not lineage or lineage.lineage_state!='COMPLETE': reasons.append('COMPLETE_DATA_LINEAGE_REQUIRED')
            if manifest.manifest_state!='READY_FOR_REPRODUCTION': reasons.append('TRAINING_MANIFEST_NOT_READY')
            if p.reproducibility_required and (not repro or repro.reproducibility_state!='MATCHED'): reasons.append('REPRODUCIBILITY_MATCH_REQUIRED')
            state='BLOCKED' if reasons else 'ELIGIBLE'
            x=JourneyRecoveryForecastModelBuildEligibilityRow(forecast_model_build_eligibility_id=nid('jfbe'),environment=m.environment,challenger_model_version_id=challenger_model_version_id,training_manifest_id=manifest.forecast_training_manifest_id,data_quality_id=(quality.training_data_quality_id if quality else 'MISSING'),reproducibility_check_id=(repro.forecast_reproducibility_check_id if repro else 'MISSING'),eligibility_state=state,reason_codes_json=reasons,evaluated_at=now(),supplier_fact_unchanged=True);s.add(x);self._event(s,m.environment,'MODEL_BUILD_ELIGIBILITY_EVALUATED',challenger_model_version_id,{'state':state,'reason_codes':reasons},actor);s.commit();return self.eligibility(x.forecast_model_build_eligibility_id)
    def assert_challenger_eligible_in_session(self,s,environment,challenger_id):
        p=self.active_policy_in_session(s,environment)
        if not p:return
        e=s.execute(select(JourneyRecoveryForecastModelBuildEligibilityRow).where(JourneyRecoveryForecastModelBuildEligibilityRow.environment==environment,JourneyRecoveryForecastModelBuildEligibilityRow.challenger_model_version_id==challenger_id,JourneyRecoveryForecastModelBuildEligibilityRow.eligibility_state=='ELIGIBLE').order_by(JourneyRecoveryForecastModelBuildEligibilityRow.evaluated_at.desc())).scalars().first()
        if not e: raise ValueError('REPRODUCIBLE_MODEL_BUILD_ELIGIBILITY_REQUIRED')
    def status(self,environment):
        with SessionLocal() as s:
            p=self.active_policy_in_session(s,environment)
            return {'active_policy':self._policy(p) if p else None,'features':[self._feature(x) for x in s.execute(select(JourneyRecoveryForecastFeatureVersionRow).where(JourneyRecoveryForecastFeatureVersionRow.environment==environment).order_by(JourneyRecoveryForecastFeatureVersionRow.created_at.desc()).limit(30)).scalars().all()],'datasets':[self._dataset(x) for x in s.execute(select(JourneyRecoveryForecastTrainingDatasetSnapshotRow).where(JourneyRecoveryForecastTrainingDatasetSnapshotRow.environment==environment).order_by(JourneyRecoveryForecastTrainingDatasetSnapshotRow.created_at.desc()).limit(20)).scalars().all()],'eligibilities':[self._eligibility(x) for x in s.execute(select(JourneyRecoveryForecastModelBuildEligibilityRow).where(JourneyRecoveryForecastModelBuildEligibilityRow.environment==environment).order_by(JourneyRecoveryForecastModelBuildEligibilityRow.evaluated_at.desc()).limit(20)).scalars().all()]}
    def _event(self,s,environment,event_type,challenger,evidence,actor):s.add(JourneyRecoveryForecastTrainingGovernanceEventRow(forecast_training_governance_event_id=nid('jftge'),environment=environment,event_type=event_type,challenger_model_version_id=challenger,evidence_json=evidence or {},actor=actor,created_at=now(),supplier_fact_unchanged=True))
    def policy(self,i):
        with SessionLocal() as s:return self._policy(s.get(JourneyRecoveryForecastTrainingPolicyRow,i))
    def feature(self,i):
        with SessionLocal() as s:return self._feature(s.get(JourneyRecoveryForecastFeatureVersionRow,i))
    def dataset(self,i):
        with SessionLocal() as s:return self._dataset(s.get(JourneyRecoveryForecastTrainingDatasetSnapshotRow,i))
    def quality(self,i):
        with SessionLocal() as s:return self._quality(s.get(JourneyRecoveryForecastTrainingDataQualityRow,i))
    def lineage(self,i):
        with SessionLocal() as s:return self._lineage(s.get(JourneyRecoveryForecastTrainingLineageRow,i))
    def manifest(self,i):
        with SessionLocal() as s:return self._manifest(s.get(JourneyRecoveryForecastTrainingManifestRow,i))
    def repro(self,i):
        with SessionLocal() as s:return self._repro(s.get(JourneyRecoveryForecastReproducibilityCheckRow,i))
    def eligibility(self,i):
        with SessionLocal() as s:return self._eligibility(s.get(JourneyRecoveryForecastModelBuildEligibilityRow,i))
    def _policy(self,x): return {'forecast_training_policy_id':x.forecast_training_policy_id,'environment':x.environment,'version_no':x.version_no,'minimum_training_rows':x.minimum_training_rows,'max_missing_rate':x.max_missing_rate,'max_duplicate_rate':x.max_duplicate_rate,'max_invalid_rate':x.max_invalid_rate,'reproducibility_required':x.reproducibility_required,'state':x.state,'supplier_fact_unchanged':True}
    def _feature(self,x): return {'forecast_feature_version_id':x.forecast_feature_version_id,'feature_key':x.feature_key,'version_no':x.version_no,'data_type':x.data_type,'transform_hash':x.transform_hash,'state':x.state,'supplier_fact_unchanged':True}
    def _dataset(self,x): return {'training_dataset_snapshot_id':x.training_dataset_snapshot_id,'dataset_key':x.dataset_key,'snapshot_version':x.snapshot_version,'row_count':x.row_count,'schema_hash':x.schema_hash,'content_hash':x.content_hash,'feature_version_ids':x.feature_version_ids_json,'supplier_fact_unchanged':True}
    def _quality(self,x): return {'training_data_quality_id':x.training_data_quality_id,'quality_state':x.quality_state,'row_count':x.row_count,'missing_rate':x.missing_rate,'duplicate_rate':x.duplicate_rate,'invalid_rate':x.invalid_rate,'reason_codes':x.reason_codes_json,'supplier_fact_unchanged':True}
    def _lineage(self,x): return {'forecast_training_lineage_id':x.forecast_training_lineage_id,'challenger_model_version_id':x.challenger_model_version_id,'training_dataset_snapshot_id':x.training_dataset_snapshot_id,'feature_version_ids':x.feature_version_ids_json,'lineage_hash':x.lineage_hash,'lineage_state':x.lineage_state,'supplier_fact_unchanged':True}
    def _manifest(self,x): return {'forecast_training_manifest_id':x.forecast_training_manifest_id,'challenger_model_version_id':x.challenger_model_version_id,'code_ref':x.code_ref,'code_hash':x.code_hash,'algorithm_key':x.algorithm_key,'random_seed':x.random_seed,'build_hash':x.build_hash,'manifest_state':x.manifest_state,'supplier_fact_unchanged':True}
    def _repro(self,x): return {'forecast_reproducibility_check_id':x.forecast_reproducibility_check_id,'reproducibility_state':x.reproducibility_state,'expected_build_hash':x.expected_build_hash,'reproduced_build_hash':x.reproduced_build_hash,'supplier_fact_unchanged':True}
    def _eligibility(self,x): return {'forecast_model_build_eligibility_id':x.forecast_model_build_eligibility_id,'challenger_model_version_id':x.challenger_model_version_id,'eligibility_state':x.eligibility_state,'reason_codes':x.reason_codes_json,'supplier_fact_unchanged':True}

recovery_forecast_training_governance_service=RecoveryForecastTrainingGovernanceService()
