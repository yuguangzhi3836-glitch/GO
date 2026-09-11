from datetime import datetime,timezone
import pytest
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import ProductionConnectorRow
from go_hotel.services.paired_connector_pilot import paired_connector_pilot_service as svc
def connectors():
 t=datetime.now(timezone.utc)
 with SessionLocal() as s:
  s.add(ProductionConnectorRow(connector_id='hotel_pilot',connector_key='hotel-pilot',display_name='Hotel Sandbox',vertical='HOTEL',supplier_legal_name='Pending Hotel Supplier',environment='SANDBOX',lifecycle_state='ENGINEERING',active_capability_version=1,created_by='test',created_at=t,updated_at=t))
  s.add(ProductionConnectorRow(connector_id='psp_pilot',connector_key='psp-pilot',display_name='PSP Sandbox',vertical='PAYMENT',supplier_legal_name='Pending PSP Supplier',environment='SANDBOX',lifecycle_state='ENGINEERING',active_capability_version=1,created_by='test',created_at=t,updated_at=t));s.commit()
 return 'hotel_pilot','psp_pilot'
def ready_pair(limit=1):
 h,p=connectors();pair=svc.create_pair({'hotel_connector_id':h,'psp_connector_id':p,'mode':'SANDBOX_ONLY','canary_limit':limit},'admin');svc.set_drill_gate(pair['pilot_pair_id'],{'smoke_passed':True,'rollback_ready':True},'sre');scenario=svc.create_scenario(pair['pilot_pair_id'],{'order_payload':{'order_id':'o1','amount_minor':10000,'currency':'CNY'}},'admin');return pair,scenario
def test_real_external_pilot_is_hard_blocked_without_supplier_inputs():
 h,p=connectors()
 with pytest.raises(ValueError,match='REAL_EXTERNAL_PILOT_INPUTS_REQUIRED'):svc.create_pair({'hotel_connector_id':h,'psp_connector_id':p,'mode':'EXTERNAL_SANDBOX'},'admin')
def test_pair_requires_hotel_and_payment_verticals():
 h,p=connectors()
 with pytest.raises(ValueError,match='HOTEL_CONNECTOR_REQUIRED'):svc.create_pair({'hotel_connector_id':p,'psp_connector_id':h},'admin')
def test_execution_requires_smoke_and_rollback_gate():
 h,p=connectors();pair=svc.create_pair({'hotel_connector_id':h,'psp_connector_id':p},'admin');scenario=svc.create_scenario(pair['pilot_pair_id'],{'order_payload':{'order_id':'o1'}},'admin')
 with pytest.raises(ValueError,match='SMOKE_AND_ROLLBACK'):svc.execute(scenario['pilot_scenario_id'],{'idempotency_key':'pilot-1'},'admin')
def test_full_sandbox_order_cancel_refund_query_flow_and_joint_reconciliation():
 pair,scenario=ready_pair();e=svc.execute(scenario['pilot_scenario_id'],{'idempotency_key':'pilot-1'},'admin');r=svc.reconcile(e['pilot_execution_id'],'admin');status=svc.status(e['pilot_execution_id'])
 assert e['state']=='SANDBOX_FLOW_COMPLETED' and r['result']=='PASS' and len(status['operations'])==7 and status['real_supplier_connected'] is False and status['production_live'] is False
def test_execution_idempotency_and_canary_limit_prevent_duplicate_or_extra_run():
 pair,scenario=ready_pair();a=svc.execute(scenario['pilot_scenario_id'],{'idempotency_key':'same'},'admin');b=svc.execute(scenario['pilot_scenario_id'],{'idempotency_key':'same'},'admin');assert a['pilot_execution_id']==b['pilot_execution_id']
 with pytest.raises(ValueError,match='CANARY_LIMIT_REACHED'):svc.execute(scenario['pilot_scenario_id'],{'idempotency_key':'new'},'admin')
def test_kill_switch_blocks_pilot_execution():
 pair,scenario=ready_pair();svc.kill_switch(pair['pilot_pair_id'],{'engaged':True},'sre')
 with pytest.raises(ValueError,match='KILL_SWITCH'):svc.execute(scenario['pilot_scenario_id'],{'idempotency_key':'pilot-kill'},'admin')
def test_signed_callbacks_are_replay_safe_and_evidence_chain_is_linked():
 pair,scenario=ready_pair();e=svc.execute(scenario['pilot_scenario_id'],{'idempotency_key':'pilot-callback'},'admin');body={'source_vertical':'PAYMENT','delivery_id':'delivery-1','event_type':'REFUND_CONFIRMED','signature_verified':True,'payload':{'refund':'ok'}};a=svc.callback(e['pilot_execution_id'],body,'gateway');b=svc.callback(e['pilot_execution_id'],body,'gateway');status=svc.status(e['pilot_execution_id']);ev=status['evidence']
 assert a['replay'] is False and b['replay'] is True and all(x['previous_hash']==('GENESIS' if i==0 else ev[i-1]['entry_hash']) for i,x in enumerate(ev))
