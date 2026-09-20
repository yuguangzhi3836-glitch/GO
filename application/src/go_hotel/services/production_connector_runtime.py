from datetime import datetime, timezone, timedelta
import hashlib, hmac, json, uuid
from sqlalchemy import select, func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
 ProductionConnectorRow, ConnectorAuthorityRow, ConnectorCredentialReferenceRow, ConnectorRuntimeHealthRow, ConnectorKillSwitchRow,
 ConnectorRuntimeAuthorizationRow, ConnectorRuntimeOperationRow, ConnectorWebhookReceiptRow,
 ConnectorRuntimeObservationRow, ConnectorRuntimeReconciliationRow, ConnectorRuntimeSafetyEventRow,
 ExternalTruthOperationRow,
)

FINAL_STATES={'CONFIRMED','FAILED','CANCELLED','REFUNDED'}
UNKNOWN_STATES={'ACCEPTED','PENDING','PROCESSING','UNKNOWN','UNKNOWN_EXTERNAL_STATE'}
UNRESOLVED_INCIDENT_STATES={'MANUAL_REVIEW','CLAIMED','PENDING_CHECKER'}

def now(): return datetime.now(timezone.utc)
def utc(v): return v if v is None or v.tzinfo else v.replace(tzinfo=timezone.utc)
def ident(p): return f'{p}_{uuid.uuid4().hex}'
def digest(v): return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def out(r): return {c.name:(utc(getattr(r,c.name)).isoformat() if isinstance(getattr(r,c.name),datetime) else getattr(r,c.name)) for c in r.__table__.columns}

BOOK_POLICIES={
 'FLIGHT':(5,600,8),'RAIL':(5,600,8),'RIDE':(5,300,6),'RENTAL':(10,600,8),'ATTRACTION':(10,900,8),'HOTEL':(10,1800,10),
}

def sla_policy(vertical,operation_type):
 v=(vertical or 'HOTEL').upper(); op=(operation_type or 'BOOK').upper()
 base=BOOK_POLICIES.get(v,(10,1800,8))
 if op in {'CHANGE','CANCEL'}:
  hard=1800 if v in {'FLIGHT','RAIL'} else max(base[1],1200)
  return {'poll_seconds':base[0],'hard_sla_seconds':hard,'max_attempts':max(base[2],8),'severity':'HIGH'}
 if op=='REFUND':
  hard=7200 if v in {'FLIGHT','RAIL'} else max(base[1],3600)
  return {'poll_seconds':max(base[0],10),'hard_sla_seconds':hard,'max_attempts':max(base[2],10),'severity':'HIGH'}
 return {'poll_seconds':base[0],'hard_sla_seconds':base[1],'max_attempts':base[2],'severity':'CRITICAL' if op in {'BOOK','CONFIRM'} else 'HIGH'}

