import json
from datetime import datetime,timezone,timedelta
import pytest
from sqlalchemy import select,func
from go_hotel.services import registration_privacy as privacy,registration_verification as verification
from go_hotel.db.models import RegistrationChallengeRow as Challenge,RegistrationRateRow as Rate,RegistrationDecisionRow as Decision,PrivacyRequestRow,RegistrationMaintenanceRow
from go_hotel.db.session import SessionLocal
from go_hotel.core.config import settings
from registration_terms_test_support import approved_terms_fixture,with_verification
from test_registration_verification import delivery,send,payload


def test_cleanup_without_any_subsequent_registration_and_restore_replay(client,monkeypatch):
    t=privacy.now_ms()
    def restored():
        with SessionLocal.begin() as s:
            s.add(Challenge(subject_key='a'*64,challenge_id='expired',code_digest='b'*64,policy_digest='c'*64,state='SENT',attempts=0,expires_ms=t-1,created_ms=t-600001))
            s.add(Rate(bucket_key='r'*64,count=1,expires_ms=t-1))
    restored();privacy.cleanup_once()
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(Challenge))==0
        assert s.scalar(select(func.count()).select_from(Rate))==0
    assert privacy.maintenance_status()['ready']
    # Restored expired rows disappear on startup cycle, independent of user traffic.
    restored();privacy.cleanup_once()
    with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(Challenge))==0
    monkeypatch.setattr(privacy,'now_ms',lambda:t+privacy.CLEANUP_MAX_AGE_MS+1000)
    assert not privacy.maintenance_status()['ready']


def test_cleanup_failure_does_not_publish_healthy_heartbeat(client,monkeypatch):
    privacy.cleanup_once()
    with SessionLocal() as s:before=s.get(RegistrationMaintenanceRow,'cleanup').success_ms
    from sqlalchemy import event
    from go_hotel.db.session import engine
    def fail(conn,cursor,statement,parameters,context,executemany):
        if statement.startswith('DELETE FROM registration_rate'):raise RuntimeError('isolated failure')
    event.listen(engine,'before_cursor_execute',fail)
    try:
        with pytest.raises(RuntimeError):privacy.cleanup_once()
    finally:event.remove(engine,'before_cursor_execute',fail)
    with SessionLocal() as s:assert s.get(RegistrationMaintenanceRow,'cleanup').success_ms==before


def test_expired_decisions_cleaned_but_active_challenge_and_open_case_retained(client):
    t=privacy.now_ms()
    with SessionLocal.begin() as s:
        s.add(Decision(decision_id='old',user_id='u',audience='consumer',decisions={},versions={},hashes={},created_ms=0,expires_ms=t-1))
        s.add(Challenge(subject_key='a',challenge_id='valid',code_digest='b',policy_digest='c',state='SENT',attempts=0,expires_ms=t+600000,created_ms=t))
    case=privacy.submit_request('u','DELETION');privacy.cleanup_once()
    with SessionLocal() as s:
        assert s.get(Decision,'old') is None
        assert s.get(Challenge,'a') is not None
        assert s.get(PrivacyRequestRow,case['request_id']).status=='RECEIVED'


def test_separate_decisions_required_before_mail_and_atomic_registration(client,delivery):
    body=payload(client,'consumer','consent@example.test')
    bad={k:v for k,v in body.items() if k not in ('password','registration_decisions')}|{'audience':'consumer'}
    assert client.post('/v1/registration/challenges',json=bad).status_code==422
    assert delivery==[]
    b=send(client,delivery,email='consent@example.test')
    assert client.post('/v1/consumer/auth/register',json=b|{'registration_decisions':{}}).status_code==409
    with SessionLocal() as s:assert s.scalar(select(func.count()).select_from(Decision))==0
    result=client.post('/v1/consumer/auth/register',json=b)
    assert result.status_code==200,result.text
    with SessionLocal() as s:
        receipt=s.scalar(select(Decision))
        assert receipt.decisions['privacy_policy']=='NOTICE_ACKNOWLEDGED'
        assert receipt.decisions['personal_vault_terms']=='DEFERRED'
        assert receipt.hashes==b['term_hashes']
        assert receipt.user_id==result.json()['data']['profile']['user_id']
    page=client.get('/v1/consumer/privacy')
    assert page.status_code==200 and page.headers['cache-control']=='no-store'
    assert len(page.json()['data']['decisions'])==1


