from datetime import datetime,timezone,timedelta
import pytest
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import ProductionConnectorRow
from go_hotel.services.paired_connector_pilot import paired_connector_pilot_service as pilot
from go_hotel.services.external_sandbox_certification import external_sandbox_certification_service as svc

def pair():
 t=datetime.now(timezone.utc)
 with SessionLocal() as s:
  s.add(ProductionConnectorRow(connector_id='hotel_ext',connector_key='hotel-ext',display_name='Hotel External Intake',vertical='HOTEL',supplier_legal_name='Pending',environment='SANDBOX',lifecycle_state='ENGINEERING',active_capability_version=1,created_by='test',created_at=t,updated_at=t))
  s.add(ProductionConnectorRow(connector_id='psp_ext',connector_key='psp-ext',display_name='PSP External Intake',vertical='PAYMENT',supplier_legal_name='Pending',environment='SANDBOX',lifecycle_state='ENGINEERING',active_capability_version=1,created_by='test',created_at=t,updated_at=t));s.commit()
 return pilot.create_pair({'hotel_connector_id':'hotel_ext','psp_connector_id':'psp_ext'},'admin')
def complete_payload(pair_id):
 t=datetime.now(timezone.utc)
 return {'pilot_pair_id':pair_id,'hotel_supplier_name':'Named Hotel CRS','psp_supplier_name':'Named PSP','contract_reference':'contract://approved/1','authority_reference':'authority://distribution/1','hotel_sandbox_endpoint':'https://hotel.example.invalid/sandbox','psp_sandbox_endpoint':'https://psp.example.invalid/sandbox','ip_allowlist_reference':'allowlist://change/1','test_hotel_reference':'hotel-test-1','test_account_reference':'account-test-1','certification_window_start':t-timedelta(minutes=5),'certification_window_end':t+timedelta(hours=1)}
def ready_intake():
 p=pair();i=svc.create_intake(complete_payload(p['pilot_pair_id']),'admin')
 svc.bind_credential(i['supplier_intake_id'],{'vertical':'HOTEL','vault_provider':'AWS_KMS','secret_reference':'kms://hotel/sandbox','access_test_passed':True},'security')
 svc.bind_credential(i['supplier_intake_id'],{'vertical':'PAYMENT','vault_provider':'AWS_KMS','secret_reference':'kms://psp/sandbox','access_test_passed':True},'security')
 return svc.assess(i['supplier_intake_id'],'admin')
def dry_run():
 i=ready_intake();suite=svc.create_suite(i['supplier_intake_id'],{},'admin');return svc.execute(suite['certification_suite_id'],{'execution_mode':'FRAMEWORK_DRY_RUN','idempotency_key':'dry-1'},'admin')

def test_missing_external_inputs_are_explicit_blockers():
 p=pair();i=svc.create_intake({'pilot_pair_id':p['pilot_pair_id']},'admin')
 assert i['state']=='INPUTS_INCOMPLETE' and 'CONTRACT_REFERENCE_REQUIRED' in i['blockers_json']
def test_raw_credentials_are_rejected_and_only_vault_references_allowed():
 p=pair();i=svc.create_intake({'pilot_pair_id':p['pilot_pair_id']},'admin')
 with pytest.raises(ValueError,match='EXTERNAL_VAULT_REFERENCE_REQUIRED'):svc.bind_credential(i['supplier_intake_id'],{'vertical':'HOTEL','secret_reference':'password=plain'},'security')
def test_complete_intake_requires_both_credential_access_tests():
 i=ready_intake();assert i['state']=='READY_FOR_EXTERNAL_EXECUTION' and i['blockers_json']==[]
def test_framework_dry_run_is_idempotent_and_not_external_execution():
 i=ready_intake();suite=svc.create_suite(i['supplier_intake_id'],{},'admin');a=svc.execute(suite['certification_suite_id'],{'idempotency_key':'same'},'admin');b=svc.execute(suite['certification_suite_id'],{'idempotency_key':'same'},'admin')
 assert a['certification_run_id']==b['certification_run_id'] and a['state']=='FRAMEWORK_DRY_RUN_COMPLETED'
def test_external_execution_is_blocked_without_provider_executor():
 i=ready_intake();suite=svc.create_suite(i['supplier_intake_id'],{},'admin')
 with pytest.raises(ValueError,match='EXTERNAL_CONNECTOR_EXECUTOR_NOT_CONFIGURED'):svc.execute(suite['certification_suite_id'],{'execution_mode':'EXTERNAL_SANDBOX','idempotency_key':'external-1'},'admin')
def test_dry_run_cannot_import_attested_external_evidence():
 r=dry_run()
 with pytest.raises(ValueError,match='DRY_RUN_CANNOT_IMPORT'):svc.import_evidence(r['certification_run_id'],{'external_reference':'supplier://evidence/1','source_attested':True},'admin')
def test_callback_proof_is_signature_gated_and_replay_safe():
 r=dry_run();body={'source_vertical':'PAYMENT','delivery_id':'external-delivery-1','signature_scheme':'HMAC-SHA256','signature_verified':True,'payload':{'state':'refunded'}};a=svc.callback_proof(r['certification_run_id'],body,'gateway');b=svc.callback_proof(r['certification_run_id'],body,'gateway')
 assert a['replay'] is False and b['replay'] is True
def test_dry_run_decision_never_claims_external_certification_or_live():
 r=dry_run();checks={x:True for x in ('order_verified','cancellation_verified','refund_verified','query_verified','callbacks_verified','reconciliation_verified')};d=svc.decide(r['certification_run_id'],checks,'admin');status=svc.status(r['certification_run_id'])
 assert d['decision']=='FRAMEWORK_VALIDATED_NOT_EXTERNAL_CERTIFIED' and status['real_supplier_connected'] is False and status['production_live'] is False
