from datetime import datetime,timezone
import pytest
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import ProductionConnectorRow
from go_hotel.services.connector_activation_readiness import connector_activation_readiness_service as svc,CERT_CHECKS,MATERIAL_KEYS
def connector():
 with SessionLocal() as s:s.add(ProductionConnectorRow(connector_id='first_connector',connector_key='first-real-template',display_name='First Connector',vertical='HOTEL',supplier_legal_name='Pending Real Supplier',environment='PRODUCTION',lifecycle_state='ENGINEERING',active_capability_version=1,created_by='test',created_at=datetime.now(timezone.utc),updated_at=datetime.now(timezone.utc)));s.commit()
 return 'first_connector'
def complete(cid):
 svc.upsert_profile(cid,{'supplier_materials':{k:f'evidence://{k}' for k in MATERIAL_KEYS},'contacts':[{'role':'OPS','reference':'contact://ops'}]},'maker')
 svc.bind_kms(cid,{'provider':'AWS_KMS','resource_reference':'aws-kms://alias/go-first','purpose':'API_CREDENTIAL','access_test':{'passed':True,'evidence_reference':'evidence://kms-test'}},'security')
 svc.register_account(cid,{'supplier_account_reference':'supplier://account/prod','legal_entity_reference':'legal://entity','contract_reference':'contract://signed','authority_scopes':['BOOK','CANCEL','REFUND'],'evidence':[{'reference':'evidence://account'}],'supplier_verified':True},'legal')
 svc.set_allowlist(cid,{'cidrs':['203.0.113.10/32'],'environment':'PRODUCTION','verification':{'passed':True,'evidence_reference':'evidence://ip-test'}},'network')
 endpoint=svc.configure_webhook(cid,{'endpoint_reference':'https://api.go.example/v1/webhooks/first','active_key_reference':'vault://webhook/first','verification':{'challenge_passed':True,'signature_passed':True}},'security')
 checks={k:True for k in CERT_CHECKS}
 for env in ('SANDBOX','PRODUCTION'):svc.run_certification(cid,{'environment':env,'checks':checks,'evidence':[{'reference':f'evidence://cert/{env.lower()}'}]},'certifier')
 for typ in ('SMOKE','CANARY','ROLLBACK'):svc.record_drill(cid,{'drill_type':typ,'plan':{'controlled':True},'result':{'passed':True},'evidence':[{'reference':f'evidence://drill/{typ.lower()}'}]},'sre')
 svc.verify_financial_closure(cid,{'settlement_verified':True,'refund_verified':True,'reconciliation_verified':True,'evidence':[{'reference':'evidence://financial-closure'}]},'finance')
 return endpoint
def test_template_contains_supplier_materials_and_does_not_imply_live():
 t=svc.onboarding_template('hotel');assert set(t['required_materials'])==MATERIAL_KEYS and t['production_live_not_implied'] is True
def test_kms_interface_rejects_inline_secrets_and_non_external_reference():
 cid=connector()
 with pytest.raises(ValueError,match='EXTERNAL_KMS'):svc.bind_kms(cid,{'provider':'LOCAL','resource_reference':'plaintext'},'security')
 with pytest.raises(ValueError,match='INLINE_SECRET'):svc.bind_kms(cid,{'provider':'KMS','resource_reference':'aws-kms://alias/x','private_key':'leak'},'security')
def test_ip_allowlist_rejects_invalid_cidr():
 cid=connector()
 with pytest.raises(ValueError,match='INVALID_IP'):svc.set_allowlist(cid,{'cidrs':['999.1.1.1/32']},'network')
def test_certification_requires_full_suite_and_evidence():
 cid=connector();r=svc.run_certification(cid,{'environment':'SANDBOX','checks':{'connectivity':True},'evidence':[{'reference':'e'}]},'certifier');assert r['result']=='FAIL'
def test_webhook_rotation_requires_overlap_proof_and_external_key():
 cid=connector();endpoint=svc.configure_webhook(cid,{'endpoint_reference':'https://api.go.example/hook','active_key_reference':'vault://hook/old','verification':{'challenge_passed':True,'signature_passed':True}},'security')
 with pytest.raises(ValueError,match='OVERLAP_TEST'):svc.rotate_webhook_key(endpoint['webhook_endpoint_id'],{'new_key_reference':'vault://hook/new','overlap_test':{'passed':False}},'security')
 r=svc.rotate_webhook_key(endpoint['webhook_endpoint_id'],{'new_key_reference':'vault://hook/new','overlap_test':{'passed':True}},'security');assert r['rotation_state']=='ROTATED_VERIFIED' and r['previous_key_reference']=='vault://hook/old'
def test_incomplete_connector_is_blocked_with_explicit_reasons():
 cid=connector();r=svc.assess(cid,'admin');assert r['assessment']['readiness_state']=='NOT_READY' and r['assessment']['blockers_json'] and r['production_live'] is False
def test_complete_readiness_is_ready_for_external_activation_but_never_live():
 cid=connector();complete(cid);r=svc.assess(cid,'admin');assert r['assessment']['readiness_state']=='READY_FOR_EXTERNAL_ACTIVATION' and r['connector']['lifecycle_state']=='ENGINEERING' and r['production_live'] is False
