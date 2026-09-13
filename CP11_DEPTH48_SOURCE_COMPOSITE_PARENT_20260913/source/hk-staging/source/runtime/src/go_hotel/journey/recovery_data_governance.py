from __future__ import annotations
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    JourneyRecoveryReliabilityProfileRow, JourneyRecoverySupplierOperationRow,
    JourneyRecoverySupplierIdentityMapRow, JourneyRecoveryDataQualityAssessmentRow,
    JourneyRecoverySampleQuarantineRow, JourneyRecoveryPrivacyBudgetRow,
    JourneyRecoveryLearningKillSwitchRow,
)

def now(): return datetime.now(timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'

class RecoveryDataGovernanceService:
    DEFAULT_EPSILON=1.0
    RELEASE_COST=0.1
    MIN_SAMPLES=5
    MAX_ANOMALY_RATE=.20

    def upsert_supplier_mapping(self, vertical, adapter_key, supplier_id, actor='SYSTEM'):
        with SessionLocal() as s:
            row=s.execute(select(JourneyRecoverySupplierIdentityMapRow).where(JourneyRecoverySupplierIdentityMapRow.vertical==vertical,JourneyRecoverySupplierIdentityMapRow.adapter_key==adapter_key)).scalar_one_or_none()
            t=now()
            if not row:
                row=JourneyRecoverySupplierIdentityMapRow(supplier_identity_map_id=nid('jrsim'),vertical=vertical,adapter_key=adapter_key,supplier_id=supplier_id,mapping_state='ACTIVE',evidence_json={'source':'GOVERNED_MAPPING','actor':actor},created_at=t,updated_at=t);s.add(row)
            else:
                row.supplier_id=supplier_id;row.mapping_state='ACTIVE';row.evidence_json={'source':'GOVERNED_MAPPING','actor':actor};row.updated_at=t
            s.commit();return {'vertical':vertical,'adapter_key':adapter_key,'supplier_id':supplier_id,'mapping_state':'ACTIVE'}

    def supplier_id(self,s,vertical,adapter_key):
        r=s.execute(select(JourneyRecoverySupplierIdentityMapRow).where(JourneyRecoverySupplierIdentityMapRow.vertical==vertical,JourneyRecoverySupplierIdentityMapRow.adapter_key==adapter_key,JourneyRecoverySupplierIdentityMapRow.mapping_state=='ACTIVE')).scalar_one_or_none()
        return r.supplier_id if r else None

    def assess_quality(self):
        with SessionLocal() as s:
            profiles=s.execute(select(JourneyRecoveryReliabilityProfileRow)).scalars().all();out=[];t=now()
            for p in profiles:
                ops=s.execute(select(JourneyRecoverySupplierOperationRow).where(JourneyRecoverySupplierOperationRow.vertical==p.vertical,JourneyRecoverySupplierOperationRow.adapter_key==p.adapter_key)).scalars().all()
                malformed=[o for o in ops if not o.supplier_idempotency_key or not o.execution_item_id]
                impossible=[o for o in ops if o.status=='CONFIRMED' and not o.supplier_confirmation_id]
                anomalies=len(malformed)+len(impossible);n=max(1,len(ops));rate=anomalies/n
                missing_mapping=self.supplier_id(s,p.vertical,p.adapter_key) is None
                contaminated=bool(rate>self.MAX_ANOMALY_RATE or impossible)
                state='QUARANTINED' if contaminated else ('INSUFFICIENT_DATA' if len(ops)<self.MIN_SAMPLES else ('MAPPING_REQUIRED' if missing_mapping else 'PASS'))
                action='QUARANTINE' if contaminated else ('HOLD_LEARNING' if state!='PASS' else 'ALLOW_LEARNING')
                a=JourneyRecoveryDataQualityAssessmentRow(data_quality_assessment_id=nid('jrdqa'),vertical=p.vertical,adapter_key=p.adapter_key,supplier_id=self.supplier_id(s,p.vertical,p.adapter_key),sample_count=len(ops),quality_state=state,contamination_detected=contaminated,anomaly_rate=rate,checks_json={'malformed_count':len(malformed),'confirmed_without_confirmation_id':len(impossible),'missing_supplier_mapping':missing_mapping,'min_samples':self.MIN_SAMPLES,'max_anomaly_rate':self.MAX_ANOMALY_RATE},action=action,created_at=t);s.add(a)
                if contaminated:
                    for o in impossible+malformed:
                        exists=s.execute(select(JourneyRecoverySampleQuarantineRow).where(JourneyRecoverySampleQuarantineRow.source_id==o.supplier_operation_id,JourneyRecoverySampleQuarantineRow.released==False)).scalar_one_or_none()
                        if not exists:s.add(JourneyRecoverySampleQuarantineRow(quarantine_id=nid('jrsq'),vertical=p.vertical,adapter_key=p.adapter_key,source_kind='SUPPLIER_OPERATION',source_id=o.supplier_operation_id,reason_code='DATA_QUALITY_ANOMALY',released=False,created_at=t))
                out.append({'vertical':p.vertical,'adapter_key':p.adapter_key,'quality_state':state,'sample_count':len(ops),'anomaly_rate':rate,'supplier_id':a.supplier_id,'action':action})
            s.commit();return out

    def latest_quality(self,s,vertical,adapter_key):
        return s.execute(select(JourneyRecoveryDataQualityAssessmentRow).where(JourneyRecoveryDataQualityAssessmentRow.vertical==vertical,JourneyRecoveryDataQualityAssessmentRow.adapter_key==adapter_key).order_by(JourneyRecoveryDataQualityAssessmentRow.created_at.desc())).scalars().first()

    def budget(self,s,scope_key):
        r=s.execute(select(JourneyRecoveryPrivacyBudgetRow).where(JourneyRecoveryPrivacyBudgetRow.scope_key==scope_key)).scalar_one_or_none();t=now()
        if not r:
            r=JourneyRecoveryPrivacyBudgetRow(privacy_budget_id=nid('jrpb'),scope_key=scope_key,epsilon_budget=self.DEFAULT_EPSILON,epsilon_used=0,release_count=0,state='AVAILABLE',reset_at=t+timedelta(days=30),governance_json={'engineering_privacy_budget':True,'not_differential_privacy_claim':True},updated_at=t);s.add(r);s.flush()
        return r
    def consume_privacy_budget(self,s,scope_key,cost=None):
        cost=float(cost or self.RELEASE_COST);r=self.budget(s,scope_key)
        if r.epsilon_used+cost>r.epsilon_budget:
            r.state='EXHAUSTED';r.updated_at=now();return False,r
        r.epsilon_used+=cost;r.release_count+=1;r.state='AVAILABLE' if r.epsilon_used<r.epsilon_budget else 'EXHAUSTED';r.updated_at=now();return True,r

    def set_kill_switch(self,scope_type,scope_key,enabled,actor,reason=None,change_control_authorized=False):
        if scope_type not in {'GLOBAL','VERTICAL','ADAPTER'}:raise ValueError('INVALID_KILL_SWITCH_SCOPE')
        with SessionLocal() as s:
            r=s.execute(select(JourneyRecoveryLearningKillSwitchRow).where(JourneyRecoveryLearningKillSwitchRow.scope_type==scope_type,JourneyRecoveryLearningKillSwitchRow.scope_key==scope_key)).scalar_one_or_none();t=now()
            if not r:r=JourneyRecoveryLearningKillSwitchRow(kill_switch_id=nid('jrlks'),scope_type=scope_type,scope_key=scope_key,enabled=False,updated_at=t);s.add(r);s.flush()
            if not enabled and r.enabled and not change_control_authorized:
                from go_hotel.db.models import JourneyRecoveryLearningIncidentRow
                incident=s.execute(select(JourneyRecoveryLearningIncidentRow).where(JourneyRecoveryLearningIncidentRow.kill_switch_id==r.kill_switch_id,JourneyRecoveryLearningIncidentRow.state!='CLOSED')).scalar_one_or_none()
                if incident:raise ValueError('LEARNING_INCIDENT_CHANGE_CONTROL_REQUIRED')
            r.enabled=enabled;r.reason=reason;r.updated_at=t
            if enabled:r.activated_by=actor;r.activated_at=t
            else:r.deactivated_by=actor;r.deactivated_at=t
            s.commit();return {'scope_type':scope_type,'scope_key':scope_key,'enabled':enabled,'reason':reason,'adaptive_effect':'BASELINE_ONLY' if enabled else 'NORMAL_GOVERNANCE'}

    def kill_switch_reason(self,s,vertical=None,adapter_key=None):
        checks=[('GLOBAL','*')]
        if vertical:checks.append(('VERTICAL',vertical))
        if adapter_key:checks.append(('ADAPTER',adapter_key))
        for typ,key in checks:
            r=s.execute(select(JourneyRecoveryLearningKillSwitchRow).where(JourneyRecoveryLearningKillSwitchRow.scope_type==typ,JourneyRecoveryLearningKillSwitchRow.scope_key==key,JourneyRecoveryLearningKillSwitchRow.enabled==True)).scalar_one_or_none()
            if r:return f'LEARNING_KILL_SWITCH:{typ}:{key}'
        return None
    def switches(self):
        with SessionLocal() as s:return [{'kill_switch_id':x.kill_switch_id,'scope_type':x.scope_type,'scope_key':x.scope_key,'enabled':x.enabled,'reason':x.reason,'activated_by':x.activated_by,'activated_at':x.activated_at.isoformat() if x.activated_at else None} for x in s.execute(select(JourneyRecoveryLearningKillSwitchRow).order_by(JourneyRecoveryLearningKillSwitchRow.updated_at.desc())).scalars().all()]
    def mappings(self):
        with SessionLocal() as s:return [{'vertical':x.vertical,'adapter_key':x.adapter_key,'supplier_id':x.supplier_id,'mapping_state':x.mapping_state} for x in s.execute(select(JourneyRecoverySupplierIdentityMapRow)).scalars().all()]
    def quality(self,limit=100):
        with SessionLocal() as s:return [{'data_quality_assessment_id':x.data_quality_assessment_id,'vertical':x.vertical,'adapter_key':x.adapter_key,'supplier_id':x.supplier_id,'sample_count':x.sample_count,'quality_state':x.quality_state,'contamination_detected':x.contamination_detected,'anomaly_rate':x.anomaly_rate,'checks':x.checks_json,'action':x.action} for x in s.execute(select(JourneyRecoveryDataQualityAssessmentRow).order_by(JourneyRecoveryDataQualityAssessmentRow.created_at.desc()).limit(limit)).scalars().all()]
    def privacy_budgets(self):
        with SessionLocal() as s:return [{'scope_key':x.scope_key,'epsilon_budget':x.epsilon_budget,'epsilon_used':x.epsilon_used,'release_count':x.release_count,'state':x.state,'reset_at':x.reset_at.isoformat() if x.reset_at else None,'governance':x.governance_json} for x in s.execute(select(JourneyRecoveryPrivacyBudgetRow)).scalars().all()]
    def quarantines(self,limit=100):
        with SessionLocal() as s:return [{'quarantine_id':x.quarantine_id,'vertical':x.vertical,'adapter_key':x.adapter_key,'source_kind':x.source_kind,'source_id':x.source_id,'reason_code':x.reason_code,'released':x.released} for x in s.execute(select(JourneyRecoverySampleQuarantineRow).order_by(JourneyRecoverySampleQuarantineRow.created_at.desc()).limit(limit)).scalars().all()]

recovery_data_governance_service=RecoveryDataGovernanceService()