def test_gate_requires_operational_evidence_and_fresh_cleanup(client,delivery,monkeypatch):
    monkeypatch.setattr(privacy,'operational_evidence_status',lambda:{'ready':False})
    assert not verification.ready()
    assert not client.get('/v1/consumer/auth/registration').json()['data']['enabled']
    monkeypatch.setattr(privacy,'operational_evidence_status',lambda:{'ready':True})
    with SessionLocal.begin() as s:s.get(RegistrationMaintenanceRow,'cleanup').success_ms=0
    assert not verification.ready()
    privacy.cleanup_once();assert verification.ready()


def test_evidence_manifest_missing_expired_or_wrong_terms_never_ready(tmp_path,monkeypatch):
    p=tmp_path/'evidence.json';monkeypatch.setattr(settings,'registration_privacy_evidence_path',str(p))
    assert not privacy.operational_evidence_status()['ready']
    item={'reviewer':'isolated-reviewer','reviewed_at':'2026-01-01T00:00:00+00:00','evidence_ref':'isolated:test','sha256':'a'*64,'scope':'synthetic only'}
    value={'schema_version':1,'status':'APPROVED','terms_version':settings.registration_terms_version,'valid_until':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),**{k:item for k in privacy.EVIDENCE_CATEGORIES}}
    p.write_text(json.dumps(value));assert privacy.operational_evidence_status()['ready']
    value['terms_version']='wrong';p.write_text(json.dumps(value));assert not privacy.operational_evidence_status()['ready']


def test_authenticated_intake_does_not_claim_deletion_and_is_user_scoped(client,delivery):
    b=send(client,delivery,email='one@example.test');assert client.post('/v1/consumer/auth/register',json=b).status_code==200
    csrf=client.cookies.get(settings.consumer_csrf_cookie_name)
    headers={settings.csrf_header_name:csrf}
    r=client.post('/v1/consumer/privacy/requests',json={'kind':'DELETION'},headers=headers)
    assert r.status_code==202,r.text
    assert r.json()['data']['status']=='RECEIVED'
    assert client.post('/v1/consumer/privacy/requests',json={'kind':'DELETION','user_id':'other'},headers=headers).status_code==422
    assert client.get('/internal/privacy/requests',headers={'Authorization':'Bearer '+client.cookies.get(settings.consumer_access_cookie_name)}).status_code==403
    client.cookies.clear()
    assert client.get('/v1/consumer/privacy').status_code==401
    b=send(client,delivery,email='two@example.test');assert client.post('/v1/consumer/auth/register',json=b).status_code==200
    assert client.get('/v1/consumer/privacy').json()['data']['requests']==[]


def test_worker_start_invalidates_restored_unexpired_challenges(client):
    t=privacy.now_ms()
    with SessionLocal.begin() as s:
        s.add(Challenge(subject_key='restored',challenge_id='old-active',code_digest='b',policy_digest='c',state='SENT',attempts=0,expires_ms=t+600000,created_ms=t))
    privacy.cleanup_once(invalidate_challenges=True)
    with SessionLocal() as s:assert s.get(Challenge,'restored') is None


def test_privacy_migration_and_rollback_guard(tmp_path):
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine,inspect,text
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path=Path('alembic/versions/0143_registration_privacy.py')
    spec=importlib.util.spec_from_file_location('privacy_migration',path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=create_engine('sqlite:///'+str(tmp_path/'migration.db'))
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            assert 'privacy_request' in inspect(conn).get_table_names()
            conn.execute(text("INSERT INTO privacy_request VALUES ('r','u','DELETION','RECEIVED',0,1,0,'{}')"))
            with pytest.raises(RuntimeError,match='PRIVACY_RECORDS_PRESENT'):migration.downgrade()
            conn.execute(text('DELETE FROM privacy_request'));migration.downgrade()
            assert not inspect(conn).get_table_names()
