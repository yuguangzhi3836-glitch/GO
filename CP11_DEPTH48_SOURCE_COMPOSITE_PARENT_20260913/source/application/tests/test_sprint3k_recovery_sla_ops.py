from datetime import timedelta
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoveryOperationalCaseRow,JourneyRecoveryOperationalEventRow,JourneyRecoverySlaPolicyRow,JourneyRecoveryReconciliationJobRow
from go_hotel.journey.recovery_sla import recovery_sla_service,now
from go_hotel.security.service import identity_service
from test_sprint3j_recovery_evidence_control import unknown_ride

def admin_headers():
    t=identity_service.login('go_admin','change-me-admin');return {'Authorization':'Bearer '+t['access_token']}

def test_case_gets_sla_queue_playbook_and_evidence_requirement(client):
    h,j,e,ride=unknown_ride(client,'sprint3k-sla@example.com');ah=admin_headers()
    case=client.get('/internal/v1/recovery/control-plane/cases',headers=ah).json()['data']['items'][0]
    assert case['sla_policy_id'] and case['queue_key']=='recovery_p1'
    assert case['acknowledge_due_at'] and case['resolution_due_at'] and case['playbook_key']
    detail=client.get(f"/internal/v1/recovery/control-plane/cases/{case['operational_case_id']}",headers=ah).json()['data']
    assert detail['required_evidence_kinds']==['FINAL_EXTERNAL_FACT']
    assert detail['closure_evidence_requirement']['satisfied'] is False

def test_sla_tick_auto_assigns_escalates_and_emits_alert_without_touching_supplier_fact(client):
    h,j,e,ride=unknown_ride(client,'sprint3k-escalate@example.com');ah=admin_headers()
    with SessionLocal.begin() as s:
        c=s.execute(select(JourneyRecoveryOperationalCaseRow).where(JourneyRecoveryOperationalCaseRow.execution_item_id==ride['execution_item_id'])).scalars().one()
        c.opened_at=now()-timedelta(hours=2);c.acknowledge_due_at=now()-timedelta(minutes=90);c.resolution_due_at=now()-timedelta(minutes=60);c.next_escalation_at=now()-timedelta(minutes=30);c.current_escalation_level=0
    out=client.post('/internal/v1/recovery/control-plane/sla/tick',headers=ah).json()['data']
    assert out['auto_assigned']>=1 and out['escalated']>=1 and out['alerts']>=1
    with SessionLocal() as s:
        c=s.execute(select(JourneyRecoveryOperationalCaseRow).where(JourneyRecoveryOperationalCaseRow.execution_item_id==ride['execution_item_id'])).scalars().one();assert c.assigned_to and c.current_escalation_level>=1 and c.state=='ESCALATED'
        kinds=s.execute(select(JourneyRecoveryOperationalEventRow.event_type).where(JourneyRecoveryOperationalEventRow.operational_case_id==c.operational_case_id)).scalars().all();assert 'AUTO_ASSIGNED' in kinds and 'SLA_ESCALATED' in kinds and 'ALERT_EMITTED' in kinds
    detail=client.get(f"/internal/v1/recovery/control-plane/cases/{c.operational_case_id}",headers=ah).json()['data'];assert detail['supplier_fact_mutable_by_admin'] is False

def test_responsibility_transfer_is_operational_only(client):
    h,j,e,ride=unknown_ride(client,'sprint3k-transfer@example.com');ah=admin_headers();case=client.get('/internal/v1/recovery/control-plane/cases',headers=ah).json()['data']['items'][0]
    out=client.post(f"/internal/v1/recovery/control-plane/cases/{case['operational_case_id']}/transfer",headers=ah,json={'queue_key':'recovery_p0','assigned_to':'ops_commander','note':'critical supplier follow-up'})
    assert out.status_code==200,out.text;d=out.json()['data'];assert d['queue_key']=='recovery_p0' and d['assigned_to']=='ops_commander' and d['supplier_fact_mutable_by_admin'] is False
    assert any(x['event_type']=='RESPONSIBILITY_TRANSFERRED' for x in d['operational_events'])

def test_case_close_is_blocked_until_required_final_external_fact_exists(client):
    h,j,e,ride=unknown_ride(client,'sprint3k-close@example.com');ah=admin_headers();case=client.get('/internal/v1/recovery/control-plane/cases',headers=ah).json()['data']['items'][0];cid=case['operational_case_id']
    blocked=client.post(f'/internal/v1/recovery/control-plane/cases/{cid}/close',headers=ah,json={'note':'cannot close yet'})
    assert blocked.status_code==409 and 'RECOVERY_CASE_RESOLUTION_EVIDENCE_REQUIRED' in blocked.text
    with SessionLocal.begin() as s:
        job=s.execute(select(JourneyRecoveryReconciliationJobRow).where(JourneyRecoveryReconciliationJobRow.execution_item_id==ride['execution_item_id'])).scalars().one();job.state='DEAD_LETTER';jid=job.reconciliation_job_id
    resolved=client.post(f'/internal/v1/recovery/reconciliation/jobs/{jid}/resolve',headers=ah,json={'resolution':'CONFIRMED','supplier_confirmation_id':'3k-confirmed','evidence_reference':'supplier-console-3k','evidence':{'operator_verified':True}})
    assert resolved.status_code==200,resolved.text
    closed=client.post(f'/internal/v1/recovery/control-plane/cases/{cid}/close',headers=ah,json={'note':'evidence complete'})
    assert closed.status_code==200,closed.text;d=closed.json()['data'];assert d['closure_evidence_requirement']['satisfied'] is True and d['closure_evidence_status']=='SATISFIED'

def test_sla_policy_and_queue_api_and_no_supplier_fact_mutator(client):
    ah=admin_headers();p=client.get('/internal/v1/recovery/control-plane/sla-policies',headers=ah);q=client.get('/internal/v1/recovery/control-plane/queues',headers=ah)
    assert p.status_code==200 and len(p.json()['data']['items'])>=3;assert q.status_code==200 and len(q.json()['data']['items'])>=3
    paths=client.app.openapi()['paths'];assert '/internal/v1/recovery/control-plane/cases/{case_id}/supplier-fact' not in paths
