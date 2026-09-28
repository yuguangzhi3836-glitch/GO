"""Internal audit integrity only; no external executor or merchant credentials."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
import os
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from go_hotel.db.models import (
    AuditEventRow, ApprovalRequestRow, HostedDirectHotelRow,
    HostedDirectPaymentReadinessRow, IncidentControlRow, OmnichannelMerchantBindingRow,
)
from go_hotel.services import payment_sandbox_cutover as module

pytestmark = pytest.mark.no_db


@pytest.fixture
def audit(tmp_path, monkeypatch, request):
    database = os.getenv('GO_TEST_DATABASE_URL')
    admin = None
    schema = None
    if database:
        url = make_url(database)
        if (url.get_backend_name() != 'postgresql' or url.host not in {'localhost', '127.0.0.1', '::1'}
                or url.database != 'go_c11_isolated'):
            raise ValueError('ISOLATED_LOOPBACK_POSTGRES_REQUIRED')
        schema = 'payment_audit_' + uuid4().hex
        admin = create_engine(url)
        with admin.begin() as connection:
            connection.execute(text('CREATE SCHEMA ' + schema))
        engine = create_engine(url.update_query_dict({'options': '-csearch_path=' + schema}))
    else:
        engine = create_engine('sqlite+pysqlite:///' + str(tmp_path / 'audit.db'))
    def cleanup():
        engine.dispose()
        if admin is not None:
            with admin.begin() as connection:
                connection.execute(text('DROP SCHEMA ' + schema + ' CASCADE'))
            admin.dispose()
    request.addfinalizer(cleanup)
    tables = [HostedDirectHotelRow.__table__, HostedDirectPaymentReadinessRow.__table__,
              OmnichannelMerchantBindingRow.__table__, AuditEventRow.__table__,
              ApprovalRequestRow.__table__, IncidentControlRow.__table__]
    for table in tables:
        table.create(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(module, 'SessionLocal', sessions)
    service = module.PaymentSandboxCutoverService()
    with sessions.begin() as s:
        s.add(HostedDirectHotelRow(hosted_hotel_id='isolated-hotel', supplier_name='ISOLATED',
              page_slug='aoluguya-harbin', city='TEST', contact_json={}, state='ACTIVE', updated_at=module.now()))
        s.add(HostedDirectPaymentReadinessRow(hosted_hotel_id='isolated-hotel', provider='ALIPAY',
              merchant_account_name='ISOLATED', application_state='SANDBOX_CERTIFIED_NOT_LIVE',
              blockers_json=[], updated_at=module.now()))
        s.add(OmnichannelMerchantBindingRow(merchant_binding_id='isolated-merchant',
              owner_type='HOSTED_HOTEL', owner_id='isolated-hotel', channel='ALIPAY', market='CN',
              merchant_reference='isolated://merchant', credential_reference='isolated://no-key',
              webhook_key_reference='isolated://no-key', capabilities_json=[],
              state='ACTIVE_CERTIFIED', updated_at=module.now()))
        event = service.record_certification_grant(s, channel='ALIPAY', actor='fixture',
              evidence_reference='evidence://isolated/grant', external_evidence_reference='isolated://not-a-psp-proof',
              scenario_results={'INTERNAL_FIXTURE': 'PASS'})
        event_id = event.audit_id
    yield service, sessions, event_id


@pytest.mark.parametrize('field', [
    'payload', 'actor', 'action', 'approval', 'content_hash', 'entry_hash',
    'previous_hash', 'evidence_reference', 'append_only', 'missing_payload', 'invalid_metadata',
])
def test_tampered_audit_blocks_certification_and_additional_writes(audit, field):
    service, sessions, event_id = audit
    assert service.evidence_ledger()['chain_valid']
    assert service.status()['certification_valid']
    with sessions.begin() as s:
        event = s.get(AuditEventRow, event_id)
        if field == 'payload':
            payload = deepcopy(event.after_state)
            payload['immutable_payload']['scenario_results'] = {'FORGED': 'PASS'}
            event.after_state = payload
        elif field == 'missing_payload':
            event.after_state = {}
        elif field == 'invalid_metadata':
            event.metadata_json = ['not-a-metadata-object']
        elif field in {'actor', 'action', 'approval'}:
            setattr(event, {'actor': 'actor_id', 'action': 'action', 'approval': 'approval_id'}[field], 'FORGED')
        else:
            meta = deepcopy(event.metadata_json)
            meta[field] = False if field == 'append_only' else 'FORGED'
            event.metadata_json = meta
    assert not service.evidence_ledger()['chain_valid']
    assert not service.status()['certification_valid']
    assert not service.status()['sandbox_execution_allowed']
    with pytest.raises(ValueError, match='VALID_PAYMENT_SANDBOX_CERTIFICATION_REQUIRED'):
        service.assert_sandbox_execution_allowed('ALIPAY')
    with pytest.raises(ValueError, match='EVIDENCE_CHAIN_INVALID'):
        with sessions.begin() as s:
            service.record_certification_grant(s, channel='ALIPAY', actor='fixture',
                evidence_reference='evidence://isolated/new', external_evidence_reference='isolated://new',
                scenario_results={'INTERNAL_FIXTURE': 'PASS'})
    with sessions() as s:
        assert len(s.scalars(select(AuditEventRow)).all()) == 1
        assert len(s.scalars(select(ApprovalRequestRow)).all()) == 0


@pytest.mark.parametrize('field', ['resource_type', 'resource_id'])
def test_changed_identity_cannot_hide_corruption_and_allow_new_grant(audit, field):
    service, sessions, event_id = audit
    with sessions.begin() as s:
        setattr(s.get(AuditEventRow, event_id), field, 'TAMPERED')
    assert not service.evidence_ledger()['chain_valid']
    with pytest.raises(ValueError, match='EVIDENCE_CHAIN_INVALID'):
        with sessions.begin() as s:
            service.record_certification_grant(s, channel='ALIPAY', actor='review',
                evidence_reference='evidence://review/new', external_evidence_reference='isolated://review',
                scenario_results={'INTERNAL': 'PASS'})


def test_preflight_cannot_report_certification_for_corrupted_chain(audit, monkeypatch):
    from go_hotel.services import payment_sandbox_runtime as runtime
    service, sessions, event_id = audit
    monkeypatch.setattr(runtime, 'SessionLocal', sessions)
    with sessions.begin() as s:
        s.get(AuditEventRow, event_id).actor_id = 'TAMPERED'
    assert not service.status()['certification_valid']
    assert runtime.payment_sandbox_runtime_service.certification_preflight()['payment_sandbox_certified'] is False


def test_concurrent_append_commits_one_serial_chain(audit):
    service, sessions, event_id = audit
    barrier = Barrier(4)
    def append(index):
        with sessions.begin() as s:
            barrier.wait(timeout=10)
            service._append_event(s, channel='ALIPAY', actor='review', action='REVIEW',
                payload={'index': index}, evidence_reference=f'evidence://review/{index}')
        return 'committed'
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(append, range(4))) == ['committed'] * 4
    ledger = service.evidence_ledger()
    assert ledger['chain_valid'] and ledger['entry_count'] == 5


def test_valid_controls_replay_and_frozen_clock_follow_hash_links(audit, monkeypatch):
    service, sessions, event_id = audit
    frozen = module.now() + timedelta(seconds=1)
    monkeypatch.setattr(module, 'now', lambda: frozen)
    with sessions.begin() as s:
        first = service._append_event(s, channel='ALIPAY', action='CONTROL_A', actor='fixture',
            payload={'reason': 'first'}, evidence_reference='evidence://isolated/a')
        first.audit_id = 'zzz-first'
        s.flush()
        second = service._append_event(s, channel='ALIPAY', action='CONTROL_B', actor='fixture',
            payload={'reason': 'second'}, evidence_reference='evidence://isolated/b')
        second.audit_id = 'aaa-second'
    assert service.evidence_ledger()['chain_valid']
    assert service.status()['certification_valid']
    with sessions.begin() as s:
        replay = service._append_event(s, channel='ALIPAY', action='CONTROL_A', actor='fixture',
            payload={'reason': 'first'}, evidence_reference='evidence://isolated/a')
        assert replay.audit_id == 'zzz-first'
    assert service.evidence_ledger()['entry_count'] == 3


@pytest.mark.parametrize('field', ['actor', 'action', 'approval_id'])
def test_evidence_reference_cannot_rebind_a_different_control(audit, field):
    service, sessions, event_id = audit
    with sessions.begin() as s:
        service._append_event(s, channel='ALIPAY', action='CONTROL', actor='fixture',
            payload={'value': 1}, evidence_reference='evidence://isolated/replay')
    kwargs = dict(channel='ALIPAY', action='CONTROL', actor='fixture', payload={'value': 1},
                  evidence_reference='evidence://isolated/replay', approval_id=None)
    kwargs[field] = 'DIFFERENT'
    with pytest.raises(ValueError, match='EVIDENCE_REFERENCE_CONFLICT'):
        with sessions.begin() as s:
            service._append_event(s, **kwargs)
    assert service.evidence_ledger()['entry_count'] == 2


def test_configuration_alone_never_reports_certified_connection(audit, monkeypatch):
    from go_hotel.services import payment_sandbox_runtime as runtime
    service, sessions, event_id = audit
    monkeypatch.setattr(runtime, 'SessionLocal', sessions)
    class ConfiguredOnly:
        configured = True
    monkeypatch.setattr(runtime, 'payment_sandbox_executor', ConfiguredOnly())
    monkeypatch.setattr(module, 'payment_sandbox_executor', ConfiguredOnly())
    with sessions.begin() as s:
        row = s.get(HostedDirectPaymentReadinessRow, 'isolated-hotel')
        row.application_state = 'READY_NOT_PSP_CONNECTED'
        row.sandbox_app_id_reference = 'sandbox-app://fixture/not-real'
        row.kms_reference = 'kms://fixture/not-real'
    result = runtime.payment_sandbox_runtime_service.readiness()
    assert result['external_configuration_present']
    assert result['external_psp_connected'] is False
    with sessions.begin() as s:
        s.get(HostedDirectPaymentReadinessRow, 'isolated-hotel').application_state = 'SANDBOX_CERTIFIED_NOT_LIVE'
    assert runtime.payment_sandbox_runtime_service.readiness()['external_psp_connected']
    with sessions.begin() as s:
        s.get(AuditEventRow, event_id).actor_id = 'tampered'
    assert runtime.payment_sandbox_runtime_service.readiness()['external_psp_connected'] is False


@pytest.mark.parametrize('expiry', [None, 'not-a-date', '2099-01-01T00:00:00'])
def test_missing_invalid_or_naive_grant_expiry_never_authorizes(audit, expiry):
    service, sessions, event_id = audit
    with sessions.begin() as s:
        service._append_event(s, channel='ALIPAY', actor='fixture',
            action='PAYMENT_SANDBOX_CERTIFICATION_GRANTED',
            evidence_reference='evidence://isolated/invalid-expiry', payload={'expires_at': expiry})
    assert service.evidence_ledger()['chain_valid']
    assert not service.status()['certification_valid']