class ProductionConnectorRuntimeService:
 def __init__(self): self._secret_resolver=None; self._poll_resolvers={}
 def set_secret_resolver(self,resolver): self._secret_resolver=resolver
 def set_poll_resolver(self,connector_id,resolver): self._poll_resolvers[connector_id]=resolver
 def _secret(self,reference):
  if not self._secret_resolver: raise ValueError('PRODUCTION_SECRET_RESOLVER_NOT_CONFIGURED')
  value=self._secret_resolver(reference)
  if not isinstance(value,(bytes,bytearray)) or not value: raise ValueError('PRODUCTION_SECRET_RESOLUTION_FAILED')
  return bytes(value)
 def _safety(self,s,connector_id,event,severity,reasons,evidence):
  s.add(ConnectorRuntimeSafetyEventRow(runtime_safety_event_id=ident('rse'),connector_id=connector_id,event_type=event,severity=severity,reason_codes_json=reasons,evidence_hash=digest(evidence),created_at=now()))
 def _connector(self,s,connector_id):
  c=s.get(ProductionConnectorRow,connector_id)
  if not c: raise ValueError('CONNECTOR_NOT_FOUND')
  return c
 def _policy(self,s,row):
  c=self._connector(s,row.connector_id); return sla_policy(c.vertical,row.operation_type)
 def authorize(self,connector_id,operation_type):
  op=operation_type.upper()
  with SessionLocal() as s:
   connector=s.get(ProductionConnectorRow,connector_id); reasons=[]
   if not connector: reasons.append('CONNECTOR_NOT_FOUND')
   else:
    if connector.environment!='PRODUCTION': reasons.append('PRODUCTION_ENVIRONMENT_REQUIRED')
    if connector.lifecycle_state!='LIVE': reasons.append('CONNECTOR_NOT_LIVE')
    kill=s.get(ConnectorKillSwitchRow,connector_id)
    if not kill or kill.engaged: reasons.append('KILL_SWITCH_NOT_READY')
    health=s.get(ConnectorRuntimeHealthRow,connector_id)
    if not health or health.health_state!='HEALTHY' or utc(health.last_observed_at) < now()-timedelta(minutes=15): reasons.append('FRESH_HEALTHY_RUNTIME_REQUIRED')
    authority=s.scalar(select(ConnectorAuthorityRow).where(ConnectorAuthorityRow.connector_id==connector_id,ConnectorAuthorityRow.state=='ACTIVE'))
    if not authority or op not in set(x.upper() for x in authority.authority_scope_json) or (authority.valid_to and utc(authority.valid_to)<=now()): reasons.append('ACTIVE_OPERATION_AUTHORITY_REQUIRED')
    credential=s.scalar(select(ConnectorCredentialReferenceRow).where(ConnectorCredentialReferenceRow.connector_id==connector_id,ConnectorCredentialReferenceRow.state=='ACTIVE'))
    if not credential or (credential.expires_at and utc(credential.expires_at)<=now()): reasons.append('ACTIVE_EXTERNAL_CREDENTIAL_REQUIRED')
   decision='ALLOW' if not reasons else 'DENY'; evidence={'connector_id':connector_id,'operation_type':op,'reasons':reasons}
   row=ConnectorRuntimeAuthorizationRow(runtime_authorization_id=ident('rauth'),connector_id=connector_id,operation_type=op,decision=decision,reason_codes_json=reasons,evidence_hash=digest(evidence),decided_at=now()); s.add(row)
   if reasons:self._safety(s,connector_id,'RUNTIME_AUTHORIZATION_DENIED','HIGH',reasons,evidence)
   s.commit(); return out(row)
 def _incident_freeze(self,s,connector_id,payload):
  order_id=(payload or {}).get('order_id')
  if not order_id:return
  connector=self._connector(s,connector_id)
  recs=s.scalars(select(ConnectorRuntimeReconciliationRow).where(ConnectorRuntimeReconciliationRow.state.in_(UNRESOLVED_INCIDENT_STATES))).all()
  for rec in recs:
   op=s.get(ConnectorRuntimeOperationRow,rec.runtime_operation_id)
   if not op:continue
   other=s.get(ProductionConnectorRow,op.connector_id)
   if other and other.vertical==connector.vertical and (op.request_json or {}).get('order_id')==order_id:
    raise ValueError('EXTERNAL_TRUTH_INCIDENT_FROZEN')
 def submit(self,connector_id,b):
  operation_type=b['operation_type'].upper(); key=b.get('idempotency_key',''); payload=b.get('request',{})
  if not key: raise ValueError('IDEMPOTENCY_KEY_REQUIRED')
  request_hash=digest({'operation_type':operation_type,'request':payload})
  with SessionLocal() as s:
   existing=s.scalar(select(ConnectorRuntimeOperationRow).where(ConnectorRuntimeOperationRow.connector_id==connector_id,ConnectorRuntimeOperationRow.idempotency_key==key))
   if existing:
    if existing.request_hash!=request_hash: raise ValueError('IDEMPOTENCY_KEY_PAYLOAD_MISMATCH')
    return out(existing)
   self._incident_freeze(s,connector_id,payload)
  auth=self.authorize(connector_id,operation_type)
  if auth['decision']!='ALLOW': raise ValueError('CONNECTOR_RUNTIME_AUTHORIZATION_DENIED:'+','.join(auth['reason_codes_json']))
  with SessionLocal() as s:
   connector=self._connector(s,connector_id); pol=sla_policy(connector.vertical,operation_type)
   row=ConnectorRuntimeOperationRow(runtime_operation_id=ident('rop'),connector_id=connector_id,operation_type=operation_type,idempotency_key=key,request_hash=request_hash,request_json=payload,state='AUTHORIZED',response_json={},authorization_id=auth['runtime_authorization_id'],created_at=now(),updated_at=now()); s.add(row)
   rec=ConnectorRuntimeReconciliationRow(reconciliation_id=ident('recon'),runtime_operation_id=row.runtime_operation_id,state='READY',attempt_count=0,max_attempts=b.get('max_attempts',pol['max_attempts']),escalation_level=0,updated_at=now()); s.add(rec); s.commit(); return out(row)
 def mark_dispatched(self,operation_id,b):
  with SessionLocal() as s:
   row=s.get(ConnectorRuntimeOperationRow,operation_id)
   if not row: raise ValueError('RUNTIME_OPERATION_NOT_FOUND')
   if row.state not in {'AUTHORIZED','DISPATCHED'}: raise ValueError('OPERATION_NOT_DISPATCHABLE')
   row.external_operation_id=b.get('external_operation_id'); row.response_json=b.get('response',{}); row.state=b.get('state','DISPATCHED').upper(); row.updated_at=now(); s.commit(); return out(row)
 def _first_unknown_at(self,s,row):
  x=s.scalar(select(ConnectorRuntimeObservationRow).where(ConnectorRuntimeObservationRow.runtime_operation_id==row.runtime_operation_id,ConnectorRuntimeObservationRow.external_state.in_(UNKNOWN_STATES)).order_by(ConnectorRuntimeObservationRow.observed_at.asc()))
  return utc(x.observed_at) if x else now()
 def _set_manual(self,s,row,rec,reason,severity='HIGH'):
  if rec.state not in {'CLAIMED','PENDING_CHECKER'}:rec.state='MANUAL_REVIEW'
  if not rec.manual_review_reason:rec.manual_review_reason=reason
  if reason.startswith('EXTERNAL_TRUTH_SLA_BREACHED') and rec.manual_review_reason!=reason:rec.manual_review_reason=reason
  self._safety(s,row.connector_id,'EXTERNAL_TRUTH_INCIDENT',severity,[reason],{'operation_id':row.runtime_operation_id,'state':row.state})
 def _evaluate_sla(self,s,row,rec):
  if rec.state in {'CONVERGED','RESOLVED'}:return False
  pol=self._policy(s,row); started=self._first_unknown_at(s,row); deadline=started+timedelta(seconds=pol['hard_sla_seconds'])
  if now()>=deadline:
   reason=f"EXTERNAL_TRUTH_SLA_BREACHED:{self._connector(s,row.connector_id).vertical}:{row.operation_type}"
   already=(rec.manual_review_reason or '').startswith('EXTERNAL_TRUTH_SLA_BREACHED')
   if rec.state not in {'CLAIMED','PENDING_CHECKER'}:rec.state='MANUAL_REVIEW'
   rec.manual_review_reason=reason
   if not already:self._safety(s,row.connector_id,'EXTERNAL_TRUTH_SLA_BREACHED',pol['severity'],[reason],{'operation_id':row.runtime_operation_id,'deadline_at':deadline.isoformat()})
   return True
  return False
 def _observe(self,s,row,source,state,evidence,supplier_reference=None):
  state=state.upper(); rec=s.scalar(select(ConnectorRuntimeReconciliationRow).where(ConnectorRuntimeReconciliationRow.runtime_operation_id==row.runtime_operation_id).with_for_update())
  if not rec:raise ValueError('RECONCILIATION_NOT_FOUND')
  # Terminal truth is monotonic. A stale non-terminal observation cannot reopen it.
  if row.state in FINAL_STATES:
   obs=ConnectorRuntimeObservationRow(runtime_observation_id=ident('robs'),runtime_operation_id=row.runtime_operation_id,source=source,external_state=state,evidence_json=evidence,evidence_hash=digest(evidence),supplier_reference=supplier_reference,observed_at=now()); s.add(obs)
   if state in UNKNOWN_STATES or state==row.state:
    rec.state='CONVERGED';rec.next_attempt_at=None;rec.updated_at=now();return obs,rec
   if state in FINAL_STATES and state!=row.state:
    rec.state='MANUAL_REVIEW';rec.manual_review_reason=f'TERMINAL_STATE_CONFLICT:{row.state}:{state}';rec.updated_at=now()
    self._safety(s,row.connector_id,'EXTERNAL_TERMINAL_TRUTH_CONFLICT','CRITICAL',[rec.manual_review_reason],{'operation_id':row.runtime_operation_id,'existing':row.state,'incoming':state})
    return obs,rec
  if state not in FINAL_STATES|UNKNOWN_STATES:raise ValueError('UNSUPPORTED_EXTERNAL_STATE')
  obs=ConnectorRuntimeObservationRow(runtime_observation_id=ident('robs'),runtime_operation_id=row.runtime_operation_id,source=source,external_state=state,evidence_json=evidence,evidence_hash=digest(evidence),supplier_reference=supplier_reference,observed_at=now()); s.add(obs)
  rec.attempt_count+=1; rec.updated_at=now()
  if state in FINAL_STATES:
   row.state=state;rec.state='CONVERGED';rec.next_attempt_at=None;rec.resolved_at=now()
   if rec.resolution_requested_by:
    rec.superseded_reason='SUPERSEDED_BY_EXTERNAL_TRUTH';rec.resolution_payload_json=None;rec.resolution_evidence_digest=None
  else:
   row.state='UNKNOWN_EXTERNAL_STATE'; rec.state='PENDING'
   pol=self._policy(s,row)
   if rec.attempt_count>=rec.max_attempts:self._set_manual(s,row,rec,'EXTERNAL_STATE_DID_NOT_CONVERGE',pol['severity'])
   else:rec.next_attempt_at=now()+timedelta(seconds=min(300,pol['poll_seconds']*(2**max(0,rec.attempt_count-1))))
  row.updated_at=now();self._evaluate_sla(s,row,rec);return obs,rec
 def record_poll(self,operation_id,b):
  with SessionLocal() as s:
   row=s.get(ConnectorRuntimeOperationRow,operation_id)
   if not row: raise ValueError('RUNTIME_OPERATION_NOT_FOUND')
   obs,rec=self._observe(s,row,'POLL',b['external_state'].upper(),b.get('evidence',{}),b.get('supplier_reference')); s.commit(); return {'operation':out(row),'observation':out(obs),'reconciliation':out(rec)}
 def ingest_webhook(self,connector_id,delivery_id,signature,payload):
  payload_hash=digest(payload)
  with SessionLocal() as s:
   prior=s.scalar(select(ConnectorWebhookReceiptRow).where(ConnectorWebhookReceiptRow.connector_id==connector_id,ConnectorWebhookReceiptRow.delivery_id==delivery_id))
   if prior:
    if prior.payload_hash!=payload_hash:
     self._safety(s,connector_id,'WEBHOOK_DELIVERY_PAYLOAD_CONFLICT','CRITICAL',['DELIVERY_ID_PAYLOAD_DRIFT'],{'delivery_id':delivery_id,'prior':prior.payload_hash,'incoming':payload_hash});s.commit();raise ValueError('WEBHOOK_DELIVERY_PAYLOAD_CONFLICT')
    return {'receipt':out(prior),'replay':True}
   credential=s.scalar(select(ConnectorCredentialReferenceRow).where(ConnectorCredentialReferenceRow.connector_id==connector_id,ConnectorCredentialReferenceRow.state=='ACTIVE'))
   if not credential: raise ValueError('ACTIVE_EXTERNAL_CREDENTIAL_REQUIRED')
  expected=hmac.new(self._secret(credential.secret_reference),json.dumps(payload,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest(); valid=hmac.compare_digest(expected,signature)
  with SessionLocal() as s:
   receipt=ConnectorWebhookReceiptRow(webhook_receipt_id=ident('wh'),connector_id=connector_id,delivery_id=delivery_id,signature_fingerprint=hashlib.sha256(signature.encode()).hexdigest(),payload_hash=payload_hash,signature_valid=valid,replay_rejected=False,state='VERIFIED' if valid else 'REJECTED',received_at=now()); s.add(receipt)
   if not valid:
    self._safety(s,connector_id,'INVALID_WEBHOOK_SIGNATURE','CRITICAL',['WEBHOOK_SIGNATURE_INVALID'],{'delivery_id':delivery_id,'payload_hash':payload_hash}); invalid=(s.scalar(select(func.count()).select_from(ConnectorWebhookReceiptRow).where(ConnectorWebhookReceiptRow.connector_id==connector_id,ConnectorWebhookReceiptRow.signature_valid==False)) or 0)+1
    if invalid>=3:
     connector=s.get(ProductionConnectorRow,connector_id); kill=s.get(ConnectorKillSwitchRow,connector_id)
     if kill: kill.engaged=True; kill.reason='REPEATED_INVALID_WEBHOOK_SIGNATURE'; kill.changed_by='RUNTIME_SAFETY'; kill.changed_at=now()
     if connector: connector.lifecycle_state='SUSPENDED'; connector.updated_at=now()
    s.commit(); raise ValueError('WEBHOOK_SIGNATURE_INVALID')
   row=s.get(ConnectorRuntimeOperationRow,payload.get('runtime_operation_id'))
   if not row or row.connector_id!=connector_id: raise ValueError('WEBHOOK_OPERATION_BINDING_INVALID')
   obs,rec=self._observe(s,row,'WEBHOOK',payload['external_state'].upper(),payload,payload.get('supplier_reference')); s.commit(); return {'receipt':out(receipt),'operation':out(row),'observation':out(obs),'reconciliation':out(rec),'replay':False}
 def admit_payment_unknown(self,external_truth_operation_id):
  """Bridge an existing payment truth operation into the Command Center case queue.
  It never writes payment state, movements, or ledger entries; only a verified
  external callback can resolve the payment authority chain.
  """
  with SessionLocal() as s:
   truth=s.get(ExternalTruthOperationRow,external_truth_operation_id)
   if not truth or truth.vertical!='PAYMENT':raise ValueError('PAYMENT_TRUTH_OPERATION_REQUIRED')
   if truth.state not in {'DISPATCHING','UNKNOWN_EXTERNAL_STATE','TRANSPORT_ACCEPTED_PENDING_SIGNED_CALLBACK'}:raise ValueError('PAYMENT_TRUTH_OPERATION_NOT_RECONCILABLE')
   key=f'PAYMENT_TRUTH_RECON:{external_truth_operation_id}'
   existing=s.scalar(select(ConnectorRuntimeOperationRow).where(ConnectorRuntimeOperationRow.idempotency_key==key))
   if existing:
    rec=s.scalar(select(ConnectorRuntimeReconciliationRow).where(ConnectorRuntimeReconciliationRow.runtime_operation_id==existing.runtime_operation_id))
    return {'operation':out(existing),'reconciliation':out(rec),'replay':True}
   connector_id='COMMAND_CENTER_PAYMENT_RECONCILIATION'
   connector=s.get(ProductionConnectorRow,connector_id)
   if not connector:
    connector=ProductionConnectorRow(connector_id=connector_id,connector_key='command-center-payment-reconciliation',display_name='Command Center Payment Reconciliation',vertical='PAYMENT',supplier_legal_name='GO Command Center Internal Control',environment='CONTROL_PLANE',lifecycle_state='INTERNAL',active_capability_version=1,created_by='PAYMENT_TRUTH_BRIDGE',created_at=now(),updated_at=now());s.add(connector)
   op=ConnectorRuntimeOperationRow(runtime_operation_id=ident('rop'),connector_id=connector_id,operation_type='RECONCILE_PAYMENT_TRUTH',idempotency_key=key,request_hash=digest({'external_truth_operation_id':external_truth_operation_id,'request_hash':truth.request_hash}),request_json={'external_truth_operation_id':external_truth_operation_id,'payment_intent_id':truth.payment_intent_id,'operation_type':truth.operation_type},state='UNKNOWN_EXTERNAL_STATE',response_json={},authorization_id='PAYMENT_TRUTH_BRIDGE_NO_EXTERNAL_AUTHORIZATION',created_at=now(),updated_at=now());s.add(op);s.flush()
   rec=ConnectorRuntimeReconciliationRow(reconciliation_id=ident('recon'),runtime_operation_id=op.runtime_operation_id,state='MANUAL_REVIEW',attempt_count=0,max_attempts=0,manual_review_reason='PAYMENT_EXTERNAL_TRUTH_RECONCILIATION_REQUIRED',claimed_by=None,lease_expires_at=None,evidence_due_at=None,resolution_requested_by=None,checker_id=None,escalation_level=0,operator_sla_due_at=None,resolved_at=None,resolution_payload_json=None,resolution_evidence_digest=None,checker_evidence_reference=None,resolution_result_json=None,resolved_by=None,superseded_reason=None,updated_at=now());s.add(rec);s.commit();return {'operation':out(op),'reconciliation':out(rec),'replay':False}
 def converge_payment_truth_from_callback(self,external_truth_operation_id):
  """Close only the Command Center case after payment truth reaches a verified terminal callback."""
  with SessionLocal() as s:
   truth=s.get(ExternalTruthOperationRow,external_truth_operation_id)
   if not truth or truth.vertical!='PAYMENT':raise ValueError('PAYMENT_TRUTH_OPERATION_REQUIRED')
   if truth.state not in {'CALLBACK_SUCCEEDED','CALLBACK_FAILED'}:return None
   key=f'PAYMENT_TRUTH_RECON:${external_truth_operation_id}'
   op=s.scalar(select(ConnectorRuntimeOperationRow).where(ConnectorRuntimeOperationRow.idempotency_key==key).with_for_update())
   if not op:return None
   rec=s.scalar(select(ConnectorRuntimeReconciliationRow).where(ConnectorRuntimeReconciliationRow.runtime_operation_id==op.runtime_operation_id).with_for_update())
   if not rec:return None
   terminal='CONFIRMED' if truth.state=='CALLBACK_SUCCEEDED' else 'FAILED'
   op.state=terminal;op.response_json={'payment_truth_operation_id':external_truth_operation_id,'verified_terminal_state':truth.state};op.updated_at=now()
   rec.state='CONVERGED';rec.resolved_at=now();rec.resolved_by='VERIFIED_PAYMENT_CALLBACK';rec.claimed_by=None;rec.lease_expires_at=None;rec.evidence_due_at=None;rec.operator_sla_due_at=None;rec.superseded_reason='SUPERSEDED_BY_VERIFIED_PAYMENT_TRUTH';rec.resolution_result_json={'decision':'VERIFIED_CALLBACK','terminal_state':terminal,'payment_truth_operation_id':external_truth_operation_id};rec.updated_at=now()
   s.commit();return {'operation':out(op),'reconciliation':out(rec)}
 def due_reconciliations(self,limit=100):
  with SessionLocal() as s:
   rows=s.scalars(select(ConnectorRuntimeReconciliationRow).where(ConnectorRuntimeReconciliationRow.state.in_({'PENDING','MANUAL_REVIEW','CLAIMED','PENDING_CHECKER'})).order_by(ConnectorRuntimeReconciliationRow.updated_at).limit(limit)).all(); result=[]
   for rec in rows:
    op=s.get(ConnectorRuntimeOperationRow,rec.runtime_operation_id); self._evaluate_sla(s,op,rec); pol=self._policy(s,op); started=self._first_unknown_at(s,op); deadline=started+timedelta(seconds=pol['hard_sla_seconds']); remaining=max(0,int((deadline-now()).total_seconds()))
    result.append({'operation':out(op),'reconciliation':out(rec),'sla_policy':pol,'unknown_since':started.isoformat(),'deadline_at':deadline.isoformat(),'remaining_seconds':remaining,'consumer_promise':'FROZEN' if rec.state in UNRESOLVED_INCIDENT_STATES else 'PENDING','supplier_mutation_frozen':rec.state in UNRESOLVED_INCIDENT_STATES,'finance_close_blocker':rec.state in UNRESOLVED_INCIDENT_STATES,'action_required':'CHECKER_REVIEW' if rec.state=='PENDING_CHECKER' else ('CONTINUE_CLAIM' if rec.state=='CLAIMED' else 'CLAIM_OR_RESOLVE')})
   s.commit();return result
 def run_due_poll(self,reconciliation_id):
  with SessionLocal() as s:
   rec=s.get(ConnectorRuntimeReconciliationRow,reconciliation_id);op=s.get(ConnectorRuntimeOperationRow,rec.runtime_operation_id) if rec else None
   if not rec or not op:raise ValueError('RECONCILIATION_NOT_FOUND')
   resolver=self._poll_resolvers.get(op.connector_id)
   if not resolver:raise ValueError('POLL_RESOLVER_NOT_CONFIGURED')
  result=resolver(out(op))
  if not isinstance(result,dict) or not result.get('external_state'):raise ValueError('POLL_RESOLVER_INVALID_RESULT')
  return self.record_poll(op.runtime_operation_id,result)
 def claim(self,reconciliation_id,actor,lease_seconds=900):
  with SessionLocal() as s:
   rec=s.scalar(select(ConnectorRuntimeReconciliationRow).where(ConnectorRuntimeReconciliationRow.reconciliation_id==reconciliation_id).with_for_update())
   if not rec:raise ValueError('RECONCILIATION_NOT_FOUND')
   t=now();lease=utc(rec.lease_expires_at)
   if rec.state=='CLAIMED' and rec.claimed_by==actor and lease and lease>t:return {'reconciliation':out(rec),'replay':True}
   if rec.state=='PENDING_CHECKER':raise ValueError('INCIDENT_PENDING_CHECKER')
   if rec.state=='CLAIMED' and lease and lease>t and rec.claimed_by!=actor:raise ValueError('INCIDENT_ALREADY_CLAIMED')
   if rec.state not in {'MANUAL_REVIEW','CLAIMED'}:raise ValueError('INCIDENT_NOT_CLAIMABLE')
   takeover=rec.state=='CLAIMED' and rec.claimed_by and rec.claimed_by!=actor
   rec.state='CLAIMED';rec.claimed_by=actor;rec.lease_expires_at=t+timedelta(seconds=lease_seconds);rec.evidence_due_at=t+timedelta(minutes=30);rec.operator_sla_due_at=t+timedelta(hours=1);rec.updated_at=t
   if takeover:rec.escalation_level+=1
   s.commit();return {'reconciliation':out(rec),'replay':False}
 def renew_claim(self,reconciliation_id,actor,lease_seconds=900):
  with SessionLocal() as s:
   rec=s.scalar(select(ConnectorRuntimeReconciliationRow).where(ConnectorRuntimeReconciliationRow.reconciliation_id==reconciliation_id).with_for_update())
   if not rec or rec.state!='CLAIMED' or rec.claimed_by!=actor:raise ValueError('ACTIVE_INCIDENT_CLAIM_REQUIRED')
   if utc(rec.lease_expires_at)<=now():raise ValueError('INCIDENT_LEASE_EXPIRED')
   rec.lease_expires_at=now()+timedelta(seconds=lease_seconds);rec.updated_at=now();s.commit();return out(rec)
 def submit_resolution(self,reconciliation_id,actor,payload):
  evidence=payload.get('evidence');terminal=(payload.get('terminal_state') or '').upper()
  if terminal not in FINAL_STATES:raise ValueError('TERMINAL_RESOLUTION_REQUIRED')
  if not isinstance(evidence,dict) or not evidence or not payload.get('evidence_reference'):raise ValueError('RESOLUTION_EVIDENCE_REQUIRED')
  frozen={'terminal_state':terminal,'evidence':evidence,'evidence_reference':payload['evidence_reference']};d=digest(frozen)
  with SessionLocal() as s:
   rec=s.scalar(select(ConnectorRuntimeReconciliationRow).where(ConnectorRuntimeReconciliationRow.reconciliation_id==reconciliation_id).with_for_update())
   if not rec:raise ValueError('RECONCILIATION_NOT_FOUND')
   if rec.state=='PENDING_CHECKER' and rec.resolution_requested_by==actor:
    if rec.resolution_evidence_digest!=d:raise ValueError('RESOLUTION_EVIDENCE_CONFLICT')
    return {'reconciliation':out(rec),'replay':True}
   if rec.state!='CLAIMED' or rec.claimed_by!=actor:raise ValueError('ACTIVE_INCIDENT_CLAIM_REQUIRED')
   if not rec.lease_expires_at or utc(rec.lease_expires_at)<=now():raise ValueError('INCIDENT_LEASE_EXPIRED')
   rec.state='PENDING_CHECKER';rec.resolution_requested_by=actor;rec.resolution_payload_json=frozen;rec.resolution_evidence_digest=d;rec.updated_at=now();s.commit();return {'reconciliation':out(rec),'replay':False}
 def review_resolution(self,reconciliation_id,checker,decision,checker_evidence_reference):
  decision=decision.upper()
  if decision not in {'APPROVE','REJECT'}:raise ValueError('INVALID_CHECKER_DECISION')
  if not checker_evidence_reference:raise ValueError('CHECKER_EVIDENCE_REQUIRED')
  with SessionLocal() as s:
   rec=s.scalar(select(ConnectorRuntimeReconciliationRow).where(ConnectorRuntimeReconciliationRow.reconciliation_id==reconciliation_id).with_for_update())
   if not rec:raise ValueError('RECONCILIATION_NOT_FOUND')
   if rec.resolution_requested_by==checker:raise ValueError('MAKER_CHECKER_REQUIRED')
   if rec.state=='RESOLVED':return {'reconciliation':out(rec),'result':rec.resolution_result_json,'replay':True}
   if rec.state!='PENDING_CHECKER':raise ValueError('RESOLUTION_NOT_PENDING_CHECKER')
   payload=rec.resolution_payload_json or {}
   if digest(payload)!=rec.resolution_evidence_digest:
    op=s.get(ConnectorRuntimeOperationRow,rec.runtime_operation_id);self._safety(s,op.connector_id,'RESOLUTION_EVIDENCE_DIGEST_MISMATCH','CRITICAL',['RESOLUTION_EVIDENCE_DIGEST_MISMATCH'],{'reconciliation_id':reconciliation_id});s.commit();raise ValueError('RESOLUTION_EVIDENCE_DIGEST_MISMATCH')
   rec.checker_id=checker;rec.checker_evidence_reference=checker_evidence_reference;rec.updated_at=now()
   if decision=='REJECT':
    rec.state='MANUAL_REVIEW';rec.claimed_by=None;rec.lease_expires_at=None;rec.resolution_requested_by=None;rec.resolution_payload_json=None;rec.resolution_evidence_digest=None;rec.escalation_level+=1;s.commit();return {'reconciliation':out(rec),'result':{'decision':'REJECTED'},'replay':False}
   op=s.get(ConnectorRuntimeOperationRow,rec.runtime_operation_id);terminal=payload['terminal_state']
   if op.state in FINAL_STATES and op.state!=terminal:raise ValueError('EXTERNAL_TRUTH_ALREADY_CONVERGED')
   obs=ConnectorRuntimeObservationRow(runtime_observation_id=ident('robs'),runtime_operation_id=op.runtime_operation_id,source='MANUAL',external_state=terminal,evidence_json=payload,evidence_hash=rec.resolution_evidence_digest,supplier_reference=None,observed_at=now());s.add(obs)
   op.state=terminal;op.updated_at=now();rec.state='RESOLVED';rec.resolved_at=now();rec.resolved_by=checker;rec.lease_expires_at=None;rec.resolution_result_json={'decision':'APPROVED','terminal_state':terminal,'operation_id':op.runtime_operation_id};s.commit();return {'reconciliation':out(rec),'result':rec.resolution_result_json,'replay':False}
 def escalate_due(self):
  changed=[]
  with SessionLocal() as s:
   rows=s.scalars(select(ConnectorRuntimeReconciliationRow).where(ConnectorRuntimeReconciliationRow.state.in_(UNRESOLVED_INCIDENT_STATES))).all();t=now()
   for rec in rows:
    due=(rec.evidence_due_at and utc(rec.evidence_due_at)<=t) or (rec.operator_sla_due_at and utc(rec.operator_sla_due_at)<=t)
    if due:
     rec.escalation_level=min(3,rec.escalation_level+1);rec.updated_at=t;changed.append(rec.reconciliation_id)
   s.commit();return changed
 def unresolved_incident_blockers(self,order_ids=None):
  with SessionLocal() as s:
   recs=s.scalars(select(ConnectorRuntimeReconciliationRow).where(ConnectorRuntimeReconciliationRow.state.in_(UNRESOLVED_INCIDENT_STATES))).all();outv=[]
   for rec in recs:
    op=s.get(ConnectorRuntimeOperationRow,rec.runtime_operation_id);oid=(op.request_json or {}).get('order_id') if op else None
    if order_ids is None or oid in set(order_ids):outv.append(f'EXTERNAL_TRUTH_REVIEW:{op.runtime_operation_id}')
   return outv
 def has_release_blocking_incident(self):
  with SessionLocal() as s:
   rec=s.scalar(select(ConnectorRuntimeReconciliationRow).where(ConnectorRuntimeReconciliationRow.state.in_(UNRESOLVED_INCIDENT_STATES)).limit(1));return bool(rec)
 def get_operation(self,operation_id):
  with SessionLocal() as s:
   row=s.get(ConnectorRuntimeOperationRow,operation_id)
   if not row: raise ValueError('RUNTIME_OPERATION_NOT_FOUND')
   rec=s.scalar(select(ConnectorRuntimeReconciliationRow).where(ConnectorRuntimeReconciliationRow.runtime_operation_id==operation_id)); observations=s.scalars(select(ConnectorRuntimeObservationRow).where(ConnectorRuntimeObservationRow.runtime_operation_id==operation_id).order_by(ConnectorRuntimeObservationRow.observed_at)).all()
   return {'operation':out(row),'reconciliation':out(rec),'observations':[out(x) for x in observations]}

production_connector_runtime_service=ProductionConnectorRuntimeService()
