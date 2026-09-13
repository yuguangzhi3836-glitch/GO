from datetime import datetime,timezone
import hashlib,ipaddress,json,uuid
from sqlalchemy import select,func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (ProductionConnectorRow,ConnectorOnboardingProfileRow,ConnectorKmsBindingRow,
 ConnectorProductionAccountRow,ConnectorIpAllowlistRow,ConnectorWebhookEndpointRow,
 ConnectorReadinessCertificationRow,ConnectorActivationDrillRow,ConnectorFinancialClosureRow,
 ConnectorActivationReadinessRow)

VAULT_PREFIXES=('vault://','aws-kms://','gcp-kms://','azure-keyvault://','hsm://')
CERT_CHECKS={'connectivity','authentication','idempotency','signed_webhook','query_by_idempotency','reconciliation','settlement','refund','rate_limit','error_mapping'}
MATERIAL_KEYS={'supplier_legal_identity','signed_contract','distribution_authority','production_account','security_contact','operations_contact','finance_contact','data_processing_terms','incident_escalation'}
DRILLS={'SMOKE','CANARY','ROLLBACK'}
def now():return datetime.now(timezone.utc)
def ident(p):return f'{p}_{uuid.uuid4().hex}'
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def out(r):return {c.name:(getattr(r,c.name).isoformat() if isinstance(getattr(r,c.name),datetime) else getattr(r,c.name)) for c in r.__table__.columns}
class ConnectorActivationReadinessService:
 def _connector(self,s,cid):
  r=s.get(ProductionConnectorRow,cid)
  if not r:raise ValueError('CONNECTOR_NOT_FOUND')
  return r
 def onboarding_template(self,vertical):
  return {'template_key':f'{vertical.upper()}_PRODUCTION_V1','required_materials':sorted(MATERIAL_KEYS),'environments':['SANDBOX','PRODUCTION'],'required_drills':sorted(DRILLS),'production_live_not_implied':True}
 def upsert_profile(self,cid,b,actor):
  materials=b.get('supplier_materials',{});contacts=b.get('contacts',[]);state='COMPLETE' if MATERIAL_KEYS<=set(k for k,v in materials.items() if v) and contacts else 'INCOMPLETE'
  with SessionLocal() as s:
   c=self._connector(s,cid);r=s.scalar(select(ConnectorOnboardingProfileRow).where(ConnectorOnboardingProfileRow.connector_id==cid));vals={'template_key':b.get('template_key',f'{c.vertical}_PRODUCTION_V1'),'supplier_materials_json':materials,'contacts_json':contacts,'state':state,'updated_at':now()}
   if r:
    for k,v in vals.items():setattr(r,k,v)
   else:r=ConnectorOnboardingProfileRow(onboarding_profile_id=ident('onb'),connector_id=cid,**vals);s.add(r)
   s.commit();return out(r)
 def bind_kms(self,cid,b,actor):
  ref=b.get('resource_reference','')
  if not ref.startswith(VAULT_PREFIXES):raise ValueError('EXTERNAL_KMS_OR_VAULT_REFERENCE_REQUIRED')
  if any(k in b for k in ('secret','plaintext_key','private_key','api_key')):raise ValueError('INLINE_SECRET_FORBIDDEN')
  test=b.get('access_test',{});state='VERIFIED' if test.get('passed') and test.get('evidence_reference') else 'UNVERIFIED'
  with SessionLocal() as s:
   self._connector(s,cid);r=ConnectorKmsBindingRow(kms_binding_id=ident('kms'),connector_id=cid,provider=b['provider'],resource_reference=ref,purpose=b.get('purpose','API_CREDENTIAL'),access_test_json=test,state=state,updated_at=now());s.add(r);s.commit();return out(r)
 def register_account(self,cid,b,actor):
  evidence=b.get('evidence',[]);required=[b.get('supplier_account_reference'),b.get('legal_entity_reference'),b.get('contract_reference'),b.get('authority_scopes'),evidence];state='VERIFIED' if all(required) and b.get('supplier_verified') else 'PENDING_VERIFICATION'
  with SessionLocal() as s:
   self._connector(s,cid);r=ConnectorProductionAccountRow(production_account_id=ident('pa'),connector_id=cid,supplier_account_reference=b.get('supplier_account_reference','MISSING'),legal_entity_reference=b.get('legal_entity_reference','MISSING'),contract_reference=b.get('contract_reference','MISSING'),authority_scopes_json=b.get('authority_scopes',[]),evidence_json=evidence,state=state,verified_at=now() if state=='VERIFIED' else None);s.add(r);s.commit();return out(r)
 def set_allowlist(self,cid,b,actor):
  cidrs=b.get('cidrs',[])
  try:[ipaddress.ip_network(x,strict=False) for x in cidrs]
  except ValueError:raise ValueError('INVALID_IP_ALLOWLIST_CIDR')
  verification=b.get('verification',{});state='VERIFIED' if cidrs and verification.get('passed') and verification.get('evidence_reference') else 'UNVERIFIED'
  with SessionLocal() as s:
   self._connector(s,cid);r=ConnectorIpAllowlistRow(ip_allowlist_id=ident('ip'),connector_id=cid,direction=b.get('direction','EGRESS'),cidrs_json=cidrs,environment=b.get('environment','PRODUCTION'),verification_json=verification,state=state,updated_at=now());s.add(r);s.commit();return out(r)
 def configure_webhook(self,cid,b,actor):
  endpoint=b.get('endpoint_reference','');key=b.get('active_key_reference','')
  if not endpoint.startswith('https://'):raise ValueError('HTTPS_WEBHOOK_ENDPOINT_REQUIRED')
  if not key.startswith(VAULT_PREFIXES):raise ValueError('EXTERNAL_WEBHOOK_KEY_REFERENCE_REQUIRED')
  verification=b.get('verification',{});state='ACTIVE' if verification.get('challenge_passed') and verification.get('signature_passed') else 'PENDING_VERIFICATION'
  with SessionLocal() as s:
   self._connector(s,cid);r=ConnectorWebhookEndpointRow(webhook_endpoint_id=ident('whe'),connector_id=cid,endpoint_reference=endpoint,signature_scheme=b.get('signature_scheme','HMAC_SHA256'),active_key_reference=key,certificate_reference=b.get('certificate_reference'),certificate_expires_at=b.get('certificate_expires_at'),rotation_state=state,verification_json=verification,updated_at=now());s.add(r);s.commit();return out(r)
 def rotate_webhook_key(self,endpoint_id,b,actor):
  ref=b.get('new_key_reference','')
  if not ref.startswith(VAULT_PREFIXES):raise ValueError('EXTERNAL_WEBHOOK_KEY_REFERENCE_REQUIRED')
  if not b.get('overlap_test',{}).get('passed'):raise ValueError('WEBHOOK_KEY_OVERLAP_TEST_REQUIRED')
  with SessionLocal() as s:
   r=s.get(ConnectorWebhookEndpointRow,endpoint_id)
   if not r:raise ValueError('WEBHOOK_ENDPOINT_NOT_FOUND')
   r.previous_key_reference=r.active_key_reference;r.active_key_reference=ref;r.rotation_state='ROTATED_VERIFIED';r.verification_json=b['overlap_test'];r.updated_at=now();s.commit();return out(r)
 def run_certification(self,cid,b,actor):
  env=b.get('environment','').upper();checks=b.get('checks',{});evidence=b.get('evidence',[])
  if env not in {'SANDBOX','PRODUCTION'}:raise ValueError('CERTIFICATION_ENVIRONMENT_REQUIRED')
  result='PASS' if CERT_CHECKS<=set(k for k,v in checks.items() if v) and evidence else 'FAIL'
  with SessionLocal() as s:
   self._connector(s,cid);r=ConnectorReadinessCertificationRow(readiness_certification_id=ident('rcert'),connector_id=cid,environment=env,suite_key=b.get('suite_key','ACTIVATION_READINESS_V1'),checks_json=checks,evidence_json=evidence,result=result,executed_at=now());s.add(r);s.commit();return out(r)
 def record_drill(self,cid,b,actor):
  typ=b.get('drill_type','').upper()
  if typ not in DRILLS:raise ValueError('UNSUPPORTED_ACTIVATION_DRILL')
  result='PASS' if b.get('result',{}).get('passed') and b.get('evidence') and b.get('plan') else 'FAIL'
  with SessionLocal() as s:
   self._connector(s,cid);r=ConnectorActivationDrillRow(activation_drill_id=ident('drill'),connector_id=cid,drill_type=typ,plan_json=b.get('plan',{}),result_json=b.get('result',{}),evidence_json=b.get('evidence',[]),result=result,executed_at=now());s.add(r);s.commit();return out(r)
 def verify_financial_closure(self,cid,b,actor):
  evidence=b.get('evidence',[])
  with SessionLocal() as s:
   self._connector(s,cid);r=ConnectorFinancialClosureRow(financial_closure_id=ident('fin'),connector_id=cid,settlement_verified=bool(b.get('settlement_verified')),refund_verified=bool(b.get('refund_verified')),reconciliation_verified=bool(b.get('reconciliation_verified')),evidence_json=evidence,evidence_hash=digest(evidence),verified_at=now());s.add(r);s.commit();return out(r)
 def assess(self,cid,actor):
  with SessionLocal() as s:
   c=self._connector(s,cid);profile=s.scalar(select(ConnectorOnboardingProfileRow).where(ConnectorOnboardingProfileRow.connector_id==cid,ConnectorOnboardingProfileRow.state=='COMPLETE'));account=s.scalar(select(ConnectorProductionAccountRow).where(ConnectorProductionAccountRow.connector_id==cid,ConnectorProductionAccountRow.state=='VERIFIED'));kms=s.scalar(select(ConnectorKmsBindingRow).where(ConnectorKmsBindingRow.connector_id==cid,ConnectorKmsBindingRow.state=='VERIFIED'));ip=s.scalar(select(ConnectorIpAllowlistRow).where(ConnectorIpAllowlistRow.connector_id==cid,ConnectorIpAllowlistRow.state=='VERIFIED'));webhook=s.scalar(select(ConnectorWebhookEndpointRow).where(ConnectorWebhookEndpointRow.connector_id==cid,ConnectorWebhookEndpointRow.rotation_state.in_(['ACTIVE','ROTATED_VERIFIED'])));certs=s.scalars(select(ConnectorReadinessCertificationRow).where(ConnectorReadinessCertificationRow.connector_id==cid,ConnectorReadinessCertificationRow.result=='PASS')).all();envs={x.environment for x in certs};drills=s.scalars(select(ConnectorActivationDrillRow).where(ConnectorActivationDrillRow.connector_id==cid,ConnectorActivationDrillRow.result=='PASS')).all();types={x.drill_type for x in drills};fin=s.scalar(select(ConnectorFinancialClosureRow).where(ConnectorFinancialClosureRow.connector_id==cid).order_by(ConnectorFinancialClosureRow.verified_at.desc()))
   checks={'connector_not_live':c.lifecycle_state!='LIVE','onboarding_materials':bool(profile),'verified_production_account':bool(account),'verified_kms_binding':bool(kms),'verified_ip_allowlist':bool(ip),'verified_webhook_lifecycle':bool(webhook),'sandbox_certification':'SANDBOX' in envs,'production_certification':'PRODUCTION' in envs,'smoke_canary_rollback':DRILLS<=types,'financial_closure':bool(fin and fin.settlement_verified and fin.refund_verified and fin.reconciliation_verified and fin.evidence_json)};blockers=[k.upper() for k,v in checks.items() if not v];state='READY_FOR_EXTERNAL_ACTIVATION' if not blockers else 'NOT_READY'
   r=ConnectorActivationReadinessRow(activation_readiness_id=ident('ready'),connector_id=cid,readiness_state=state,checks_json=checks,blockers_json=blockers,evidence_hash=digest(checks),assessed_by=actor,assessed_at=now());s.add(r);s.commit();return {'connector':out(c),'assessment':out(r),'production_live':False}
 def dashboard(self):
  with SessionLocal() as s:return {'readiness':dict(s.execute(select(ConnectorActivationReadinessRow.readiness_state,func.count()).group_by(ConnectorActivationReadinessRow.readiness_state)).all()),'production_live_not_implied':True,'external_activation_required':True}
connector_activation_readiness_service=ConnectorActivationReadinessService()
