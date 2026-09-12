from datetime import datetime, timezone
import hashlib, json, uuid
from sqlalchemy import select, func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (ProductionConnectorRow, ConnectorCapabilityMatrixRow,
 ConnectorAuthorityRow, ConnectorCredentialReferenceRow, ConnectorCertificationRunRow,
 ConnectorRuntimeHealthRow, ConnectorLiveGateAssessmentRow, ConnectorActivationChangeRow,
 ConnectorKillSwitchRow, ConnectorGovernanceEventRow)

VERTICALS={'PAYMENT','HOTEL','FLIGHT','RAIL','MOBILITY','CAR_RENTAL','ATTRACTION','IDENTITY','PUSH','MONITORING'}
LIFECYCLE=('ENGINEERING','CONNECTABLE','CERTIFIABLE','CERTIFIED','OBSERVABLE','SWITCHABLE','LIVE')
TERMINAL={'SUSPENDED','REVOKED'}
REQUIRED_CAPABILITIES={'idempotency','signed_webhook','query_by_idempotency','reconciliation','telemetry','kill_switch','rollback'}
REQUIRED_CERT_CHECKS={'connectivity','idempotency','signed_webhook','query_by_idempotency','reconciliation','refund','settlement'}
POLICY_VERSION='PRODUCTION_LIVE_GATE_V1'

def now(): return datetime.now(timezone.utc)
def ident(prefix): return f'{prefix}_{uuid.uuid4().hex}'
def digest(value): return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def out(row): return {c.name:(getattr(row,c.name).isoformat() if isinstance(getattr(row,c.name),datetime) else getattr(row,c.name)) for c in row.__table__.columns}

