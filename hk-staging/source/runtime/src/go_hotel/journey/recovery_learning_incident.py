from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
from json import dumps
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    JourneyRecoveryLearningIncidentRow, JourneyRecoveryRollbackSnapshotRow,
    JourneyRecoveryLearningChangeRequestRow, JourneyRecoveryLearningIncidentEventRow,
    JourneyRecoveryLearningKillSwitchRow, JourneyRecoveryStrategyVersionRow,
    JourneyRecoveryExperimentRow, JourneyRecoveryCalibrationProfileRow,
    JourneyRecoveryLearningRegistryRow,
)
from go_hotel.journey.recovery_data_governance import recovery_data_governance_service as dg
from go_hotel.journey.recovery_strategy_governance import BASE

def now(): return datetime.now(timezone.utc)
def nid(p): return f'{p}_{uuid4().hex[:18]}'
def utc(v):
    if v is None:return None
    return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)
def h(obj): return sha256(dumps(obj,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()

class RecoveryLearningIncidentService:
    VALID_SCOPES={'GLOBAL','VERTICAL','ADAPTER'}
    VALID_SEVERITY={'SEV1','SEV2','SEV3','SEV4'}

    def _event(self,s,incident_id,event_type,actor,payload=None):
        s.add(JourneyRecoveryLearningIncidentEventRow(event_id=nid('jrlie'),incident_id=incident_id,event_type=event_type,actor_id=actor,payload_json=payload or {},supplier_fact_unchanged=True,created_at=now()))

    def _affected_registries(self,s,scope_type,scope_key):
        q=select(JourneyRecoveryLearningRegistryRow)
        if scope_type=='VERTICAL':q=q.where(JourneyRecoveryLearningRegistryRow.vertical==scope_key)
        elif scope_type=='ADAPTER':q=q.where(JourneyRecoveryLearningRegistryRow.adapter_key==scope_key)
        return s.execute(q).scalars().all()

    def _snapshot(self,s,incident,actor):
        regs=self._affected_registries(s,incident.scope_type,incident.scope_key)
        strategy_ids=sorted({x.strategy_version_id for x in regs if x.strategy_version_id})
        experiment_ids=sorted({x.experiment_id for x in regs if x.experiment_id})
        calibration_ids=sorted({x.calibration_profile_id for x in regs if x.calibration_profile_id})
        strategies=[s.get(JourneyRecoveryStrategyVersionRow,x) for x in strategy_ids]
        experiments=[s.get(JourneyRecoveryExperimentRow,x) for x in experiment_ids]
        calibrations=[s.get(JourneyRecoveryCalibrationProfileRow,x) for x in calibration_ids]
        st=[{'id':x.strategy_version_id,'state':x.state,'rollout_percent':x.rollout_percent,'approved_by':x.approved_by,'activated_at':x.activated_at.isoformat() if x.activated_at else None} for x in strategies if x]
        ex=[{'id':x.experiment_id,'state':x.state,'control':x.control_strategy_version_id,'candidate':x.candidate_strategy_version_id,'allocation_percent':x.allocation_percent} for x in experiments if x]
        ca=[{'id':x.calibration_profile_id,'vertical':x.vertical,'adapter_key':x.adapter_key,'state':x.state,'parameters':x.calibrated_parameters_json} for x in calibrations if x]
        rg=[{'id':x.learning_registry_id,'vertical':x.vertical,'adapter_key':x.adapter_key,'state':x.state,'freshness_state':x.freshness_state,'revalidation_required':x.revalidation_required,'provenance_hash':x.provenance_hash} for x in regs]
        body={'baseline':dict(BASE),'strategies':st,'experiments':ex,'calibrations':ca,'registries':rg}
        snap=JourneyRecoveryRollbackSnapshotRow(rollback_snapshot_id=nid('jrrs'),incident_id=incident.incident_id,scope_type=incident.scope_type,scope_key=incident.scope_key,baseline_parameters_json=dict(BASE),strategy_snapshot_json=st,experiment_snapshot_json=ex,calibration_snapshot_json=ca,learning_registry_snapshot_json=rg,snapshot_hash=h(body),created_by=actor,created_at=now());s.add(snap);s.flush()
        incident.rollback_snapshot_id=snap.rollback_snapshot_id
        incident.affected_objects_json={'strategy_version_ids':strategy_ids,'experiment_ids':experiment_ids,'calibration_profile_ids':calibration_ids,'learning_registry_ids':[x.learning_registry_id for x in regs]}
        return snap

    def open_incident(self,scope_type,scope_key,severity,reason,actor):
        if scope_type not in self.VALID_SCOPES:raise ValueError('INVALID_INCIDENT_SCOPE')
        if severity not in self.VALID_SEVERITY:raise ValueError('INVALID_INCIDENT_SEVERITY')
        if scope_type=='GLOBAL':scope_key='*'
        with SessionLocal() as s:
            existing=s.execute(select(JourneyRecoveryLearningIncidentRow).where(JourneyRecoveryLearningIncidentRow.scope_type==scope_type,JourneyRecoveryLearningIncidentRow.scope_key==scope_key,JourneyRecoveryLearningIncidentRow.state.notin_(['CLOSED']))).scalar_one_or_none()
            if existing:raise ValueError('OPEN_LEARNING_INCIDENT_ALREADY_EXISTS')
            t=now();inc=JourneyRecoveryLearningIncidentRow(incident_id=nid('jrli'),scope_type=scope_type,scope_key=scope_key,severity=severity,state='OPEN',reason=reason,opened_by=actor,opened_at=t,affected_objects_json={},postmortem_evidence_json={},created_at=t,updated_at=t);s.add(inc);s.flush();snap=self._snapshot(s,inc,actor);self._event(s,inc.incident_id,'INCIDENT_OPENED',actor,{'reason':reason,'severity':severity,'snapshot_hash':snap.snapshot_hash});s.commit();iid=inc.incident_id
        dg.set_kill_switch(scope_type,scope_key,True,actor,f'INCIDENT:{iid}:{reason}')
        with SessionLocal() as s:
            inc=s.get(JourneyRecoveryLearningIncidentRow,iid);ks=s.execute(select(JourneyRecoveryLearningKillSwitchRow).where(JourneyRecoveryLearningKillSwitchRow.scope_type==scope_type,JourneyRecoveryLearningKillSwitchRow.scope_key==scope_key)).scalar_one();inc.kill_switch_id=ks.kill_switch_id;inc.state='BASELINE_ONLY';inc.updated_at=now();self._event(s,iid,'KILL_SWITCH_ACTIVATED',actor,{'kill_switch_id':ks.kill_switch_id,'effect':'BASELINE_ONLY'});s.commit();return self.get(iid)

    def add_postmortem(self,incident_id,evidence_reference,summary,root_cause,corrective_actions,actor):
        if not evidence_reference or not summary or not root_cause:raise ValueError('POSTMORTEM_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            inc=s.get(JourneyRecoveryLearningIncidentRow,incident_id)
            if not inc:raise ValueError('LEARNING_INCIDENT_NOT_FOUND')
            if inc.state=='CLOSED':raise ValueError('INCIDENT_ALREADY_CLOSED')
            inc.postmortem_evidence_json={'evidence_reference':evidence_reference,'summary':summary,'root_cause':root_cause,'corrective_actions':corrective_actions or [],'recorded_by':actor,'recorded_at':now().isoformat()};inc.state='POSTMORTEM_READY';inc.updated_at=now();self._event(s,incident_id,'POSTMORTEM_EVIDENCE_ATTACHED',actor,inc.postmortem_evidence_json);s.commit();return self.get(incident_id)

    def request_resume(self,incident_id,window_start,window_end,resume_plan,actor):
        ws, we=utc(window_start),utc(window_end)
        if not ws or not we or we<=ws:raise ValueError('INVALID_CHANGE_WINDOW')
        with SessionLocal() as s:
            inc=s.get(JourneyRecoveryLearningIncidentRow,incident_id)
            if not inc:raise ValueError('LEARNING_INCIDENT_NOT_FOUND')
            if not inc.postmortem_evidence_json:raise ValueError('POSTMORTEM_REQUIRED_BEFORE_RESUME')
            if inc.state=='CLOSED':raise ValueError('INCIDENT_ALREADY_CLOSED')
            scope={'scope_type':inc.scope_type,'scope_key':inc.scope_key}
            cr=JourneyRecoveryLearningChangeRequestRow(change_request_id=nid('jrlcr'),incident_id=incident_id,change_type='RESUME_LEARNING',state='PENDING_APPROVAL',requested_scope_json=scope,resume_plan_json=resume_plan or {},change_window_start=ws,change_window_end=we,requested_by=actor,requested_at=now(),execution_result_json={},supplier_fact_unchanged=True);s.add(cr);inc.state='RESUME_PENDING_APPROVAL';inc.updated_at=now();self._event(s,incident_id,'RESUME_CHANGE_REQUESTED',actor,{'change_request_id':cr.change_request_id,'change_window_start':ws.isoformat(),'change_window_end':we.isoformat(),'resume_plan':resume_plan or {}});s.commit();return self.change(cr.change_request_id)

    def approve_resume(self,change_request_id,actor):
        with SessionLocal() as s:
            cr=s.get(JourneyRecoveryLearningChangeRequestRow,change_request_id)
            if not cr:raise ValueError('CHANGE_REQUEST_NOT_FOUND')
            inc=s.get(JourneyRecoveryLearningIncidentRow,cr.incident_id)
            if cr.state!='PENDING_APPROVAL':raise ValueError('CHANGE_REQUEST_NOT_PENDING_APPROVAL')
            if actor in {cr.requested_by,inc.opened_by}:raise ValueError('MAKER_CHECKER_DISTINCT_ACTOR_REQUIRED')
            cr.state='APPROVED';cr.approved_by=actor;cr.approved_at=now();inc.approved_resume_change_id=cr.change_request_id;inc.state='RESUME_APPROVED';inc.updated_at=now();self._event(s,inc.incident_id,'RESUME_APPROVED',actor,{'change_request_id':cr.change_request_id});s.commit();return self.change(change_request_id)

    def execute_resume(self,change_request_id,actor,at=None):
        t=utc(at or now())
        with SessionLocal() as s:
            cr=s.get(JourneyRecoveryLearningChangeRequestRow,change_request_id)
            if not cr:raise ValueError('CHANGE_REQUEST_NOT_FOUND')
            inc=s.get(JourneyRecoveryLearningIncidentRow,cr.incident_id)
            if cr.state!='APPROVED':raise ValueError('APPROVED_CHANGE_REQUIRED')
            if not (utc(cr.change_window_start)<=t<=utc(cr.change_window_end)):raise ValueError('OUTSIDE_APPROVED_CHANGE_WINDOW')
            if not inc.postmortem_evidence_json:raise ValueError('POSTMORTEM_REQUIRED_BEFORE_RESUME')
            plan=cr.resume_plan_json or {};remaining=plan.get('remaining_block_scopes') or []
            scope_type,scope_key=inc.scope_type,inc.scope_key
        # Activate narrower safety blocks first, then release incident switch.
        for b in remaining:
            typ=b.get('scope_type');key=b.get('scope_key')
            if typ in self.VALID_SCOPES and key:dg.set_kill_switch(typ,key,True,actor,f'STAGED_RESUME:{inc.incident_id}')
        dg.set_kill_switch(scope_type,scope_key,False,actor,f'APPROVED_RESUME:{inc.incident_id}',change_control_authorized=True)
        with SessionLocal() as s:
            cr=s.get(JourneyRecoveryLearningChangeRequestRow,change_request_id);inc=s.get(JourneyRecoveryLearningIncidentRow,cr.incident_id)
            cr.state='EXECUTED';cr.executed_by=actor;cr.executed_at=t;cr.execution_result_json={'released_scope':{'scope_type':inc.scope_type,'scope_key':inc.scope_key},'remaining_block_scopes':remaining,'adaptive_effect':'STAGED_GOVERNANCE' if remaining else 'NORMAL_GOVERNANCE'}
            inc.state='MONITORING_AFTER_RESUME';inc.updated_at=now();self._event(s,inc.incident_id,'RESUME_EXECUTED',actor,cr.execution_result_json);s.commit();return self.change(change_request_id)

    def close_incident(self,incident_id,actor,closure_evidence_reference):
        if not closure_evidence_reference:raise ValueError('CLOSURE_EVIDENCE_REQUIRED')
        with SessionLocal() as s:
            inc=s.get(JourneyRecoveryLearningIncidentRow,incident_id)
            if not inc:raise ValueError('LEARNING_INCIDENT_NOT_FOUND')
            if inc.state!='MONITORING_AFTER_RESUME':raise ValueError('INCIDENT_NOT_READY_TO_CLOSE')
            cr=s.get(JourneyRecoveryLearningChangeRequestRow,inc.approved_resume_change_id) if inc.approved_resume_change_id else None
            if not cr or cr.state!='EXECUTED':raise ValueError('EXECUTED_RESUME_CHANGE_REQUIRED')
            inc.state='CLOSED';inc.closed_by=actor;inc.closed_at=now();inc.updated_at=now();e=dict(inc.postmortem_evidence_json or {});e['closure_evidence_reference']=closure_evidence_reference;e['closed_by']=actor;e['closed_at']=inc.closed_at.isoformat();inc.postmortem_evidence_json=e;self._event(s,incident_id,'INCIDENT_CLOSED',actor,{'closure_evidence_reference':closure_evidence_reference});s.commit();return self.get(incident_id)

    def get(self,incident_id):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryLearningIncidentRow,incident_id)
            if not x:raise ValueError('LEARNING_INCIDENT_NOT_FOUND')
            ev=s.execute(select(JourneyRecoveryLearningIncidentEventRow).where(JourneyRecoveryLearningIncidentEventRow.incident_id==incident_id).order_by(JourneyRecoveryLearningIncidentEventRow.created_at)).scalars().all()
            snap=s.get(JourneyRecoveryRollbackSnapshotRow,x.rollback_snapshot_id) if x.rollback_snapshot_id else None
            return {'incident_id':x.incident_id,'scope_type':x.scope_type,'scope_key':x.scope_key,'severity':x.severity,'state':x.state,'reason':x.reason,'opened_by':x.opened_by,'opened_at':x.opened_at.isoformat(),'kill_switch_id':x.kill_switch_id,'rollback_snapshot':({'rollback_snapshot_id':snap.rollback_snapshot_id,'snapshot_hash':snap.snapshot_hash,'baseline_parameters':snap.baseline_parameters_json,'strategy_snapshot':snap.strategy_snapshot_json,'experiment_snapshot':snap.experiment_snapshot_json,'calibration_snapshot':snap.calibration_snapshot_json} if snap else None),'affected_objects':x.affected_objects_json,'postmortem_evidence':x.postmortem_evidence_json,'approved_resume_change_id':x.approved_resume_change_id,'events':[{'event_type':e.event_type,'actor_id':e.actor_id,'payload':e.payload_json,'supplier_fact_unchanged':e.supplier_fact_unchanged,'created_at':e.created_at.isoformat()} for e in ev]}

    def list(self,limit=100):
        with SessionLocal() as s:
            rows=s.execute(select(JourneyRecoveryLearningIncidentRow).order_by(JourneyRecoveryLearningIncidentRow.opened_at.desc()).limit(limit)).scalars().all();return [{'incident_id':x.incident_id,'scope_type':x.scope_type,'scope_key':x.scope_key,'severity':x.severity,'state':x.state,'reason':x.reason,'opened_by':x.opened_by,'opened_at':x.opened_at.isoformat(),'approved_resume_change_id':x.approved_resume_change_id} for x in rows]

    def change(self,change_request_id):
        with SessionLocal() as s:
            x=s.get(JourneyRecoveryLearningChangeRequestRow,change_request_id)
            if not x:raise ValueError('CHANGE_REQUEST_NOT_FOUND')
            return {'change_request_id':x.change_request_id,'incident_id':x.incident_id,'state':x.state,'requested_scope':x.requested_scope_json,'resume_plan':x.resume_plan_json,'change_window_start':x.change_window_start.isoformat(),'change_window_end':x.change_window_end.isoformat(),'requested_by':x.requested_by,'approved_by':x.approved_by,'executed_by':x.executed_by,'execution_result':x.execution_result_json,'supplier_fact_unchanged':x.supplier_fact_unchanged}

recovery_learning_incident_service=RecoveryLearningIncidentService()
