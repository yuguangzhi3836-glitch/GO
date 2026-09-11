from datetime import datetime,timezone
import hashlib,json,uuid
from sqlalchemy import select,func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (ExternalSandboxSupplierIntakeRow,ExternalSandboxCredentialBindingRow,
 ExternalSandboxCertificationSuiteRow,NamedSupplierAdapterRow,NamedSupplierAdapterBindingRow,
 ExternalSandboxExecutionAuthorizationRow,ExternalSandboxExecutionAttemptRow,
 ExternalSandboxTransportEvidenceRow,ExternalSandboxExecutionDecisionRow)
from go_hotel.connectors.external_sandbox import external_sandbox_executor

CAPS={'HOTEL':{'BOOK','QUERY','CANCEL','WEBHOOK'},'PAYMENT':{'AUTHORIZE','CAPTURE','REFUND','SETTLEMENT','CALLBACK'}}
REQUIRED_OPS=['HOTEL_BOOK','HOTEL_QUERY','HOTEL_CANCEL','PSP_AUTHORIZE','PSP_CAPTURE','PSP_REFUND','PSP_SETTLEMENT','HOTEL_WEBHOOK','PSP_CALLBACK']
def now():return datetime.now(timezone.utc)
def utc(v):return v.replace(tzinfo=timezone.utc) if v and v.tzinfo is None else v
def ident(p):return f'{p}_{uuid.uuid4().hex}'
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def out(r):return {c.name:(getattr(r,c.name).isoformat() if isinstance(getattr(r,c.name),datetime) else getattr(r,c.name)) for c in r.__table__.columns}

