from __future__ import annotations
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    JourneyRecoveryReliabilityProfileRow, JourneyRecoveryStrategyVersionRow,
    JourneyRecoveryExperimentRow, JourneyRecoveryCalibrationProfileRow,
    JourneyRecoveryLearningRegistryRow, JourneyRecoveryProvenanceEdgeRow,
    JourneyRecoveryBenchmarkProfileRow, JourneyRecoveryDriftAssessmentRow,
)
from go_hotel.journey.recovery_data_governance import recovery_data_governance_service

def now(): return datetime.now(timezone.utc)
def aware(dt):
    if dt is None: return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'
def h(*parts): return sha256('|'.join(str(x or '') for x in parts).encode()).hexdigest()

class RecoveryLearningRegistryService:
    DEFAULT_TTL_DAYS=30
    DEFAULT_K=3
    DRIFT_THRESHOLDS={'confirmation_rate':0.10,'timeout_rate':0.08,'manual_review_rate':0.08}

    def rebuild_benchmarks(self, ttl_days:int=30, anonymization_k:int=3):
        with SessionLocal() as s:
            profiles=s.execute(select(JourneyRecoveryReliabilityProfileRow)).scalars().all()
            groups={}
            for p in profiles:
                mapping=recovery_data_governance_service.supplier_id(s,p.vertical,p.adapter_key)
                quality=recovery_data_governance_service.latest_quality(s,p.vertical,p.adapter_key)
                if quality and quality.quality_state in {'QUARANTINED','INSUFFICIENT_DATA'}:
                    continue
                # Backward-compatible engineering proxy until a governed supplier mapping exists.
                # 3P quality metadata makes the distinction explicit; production publication should require governed mappings.
                groups.setdefault(p.vertical,[]).append((p,mapping or p.adapter_key))
            out=[];t=now()
            for vertical,rows in groups.items():
                supplier_ids={supplier_id for _,supplier_id in rows};supplier_count=len(supplier_ids);sample_count=sum(p.sample_count for p,_ in rows)
                cohort=f'{vertical}:governed-suppliers';scope=f'benchmark:{vertical}'
                privacy_ok,budget=recovery_data_governance_service.consume_privacy_budget(s,scope)
                state='AVAILABLE' if supplier_count>=max(2,anonymization_k) and privacy_ok else ('WITHHELD_PRIVACY_BUDGET' if not privacy_ok else 'WITHHELD_K_ANONYMITY')
                metrics={} if state!='AVAILABLE' else {
                    'confirmation_rate':sum(p.confirmation_rate*p.sample_count for p,_ in rows)/max(1,sample_count),
                    'timeout_rate':sum(p.timeout_rate*p.sample_count for p,_ in rows)/max(1,sample_count),
                    'manual_review_rate':sum(p.manual_review_rate*p.sample_count for p,_ in rows)/max(1,sample_count),
                }
                bid=f'benchmark:{vertical}:{t.date().isoformat()}'
                vals=dict(vertical=vertical,cohort_key=cohort,supplier_count=supplier_count,sample_count=sample_count,anonymization_k=max(2,anonymization_k),benchmark_metrics_json=metrics,confidence_json={'supplier_count':supplier_count,'sample_count':sample_count,'k_anonymity_satisfied':supplier_count>=max(2,anonymization_k),'privacy_budget_state':budget.state,'epsilon_used':budget.epsilon_used,'supplier_identity_governed':all(recovery_data_governance_service.supplier_id(s,vertical,p.adapter_key) is not None for p,_ in rows)},state=state,calculated_at=t,valid_until=t+timedelta(days=max(1,ttl_days)))
                row=s.get(JourneyRecoveryBenchmarkProfileRow,bid)
                if not row: row=JourneyRecoveryBenchmarkProfileRow(benchmark_profile_id=bid,**vals);s.add(row)
                else:
                    for k,v in vals.items():setattr(row,k,v)
                out.append({'benchmark_profile_id':bid,'vertical':vertical,'supplier_count':supplier_count,'sample_count':sample_count,'state':state,'metrics':metrics,'privacy_budget_state':budget.state})
            s.commit();return out

    def _latest_experiment_for_calibration(self,s,cal):
        return s.get(JourneyRecoveryExperimentRow,cal.source_experiment_id) if cal and cal.source_experiment_id else None

    def rebuild_registry(self, ttl_days:int=30):
        with SessionLocal() as s:
            cals=s.execute(select(JourneyRecoveryCalibrationProfileRow)).scalars().all();t=now();out=[]
            for cal in cals:
                rel=s.execute(select(JourneyRecoveryReliabilityProfileRow).where(JourneyRecoveryReliabilityProfileRow.vertical==cal.vertical,JourneyRecoveryReliabilityProfileRow.adapter_key==cal.adapter_key).order_by(JourneyRecoveryReliabilityProfileRow.calculated_at.desc())).scalars().first()
                exp=self._latest_experiment_for_calibration(s,cal)
                strategy=s.get(JourneyRecoveryStrategyVersionRow,exp.candidate_strategy_version_id) if exp else None
                bench=s.execute(select(JourneyRecoveryBenchmarkProfileRow).where(JourneyRecoveryBenchmarkProfileRow.vertical==cal.vertical,JourneyRecoveryBenchmarkProfileRow.state=='AVAILABLE').order_by(JourneyRecoveryBenchmarkProfileRow.calculated_at.desc())).scalars().first()
                rid=f'jrlr_{sha256((cal.vertical+"|"+cal.adapter_key).encode()).hexdigest()[:24]}'
                valid_until=aware(cal.updated_at)+timedelta(days=max(1,ttl_days));fresh='FRESH' if valid_until>t else 'STALE';reval=fresh!='FRESH'
                prov=h(rel.reliability_profile_id if rel else '',strategy.strategy_version_id if strategy else '',exp.experiment_id if exp else '',cal.calibration_profile_id,bench.benchmark_profile_id if bench else '',cal.updated_at.isoformat())
                row=s.get(JourneyRecoveryLearningRegistryRow,rid)
                vals=dict(vertical=cal.vertical,adapter_key=cal.adapter_key,reliability_profile_id=rel.reliability_profile_id if rel else None,strategy_version_id=strategy.strategy_version_id if strategy else None,experiment_id=exp.experiment_id if exp else None,calibration_profile_id=cal.calibration_profile_id,benchmark_profile_id=bench.benchmark_profile_id if bench else None,state='REVALIDATION_REQUIRED' if reval else 'VALID',freshness_state=fresh,valid_until=valid_until,revalidation_required=reval,provenance_hash=prov,governance_json={'calibration_state':cal.state,'ttl_days':ttl_days,'supplier_fact_unchanged':True},updated_at=t)
                if not row: row=JourneyRecoveryLearningRegistryRow(learning_registry_id=rid,created_at=t,**vals);s.add(row)
                else:
                    for k,v in vals.items(): setattr(row,k,v)
                s.flush();s.query(JourneyRecoveryProvenanceEdgeRow).filter(JourneyRecoveryProvenanceEdgeRow.learning_registry_id==rid).delete(synchronize_session=False)
                nodes=[]
                if rel:nodes.append(('RELIABILITY_PROFILE',rel.reliability_profile_id))
                if strategy:nodes.append(('STRATEGY_VERSION',strategy.strategy_version_id))
                if exp:nodes.append(('EXPERIMENT',exp.experiment_id))
                nodes.append(('CALIBRATION_PROFILE',cal.calibration_profile_id))
                if bench:nodes.append(('BENCHMARK_PROFILE',bench.benchmark_profile_id))
                nodes.append(('LEARNING_REGISTRY',rid))
                for i in range(len(nodes)-1):
                    fk,fid=nodes[i];tk,tid=nodes[i+1];s.add(JourneyRecoveryProvenanceEdgeRow(provenance_edge_id=nid('jrpe'),learning_registry_id=rid,from_kind=fk,from_id=fid,to_kind=tk,to_id=tid,relation='DERIVES_OR_GOVERNS',edge_hash=h(rid,fk,fid,tk,tid),created_at=t))
                out.append({'learning_registry_id':rid,'vertical':cal.vertical,'adapter_key':cal.adapter_key,'state':row.state,'freshness_state':fresh,'valid_until':valid_until.isoformat(),'revalidation_required':reval,'provenance_hash':prov})
            s.commit();return out

    def assess_drift(self):
        with SessionLocal() as s:
            regs=s.execute(select(JourneyRecoveryLearningRegistryRow)).scalars().all();t=now();out=[]
            for reg in regs:
                cal=s.get(JourneyRecoveryCalibrationProfileRow,reg.calibration_profile_id) if reg.calibration_profile_id else None
                rel=s.get(JourneyRecoveryReliabilityProfileRow,reg.reliability_profile_id) if reg.reliability_profile_id else None
                if not cal or not rel: continue
                base=cal.calibrated_parameters_json or {};current={'confirmation_rate':rel.confirmation_rate,'timeout_rate':rel.timeout_rate,'manual_review_rate':rel.manual_review_rate}
                deltas={k:abs(float(current.get(k,0))-float(base.get('observed_'+k,base.get(k,0)) or 0)) for k in self.DRIFT_THRESHOLDS}
                breaches={k:v>self.DRIFT_THRESHOLDS[k] for k,v in deltas.items()};drift=any(breaches.values())
                severity='HIGH' if sum(breaches.values())>=2 else ('MEDIUM' if drift else 'LOW');action='REVALIDATE' if drift else 'NONE'
                d=JourneyRecoveryDriftAssessmentRow(drift_assessment_id=nid('jrda'),learning_registry_id=reg.learning_registry_id,vertical=reg.vertical,adapter_key=reg.adapter_key,baseline_window_json={'source':'CALIBRATION','profile_id':cal.calibration_profile_id,'metrics':base},current_window_json={'source':'RELIABILITY_MEMORY','profile_id':rel.reliability_profile_id,'metrics':current},drift_metrics_json={'absolute_deltas':deltas,'thresholds':self.DRIFT_THRESHOLDS,'breaches':breaches},drift_detected=drift,severity=severity,action=action,supplier_fact_unchanged=True,created_at=t);s.add(d)
                expired=bool(reg.valid_until and aware(reg.valid_until)<=t)
                if drift or expired:
                    reg.state='REVALIDATION_REQUIRED';reg.revalidation_required=True;reg.freshness_state='EXPIRED' if expired else 'DRIFTED';reg.updated_at=t
                out.append({'learning_registry_id':reg.learning_registry_id,'vertical':reg.vertical,'adapter_key':reg.adapter_key,'drift_detected':drift,'severity':severity,'action':action,'expired':expired,'supplier_fact_unchanged':True})
            s.commit();return out

    def revalidate(self,registry_id:str,actor:str):
        with SessionLocal() as s:
            reg=s.get(JourneyRecoveryLearningRegistryRow,registry_id)
            if not reg: raise ValueError('LEARNING_REGISTRY_NOT_FOUND')
            cal=s.get(JourneyRecoveryCalibrationProfileRow,reg.calibration_profile_id) if reg.calibration_profile_id else None
            if not cal or cal.state!='CALIBRATED': raise ValueError('CALIBRATION_NOT_ELIGIBLE_FOR_REVALIDATION')
            reg.state='VALID';reg.freshness_state='FRESH';reg.revalidation_required=False;reg.valid_until=now()+timedelta(days=self.DEFAULT_TTL_DAYS);reg.updated_at=now();g=dict(reg.governance_json or {});g.update({'last_revalidated_by':actor,'last_revalidated_at':now().isoformat(),'supplier_fact_unchanged':True});reg.governance_json=g;s.commit();return {'learning_registry_id':registry_id,'state':'VALID','valid_until':reg.valid_until.isoformat(),'supplier_fact_unchanged':True}

    def list_registry(self):
        with SessionLocal() as s:return [{'learning_registry_id':x.learning_registry_id,'vertical':x.vertical,'adapter_key':x.adapter_key,'state':x.state,'freshness_state':x.freshness_state,'valid_until':x.valid_until.isoformat() if x.valid_until else None,'revalidation_required':x.revalidation_required,'reliability_profile_id':x.reliability_profile_id,'strategy_version_id':x.strategy_version_id,'experiment_id':x.experiment_id,'calibration_profile_id':x.calibration_profile_id,'benchmark_profile_id':x.benchmark_profile_id,'provenance_hash':x.provenance_hash} for x in s.execute(select(JourneyRecoveryLearningRegistryRow).order_by(JourneyRecoveryLearningRegistryRow.updated_at.desc())).scalars().all()]
    def graph(self,registry_id:str):
        with SessionLocal() as s:
            r=s.get(JourneyRecoveryLearningRegistryRow,registry_id)
            if not r: raise ValueError('LEARNING_REGISTRY_NOT_FOUND')
            edges=s.execute(select(JourneyRecoveryProvenanceEdgeRow).where(JourneyRecoveryProvenanceEdgeRow.learning_registry_id==registry_id).order_by(JourneyRecoveryProvenanceEdgeRow.created_at)).scalars().all()
            return {'learning_registry_id':registry_id,'provenance_hash':r.provenance_hash,'edges':[{'from_kind':e.from_kind,'from_id':e.from_id,'to_kind':e.to_kind,'to_id':e.to_id,'relation':e.relation,'edge_hash':e.edge_hash} for e in edges]}
    def benchmarks(self):
        with SessionLocal() as s:return [{'benchmark_profile_id':x.benchmark_profile_id,'vertical':x.vertical,'cohort_key':x.cohort_key,'supplier_count':x.supplier_count,'sample_count':x.sample_count,'anonymization_k':x.anonymization_k,'state':x.state,'metrics':x.benchmark_metrics_json,'confidence':x.confidence_json,'valid_until':x.valid_until.isoformat()} for x in s.execute(select(JourneyRecoveryBenchmarkProfileRow).order_by(JourneyRecoveryBenchmarkProfileRow.calculated_at.desc())).scalars().all()]
    def drift_history(self,limit=100):
        with SessionLocal() as s:return [{'drift_assessment_id':x.drift_assessment_id,'learning_registry_id':x.learning_registry_id,'vertical':x.vertical,'adapter_key':x.adapter_key,'drift_detected':x.drift_detected,'severity':x.severity,'action':x.action,'metrics':x.drift_metrics_json,'supplier_fact_unchanged':x.supplier_fact_unchanged} for x in s.execute(select(JourneyRecoveryDriftAssessmentRow).order_by(JourneyRecoveryDriftAssessmentRow.created_at.desc()).limit(limit)).scalars().all()]

recovery_learning_registry_service=RecoveryLearningRegistryService()
