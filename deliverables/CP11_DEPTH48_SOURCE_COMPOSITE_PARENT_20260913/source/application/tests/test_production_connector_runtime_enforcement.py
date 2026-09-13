from datetime import datetime,timezone
import hashlib,hmac,json
import pytest
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (ProductionConnectorRow,ConnectorAuthorityRow,ConnectorCredentialReferenceRow,ConnectorRuntimeHealthRow,ConnectorKillSwitchRow)
from go_hotel.services.production_connector_runtime import production_connector_runtime_service as svc

SECRET=b'production-webhook-secret'
def live_connector(state='LIVE'):
 t=datetime.now(timezone.utc);cid='conn_runtime'
 with SessionLocal() as s:
  s.add(ProductionConnectorRow(connector_id=cid,connector_key='runtime-primary',display_name='Runtime Primary',vertical='HOTEL',supplier_legal_name='Formal Supplier Ltd',environment='PRODUCTION',lifecycle_state=state,active_capability_version=1,created_by='test',created_at=t,updated_at=t))
  s.add(ConnectorAuthorityRow(connector_authority_id='auth_runtime',connector_id=cid,contract_reference='contract://signed',authority_scope_json=['BOOK','CANCEL','REFUND'],evidence_json=[{'reference':'evidence://contract'}],valid_from=t,state='ACTIVE'))
  s.add(ConnectorCredentialReferenceRow(credential_reference_id='cred_runtime',connector_id=cid,credential_kind='WEBHOOK_HMAC',secret_reference='vault://runtime/primary',state='ACTIVE',updated_at=t))
  s.add(ConnectorRuntimeHealthRow(connector_id=cid,health_state='HEALTHY',slo_json={'availability_bps':9990},telemetry_binding_json={'dashboard':'d','alert_policy':'a'},last_observed_at=t))
  s.add(ConnectorKillSwitchRow(connector_id=cid,engaged=False,fallback_mode='FAIL_CLOSED',changed_by='test',changed_at=t));s.commit()
 svc.set_secret_resolver(lambda ref:SECRET if ref=='vault://runtime/primary' else None)
 return cid
def submit(cid,key='key-1',max_attempts=8):return svc.submit(cid,{'operation_type':'BOOK','idempotency_key':key,'request':{'order_id':'o1'},'max_attempts':max_attempts})
def signature(payload):return hmac.new(SECRET,json.dumps(payload,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()

def test_non_live_connector_is_denied_before_supplier_mutation():
 cid=live_connector('CERTIFIED');decision=svc.authorize(cid,'BOOK')
 assert decision['decision']=='DENY' and 'CONNECTOR_NOT_LIVE' in decision['reason_codes_json']
 with pytest.raises(ValueError,match='RUNTIME_AUTHORIZATION_DENIED'):submit(cid)
def test_operation_idempotency_reuses_same_operation_and_rejects_payload_drift():
 cid=live_connector();a=submit(cid);b=submit(cid)
 assert a['runtime_operation_id']==b['runtime_operation_id']
 with pytest.raises(ValueError,match='PAYLOAD_MISMATCH'):svc.submit(cid,{'operation_type':'BOOK','idempotency_key':'key-1','request':{'order_id':'different'}})
def test_signed_webhook_converges_operation_and_duplicate_delivery_is_replay_safe():
 cid=live_connector();op=submit(cid);payload={'runtime_operation_id':op['runtime_operation_id'],'external_state':'CONFIRMED','supplier_reference':'supplier-confirmation'}
 first=svc.ingest_webhook(cid,'delivery-1',signature(payload),payload);second=svc.ingest_webhook(cid,'delivery-1',signature(payload),payload)
 assert first['operation']['state']=='CONFIRMED' and first['replay'] is False and second['replay'] is True
def test_repeated_invalid_webhook_signatures_engage_fail_safe_and_suspend():
 cid=live_connector();op=submit(cid);payload={'runtime_operation_id':op['runtime_operation_id'],'external_state':'CONFIRMED'}
 for i in range(3):
  with pytest.raises(ValueError,match='WEBHOOK_SIGNATURE_INVALID'):svc.ingest_webhook(cid,f'bad-{i}','invalid',payload)
 with SessionLocal() as s:
  assert s.get(ProductionConnectorRow,cid).lifecycle_state=='SUSPENDED' and s.get(ConnectorKillSwitchRow,cid).engaged is True
def test_unknown_external_state_never_authorizes_blind_resend_and_enters_manual_review():
 cid=live_connector();op=submit(cid,max_attempts=2)
 a=svc.record_poll(op['runtime_operation_id'],{'external_state':'UNKNOWN','evidence':{'poll':1}});b=svc.record_poll(op['runtime_operation_id'],{'external_state':'PENDING','evidence':{'poll':2}})
 assert a['operation']['state']=='UNKNOWN_EXTERNAL_STATE' and b['reconciliation']['state']=='MANUAL_REVIEW'
def test_poll_final_fact_converges_without_changing_supplier_evidence():
 cid=live_connector();op=submit(cid)
 result=svc.record_poll(op['runtime_operation_id'],{'external_state':'REFUNDED','supplier_reference':'refund-1','evidence':{'source':'supplier-query'}})
 assert result['operation']['state']=='REFUNDED' and result['reconciliation']['state']=='CONVERGED' and result['observation']['evidence_hash']