class NamedSupplierExternalExecutionService:
 def register_adapter(self,intake_id,b,actor):
  vertical=b.get('vertical');caps=set(b.get('capabilities',[]))
  if vertical not in CAPS:raise ValueError('HOTEL_OR_PAYMENT_VERTICAL_REQUIRED')
  if not CAPS[vertical].issubset(caps):raise ValueError('REQUIRED_CAPABILITY_MANIFEST_INCOMPLETE')
  with SessionLocal() as s:
   intake=s.get(ExternalSandboxSupplierIntakeRow,intake_id)
   if not intake:raise ValueError('SUPPLIER_INTAKE_NOT_FOUND')
   expected=intake.hotel_supplier_name if vertical=='HOTEL' else intake.psp_supplier_name
   if not expected or b.get('supplier_name')!=expected:raise ValueError('NAMED_SUPPLIER_MUST_MATCH_INTAKE')
   verified=bool(b.get('implementation_verified'))
   r=NamedSupplierAdapterRow(named_adapter_id=ident('nsa'),supplier_intake_id=intake_id,vertical=vertical,supplier_name=expected,adapter_key=b['adapter_key'],adapter_version=b.get('adapter_version',1),capability_manifest_json=sorted(caps),implementation_reference=b.get('implementation_reference','template://not-implemented'),state='IMPLEMENTATION_VERIFIED' if verified else 'TEMPLATE_ONLY',updated_at=now());s.add(r);s.commit();return out(r)
 def bind_adapter(self,adapter_id,b,actor):
  with SessionLocal() as s:
   adapter=s.get(NamedSupplierAdapterRow,adapter_id)
   if not adapter:raise ValueError('NAMED_ADAPTER_NOT_FOUND')
   intake=s.get(ExternalSandboxSupplierIntakeRow,adapter.supplier_intake_id)
   credential=s.get(ExternalSandboxCredentialBindingRow,b['credential_binding_id'])
   if not credential or credential.supplier_intake_id!=intake.supplier_intake_id or credential.vertical!=adapter.vertical or credential.access_test_state!='PASS':raise ValueError('VALID_MATCHING_CREDENTIAL_BINDING_REQUIRED')
   endpoint=intake.hotel_sandbox_endpoint if adapter.vertical=='HOTEL' else intake.psp_sandbox_endpoint
   if b.get('endpoint_reference')!=endpoint:raise ValueError('ENDPOINT_MUST_MATCH_APPROVED_INTAKE')
   attested=bool(b.get('configuration_attested'))
   r=NamedSupplierAdapterBindingRow(adapter_binding_id=ident('nab'),named_adapter_id=adapter_id,endpoint_reference=endpoint,credential_binding_id=credential.credential_binding_id,allowlist_reference=intake.ip_allowlist_reference,test_resource_reference=intake.test_hotel_reference if adapter.vertical=='HOTEL' else intake.test_account_reference,configuration_attested=attested,state='BOUND_AND_ATTESTED' if attested and adapter.state=='IMPLEMENTATION_VERIFIED' else 'BINDING_INCOMPLETE',updated_at=now());s.add(r);s.commit();return out(r)
 def request_authorization(self,suite_id,b,actor):
  with SessionLocal() as s:
   suite=s.get(ExternalSandboxCertificationSuiteRow,suite_id)
   if not suite:raise ValueError('CERTIFICATION_SUITE_NOT_FOUND')
   hotel=s.get(NamedSupplierAdapterBindingRow,b['hotel_adapter_binding_id']);psp=s.get(NamedSupplierAdapterBindingRow,b['psp_adapter_binding_id'])
   if not hotel or not psp:raise ValueError('PAIRED_ADAPTER_BINDINGS_REQUIRED')
   ha=s.get(NamedSupplierAdapterRow,hotel.named_adapter_id);pa=s.get(NamedSupplierAdapterRow,psp.named_adapter_id)
   if ha.supplier_intake_id!=suite.supplier_intake_id or pa.supplier_intake_id!=suite.supplier_intake_id or ha.vertical!='HOTEL' or pa.vertical!='PAYMENT':raise ValueError('BINDINGS_MUST_MATCH_SUITE_AND_VERTICALS')
   expires=b.get('expires_at')
   if not expires or utc(expires)<=now():raise ValueError('FUTURE_AUTHORIZATION_EXPIRY_REQUIRED')
   ready=hotel.state=='BOUND_AND_ATTESTED' and psp.state=='BOUND_AND_ATTESTED'
   r=ExternalSandboxExecutionAuthorizationRow(execution_authorization_id=ident('esa'),certification_suite_id=suite_id,hotel_adapter_binding_id=hotel.adapter_binding_id,psp_adapter_binding_id=psp.adapter_binding_id,maker_id=actor,checker_id=None,evidence_reference=None,state='PENDING_CHECKER' if ready else 'BLOCKED_BINDINGS_INCOMPLETE',approved_at=None,expires_at=expires);s.add(r);s.commit();return out(r)
 def approve(self,authorization_id,b,actor):
  with SessionLocal() as s:
   r=s.get(ExternalSandboxExecutionAuthorizationRow,authorization_id)
   if not r:raise ValueError('EXECUTION_AUTHORIZATION_NOT_FOUND')
   if r.state!='PENDING_CHECKER':raise ValueError('AUTHORIZATION_NOT_APPROVABLE')
   if actor==r.maker_id:raise ValueError('MAKER_CHECKER_SEPARATION_REQUIRED')
   if not b.get('evidence_reference'):raise ValueError('APPROVAL_EVIDENCE_REQUIRED')
   r.checker_id=actor;r.evidence_reference=b['evidence_reference'];r.state='APPROVED_EXTERNAL_SANDBOX_ONLY';r.approved_at=now();s.commit();return out(r)
 def execute(self,authorization_id,b,actor):
  key=b.get('idempotency_key','')
  if not key:raise ValueError('IDEMPOTENCY_KEY_REQUIRED')
  with SessionLocal() as s:
   old=s.scalar(select(ExternalSandboxExecutionAttemptRow).where(ExternalSandboxExecutionAttemptRow.idempotency_key==key))
   if old:return out(old)
   auth=s.get(ExternalSandboxExecutionAuthorizationRow,authorization_id)
   if not auth:raise ValueError('EXECUTION_AUTHORIZATION_NOT_FOUND')
   blocker=None
   if auth.state!='APPROVED_EXTERNAL_SANDBOX_ONLY':blocker='EXTERNAL_SANDBOX_AUTHORIZATION_REQUIRED'
   elif utc(auth.expires_at)<=now():blocker='EXTERNAL_SANDBOX_AUTHORIZATION_EXPIRED'
   elif not external_sandbox_executor.configured:blocker='EXTERNAL_CONNECTOR_EXECUTOR_NOT_CONFIGURED'
   invoked=False;state='BLOCKED' if blocker else 'EXTERNAL_TRANSPORT_STARTED'
   if not blocker:
    external_sandbox_executor.execute(auth,b);invoked=True
   r=ExternalSandboxExecutionAttemptRow(execution_attempt_id=ident('exa'),execution_authorization_id=authorization_id,idempotency_key=key,state=state,blocker_code=blocker,transport_invoked=invoked,created_at=now());s.add(r);s.commit();return out(r)
 def record_transport_evidence(self,attempt_id,b,actor):
  with SessionLocal() as s:
   attempt=s.get(ExternalSandboxExecutionAttemptRow,attempt_id)
   if not attempt:raise ValueError('EXECUTION_ATTEMPT_NOT_FOUND')
   if not attempt.transport_invoked:raise ValueError('NO_REAL_EXTERNAL_TRANSPORT_TO_ATTEST')
   if not b.get('source_attested'):raise ValueError('SOURCE_ATTESTATION_REQUIRED')
   r=ExternalSandboxTransportEvidenceRow(transport_evidence_id=ident('ete'),execution_attempt_id=attempt_id,operation_type=b['operation_type'],supplier_reference=b['supplier_reference'],request_hash=digest(b.get('request',{})),response_hash=digest(b.get('response',{})),source_attested=True,recorded_at=now());s.add(r);s.commit();return out(r)
 def decide(self,attempt_id,actor):
  with SessionLocal() as s:
   attempt=s.get(ExternalSandboxExecutionAttemptRow,attempt_id)
   if not attempt:raise ValueError('EXECUTION_ATTEMPT_NOT_FOUND')
   evidence=s.scalars(select(ExternalSandboxTransportEvidenceRow).where(ExternalSandboxTransportEvidenceRow.execution_attempt_id==attempt_id)).all();observed=sorted({x.operation_type for x in evidence if x.source_attested});blockers=[x+'_REQUIRED' for x in REQUIRED_OPS if x not in observed]
   if not attempt.transport_invoked:blockers.insert(0,'REAL_EXTERNAL_TRANSPORT_REQUIRED')
   decision='EXTERNAL_SANDBOX_EXECUTION_VERIFIED' if not blockers else 'NOT_EXTERNALLY_VERIFIED'
   r=ExternalSandboxExecutionDecisionRow(execution_decision_id=ident('exd'),execution_attempt_id=attempt_id,required_operations_json=REQUIRED_OPS,observed_operations_json=observed,decision=decision,blockers_json=blockers,evidence_hash=digest([x.response_hash for x in evidence]),decided_at=now());s.add(r);s.commit();return out(r)
 def status(self,attempt_id):
  with SessionLocal() as s:
   attempt=s.get(ExternalSandboxExecutionAttemptRow,attempt_id)
   if not attempt:raise ValueError('EXECUTION_ATTEMPT_NOT_FOUND')
   decision=s.scalar(select(ExternalSandboxExecutionDecisionRow).where(ExternalSandboxExecutionDecisionRow.execution_attempt_id==attempt_id))
   return {'attempt':out(attempt),'decision':out(decision) if decision else None,'real_supplier_connected':False,'production_live':False}
 def dashboard(self):
  with SessionLocal() as s:return {'adapters':dict(s.execute(select(NamedSupplierAdapterRow.state,func.count()).group_by(NamedSupplierAdapterRow.state)).all()),'external_executor_configured':external_sandbox_executor.configured,'real_supplier_connected':False,'production_live':False}

named_supplier_external_execution_service=NamedSupplierExternalExecutionService()
