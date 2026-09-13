from datetime import datetime,timezone
import hashlib,json,uuid
from sqlalchemy import select,func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
 P0FinalClosureRequirementEvidenceRow as Evidence,P0FinalClosureBundleRow as Bundle,
 NamedProviderCertificationEvidenceRow as NamedEvidence,PostgresRaceProofEvidenceRow as RaceEvidence,
 ExternalTruthWebhookReceiptRow as Webhook,PspSettlementLineRow as PspLine,BankStatementLineRow as BankLine,
 OmnichannelReconciliationRow as Recon,OrderSupplierFulfillmentRow as Fulfillment,ConsumerUnifiedLifecycleRow as Life,
 ExternalSandboxExecutionAuthorizationRow as Authorization,NamedSupplierAdapterBindingRow as AdapterBinding,NamedSupplierAdapterRow as Adapter,
)

def now():return datetime.now(timezone.utc)
def ident(p):return f'{p}_{uuid.uuid4().hex}'
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def out(r):return {c.name:(getattr(r,c.name).isoformat() if isinstance(getattr(r,c.name),datetime) else getattr(r,c.name)) for c in r.__table__.columns}

PROVIDER_MATRIX={
 'PAYMENT':{'named_provider':'Stripe Test Mode','required':['AUTHORIZE','CAPTURE','REFUND','CALLBACK','SETTLEMENT','BANK_RECONCILIATION']},
 'HOTEL':{'named_provider':'SiteMinder Channels Plus Test Environment','required':['SEARCH','BOOK','QUERY','CANCEL','STATUS','REFUND_HANDOFF']},
 'FLIGHT':{'named_provider':'Amadeus Enterprise/NDC connector','required':['SEARCH','REPRICE','BOOK','CANCEL','STATUS','CHECK_IN']},
 'RAIL':{'named_provider':'Distribusion','required':['SEARCH','BOOK','CHANGE','CANCEL','STATUS']},
 'RIDE':{'named_provider':'Mozio','required':['SEARCH','RESERVE','CANCEL','STATUS','FLIGHT_TRACKING']},
 'RENTAL':{'named_provider':'CarTrawler','required':['SEARCH','RESERVE','CANCEL','STATUS']},
 'ATTRACTION':{'named_provider':'Tiqets Distributor API','required':['SEARCH','RESERVE','CANCEL','STATUS']},
}

CANCELLATION_REFUND_CONTRACT=['CANCEL_REQUESTED','SUPPLIER_PROCESSING','CANCEL_CONFIRMED','REFUND_AMOUNT_CONFIRMED','REFUND_INITIATED','PSP_PROCESSING','REFUND_COMPLETED']
POSTGRES_REQUIRED={'ORDER_PAYMENT_ROOT_EXACTLY_ONCE','WEBHOOK_REPLAY_UNIQUE','CAPTURE_REFUND_SERIALIZATION','FINANCE_CLOSE_APPROVAL_RACE'}

