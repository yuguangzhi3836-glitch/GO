from datetime import datetime,timezone,timedelta
import json
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    JourneyRecoveryExecutionItemRow,JourneyRecoverySupplierOperationRow,
    JourneyRecoveryReconciliationJobRow,JourneyRecoveryReconciliationObservationRow,
)
from go_hotel.journey.recovery_reconciliation import recovery_reconciliation_service
from go_hotel.recovery_adapters.registry import recovery_adapter_registry
from go_hotel.services.webhooks import webhook_service
from test_sprint3g_journey_recovery import auth,seed,journey,disruption
from test_sprint3h_recovery_execution import selected_plan

def make_execution(client,email='sprint3i@example.com'):
    h,uid=auth(client,email);seed(uid);j=journey(client,h);d=disruption(client,h,j);p=selected_plan(client,h,j,d)
    e=client.post(f"/v1/trips/journeys/{j['journey_id']}/recovery-executions",headers=h|{'Idempotency-Key':'sprint3i-intent'},json={'plan_id':p['plan_id'],'authorized_delta_minor':50000}).json()['data']
    return h,j,e

def test_recovery_adapter_contract_covers_all_verticals():
    meta={m.vertical:m for m in recovery_adapter_registry.list()}
    assert {'FLIGHT','RAIL','RIDE','RENTAL','HOTEL','ATTRACTION'}<=set(meta)
    assert all(x.capabilities.poll and x.capabilities.webhooks and x.capabilities.supplier_idempotency and x.capabilities.query_by_idempotency_key for x in meta.values())

def test_unknown_mutation_creates_durable_job_and_poll_resolves_without_second_mutation(client):
    h,j,e=make_execution(client,'sprint3i-unknown@example.com')
    with SessionLocal.begin() as s:
        item=s.execute(select(JourneyRecoveryExecutionItemRow).where(JourneyRecoveryExecutionItemRow.execution_id==e['execution_id'],JourneyRecoveryExecutionItemRow.vertical=='RIDE')).scalars().first()
        item.facts_json=dict(item.facts_json or {})|{'force_unknown_external_state':True,'poll_result':'CONFIRMED'}
    out=client.post(f"/v1/trips/journeys/{j['journey_id']}/recovery-executions/{e['execution_id']}/confirm",headers=h).json()['data']
    ride=next(x for x in out['items'] if x['vertical']=='RIDE');assert ride['status']=='UNKNOWN_EXTERNAL_STATE'
    with SessionLocal() as s:
        op=s.execute(select(JourneyRecoverySupplierOperationRow).where(JourneyRecoverySupplierOperationRow.execution_item_id==ride['execution_item_id'])).scalars().one()
        job=s.execute(select(JourneyRecoveryReconciliationJobRow).where(JourneyRecoveryReconciliationJobRow.supplier_operation_id==op.supplier_operation_id)).scalars().one()
        op_id,idem,job_id=op.supplier_operation_id,op.supplier_idempotency_key,job.reconciliation_job_id
    stats=recovery_reconciliation_service.run_once(20);assert stats['resolved']>=1
    final=client.get(f"/v1/trips/journeys/{j['journey_id']}/recovery-executions/{e['execution_id']}",headers=h).json()['data']
    ride2=next(x for x in final['items'] if x['vertical']=='RIDE');assert ride2['status']=='CONFIRMED' and ride2['attempt_count']==1
    with SessionLocal() as s:
        ops=s.execute(select(JourneyRecoverySupplierOperationRow).where(JourneyRecoverySupplierOperationRow.execution_item_id==ride['execution_item_id'])).scalars().all();assert len(ops)==1 and ops[0].supplier_operation_id==op_id and ops[0].supplier_idempotency_key==idem
        assert s.get(JourneyRecoveryReconciliationJobRow,job_id).state=='RESOLVED'

