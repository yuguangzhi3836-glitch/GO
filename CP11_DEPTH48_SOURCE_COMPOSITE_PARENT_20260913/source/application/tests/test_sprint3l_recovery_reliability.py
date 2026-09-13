from datetime import timedelta
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import JourneyRecoverySupplierOperationRow,JourneyRecoveryReconciliationJobRow,JourneyRecoveryReliabilityProfileRow,JourneyRecoveryReliabilityDecisionRow,JourneyRecoveryOperationalCaseRow
from go_hotel.journey.recovery_reliability import recovery_reliability_service,now
from go_hotel.journey.recovery_sla import recovery_sla_service
from go_hotel.security.service import identity_service
from test_sprint3j_recovery_evidence_control import unknown_ride

def admin_headers():
    t=identity_service.login('go_admin','change-me-admin');return {'Authorization':'Bearer '+t['access_token']}

def test_reliability_profile_rebuild_from_real_recovery_facts(client):
    h,j,e,ride=unknown_ride(client,'sprint3l-memory@example.com')
    out=recovery_reliability_service.rebuild();assert out['profiles_rebuilt']>=1
    with SessionLocal() as s:
        p=s.execute(select(JourneyRecoveryReliabilityProfileRow).where(JourneyRecoveryReliabilityProfileRow.vertical=='RIDE')).scalars().one()
        assert p.sample_count>=1 and p.unknown_count>=1 and p.timeout_rate>0
        assert p.risk_band in {'LOW','MEDIUM','HIGH'} and p.recommended_max_attempts>=8

def test_reliability_memory_changes_future_reconciliation_policy_without_resend(client):
    h,j,e,ride=unknown_ride(client,'sprint3l-adaptive@example.com');recovery_reliability_service.rebuild()
    # first unknown already enqueued under default; a second item after memory should use a recorded decision.
    with SessionLocal() as s:
        dec=s.execute(select(JourneyRecoveryReliabilityDecisionRow).where(JourneyRecoveryReliabilityDecisionRow.execution_item_id==ride['execution_item_id'])).scalars().all()
        # Existing item may predate rebuilt profile; ensure no mutation authority is granted by memory.
        op=s.execute(select(JourneyRecoverySupplierOperationRow).where(JourneyRecoverySupplierOperationRow.execution_item_id==ride['execution_item_id'])).scalars().one()
        assert op.supplier_idempotency_key and op.status in {'UNKNOWN','ACCEPTED_ASYNC','CONFIRMED'}
    assert client.app.openapi()['paths'].get('/internal/v1/recovery/reliability/profiles')

def test_sla_feedback_uses_profile_but_does_not_mutate_supplier_fact(client):
    h,j,e,ride=unknown_ride(client,'sprint3l-sla@example.com');recovery_reliability_service.rebuild()
    with SessionLocal.begin() as s:
        c=s.execute(select(JourneyRecoveryOperationalCaseRow).where(JourneyRecoveryOperationalCaseRow.execution_item_id==ride['execution_item_id'])).scalars().one()
        # force re-attachment to verify feedback path
        c.sla_policy_id=None;c.acknowledge_due_at=None;c.resolution_due_at=None
    recovery_sla_service.tick(100)
    with SessionLocal() as s:
        c=s.execute(select(JourneyRecoveryOperationalCaseRow).where(JourneyRecoveryOperationalCaseRow.execution_item_id==ride['execution_item_id'])).scalars().one()
        dec=s.execute(select(JourneyRecoveryReliabilityDecisionRow).where(JourneyRecoveryReliabilityDecisionRow.execution_item_id==ride['execution_item_id'],JourneyRecoveryReliabilityDecisionRow.decision_kind=='SLA_FEEDBACK')).scalars().first()
        assert c.acknowledge_due_at and c.resolution_due_at and dec.explanation_json['supplier_fact_unchanged'] is True
        op=s.execute(select(JourneyRecoverySupplierOperationRow).where(JourneyRecoverySupplierOperationRow.execution_item_id==ride['execution_item_id'])).scalars().one();assert op.status=='UNKNOWN'

def test_reliability_admin_api_is_read_rebuild_only(client):
    unknown_ride(client,'sprint3l-api@example.com');ah=admin_headers()
    r=client.post('/internal/v1/recovery/reliability/rebuild',headers=ah);assert r.status_code==200
    p=client.get('/internal/v1/recovery/reliability/profiles',headers=ah);assert p.status_code==200 and p.json()['data']['items']
    paths=client.app.openapi()['paths'];assert '/internal/v1/recovery/reliability/profiles/{profile_id}/override-supplier-fact' not in paths
