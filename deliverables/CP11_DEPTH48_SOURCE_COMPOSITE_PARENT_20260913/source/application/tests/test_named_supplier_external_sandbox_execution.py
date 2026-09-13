from datetime import datetime,timezone,timedelta
import pytest
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import ProductionConnectorRow
from go_hotel.services.paired_connector_pilot import paired_connector_pilot_service as pilot
from go_hotel.services.external_sandbox_certification import external_sandbox_certification_service as cert
from go_hotel.services.named_supplier_external_execution import named_supplier_external_execution_service as svc

def base():
 t=datetime.now(timezone.utc)
 with SessionLocal() as s:
  for cid,vertical in [('hotel_named','HOTEL'),('psp_named','PAYMENT')]:s.add(ProductionConnectorRow(connector_id=cid,connector_key=cid,display_name=cid,vertical=vertical,supplier_legal_name='Pending',environment='SANDBOX',lifecycle_state='ENGINEERING',active_capability_version=1,created_by='test',created_at=t,updated_at=t))
  s.commit()
 p=pilot.create_pair({'hotel_connector_id':'hotel_named','psp_connector_id':'psp_named'},'admin');payload={'pilot_pair_id':p['pilot_pair_id'],'hotel_supplier_name':'Test Hotel Supplier','psp_supplier_name':'Test PSP','contract_reference':'contract://test','authority_reference':'authority://test','hotel_sandbox_endpoint':'https://hotel.example.invalid/sandbox','psp_sandbox_endpoint':'https://psp.example.invalid/sandbox','ip_allowlist_reference':'allowlist://test','test_hotel_reference':'hotel-test','test_account_reference':'account-test','certification_window_start':t-timedelta(minutes=5),'certification_window_end':t+timedelta(hours=1)};i=cert.create_intake(payload,'admin')
 hc=cert.bind_credential(i['supplier_intake_id'],{'vertical':'HOTEL','secret_reference':'kms://hotel/test','access_test_passed':True},'security');pc=cert.bind_credential(i['supplier_intake_id'],{'vertical':'PAYMENT','secret_reference':'kms://psp/test','access_test_passed':True},'security');cert.assess(i['supplier_intake_id'],'admin');suite=cert.create_suite(i['supplier_intake_id'],{},'admin');return i,hc,pc,suite
def adapters(verified=True):
 i,hc,pc,suite=base();h=svc.register_adapter(i['supplier_intake_id'],{'vertical':'HOTEL','supplier_name':'Test Hotel Supplier','adapter_key':'test-hotel-v1','capabilities':['BOOK','QUERY','CANCEL','WEBHOOK'],'implementation_reference':'code://hotel/test','implementation_verified':verified},'engineer');p=svc.register_adapter(i['supplier_intake_id'],{'vertical':'PAYMENT','supplier_name':'Test PSP','adapter_key':'test-psp-v1','capabilities':['AUTHORIZE','CAPTURE','REFUND','SETTLEMENT','CALLBACK'],'implementation_reference':'code://psp/test','implementation_verified':verified},'engineer');hb=svc.bind_adapter(h['named_adapter_id'],{'endpoint_reference':'https://hotel.example.invalid/sandbox','credential_binding_id':hc['credential_binding_id'],'configuration_attested':verified},'security');pb=svc.bind_adapter(p['named_adapter_id'],{'endpoint_reference':'https://psp.example.invalid/sandbox','credential_binding_id':pc['credential_binding_id'],'configuration_attested':verified},'security');return suite,hb,pb
def authorization():
 suite,hb,pb=adapters();a=svc.request_authorization(suite['certification_suite_id'],{'hotel_adapter_binding_id':hb['adapter_binding_id'],'psp_adapter_binding_id':pb['adapter_binding_id'],'expires_at':datetime.now(timezone.utc)+timedelta(hours=1)},'maker');return svc.approve(a['execution_authorization_id'],{'evidence_reference':'approval://test'},'checker')

def test_named_supplier_must_match_approved_intake():
 i,_,_,_=base()
 with pytest.raises(ValueError,match='NAMED_SUPPLIER_MUST_MATCH_INTAKE'):svc.register_adapter(i['supplier_intake_id'],{'vertical':'HOTEL','supplier_name':'Wrong','adapter_key':'wrong','capabilities':['BOOK','QUERY','CANCEL','WEBHOOK']},'engineer')
def test_required_capability_manifest_is_enforced():
 i,_,_,_=base()
 with pytest.raises(ValueError,match='CAPABILITY_MANIFEST_INCOMPLETE'):svc.register_adapter(i['supplier_intake_id'],{'vertical':'PAYMENT','supplier_name':'Test PSP','adapter_key':'short','capabilities':['REFUND']},'engineer')
def test_template_only_bindings_cannot_request_execution_approval():
 suite,hb,pb=adapters(False);a=svc.request_authorization(suite['certification_suite_id'],{'hotel_adapter_binding_id':hb['adapter_binding_id'],'psp_adapter_binding_id':pb['adapter_binding_id'],'expires_at':datetime.now(timezone.utc)+timedelta(hours=1)},'maker');assert a['state']=='BLOCKED_BINDINGS_INCOMPLETE'
def test_authorization_requires_maker_checker_separation():
 suite,hb,pb=adapters();a=svc.request_authorization(suite['certification_suite_id'],{'hotel_adapter_binding_id':hb['adapter_binding_id'],'psp_adapter_binding_id':pb['adapter_binding_id'],'expires_at':datetime.now(timezone.utc)+timedelta(hours=1)},'maker')
 with pytest.raises(ValueError,match='MAKER_CHECKER'):svc.approve(a['execution_authorization_id'],{'evidence_reference':'approval://test'},'maker')
def test_approved_execution_is_still_blocked_without_real_executor():
 a=authorization();attempt=svc.execute(a['execution_authorization_id'],{'idempotency_key':'external-attempt-1'},'operator');assert attempt['state']=='BLOCKED' and attempt['blocker_code']=='EXTERNAL_CONNECTOR_EXECUTOR_NOT_CONFIGURED' and attempt['transport_invoked'] is False
def test_blocked_attempt_cannot_create_fake_transport_evidence():
 a=authorization();attempt=svc.execute(a['execution_authorization_id'],{'idempotency_key':'external-attempt-1'},'operator')
 with pytest.raises(ValueError,match='NO_REAL_EXTERNAL_TRANSPORT'):svc.record_transport_evidence(attempt['execution_attempt_id'],{'operation_type':'HOTEL_BOOK','supplier_reference':'fake','source_attested':True},'operator')
def test_decision_never_claims_external_verification_without_transport():
 a=authorization();attempt=svc.execute(a['execution_authorization_id'],{'idempotency_key':'external-attempt-1'},'operator');d=svc.decide(attempt['execution_attempt_id'],'admin');status=svc.status(attempt['execution_attempt_id']);assert d['decision']=='NOT_EXTERNALLY_VERIFIED' and 'REAL_EXTERNAL_TRANSPORT_REQUIRED' in d['blockers_json'] and status['production_live'] is False
