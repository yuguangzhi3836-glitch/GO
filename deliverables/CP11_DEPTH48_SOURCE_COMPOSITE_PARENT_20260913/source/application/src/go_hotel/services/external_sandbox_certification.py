from datetime import datetime,timezone
import hashlib,json,uuid
from sqlalchemy import select,func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (ConnectorPilotPairRow,ExternalSandboxSupplierIntakeRow,
 ExternalSandboxCredentialBindingRow,ExternalSandboxCertificationSuiteRow,
 ExternalSandboxCertificationRunRow,ExternalSandboxEvidenceImportRow,
 ExternalSandboxCallbackProofRow,ExternalSandboxCertificationDecisionRow)
from go_hotel.connectors.external_sandbox import external_sandbox_executor

REQUIRED_FIELDS=('hotel_supplier_name','psp_supplier_name','contract_reference','authority_reference',
 'hotel_sandbox_endpoint','psp_sandbox_endpoint','ip_allowlist_reference','test_hotel_reference',
 'test_account_reference','certification_window_start','certification_window_end')
SCENARIOS=['HOTEL_ORDER','HOTEL_QUERY','HOTEL_CANCEL','PSP_AUTHORIZE_CAPTURE','PSP_REFUND','PSP_SETTLEMENT_RECONCILIATION','HOTEL_WEBHOOK','PSP_CALLBACK']
def now():return datetime.now(timezone.utc)
def utc(v):return v.replace(tzinfo=timezone.utc) if v and v.tzinfo is None else v
def ident(p):return f'{p}_{uuid.uuid4().hex}'
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def out(r):return {c.name:(getattr(r,c.name).isoformat() if isinstance(getattr(r,c.name),datetime) else getattr(r,c.name)) for c in r.__table__.columns}