class ProductionConnectorService:
 def _event(self,s,connector_id,event,actor,payload):
  s.add(ConnectorGovernanceEventRow(connector_governance_event_id=ident('cge'),connector_id=connector_id,event_type=event,payload_json=payload,payload_hash=digest(payload),actor_id=actor,created_at=now()))
 def _connector(self,s,connector_id):
  row=s.get(ProductionConnectorRow,connector_id)
  if not row: raise ValueError('CONNECTOR_NOT_FOUND')
  return row
 def register(self,b,actor):
  vertical=b['vertical'].upper(); environment=b.get('environment','ENGINEERING').upper()
  if vertical not in VERTICALS: raise ValueError('UNSUPPORTED_CONNECTOR_VERTICAL')
  if environment not in {'ENGINEERING','SANDBOX','PRODUCTION'}: raise ValueError('INVALID_CONNECTOR_ENVIRONMENT')
  if not b.get('supplier_legal_name'): raise ValueError('FORMAL_SUPPLIER_IDENTITY_REQUIRED')
  with SessionLocal() as s:
   row=ProductionConnectorRow(connector_id=ident('conn'),connector_key=b['connector_key'],display_name=b['display_name'],vertical=vertical,supplier_legal_name=b['supplier_legal_name'],environment=environment,lifecycle_state='ENGINEERING',active_capability_version=1,created_by=actor,created_at=now(),updated_at=now())
   s.add(row); self._event(s,row.connector_id,'CONNECTOR_REGISTERED',actor,{'environment':environment,'vertical':vertical}); s.commit(); return out(row)
 def bind_capabilities(self,connector_id,b,actor):
  capabilities=b.get('capabilities',{})
  with SessionLocal() as s:
   row=self._connector(s,connector_id); version=(s.scalar(select(func.max(ConnectorCapabilityMatrixRow.version_no)).where(ConnectorCapabilityMatrixRow.connector_id==connector_id)) or 0)+1
   matrix=ConnectorCapabilityMatrixRow(capability_matrix_id=ident('ccm'),connector_id=connector_id,version_no=version,capabilities_json=capabilities,content_hash=digest(capabilities),created_at=now()); s.add(matrix); row.active_capability_version=version
   if row.lifecycle_state=='ENGINEERING' and REQUIRED_CAPABILITIES<=set(k for k,v in capabilities.items() if v): row.lifecycle_state='CONNECTABLE'
   row.updated_at=now(); self._event(s,connector_id,'CAPABILITY_MATRIX_BOUND',actor,{'version':version,'lifecycle_state':row.lifecycle_state}); s.commit(); return {'connector':out(row),'capability_matrix':out(matrix)}
 def bind_authority(self,connector_id,b,actor):
  if not b.get('contract_reference') or not b.get('evidence'): raise ValueError('CONTRACT_AND_AUTHORITY_EVIDENCE_REQUIRED')
  with SessionLocal() as s:
   row=self._connector(s,connector_id); authority=ConnectorAuthorityRow(connector_authority_id=ident('cauth'),connector_id=connector_id,contract_reference=b['contract_reference'],authority_scope_json=b.get('authority_scope',[]),evidence_json=b['evidence'],valid_from=now(),valid_to=None,state='ACTIVE'); s.add(authority)
   self._event(s,connector_id,'CONTRACT_AUTHORITY_BOUND',actor,{'authority_id':authority.connector_authority_id}); s.commit(); return out(authority)
 def bind_credential(self,connector_id,b,actor):
  ref=b.get('secret_reference','')
  if not ref.startswith(('vault://','aws-secrets://','gcp-secrets://','azure-keyvault://')): raise ValueError('EXTERNAL_SECRET_REFERENCE_REQUIRED')
  if any(x in b for x in ('secret','api_key','password','private_key')): raise ValueError('INLINE_SECRET_FORBIDDEN')
  with SessionLocal() as s:
   self._connector(s,connector_id); row=ConnectorCredentialReferenceRow(credential_reference_id=ident('cref'),connector_id=connector_id,credential_kind=b['credential_kind'],secret_reference=ref,key_fingerprint=b.get('key_fingerprint'),expires_at=b.get('expires_at'),state='ACTIVE',updated_at=now()); s.add(row); self._event(s,connector_id,'CREDENTIAL_REFERENCE_BOUND',actor,{'credential_kind':row.credential_kind}); s.commit(); return out(row)
 def record_certification(self,connector_id,b,actor):
  environment=b['environment'].upper(); checks=b.get('checks',{}); evidence=b.get('evidence',[])
  if environment not in {'SANDBOX','PRODUCTION'}: raise ValueError('CERTIFICATION_ENVIRONMENT_REQUIRED')
  result='PASS' if REQUIRED_CERT_CHECKS<=set(k for k,v in checks.items() if v) and evidence else 'FAIL'
  with SessionLocal() as s:
   row=self._connector(s,connector_id); run=ConnectorCertificationRunRow(certification_run_id=ident('cert'),connector_id=connector_id,environment=environment,suite_version=b.get('suite_version','v1'),result=result,checks_json=checks,evidence_json=evidence,evidence_hash=digest({'checks':checks,'evidence':evidence}),executed_by=actor,completed_at=now()); s.add(run)
   if result=='PASS' and environment=='SANDBOX' and row.lifecycle_state in {'CONNECTABLE','CERTIFIABLE'}: row.lifecycle_state='CERTIFIABLE'
   if result=='PASS' and environment=='PRODUCTION' and row.lifecycle_state=='CERTIFIABLE': row.lifecycle_state='CERTIFIED'
   row.updated_at=now(); self._event(s,connector_id,'CERTIFICATION_RECORDED',actor,{'environment':environment,'result':result}); s.commit(); return {'connector':out(row),'certification':out(run)}
 def bind_health(self,connector_id,b,actor):
  telemetry=b.get('telemetry_binding',{}); slo=b.get('slo',{})
  if not telemetry.get('dashboard') or not telemetry.get('alert_policy') or not slo: raise ValueError('TELEMETRY_AND_SLO_REQUIRED')
  with SessionLocal() as s:
   row=self._connector(s,connector_id); health=s.get(ConnectorRuntimeHealthRow,connector_id)
   values={'health_state':b.get('health_state','HEALTHY'),'slo_json':slo,'telemetry_binding_json':telemetry,'last_observed_at':now()}
   if health:
    for k,v in values.items(): setattr(health,k,v)
   else: health=ConnectorRuntimeHealthRow(connector_id=connector_id,**values); s.add(health)
   if row.lifecycle_state=='CERTIFIED' and health.health_state=='HEALTHY': row.lifecycle_state='OBSERVABLE'
   row.updated_at=now(); self._event(s,connector_id,'RUNTIME_HEALTH_BOUND',actor,{'health_state':health.health_state}); s.commit(); return {'connector':out(row),'runtime_health':out(health)}
 def assess_live_gate(self,connector_id,actor):
  with SessionLocal() as s:
   row=self._connector(s,connector_id)
   matrix=s.scalar(select(ConnectorCapabilityMatrixRow).where(ConnectorCapabilityMatrixRow.connector_id==connector_id).order_by(ConnectorCapabilityMatrixRow.version_no.desc()))
   authority=s.scalar(select(ConnectorAuthorityRow).where(ConnectorAuthorityRow.connector_id==connector_id,ConnectorAuthorityRow.state=='ACTIVE'))
   credential=s.scalar(select(ConnectorCredentialReferenceRow).where(ConnectorCredentialReferenceRow.connector_id==connector_id,ConnectorCredentialReferenceRow.state=='ACTIVE'))
   certs=s.scalars(select(ConnectorCertificationRunRow).where(ConnectorCertificationRunRow.connector_id==connector_id,ConnectorCertificationRunRow.result=='PASS')).all(); envs={x.environment for x in certs}
   health=s.get(ConnectorRuntimeHealthRow,connector_id); kill=s.get(ConnectorKillSwitchRow,connector_id)
   caps=matrix.capabilities_json if matrix else {}
   checks={'formal_supplier_identity':bool(row.supplier_legal_name),'production_environment':row.environment=='PRODUCTION','contract_authority':bool(authority),'external_secret_reference':bool(credential),'sandbox_certification':'SANDBOX' in envs,'production_certification':'PRODUCTION' in envs,'required_capabilities':REQUIRED_CAPABILITIES<=set(k for k,v in caps.items() if v),'settlement_refund':bool(caps.get('settlement') and caps.get('refund')),'runtime_observable':bool(health and health.health_state=='HEALTHY'),'kill_switch_ready':bool(kill and not kill.engaged),'fail_safe':bool(caps.get('fail_safe'))}
   blockers=[k.upper() for k,v in checks.items() if not v]; state='PASS' if not blockers else 'BLOCK'
   gate=ConnectorLiveGateAssessmentRow(live_gate_assessment_id=ident('gate'),connector_id=connector_id,policy_version=POLICY_VERSION,gate_state=state,checks_json=checks,blockers_json=blockers,evidence_hash=digest(checks),assessed_by=actor,assessed_at=now()); s.add(gate)
   if state=='PASS' and row.lifecycle_state=='OBSERVABLE': row.lifecycle_state='SWITCHABLE'
   row.updated_at=now(); self._event(s,connector_id,'LIVE_GATE_ASSESSED',actor,{'state':state,'blockers':blockers}); s.commit(); return {'connector':out(row),'assessment':out(gate)}
 def request_activation(self,connector_id,b,actor):
  if b.get('target_state')!='LIVE': raise ValueError('ONLY_LIVE_ACTIVATION_SUPPORTED')
  with SessionLocal() as s:
   row=self._connector(s,connector_id); gate=s.get(ConnectorLiveGateAssessmentRow,b.get('live_gate_assessment_id'))
   if row.lifecycle_state!='SWITCHABLE' or not gate or gate.connector_id!=connector_id or gate.gate_state!='PASS': raise ValueError('PASSING_LIVE_GATE_REQUIRED')
   if not b.get('change_window',{}).get('approved') or not b.get('rollback_plan',{}).get('tested') or not b.get('smoke_test',{}).get('passed'): raise ValueError('APPROVED_CHANGE_WINDOW_TESTED_ROLLBACK_PASSED_SMOKE_REQUIRED')
   change=ConnectorActivationChangeRow(activation_change_id=ident('act'),connector_id=connector_id,target_state='LIVE',live_gate_assessment_id=gate.live_gate_assessment_id,change_window_json=b['change_window'],rollback_plan_json=b['rollback_plan'],smoke_test_json=b['smoke_test'],state='PENDING_APPROVAL',requested_by=actor,created_at=now()); s.add(change); self._event(s,connector_id,'LIVE_ACTIVATION_REQUESTED',actor,{'change_id':change.activation_change_id}); s.commit(); return out(change)
 def approve_activation(self,change_id,actor):
  with SessionLocal() as s:
   change=s.get(ConnectorActivationChangeRow,change_id)
   if not change: raise ValueError('ACTIVATION_CHANGE_NOT_FOUND')
   if change.requested_by==actor: raise ValueError('MAKER_CHECKER_REQUIRED')
   row=self._connector(s,change.connector_id); gate=s.get(ConnectorLiveGateAssessmentRow,change.live_gate_assessment_id); kill=s.get(ConnectorKillSwitchRow,row.connector_id); health=s.get(ConnectorRuntimeHealthRow,row.connector_id)
   authority=s.scalar(select(ConnectorAuthorityRow).where(ConnectorAuthorityRow.connector_id==row.connector_id,ConnectorAuthorityRow.state=='ACTIVE'))
   credential=s.scalar(select(ConnectorCredentialReferenceRow).where(ConnectorCredentialReferenceRow.connector_id==row.connector_id,ConnectorCredentialReferenceRow.state=='ACTIVE'))
   current_ok=(row.environment=='PRODUCTION' and row.lifecycle_state=='SWITCHABLE' and gate and gate.gate_state=='PASS' and health and health.health_state=='HEALTHY' and authority and (authority.valid_to is None or authority.valid_to>now()) and credential and (credential.expires_at is None or credential.expires_at>now()) and not (kill and kill.engaged))
   if not current_ok: raise ValueError('LIVE_GATE_NO_LONGER_VALID')
   change.state='EXECUTED'; change.approved_by=actor; change.executed_at=now(); row.lifecycle_state='LIVE'; row.updated_at=now(); self._event(s,row.connector_id,'CONNECTOR_LIVE',actor,{'change_id':change_id}); s.commit(); return {'connector':out(row),'activation':out(change)}
 def set_kill_switch(self,connector_id,b,actor):
  with SessionLocal() as s:
   row=self._connector(s,connector_id); kill=s.get(ConnectorKillSwitchRow,connector_id)
   values={'engaged':bool(b['engaged']),'fallback_mode':b.get('fallback_mode','FAIL_CLOSED'),'reason':b.get('reason'),'changed_by':actor,'changed_at':now()}
   if kill:
    for k,v in values.items(): setattr(kill,k,v)
   else: kill=ConnectorKillSwitchRow(connector_id=connector_id,**values); s.add(kill)
   if kill.engaged: row.lifecycle_state='SUSPENDED'; row.updated_at=now()
   self._event(s,connector_id,'KILL_SWITCH_ENGAGED' if kill.engaged else 'KILL_SWITCH_RESET',actor,{'fallback_mode':kill.fallback_mode,'reason':kill.reason}); s.commit(); return {'connector':out(row),'kill_switch':out(kill)}
 def dashboard(self):
  with SessionLocal() as s:
   return {'states':dict(s.execute(select(ProductionConnectorRow.lifecycle_state,func.count()).group_by(ProductionConnectorRow.lifecycle_state)).all()),'verticals':dict(s.execute(select(ProductionConnectorRow.vertical,func.count()).group_by(ProductionConnectorRow.vertical)).all()),'policy_version':POLICY_VERSION,'live_requires_production_certification':True,'engineering_or_sandbox_can_never_be_live':True}

production_connector_service=ProductionConnectorService()
