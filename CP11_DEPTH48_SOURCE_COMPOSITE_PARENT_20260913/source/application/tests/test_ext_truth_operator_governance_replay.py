from datetime import datetime,timezone,timedelta
import hashlib,hmac,json
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
 ProductionConnectorRow,ConnectorAuthorityRow,ConnectorCredentialReferenceRow,ConnectorRuntimeHealthRow,ConnectorKillSwitchRow,
 ConnectorRuntimeReconciliationRow,ConnectorRuntimeObservationRow,ConnectorRuntimeSafetyEventRow
)
from go_hotel.services.production_connector_runtime import production_connector_runtime_service as svc
from go_hotel.journey.recovery_runtime_observability import recovery_runtime_observability_service as safety

SECRET=b'op-workflow-secret'
def setup_connector(vertical='FLIGHT',key='op-gov'):
 t=datetime.now(timezone.utc);cid=f'conn_{key}'
 with SessionLocal() as s:
  s.add(ProductionConnectorRow(connector_id=cid,connector_key=key,display_name=key,vertical=vertical,supplier_legal_name='Supplier',environment='PRODUCTION',lifecycle_state='LIVE',active_capability_version=1,created_by='test',created_at=t,updated_at=t))
  s.add(ConnectorAuthorityRow(connector_authority_id=f'auth_{key}',connector_id=cid,contract_reference='contract://signed',authority_scope_json=['BOOK','CANCEL','REFUND'],evidence_json=[{'reference':'evidence://contract'}],valid_from=t,state='ACTIVE'))
  s.add(ConnectorCredentialReferenceRow(credential_reference_id=f'cred_{key}',connector_id=cid,credential_kind='WEBHOOK_HMAC',secret_reference=f'vault://{key}',state='ACTIVE',updated_at=t))
  s.add(ConnectorRuntimeHealthRow(connector_id=cid,health_state='HEALTHY',slo_json={'availability_bps':9990},telemetry_binding_json={'dashboard':'d','alert_policy':'a'},last_observed_at=t))
  s.add(ConnectorKillSwitchRow(connector_id=cid,engaged=False,fallback_mode='FAIL_CLOSED',changed_by='test',changed_at=t));s.commit()
 svc.set_secret_resolver(lambda ref:SECRET)
 return cid

def incident(key='op-gov',vertical='FLIGHT'):
 cid=setup_connector(vertical,key)
 op=svc.submit(cid,{'operation_type':'BOOK','idempotency_key':f'idem-{key}','request':{'order_id':f'order-{key}'},'max_attempts':1})
 result=svc.record_poll(op['runtime_operation_id'],{'external_state':'UNKNOWN','evidence':{'poll':1}})
 assert result['reconciliation']['state']=='MANUAL_REVIEW'
 return cid,op,result['reconciliation']