def test_webhook_and_poll_converge_on_same_supplier_operation(client):
    h,j,e=make_execution(client,'sprint3i-webhook@example.com')
    with SessionLocal.begin() as s:
        item=s.execute(select(JourneyRecoveryExecutionItemRow).where(JourneyRecoveryExecutionItemRow.execution_id==e['execution_id'],JourneyRecoveryExecutionItemRow.vertical=='RAIL')).scalars().first()
        item.facts_json=dict(item.facts_json or {})|{'force_async_supplier':True,'poll_result':'PENDING'}
    out=client.post(f"/v1/trips/journeys/{j['journey_id']}/recovery-executions/{e['execution_id']}/confirm",headers=h).json()['data']
    rail=next(x for x in out['items'] if x['vertical']=='RAIL');assert rail['status']=='AWAITING_SUPPLIER_CONFIRMATION'
    with SessionLocal() as s:
        op=s.execute(select(JourneyRecoverySupplierOperationRow).where(JourneyRecoverySupplierOperationRow.execution_item_id==rail['execution_item_id'])).scalars().one()
        adapter_key,ext,idem=op.adapter_key,op.external_operation_id,op.supplier_idempotency_key
    recovery_reconciliation_service.run_once(20)
    payload={'external_event_id':'evt-s3i-rail-1','external_operation_id':ext,'idempotency_key':idem,'status':'CONFIRMED','supplier_confirmation_id':'rail-confirmed-001'}
    raw=json.dumps(payload,separators=(',',':')).encode();sig=webhook_service.signature(raw)
    client.cookies.clear()
    r=client.post(f'/internal/v1/recovery/adapters/{adapter_key}/webhooks',content=raw,headers={'content-type':'application/json','X-GO-Signature':sig});assert r.status_code==200,r.text
    r2=client.post(f'/internal/v1/recovery/adapters/{adapter_key}/webhooks',content=raw,headers={'content-type':'application/json','X-GO-Signature':sig});assert r2.status_code==200,r2.text
    final=client.get(f"/v1/trips/journeys/{j['journey_id']}/recovery-executions/{e['execution_id']}",headers=h).json()['data'];rail2=next(x for x in final['items'] if x['vertical']=='RAIL');assert rail2['status']=='CONFIRMED' and rail2['supplier_confirmation_id']=='rail-confirmed-001'
    with SessionLocal() as s:
        obs=s.execute(select(JourneyRecoveryReconciliationObservationRow).where(JourneyRecoveryReconciliationObservationRow.external_event_id=='evt-s3i-rail-1')).scalars().all();assert len(obs)==1

def test_expired_worker_lease_is_reclaimed_after_crash(client):
    h,j,e=make_execution(client,'sprint3i-crash@example.com')
    with SessionLocal.begin() as s:
        item=s.execute(select(JourneyRecoveryExecutionItemRow).where(JourneyRecoveryExecutionItemRow.execution_id==e['execution_id'],JourneyRecoveryExecutionItemRow.vertical=='HOTEL')).scalars().first();item.facts_json=dict(item.facts_json or {})|{'force_unknown_external_state':True,'poll_result':'CONFIRMED'}
    out=client.post(f"/v1/trips/journeys/{j['journey_id']}/recovery-executions/{e['execution_id']}/confirm",headers=h).json()['data'];hotel=next(x for x in out['items'] if x['vertical']=='HOTEL')
    with SessionLocal.begin() as s:
        job=s.execute(select(JourneyRecoveryReconciliationJobRow).where(JourneyRecoveryReconciliationJobRow.execution_item_id==hotel['execution_item_id'])).scalars().one();job.state='RUNNING';job.lease_token='dead-worker';job.lease_until=datetime.now(timezone.utc)-timedelta(seconds=1);job.next_attempt_at=datetime.now(timezone.utc)-timedelta(seconds=1)
    stats=recovery_reconciliation_service.run_once(20);assert stats['resolved']>=1
    with SessionLocal() as s:
        job=s.execute(select(JourneyRecoveryReconciliationJobRow).where(JourneyRecoveryReconciliationJobRow.execution_item_id==hotel['execution_item_id'])).scalars().one();assert job.state=='RESOLVED' and job.lease_token is None

def test_dead_letter_requires_manual_review_and_can_be_resolved(client):
    h,j,e=make_execution(client,'sprint3i-dlq@example.com')
    with SessionLocal.begin() as s:
        item=s.execute(select(JourneyRecoveryExecutionItemRow).where(JourneyRecoveryExecutionItemRow.execution_id==e['execution_id'],JourneyRecoveryExecutionItemRow.vertical=='ATTRACTION')).scalars().first();item.facts_json=dict(item.facts_json or {})|{'force_unknown_external_state':True,'poll_result':'PENDING'}
    out=client.post(f"/v1/trips/journeys/{j['journey_id']}/recovery-executions/{e['execution_id']}/confirm",headers=h).json()['data'];a=next(x for x in out['items'] if x['vertical']=='ATTRACTION')
    with SessionLocal.begin() as s:
        job=s.execute(select(JourneyRecoveryReconciliationJobRow).where(JourneyRecoveryReconciliationJobRow.execution_item_id==a['execution_item_id'])).scalars().one();job.max_attempts=1;job.next_attempt_at=datetime.now(timezone.utc)-timedelta(seconds=1);jid=job.reconciliation_job_id
    stats=recovery_reconciliation_service.run_once(20);assert stats['dead_letter']>=1
    with SessionLocal() as s:
        job=s.get(JourneyRecoveryReconciliationJobRow,jid);item=s.get(JourneyRecoveryExecutionItemRow,a['execution_item_id']);assert job.state=='DEAD_LETTER' and item.reconciliation_state=='MANUAL_REVIEW'
    r=recovery_reconciliation_service.manual_resolve(jid,'CONFIRMED','manual-confirm-001');assert r['state']=='RESOLVED'
    final=client.get(f"/v1/trips/journeys/{j['journey_id']}/recovery-executions/{e['execution_id']}",headers=h).json()['data'];a2=next(x for x in final['items'] if x['vertical']=='ATTRACTION');assert a2['status']=='CONFIRMED' and a2['supplier_confirmation_id']=='manual-confirm-001'
