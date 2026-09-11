from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoveryExecutionItemRow,JourneyRecoveryCommandLedgerRow,JourneyRecoveryEvidenceChainRow,JourneyRecoveryOperationalCaseRow,JourneyRecoveryReconciliationJobRow
from go_hotel.journey.recovery_reconciliation import recovery_reconciliation_service
from go_hotel.journey.recovery_evidence import recovery_evidence_service
from go_hotel.security.service import identity_service
from test_sprint3i_recovery_reconciliation import make_execution

def admin_headers():
    t=identity_service.login('go_admin','change-me-admin')
    return {'Authorization':'Bearer '+t['access_token']}

def unknown_ride(client,email):
    h,j,e=make_execution(client,email)
    with SessionLocal.begin() as s:
        i=s.execute(select(JourneyRecoveryExecutionItemRow).where(JourneyRecoveryExecutionItemRow.execution_id==e['execution_id'],JourneyRecoveryExecutionItemRow.vertical=='RIDE')).scalars().first();i.facts_json=dict(i.facts_json or {})|{'force_unknown_external_state':True,'poll_result':'PENDING'}
    out=client.post(f"/v1/trips/journeys/{j['journey_id']}/recovery-executions/{e['execution_id']}/confirm",headers=h).json()['data']
    return h,j,e,next(x for x in out['items'] if x['vertical']=='RIDE')

def test_supplier_mutation_creates_command_ledger_and_operational_case(client):
    h,j,e,ride=unknown_ride(client,'sprint3j-ledger@example.com')
    with SessionLocal() as s:
        cmds=s.execute(select(JourneyRecoveryCommandLedgerRow).where(JourneyRecoveryCommandLedgerRow.execution_item_id==ride['execution_item_id']).order_by(JourneyRecoveryCommandLedgerRow.sequence_no)).scalars().all()
        assert [x.command_kind for x in cmds][:2]==['FINANCIAL_RAIL_REFERENCE','SUPPLIER_MUTATION']
        assert all(x.entry_hash and x.payload_hash for x in cmds)
        c=s.execute(select(JourneyRecoveryOperationalCaseRow).where(JourneyRecoveryOperationalCaseRow.execution_item_id==ride['execution_item_id'])).scalars().one();assert c.state=='OPEN'
        assert recovery_evidence_service.verify_item(s,ride['execution_item_id'])['valid']

def test_poll_and_final_external_fact_are_chained_without_resend(client):
    h,j,e,ride=unknown_ride(client,'sprint3j-poll@example.com')
    with SessionLocal.begin() as s:
        i=s.get(JourneyRecoveryExecutionItemRow,ride['execution_item_id']);i.facts_json=dict(i.facts_json or {})|{'poll_result':'CONFIRMED'}
        job=s.execute(select(JourneyRecoveryReconciliationJobRow).where(JourneyRecoveryReconciliationJobRow.execution_item_id==ride['execution_item_id'])).scalars().one();job.next_attempt_at=job.created_at
    recovery_reconciliation_service.run_once(20)
    with SessionLocal() as s:
        cmds=s.execute(select(JourneyRecoveryCommandLedgerRow).where(JourneyRecoveryCommandLedgerRow.execution_item_id==ride['execution_item_id'])).scalars().all();assert sum(x.command_kind=='SUPPLIER_MUTATION' for x in cmds)==1 and any(x.command_kind=='SUPPLIER_POLL' for x in cmds)
        ev=s.execute(select(JourneyRecoveryEvidenceChainRow).where(JourneyRecoveryEvidenceChainRow.execution_item_id==ride['execution_item_id']).order_by(JourneyRecoveryEvidenceChainRow.sequence_no)).scalars().all();assert any(x.evidence_kind=='SUPPLIER_OBSERVATION' for x in ev) and any(x.evidence_kind=='FINAL_EXTERNAL_FACT' and x.observed_status=='CONFIRMED' for x in ev)
        c=s.execute(select(JourneyRecoveryOperationalCaseRow).where(JourneyRecoveryOperationalCaseRow.execution_item_id==ride['execution_item_id'])).scalars().one();assert c.state=='RESOLVED'
        assert recovery_evidence_service.verify_item(s,ride['execution_item_id'])['valid']

def test_admin_control_plane_assigns_owner_but_exposes_no_supplier_fact_mutation(client):
    h,j,e,ride=unknown_ride(client,'sprint3j-admin@example.com');ah=admin_headers()
    listing=client.get('/internal/v1/recovery/control-plane/cases',headers=ah);assert listing.status_code==200
    case=listing.json()['data']['items'][0];cid=case['operational_case_id'];assert case['age_seconds']>=0 and case['attempt_count']==0
    assigned=client.post(f'/internal/v1/recovery/control-plane/cases/{cid}/assign',headers=ah,json={'assigned_to':'ops_tokyo','note':'follow supplier'});assert assigned.status_code==200 and assigned.json()['data']['assigned_to']=='ops_tokyo'
    detail=client.get(f'/internal/v1/recovery/control-plane/cases/{cid}',headers=ah).json()['data'];assert detail['supplier_fact_mutable_by_admin'] is False and detail['chain_verification']['valid']
    paths=client.app.openapi()['paths'];assert f'/internal/v1/recovery/control-plane/cases/{cid}/supplier-fact' not in paths

def test_manual_resolution_endpoint_requires_evidence_reference(client):
    h,j,e,ride=unknown_ride(client,'sprint3j-manual@example.com')
    with SessionLocal.begin() as s:
        job=s.execute(select(JourneyRecoveryReconciliationJobRow).where(JourneyRecoveryReconciliationJobRow.execution_item_id==ride['execution_item_id'])).scalars().one();job.state='DEAD_LETTER';jid=job.reconciliation_job_id
    ah=admin_headers();bad=client.post(f'/internal/v1/recovery/reconciliation/jobs/{jid}/resolve',headers=ah,json={'resolution':'CONFIRMED','supplier_confirmation_id':'manual-3j'});assert bad.status_code==422
    good=client.post(f'/internal/v1/recovery/reconciliation/jobs/{jid}/resolve',headers=ah,json={'resolution':'CONFIRMED','supplier_confirmation_id':'manual-3j','evidence_reference':'supplier-console-case-991','evidence':{'verified_by':'ops'}});assert good.status_code==200,good.text
    with SessionLocal() as s:
        ev=s.execute(select(JourneyRecoveryEvidenceChainRow).where(JourneyRecoveryEvidenceChainRow.execution_item_id==ride['execution_item_id'])).scalars().all();assert any(x.evidence_kind=='MANUAL_VERIFIED_EVIDENCE' for x in ev) and any(x.evidence_kind=='FINAL_EXTERNAL_FACT' for x in ev)
        assert recovery_evidence_service.verify_item(s,ride['execution_item_id'])['valid']
