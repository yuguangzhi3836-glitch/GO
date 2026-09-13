import pytest
from go_hotel.services.production_connectors import production_connector_service as svc, REQUIRED_CAPABILITIES
def connector(environment='PRODUCTION'):
 return svc.register({'connector_key':'hotel-primary','display_name':'Hotel Primary','vertical':'HOTEL','supplier_legal_name':'Formal Supplier Ltd','environment':environment},'maker')
def capabilities():
 return {**{k:True for k in REQUIRED_CAPABILITIES},'settlement':True,'refund':True,'fail_safe':True}
def prepare_switchable():
 row=connector(); cid=row['connector_id']
 svc.bind_capabilities(cid,{'capabilities':capabilities()},'maker')
 svc.bind_authority(cid,{'contract_reference':'contract://signed/001','authority_scope':['BOOK','CANCEL','REFUND'],'evidence':[{'type':'SIGNED_CONTRACT','reference':'evidence://contract/001'}]},'legal')
 svc.bind_credential(cid,{'credential_kind':'OAUTH_CLIENT','secret_reference':'vault://production/connectors/hotel-primary'},'security')
 checks={'connectivity':True,'idempotency':True,'signed_webhook':True,'query_by_idempotency':True,'reconciliation':True,'refund':True,'settlement':True}
 svc.record_certification(cid,{'environment':'SANDBOX','checks':checks,'evidence':[{'reference':'evidence://sandbox/cert'}]},'certifier')
 svc.record_certification(cid,{'environment':'PRODUCTION','checks':checks,'evidence':[{'reference':'evidence://production/cert'}]},'certifier')
 svc.bind_health(cid,{'health_state':'HEALTHY','slo':{'availability_bps':9990},'telemetry_binding':{'dashboard':'monitor://connector/hotel-primary','alert_policy':'alert://connector/hotel-primary'}},'sre')
 svc.set_kill_switch(cid,{'engaged':False,'fallback_mode':'FAIL_CLOSED'},'sre')
 return cid

def test_engineering_or_sandbox_adapter_never_passes_live_gate():
 cid=connector('SANDBOX')['connector_id']
 result=svc.assess_live_gate(cid,'admin')
 assert result['assessment']['gate_state']=='BLOCK'
 assert 'PRODUCTION_ENVIRONMENT' in result['assessment']['blockers_json']

def test_inline_secret_is_forbidden_and_external_reference_required():
 cid=connector()['connector_id']
 with pytest.raises(ValueError,match='EXTERNAL_SECRET_REFERENCE'): svc.bind_credential(cid,{'credential_kind':'API_KEY','secret_reference':'plain-text'},'security')
 with pytest.raises(ValueError,match='INLINE_SECRET_FORBIDDEN'): svc.bind_credential(cid,{'credential_kind':'API_KEY','secret_reference':'vault://x','api_key':'leak'},'security')

def test_production_certification_requires_sandbox_first_in_state_machine():
 cid=connector()['connector_id']; svc.bind_capabilities(cid,{'capabilities':capabilities()},'maker')
 result=svc.record_certification(cid,{'environment':'PRODUCTION','checks':{'connectivity':True,'idempotency':True,'signed_webhook':True,'query_by_idempotency':True,'reconciliation':True,'refund':True,'settlement':True},'evidence':[{'reference':'e'}]},'certifier')
 assert result['connector']['lifecycle_state']=='CONNECTABLE'

def test_live_gate_blocks_missing_contract_certification_observability_and_fail_safe():
 cid=connector()['connector_id']; svc.bind_capabilities(cid,{'capabilities':capabilities()},'maker')
 result=svc.assess_live_gate(cid,'admin')
 assert result['assessment']['gate_state']=='BLOCK'
 assert {'CONTRACT_AUTHORITY','EXTERNAL_SECRET_REFERENCE','SANDBOX_CERTIFICATION','PRODUCTION_CERTIFICATION','RUNTIME_OBSERVABLE','KILL_SWITCH_READY'} <= set(result['assessment']['blockers_json'])

def test_full_gate_then_maker_checker_activation_reaches_live():
 cid=prepare_switchable(); gate=svc.assess_live_gate(cid,'gate-admin')
 assert gate['assessment']['gate_state']=='PASS' and gate['connector']['lifecycle_state']=='SWITCHABLE'
 change=svc.request_activation(cid,{'target_state':'LIVE','live_gate_assessment_id':gate['assessment']['live_gate_assessment_id'],'change_window':{'approved':True,'start':'approved-window'},'rollback_plan':{'tested':True,'mode':'FAIL_CLOSED'},'smoke_test':{'passed':True,'suite':'production-smoke-v1'}},'maker')
 with pytest.raises(ValueError,match='MAKER_CHECKER'): svc.approve_activation(change['activation_change_id'],'maker')
 result=svc.approve_activation(change['activation_change_id'],'checker')
 assert result['connector']['lifecycle_state']=='LIVE' and result['activation']['state']=='EXECUTED'

def test_kill_switch_suspends_live_connector_and_records_fail_safe():
 cid=prepare_switchable(); gate=svc.assess_live_gate(cid,'gate-admin'); change=svc.request_activation(cid,{'target_state':'LIVE','live_gate_assessment_id':gate['assessment']['live_gate_assessment_id'],'change_window':{'approved':True,'id':'cw'},'rollback_plan':{'tested':True,'mode':'FAIL_CLOSED'},'smoke_test':{'passed':True,'suite':'smoke'}},'maker'); svc.approve_activation(change['activation_change_id'],'checker')
 result=svc.set_kill_switch(cid,{'engaged':True,'fallback_mode':'FAIL_CLOSED','reason':'SLO_BREACH'},'incident-commander')
 assert result['connector']['lifecycle_state']=='SUSPENDED' and result['kill_switch']['engaged'] is True