def sig(payload):return hmac.new(SECRET,json.dumps(payload,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()

def test_claim_is_replay_safe_and_lease_takeover_requires_expiry():
 _,_,rec=incident('claim')
 first=svc.claim(rec['reconciliation_id'],'maker-a',600);second=svc.claim(rec['reconciliation_id'],'maker-a',600)
 assert second['replay'] is True and second['reconciliation']['lease_expires_at']==first['reconciliation']['lease_expires_at']
 with pytest.raises(ValueError,match='INCIDENT_ALREADY_CLAIMED'):svc.claim(rec['reconciliation_id'],'maker-b',600)
 with SessionLocal() as s:
  r=s.get(ConnectorRuntimeReconciliationRow,rec['reconciliation_id']);r.lease_expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);s.commit()
 takeover=svc.claim(rec['reconciliation_id'],'maker-b',600)
 assert takeover['reconciliation']['claimed_by']=='maker-b' and takeover['reconciliation']['escalation_level']==1

def test_maker_checker_resolution_and_checker_replay_are_exactly_once():
 _,op,rec=incident('approve')
 svc.claim(rec['reconciliation_id'],'maker',600)
 proposal={'terminal_state':'FAILED','evidence':{'supplier_status':'FAILED'},'evidence_reference':'case://1'}
 a=svc.submit_resolution(rec['reconciliation_id'],'maker',proposal);b=svc.submit_resolution(rec['reconciliation_id'],'maker',proposal)
 assert a['replay'] is False and b['replay'] is True
 with pytest.raises(ValueError,match='MAKER_CHECKER_REQUIRED'):svc.review_resolution(rec['reconciliation_id'],'maker','APPROVE','review://self')
 approved=svc.review_resolution(rec['reconciliation_id'],'checker','APPROVE','review://ok')
 replay=svc.review_resolution(rec['reconciliation_id'],'checker','APPROVE','review://ok')
 assert approved['result']['terminal_state']=='FAILED' and replay['replay'] is True
 assert svc.get_operation(op['runtime_operation_id'])['operation']['state']=='FAILED'

def test_evidence_digest_blocks_post_submission_tampering():
 _,_,rec=incident('digest')
 svc.claim(rec['reconciliation_id'],'maker',600)
 svc.submit_resolution(rec['reconciliation_id'],'maker',{'terminal_state':'FAILED','evidence':{'truth':'A'},'evidence_reference':'case://digest'})
 with SessionLocal() as s:
  r=s.get(ConnectorRuntimeReconciliationRow,rec['reconciliation_id']);r.resolution_payload_json={'terminal_state':'CONFIRMED','evidence':{'truth':'B'},'evidence_reference':'case://digest'};s.commit()
 with pytest.raises(ValueError,match='RESOLUTION_EVIDENCE_DIGEST_MISMATCH'):svc.review_resolution(rec['reconciliation_id'],'checker','APPROVE','review://digest')
 with SessionLocal() as s:
  assert s.scalar(select(ConnectorRuntimeSafetyEventRow).where(ConnectorRuntimeSafetyEventRow.event_type=='RESOLUTION_EVIDENCE_DIGEST_MISMATCH')) is not None

def test_real_external_terminal_truth_supersedes_unapproved_manual_draft():
 cid,op,rec=incident('supersede')
 svc.claim(rec['reconciliation_id'],'maker',600)
 svc.submit_resolution(rec['reconciliation_id'],'maker',{'terminal_state':'FAILED','evidence':{'manual':'failed'},'evidence_reference':'case://draft'})
 payload={'runtime_operation_id':op['runtime_operation_id'],'external_state':'CONFIRMED','supplier_reference':'supplier-confirmed'}
 x=svc.ingest_webhook(cid,'delivery-final',sig(payload),payload)
 assert x['operation']['state']=='CONFIRMED' and x['reconciliation']['superseded_reason']=='SUPERSEDED_BY_EXTERNAL_TRUTH'
 with pytest.raises(ValueError,match='RESOLUTION_NOT_PENDING_CHECKER'):svc.review_resolution(rec['reconciliation_id'],'checker','APPROVE','review://late')

def test_webhook_delivery_payload_drift_is_truth_conflict():
 cid,op,_=incident('drift')
 p1={'runtime_operation_id':op['runtime_operation_id'],'external_state':'CONFIRMED'}
 svc.ingest_webhook(cid,'same-delivery',sig(p1),p1)
 p2={'runtime_operation_id':op['runtime_operation_id'],'external_state':'FAILED'}
 with pytest.raises(ValueError,match='WEBHOOK_DELIVERY_PAYLOAD_CONFLICT'):svc.ingest_webhook(cid,'same-delivery',sig(p2),p2)

def test_sla_queue_freezes_promise_supplier_and_finance_and_blocks_promotion_until_resolution():
 _,op,rec=incident('sla')
 with SessionLocal() as s:
  obs=s.scalar(select(ConnectorRuntimeObservationRow).where(ConnectorRuntimeObservationRow.runtime_operation_id==op['runtime_operation_id']))
  obs.observed_at=datetime.now(timezone.utc)-timedelta(minutes=11);s.commit()
 q=next(x for x in svc.due_reconciliations() if x['operation']['runtime_operation_id']==op['runtime_operation_id'])
 assert q['reconciliation']['state']=='MANUAL_REVIEW'
 assert q['consumer_promise']=='FROZEN' and q['supplier_mutation_frozen'] is True and q['finance_close_blocker'] is True
 assert safety.promotion_allowed('PROD') is False
 svc.claim(rec['reconciliation_id'],'maker',600)
 svc.submit_resolution(rec['reconciliation_id'],'maker',{'terminal_state':'FAILED','evidence':{'supplier':'failed'},'evidence_reference':'case://sla'})
 svc.review_resolution(rec['reconciliation_id'],'checker','APPROVE','review://sla')
 assert safety.promotion_allowed('PROD') is True