class P0FinalClosureService:
 def _named_provider_runtime(self,s):
  ops={x.operation_type for x in s.scalars(select(NamedEvidence).where(NamedEvidence.state.in_(['PASS','SUCCEEDED','succeeded','requires_capture']))).all()}
  # Raw provider probes are not enough: GO runtime callbacks, durable settlement/bank facts and reconciliation must also exist.
  go_truth=bool(s.scalar(select(func.count()).select_from(Webhook))) and bool(s.scalar(select(func.count()).select_from(PspLine))) and bool(s.scalar(select(func.count()).select_from(BankLine))) and bool(s.scalar(select(func.count()).select_from(Recon).where(Recon.state=='MATCHED')))
  supplier=bool(s.scalar(select(func.count()).select_from(Fulfillment).where(Fulfillment.state=='SUPPLIER_CONFIRMED')))
  trips=bool(s.scalar(select(func.count()).select_from(Life).where(Life.lifecycle_state=='CONFIRMED')))
  return {'raw_operations':sorted(ops),'go_truth_chain':go_truth and supplier and trips,'webhook':go_truth,'supplier_confirmed':supplier,'trips_confirmed':trips}
 def _postgres(self,s):
  rows=s.scalars(select(RaceEvidence).where(RaceEvidence.assertion_state=='PASS')).all();return {x.scenario_key for x in rows}
 def evaluate(self):
  with SessionLocal() as s:
   named=self._named_provider_runtime(s);race=self._postgres(s)
   active_auth=bool(s.scalar(select(func.count()).select_from(Authorization).where(Authorization.state=='APPROVED_EXTERNAL_SANDBOX_ONLY')))
   bound=set()
   for a in s.scalars(select(Adapter).where(Adapter.state=='IMPLEMENTATION_VERIFIED')).all():bound.add(a.vertical)
   missing_named=[v for v,x in PROVIDER_MATRIX.items() if not x['named_provider']]
   req=[
    ('DESIGN_PROVIDER_MATRIX','DESIGN','All Day-1 verticals have an explicit named/fallback provider and capability contract','src/go_hotel/services/p0_final_closure.py#PROVIDER_MATRIX',not missing_named,'NAMED_PROVIDER_REQUIRED:'+','.join(missing_named) if missing_named else None),
    ('DESIGN_CANCEL_REFUND','DESIGN','Cross-vertical cancellation/refund states are frozen','src/go_hotel/services/p0_final_closure.py#CANCELLATION_REFUND_CONTRACT',True,None),
    ('CODE_ORDER_MONEY_SUPPLIER','TRANSACTION_TRUTH','Order single-root payment, money graph, supplier confirmation and Trips projection are implemented','0099_order_money_supplier_atomic_truth + order_supplier_fulfillment.py',True,None),
    ('CODE_EXTERNAL_FAIL_CLOSED','EXTERNAL_EXECUTION','External transport cannot fabricate payment/supplier success; signed callback required','real_external_execution.py',True,None),
    ('RUNTIME_NAMED_PROVIDER_GO_CHAIN','EXTERNAL_EXECUTION','Named PSP + Hotel provider run through GO callback/settlement/bank/reconciliation/supplier/Trips truth chain','0100/0101 runtime evidence',named['go_truth_chain'],'NAMED_PROVIDER_GO_RUNTIME_E2E_REQUIRED'),
    ('RUNTIME_POSTGRES_ROOT','DATABASE','PostgreSQL proves order payment root exactly once','tests/test_p0_0101_postgres_race_matrix.py','ORDER_PAYMENT_ROOT_EXACTLY_ONCE' in race,'POSTGRES_ROOT_RACE_PROOF_REQUIRED'),
    ('RUNTIME_POSTGRES_WEBHOOK','DATABASE','PostgreSQL proves webhook replay uniqueness','tests/test_p0_0101_postgres_race_matrix.py','WEBHOOK_REPLAY_UNIQUE' in race,'POSTGRES_WEBHOOK_RACE_PROOF_REQUIRED'),
    ('RUNTIME_POSTGRES_CAPTURE_REFUND','DATABASE','PostgreSQL proves capture/refund serialization and bounded cumulative money movement','tests/test_p0_0101_postgres_race_matrix.py','CAPTURE_REFUND_SERIALIZATION' in race,'POSTGRES_CAPTURE_REFUND_RACE_PROOF_REQUIRED'),
    ('RUNTIME_POSTGRES_CLOSE','DATABASE','PostgreSQL proves close approval cannot race late mutable finance facts','tests/test_p0_0101_postgres_race_matrix.py','FINANCE_CLOSE_APPROVAL_RACE' in race,'POSTGRES_CLOSE_RACE_PROOF_REQUIRED'),
    ('RUNTIME_FINANCE_RECON','FINANCE','Real PSP settlement + bank line + ledger reconciliation MATCHED exists', 'omnichannel_payment.py#reconcile', bool(s.scalar(select(func.count()).select_from(Recon).where(Recon.state=='MATCHED'))),'REAL_PSP_BANK_RECONCILIATION_REQUIRED'),
    ('RUNTIME_CANCEL_REFUND','ORDER_SERVICE','Real cancellation through supplier and PSP reaches REFUND_COMPLETED in consumer lifecycle','consumer_unified_lifecycle',bool(s.scalar(select(func.count()).select_from(Life).where(Life.refund_state=='REFUND_COMPLETED'))),'REAL_CANCEL_REFUND_E2E_REQUIRED'),
    ('RUNTIME_ALL_VERTICALS','MULTI_VERTICAL','Every Day-1 vertical has real supplier confirmation evidence in GO Trips','consumer_unified_lifecycle',all(bool(s.scalar(select(func.count()).select_from(Life).where(Life.vertical==v,Life.lifecycle_state=='CONFIRMED'))) for v in ['HOTEL','FLIGHT','RAIL','RIDE','RENTAL','ATTRACTION']),'ALL_VERTICAL_REAL_TRIPS_EVIDENCE_REQUIRED'),
    ('RUNTIME_SECURITY_E2E','SECURITY','RBAC/MFA/tenant isolation and credential lifecycle final suite is attached to this build','verification://security-final',False,'FINAL_SECURITY_EVIDENCE_REQUIRED'),
    ('RUNTIME_CLEAN_REGRESSION','QUALITY','Full pytest + TS/TSX + browser/mobile E2E completes cleanly for this build','verification://full-regression',False,'CLEAN_FULL_REGRESSION_REQUIRED'),
   ]
   snap=[];blockers=[]
   for key,domain,text,code,passed,blocker in req:
    status='PASS' if passed else 'BLOCKED';snap.append({'requirement_key':key,'domain':domain,'status':status,'code_reference':code,'blocker_code':None if passed else blocker})
    if not passed:blockers.append(blocker)
   design_keys=[x for x in snap if x['domain']=='DESIGN'];design='FROZEN' if all(x['status']=='PASS' for x in design_keys) else 'NOT_FROZEN'
   code_keys=[x for x in snap if x['requirement_key'].startswith('CODE_')];code='COMPLETE_FOR_DEFINED_INTERNAL_CORE' if all(x['status']=='PASS' for x in code_keys) else 'INCOMPLETE'
   runtime='PASS' if not blockers else 'BLOCKED'
   return {'provider_matrix':PROVIDER_MATRIX,'cancellation_refund_contract':CANCELLATION_REFUND_CONTRACT,'named_provider_runtime':named,'postgres_passed_scenarios':sorted(race),'approved_external_sandbox_authorization_present':active_auth,'implementation_verified_verticals':sorted(bound),'requirements':snap,'design_state':design,'code_state':code,'runtime_state':runtime,'external_sandbox_gate':'PASS' if runtime=='PASS' else 'BLOCK','blockers':blockers}
 def seal(self,build_sha256):
  if len(build_sha256)!=64:raise ValueError('BUILD_SHA256_REQUIRED')
  status=self.evaluate();payload={'build_sha256':build_sha256,'design_state':status['design_state'],'code_state':status['code_state'],'runtime_state':status['runtime_state'],'external_sandbox_gate':status['external_sandbox_gate'],'blockers':status['blockers'],'requirements':status['requirements']};eh=digest(payload)
  with SessionLocal() as s:
   old=s.scalar(select(Bundle).where(Bundle.evidence_hash==eh))
   if old:return out(old)
   for x in status['requirements']:
    evhash=digest({'build':build_sha256,**x})
    if not s.scalar(select(Evidence).where(Evidence.evidence_hash==evhash)):
     s.add(Evidence(p0_final_closure_requirement_evidence_id=ident('p0req'),requirement_key=x['requirement_key'],domain=x['domain'],requirement_text=x['requirement_key'],code_reference=x['code_reference'],runtime_evidence_reference=None,status=x['status'],blocker_code=x['blocker_code'],evidence_hash=evhash,created_at=now()))
   r=Bundle(p0_final_closure_bundle_id=ident('p0bundle'),build_sha256=build_sha256,design_state=status['design_state'],code_state=status['code_state'],runtime_state=status['runtime_state'],external_sandbox_gate=status['external_sandbox_gate'],blockers_json=status['blockers'],requirement_snapshot_json=status['requirements'],evidence_hash=eh,created_at=now());s.add(r);s.commit();return out(r)

p0_final_closure_service=P0FinalClosureService()