class ExternalSandboxCertificationService:
 def create_intake(self,b,actor):
  with SessionLocal() as s:
   pair=s.get(ConnectorPilotPairRow,b['pilot_pair_id'])
   if not pair:raise ValueError('PILOT_PAIR_NOT_FOUND')
   values={k:b.get(k) for k in REQUIRED_FIELDS};blockers=[k.upper()+'_REQUIRED' for k,v in values.items() if not v]
   r=ExternalSandboxSupplierIntakeRow(supplier_intake_id=ident('esi'),pilot_pair_id=pair.pilot_pair_id,**values,state='INPUTS_INCOMPLETE' if blockers else 'PENDING_CREDENTIAL_BINDINGS',blockers_json=blockers,updated_at=now());s.add(r);s.commit();return out(r)
 def update_intake(self,intake_id,b,actor):
  with SessionLocal() as s:
   r=s.get(ExternalSandboxSupplierIntakeRow,intake_id)
   if not r:raise ValueError('SUPPLIER_INTAKE_NOT_FOUND')
   for k in REQUIRED_FIELDS:
    if k in b:setattr(r,k,b[k])
   r.updated_at=now();s.commit();return self.assess(intake_id,actor)
 def bind_credential(self,intake_id,b,actor):
  vertical=b.get('vertical')
  if vertical not in ('HOTEL','PAYMENT'):raise ValueError('HOTEL_OR_PAYMENT_VERTICAL_REQUIRED')
  ref=b.get('secret_reference','')
  if not ref or any(x in ref.lower() for x in ('secret=','password=','token=')):raise ValueError('EXTERNAL_VAULT_REFERENCE_REQUIRED')
  with SessionLocal() as s:
   if not s.get(ExternalSandboxSupplierIntakeRow,intake_id):raise ValueError('SUPPLIER_INTAKE_NOT_FOUND')
   old=s.scalar(select(ExternalSandboxCredentialBindingRow).where(ExternalSandboxCredentialBindingRow.supplier_intake_id==intake_id,ExternalSandboxCredentialBindingRow.vertical==vertical))
   r=old or ExternalSandboxCredentialBindingRow(credential_binding_id=ident('ecb'),supplier_intake_id=intake_id,vertical=vertical)
   r.vault_provider=b.get('vault_provider','EXTERNAL');r.secret_reference=ref;r.credential_fingerprint=digest(ref);r.access_test_state='PASS' if b.get('access_test_passed') else 'PENDING';r.updated_at=now();s.add(r);s.commit();return out(r)
 def assess(self,intake_id,actor):
  with SessionLocal() as s:
   r=s.get(ExternalSandboxSupplierIntakeRow,intake_id)
   if not r:raise ValueError('SUPPLIER_INTAKE_NOT_FOUND')
   blockers=[k.upper()+'_REQUIRED' for k in REQUIRED_FIELDS if not getattr(r,k)]
   bindings=s.scalars(select(ExternalSandboxCredentialBindingRow).where(ExternalSandboxCredentialBindingRow.supplier_intake_id==intake_id)).all();by={x.vertical:x for x in bindings}
   for vertical in ('HOTEL','PAYMENT'):
    if vertical not in by:blockers.append(vertical+'_VAULT_BINDING_REQUIRED')
    elif by[vertical].access_test_state!='PASS':blockers.append(vertical+'_VAULT_ACCESS_TEST_REQUIRED')
   if r.certification_window_start and r.certification_window_end and r.certification_window_start>=r.certification_window_end:blockers.append('CERTIFICATION_WINDOW_INVALID')
   r.blockers_json=blockers;r.state='READY_FOR_EXTERNAL_EXECUTION' if not blockers else 'INPUTS_INCOMPLETE';r.updated_at=now();s.commit();return out(r)
 def create_suite(self,intake_id,b,actor):
  with SessionLocal() as s:
   intake=s.get(ExternalSandboxSupplierIntakeRow,intake_id)
   if not intake:raise ValueError('SUPPLIER_INTAKE_NOT_FOUND')
   version=(s.scalar(select(func.max(ExternalSandboxCertificationSuiteRow.suite_version)).where(ExternalSandboxCertificationSuiteRow.supplier_intake_id==intake_id)) or 0)+1
   r=ExternalSandboxCertificationSuiteRow(certification_suite_id=ident('ecs'),supplier_intake_id=intake_id,suite_version=version,required_scenarios_json=SCENARIOS,state='FRAMEWORK_READY',created_at=now());s.add(r);s.commit();return out(r)
 def execute(self,suite_id,b,actor):
  mode=b.get('execution_mode','FRAMEWORK_DRY_RUN');key=b.get('idempotency_key','')
  if not key:raise ValueError('IDEMPOTENCY_KEY_REQUIRED')
  with SessionLocal() as s:
   old=s.scalar(select(ExternalSandboxCertificationRunRow).where(ExternalSandboxCertificationRunRow.idempotency_key==key))
   if old:return out(old)
   suite=s.get(ExternalSandboxCertificationSuiteRow,suite_id)
   if not suite:raise ValueError('CERTIFICATION_SUITE_NOT_FOUND')
   intake=s.get(ExternalSandboxSupplierIntakeRow,suite.supplier_intake_id)
   if mode=='EXTERNAL_SANDBOX':
    if intake.state!='READY_FOR_EXTERNAL_EXECUTION':raise ValueError('EXTERNAL_SANDBOX_INPUTS_INCOMPLETE')
    current=now()
    if not utc(intake.certification_window_start)<=current<=utc(intake.certification_window_end):raise ValueError('OUTSIDE_CERTIFICATION_WINDOW')
    if not external_sandbox_executor.configured:raise ValueError('EXTERNAL_CONNECTOR_EXECUTOR_NOT_CONFIGURED')
    results=external_sandbox_executor.execute(intake,suite,b)
   elif mode=='FRAMEWORK_DRY_RUN':results={x:'FRAMEWORK_CONTRACT_PASS' for x in suite.required_scenarios_json}
   else:raise ValueError('UNSUPPORTED_EXECUTION_MODE')
   state='FRAMEWORK_DRY_RUN_COMPLETED' if mode=='FRAMEWORK_DRY_RUN' else 'EXTERNAL_SANDBOX_EXECUTED_PENDING_EVIDENCE'
   r=ExternalSandboxCertificationRunRow(certification_run_id=ident('ecr'),certification_suite_id=suite_id,execution_mode=mode,idempotency_key=key,state=state,scenario_results_json=results,started_at=now(),completed_at=now());s.add(r);s.commit();return out(r)
 def import_evidence(self,run_id,b,actor):
  with SessionLocal() as s:
   run=s.get(ExternalSandboxCertificationRunRow,run_id)
   if not run:raise ValueError('CERTIFICATION_RUN_NOT_FOUND')
   attested=bool(b.get('source_attested'))
   if run.execution_mode!='EXTERNAL_SANDBOX' and attested:raise ValueError('DRY_RUN_CANNOT_IMPORT_ATTESTED_EXTERNAL_EVIDENCE')
   ref=b.get('external_reference','')
   if not ref:raise ValueError('EXTERNAL_EVIDENCE_REFERENCE_REQUIRED')
   r=ExternalSandboxEvidenceImportRow(evidence_import_id=ident('eei'),certification_run_id=run_id,evidence_type=b.get('evidence_type','SUPPLIER_CERTIFICATION'),external_reference=ref,payload_hash=digest(b.get('payload',{})),source_attested=attested,imported_by=actor,imported_at=now());s.add(r);s.commit();return out(r)
 def callback_proof(self,run_id,b,actor):
  if not b.get('signature_verified'):raise ValueError('CALLBACK_SIGNATURE_VERIFICATION_REQUIRED')
  with SessionLocal() as s:
   run=s.get(ExternalSandboxCertificationRunRow,run_id)
   if not run:raise ValueError('CERTIFICATION_RUN_NOT_FOUND')
   old=s.scalar(select(ExternalSandboxCallbackProofRow).where(ExternalSandboxCallbackProofRow.delivery_id==b['delivery_id']))
   if old:return {'proof':out(old),'replay':True}
   r=ExternalSandboxCallbackProofRow(callback_proof_id=ident('ecp'),certification_run_id=run_id,source_vertical=b['source_vertical'],delivery_id=b['delivery_id'],signature_scheme=b.get('signature_scheme','SUPPLIER_DEFINED'),signature_verified=True,payload_hash=digest(b.get('payload',{})),verified_at=now());s.add(r);s.commit();return {'proof':out(r),'replay':False}
 def decide(self,run_id,b,actor):
  with SessionLocal() as s:
   run=s.get(ExternalSandboxCertificationRunRow,run_id)
   if not run:raise ValueError('CERTIFICATION_RUN_NOT_FOUND')
   checks={k:bool(b.get(k)) for k in ('order_verified','cancellation_verified','refund_verified','query_verified','callbacks_verified','reconciliation_verified')};blockers=[k.upper()+'_REQUIRED' for k,v in checks.items() if not v]
   evidence=s.scalars(select(ExternalSandboxEvidenceImportRow).where(ExternalSandboxEvidenceImportRow.certification_run_id==run_id)).all()
   if run.execution_mode!='EXTERNAL_SANDBOX':decision='FRAMEWORK_VALIDATED_NOT_EXTERNAL_CERTIFIED';blockers.append('REAL_EXTERNAL_SANDBOX_EXECUTION_REQUIRED')
   elif not evidence or not all(x.source_attested for x in evidence):decision='BLOCKED';blockers.append('ATTESTED_EXTERNAL_EVIDENCE_REQUIRED')
   else:decision='EXTERNAL_SANDBOX_CERTIFIED' if not blockers else 'BLOCKED'
   r=ExternalSandboxCertificationDecisionRow(certification_decision_id=ident('ecd'),certification_run_id=run_id,**checks,decision=decision,blockers_json=blockers,evidence_hash=digest({'checks':checks,'evidence':[x.payload_hash for x in evidence]}),decided_at=now());s.add(r);s.commit();return out(r)
 def status(self,run_id):
  with SessionLocal() as s:
   run=s.get(ExternalSandboxCertificationRunRow,run_id)
   if not run:raise ValueError('CERTIFICATION_RUN_NOT_FOUND')
   evidence=s.scalars(select(ExternalSandboxEvidenceImportRow).where(ExternalSandboxEvidenceImportRow.certification_run_id==run_id)).all();proofs=s.scalars(select(ExternalSandboxCallbackProofRow).where(ExternalSandboxCallbackProofRow.certification_run_id==run_id)).all();decision=s.scalar(select(ExternalSandboxCertificationDecisionRow).where(ExternalSandboxCertificationDecisionRow.certification_run_id==run_id))
   return {'run':out(run),'evidence':[out(x) for x in evidence],'callback_proofs':[out(x) for x in proofs],'decision':out(decision) if decision else None,'real_supplier_connected':False,'production_live':False}
 def dashboard(self):
  with SessionLocal() as s:return {'intakes':dict(s.execute(select(ExternalSandboxSupplierIntakeRow.state,func.count()).group_by(ExternalSandboxSupplierIntakeRow.state)).all()),'external_executor_configured':external_sandbox_executor.configured,'real_supplier_connected':False,'production_live':False}

external_sandbox_certification_service=ExternalSandboxCertificationService()
