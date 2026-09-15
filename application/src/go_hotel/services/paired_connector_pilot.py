from datetime import datetime,timezone
import hashlib,json,uuid
from sqlalchemy import select,func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (ProductionConnectorRow,ConnectorActivationReadinessRow,ConnectorPilotPairRow,
 ConnectorPilotScenarioRow,ConnectorPilotExecutionRow,ConnectorPilotOperationRow,ConnectorPilotCallbackRow,
 ConnectorPilotEvidenceRow,ConnectorPilotReconciliationRow,ConnectorPilotControlRow)
from go_hotel.connectors.paired_pilot import SandboxHotelPilotAdapter,SandboxPspPilotAdapter
def now():return datetime.now(timezone.utc)
def ident(p):return f'{p}_{uuid.uuid4().hex}'
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def out(r):return {c.name:(getattr(r,c.name).isoformat() if isinstance(getattr(r,c.name),datetime) else getattr(r,c.name)) for c in r.__table__.columns}
class PairedConnectorPilotService:
 def __init__(self):self.hotel=SandboxHotelPilotAdapter();self.psp=SandboxPspPilotAdapter()
 def create_pair(self,b,actor):
  mode=b.get('mode','SANDBOX_ONLY')
  if mode!='SANDBOX_ONLY':raise ValueError('REAL_EXTERNAL_PILOT_INPUTS_REQUIRED')
  with SessionLocal() as s:
   h=s.get(ProductionConnectorRow,b['hotel_connector_id']);p=s.get(ProductionConnectorRow,b['psp_connector_id'])
   if not h or h.vertical!='HOTEL':raise ValueError('HOTEL_CONNECTOR_REQUIRED')
   if not p or p.vertical!='PAYMENT':raise ValueError('PSP_CONNECTOR_REQUIRED')
   r=ConnectorPilotPairRow(pilot_pair_id=ident('pair'),hotel_connector_id=h.connector_id,psp_connector_id=p.connector_id,mode=mode,hotel_adapter_key=self.hotel.key,psp_adapter_key=self.psp.key,state='CONFIGURED',created_at=now());s.add(r);s.add(ConnectorPilotControlRow(pilot_pair_id=r.pilot_pair_id,canary_limit=b.get('canary_limit',1),completed_count=0,kill_switch_engaged=False,rollback_ready=False,smoke_passed=False,state='BLOCKED_PENDING_DRILLS',updated_at=now()));s.commit();return out(r)
 def create_scenario(self,pair_id,b,actor):
  with SessionLocal() as s:
   pair=s.get(ConnectorPilotPairRow,pair_id)
   if not pair:raise ValueError('PILOT_PAIR_NOT_FOUND')
   r=ConnectorPilotScenarioRow(pilot_scenario_id=ident('scenario'),pilot_pair_id=pair_id,scenario_key=b.get('scenario_key','ORDER_CANCEL_REFUND_QUERY'),order_payload_json=b.get('order_payload',{}),expected_flow_json=['PSP_AUTHORIZE','HOTEL_BOOK','PSP_CAPTURE','HOTEL_QUERY','HOTEL_CANCEL','PSP_REFUND','PSP_SETTLEMENT_QUERY'],state='READY',created_at=now());s.add(r);s.commit();return out(r)
 def set_drill_gate(self,pair_id,b,actor):
  with SessionLocal() as s:
   r=s.get(ConnectorPilotControlRow,pair_id)
   if not r:raise ValueError('PILOT_PAIR_NOT_FOUND')
   r.smoke_passed=bool(b.get('smoke_passed'));r.rollback_ready=bool(b.get('rollback_ready'));r.state='CANARY_READY' if r.smoke_passed and r.rollback_ready else 'BLOCKED_PENDING_DRILLS';r.updated_at=now();s.commit();return out(r)
 def kill_switch(self,pair_id,b,actor):
  with SessionLocal() as s:
   r=s.get(ConnectorPilotControlRow,pair_id)
   if not r:raise ValueError('PILOT_PAIR_NOT_FOUND')
   r.kill_switch_engaged=bool(b.get('engaged'));r.state='SUSPENDED' if r.kill_switch_engaged else ('CANARY_READY' if r.smoke_passed and r.rollback_ready else 'BLOCKED_PENDING_DRILLS');r.updated_at=now();s.commit();return out(r)
 def _evidence(self,s,eid,typ,payload):
  last=s.scalar(select(ConnectorPilotEvidenceRow).where(ConnectorPilotEvidenceRow.pilot_execution_id==eid).order_by(ConnectorPilotEvidenceRow.sequence_no.desc()));seq=(last.sequence_no if last else 0)+1;prev=last.entry_hash if last else 'GENESIS';entry=digest({'execution':eid,'sequence':seq,'type':typ,'payload':payload,'previous_hash':prev});r=ConnectorPilotEvidenceRow(pilot_evidence_id=ident('pev'),pilot_execution_id=eid,sequence_no=seq,evidence_type=typ,payload_json=payload,previous_hash=prev,entry_hash=entry,created_at=now());s.add(r);s.flush();return r
 def _op(self,s,e,vertical,typ,key,payload,result):
  r=ConnectorPilotOperationRow(pilot_operation_id=ident('pop'),pilot_execution_id=e.pilot_execution_id,vertical=vertical,operation_type=typ,idempotency_key=key,external_reference=result.get('reference'),state=result['state'],request_hash=digest(payload),result_json=result,updated_at=now());s.add(r);self._evidence(s,e.pilot_execution_id,f'{vertical}_{typ}',{'request_hash':r.request_hash,'result':result});return r
 def execute(self,scenario_id,b,actor):
  key=b.get('idempotency_key','')
  if not key:raise ValueError('IDEMPOTENCY_KEY_REQUIRED')
  with SessionLocal() as s:
   old=s.scalar(select(ConnectorPilotExecutionRow).where(ConnectorPilotExecutionRow.idempotency_key==key))
   if old:return out(old)
   sc=s.get(ConnectorPilotScenarioRow,scenario_id)
   if not sc:raise ValueError('PILOT_SCENARIO_NOT_FOUND')
   pair=s.get(ConnectorPilotPairRow,sc.pilot_pair_id);control=s.get(ConnectorPilotControlRow,pair.pilot_pair_id)
   if pair.mode!='SANDBOX_ONLY':raise ValueError('REAL_EXTERNAL_PILOT_INPUTS_REQUIRED')
   if control.kill_switch_engaged:raise ValueError('PILOT_KILL_SWITCH_ENGAGED')
   if not control.smoke_passed or not control.rollback_ready:raise ValueError('SMOKE_AND_ROLLBACK_GATE_REQUIRED')
   if control.completed_count>=control.canary_limit:raise ValueError('CANARY_LIMIT_REACHED')
   e=ConnectorPilotExecutionRow(pilot_execution_id=ident('pex'),pilot_scenario_id=scenario_id,mode=pair.mode,idempotency_key=key,state='RUNNING',created_at=now(),updated_at=now());s.add(e);s.flush();payload=sc.order_payload_json
   auth=self.psp.authorize(key+':auth',payload);self._op(s,e,'PAYMENT','AUTHORIZE',key+':auth',payload,auth)
   book=self.hotel.book(key+':book',payload);self._op(s,e,'HOTEL','BOOK',key+':book',payload,book);e.hotel_order_reference=book['reference']
   cap=self.psp.capture(key+':capture',auth['reference']);self._op(s,e,'PAYMENT','CAPTURE',key+':capture',{'reference':auth['reference']},cap);e.payment_reference=cap['reference']
   query=self.hotel.query(key+':query',book['reference']);self._op(s,e,'HOTEL','QUERY',key+':query',{'reference':book['reference']},query)
   cancel=self.hotel.cancel(key+':cancel',book['reference']);self._op(s,e,'HOTEL','CANCEL',key+':cancel',{'reference':book['reference']},cancel)
   refund=self.psp.refund(key+':refund',cap['reference']);self._op(s,e,'PAYMENT','REFUND',key+':refund',{'reference':cap['reference']},refund);e.refund_reference=refund['reference']
   settlement=self.psp.settlement(key+':settlement',refund['reference']);self._op(s,e,'PAYMENT','SETTLEMENT_QUERY',key+':settlement',{'reference':refund['reference']},settlement)
   e.state='SANDBOX_FLOW_COMPLETED';e.updated_at=now();control.completed_count+=1;control.state='CANARY_LIMIT_REACHED' if control.completed_count>=control.canary_limit else 'CANARY_READY';control.updated_at=now();s.commit();return out(e)
 def callback(self,execution_id,b,actor):
  if not b.get('signature_verified'):raise ValueError('CALLBACK_SIGNATURE_REQUIRED')
  with SessionLocal() as s:
   e=s.get(ConnectorPilotExecutionRow,execution_id)
   if not e:raise ValueError('PILOT_EXECUTION_NOT_FOUND')
   old=s.scalar(select(ConnectorPilotCallbackRow).where(ConnectorPilotCallbackRow.delivery_id==b['delivery_id']))
   if old:return {'callback':out(old),'replay':True}
   r=ConnectorPilotCallbackRow(pilot_callback_id=ident('pcb'),pilot_execution_id=execution_id,source_vertical=b['source_vertical'],delivery_id=b['delivery_id'],event_type=b['event_type'],signature_verified=True,payload_hash=digest(b.get('payload',{})),received_at=now());s.add(r);self._evidence(s,execution_id,'SIGNED_CALLBACK',{'delivery_id':r.delivery_id,'source':r.source_vertical,'payload_hash':r.payload_hash});s.commit();return {'callback':out(r),'replay':False}
 def reconcile(self,execution_id,actor):
  with SessionLocal() as s:
   e=s.get(ConnectorPilotExecutionRow,execution_id)
   if not e:raise ValueError('PILOT_EXECUTION_NOT_FOUND')
   ops=s.scalars(select(ConnectorPilotOperationRow).where(ConnectorPilotOperationRow.pilot_execution_id==execution_id)).all();states={x.operation_type:x.state for x in ops};checks={'order':states.get('CANCEL')=='CANCELLED','payment':states.get('CAPTURE')=='CAPTURED','refund':states.get('REFUND')=='REFUNDED','settlement':states.get('SETTLEMENT_QUERY')=='RECONCILED'};blockers=[k.upper() for k,v in checks.items() if not v];result='PASS' if not blockers else 'BLOCK';r=ConnectorPilotReconciliationRow(pilot_reconciliation_id=ident('prec'),pilot_execution_id=execution_id,order_state=states.get('CANCEL','UNKNOWN'),payment_state=states.get('CAPTURE','UNKNOWN'),refund_state=states.get('REFUND','UNKNOWN'),settlement_state=states.get('SETTLEMENT_QUERY','UNKNOWN'),result=result,blockers_json=blockers,evidence_hash=digest(states),reconciled_at=now());s.add(r);self._evidence(s,execution_id,'JOINT_RECONCILIATION',{'states':states,'result':result});s.commit();return out(r)
 def status(self,execution_id):
  with SessionLocal() as s:
   e=s.get(ConnectorPilotExecutionRow,execution_id)
   if not e:raise ValueError('PILOT_EXECUTION_NOT_FOUND')
   ops=s.scalars(select(ConnectorPilotOperationRow).where(ConnectorPilotOperationRow.pilot_execution_id==execution_id)).all();ev=s.scalars(select(ConnectorPilotEvidenceRow).where(ConnectorPilotEvidenceRow.pilot_execution_id==execution_id).order_by(ConnectorPilotEvidenceRow.sequence_no)).all();return {'execution':out(e),'operations':[out(x) for x in ops],'evidence':[out(x) for x in ev],'real_supplier_connected':False,'production_live':False}
 def dashboard(self):
  with SessionLocal() as s:return {'pairs':dict(s.execute(select(ConnectorPilotPairRow.state,func.count()).group_by(ConnectorPilotPairRow.state)).all()),'sandbox_only':True,'real_supplier_connected':False,'production_live':False}
paired_connector_pilot_service=PairedConnectorPilotService()
