"""Real session/RBAC privacy boundaries; all users and records are isolated."""
from uuid import uuid4
import pytest
from sqlalchemy import select, func, event
from go_hotel.core.config import settings
from go_hotel.db.session import SessionLocal, engine
from go_hotel.db.models import PrivacyRequestRow, AuditEventRow, IdentityUserRow
from go_hotel.security.service import identity_service
from go_hotel.security.rbac import PERMISSIONS, ADMIN_ROLES, SUPPLIER_ROLES
from go_hotel.services import registration_privacy as privacy

QUEUE = '/internal/privacy/requests'


def session(role, actor='GO_ADMIN'):
    name = 'privacy-isolated-' + uuid4().hex
    password = 'Synthetic-privacy-only-2026!'
    uid = identity_service.ensure_user(name, password, actor,
        'isolated-supplier' if actor == 'SUPPLIER_USER' else None, [role])
    tokens = identity_service.login(name, password)
    return uid, tokens, {'Authorization': 'Bearer ' + tokens['access_token']}


def body(expected='RECEIVED', status='IN_REVIEW', **kw):
    return {'expected_status': expected, 'status': status,
            'evidence_ref': 'isolated://case-review', 'summary': 'isolated review', **kw}


def test_privacy_role_matrix_rejects_all_other_roles_and_actors(client, monkeypatch):
    monkeypatch.setattr(settings, 'mfa_required_for_admin', False)
    # Authoritative source mapping, not permissions supplied in a request/token.
    assert {r for r, p in PERMISSIONS.items() if 'admin:trust' in p} == {'GO_TRUST', 'GO_GOVERNANCE'}
    case = privacy.submit_request('isolated-subject', 'ACCESS')
    target = QUEUE + '/' + case['request_id'] + '/resolution'
    assert client.get(QUEUE).status_code == 401
    assert client.post(target, json=body()).status_code == 401
    for role in sorted(ADMIN_ROLES - {'GO_TRUST', 'GO_GOVERNANCE'}):
        _, _, headers = session(role)
        assert client.get(QUEUE, headers=headers).status_code == 403, role
        assert client.post(target, headers=headers, json=body()).status_code == 403, role
    for actor, roles in [('SUPPLIER_USER', SUPPLIER_ROLES | {'GO_TRUST'}),
                         ('CONSUMER', {'CONSUMER', 'GO_GOVERNANCE'})]:
        for role in sorted(roles):
            _, _, headers = session(role, actor)
            assert client.get(QUEUE, headers=headers).status_code == 403, (actor, role)
            assert client.post(target, headers=headers, json=body()).status_code == 403, (actor, role)
    with SessionLocal() as s:
        assert s.get(PrivacyRequestRow, case['request_id']).status == 'RECEIVED'
        assert s.scalar(select(func.count()).select_from(AuditEventRow).where(
            AuditEventRow.action == 'PRIVACY_REQUEST_RESOLVED')) == 0


@pytest.mark.parametrize('role', ['GO_TRUST', 'GO_GOVERNANCE'])
def test_authorized_review_and_user_visible_outcome_are_audited(client, monkeypatch, role):
    monkeypatch.setattr(settings, 'mfa_required_for_admin', False)
    subject, _, consumer = session('CONSUMER', 'CONSUMER')
    case = client.post('/v1/consumer/privacy/requests', headers=consumer, json={'kind': 'ACCESS'}).json()['data']
    operator, _, headers = session(role)
    queue = client.get(QUEUE, headers=headers)
    assert queue.status_code == 200 and queue.headers['cache-control'] == 'no-store'
    assert case['request_id'] in {x['request_id'] for x in queue.json()['data']['items']}
    target = QUEUE + '/' + case['request_id'] + '/resolution'
    assert client.post(target, headers=headers, json=body(status='COMPLETED')).status_code == 409
    assert client.post(target, headers=headers, json=body(evidence_ref='')).status_code == 422
    assert client.post(target, headers=headers, json=body()).status_code == 200
    assert client.post(target, headers=headers, json=body()).status_code == 409
    assert client.post(target, headers=headers, json=body('IN_REVIEW', 'REJECTED')).status_code == 422
    restriction = body('IN_REVIEW', 'RESTRICTED_RETENTION', legal_basis='isolated obligation')
    assert client.post(target, headers=headers, json=restriction).status_code == 422
    assert client.post(target, headers=headers, json=body('IN_REVIEW', 'COMPLETED',
        evidence_ref='isolated://access-response-receipt', summary='synthetic access response delivered')).status_code == 200
    assert client.post(target, headers=headers, json=body('IN_REVIEW', 'COMPLETED')).status_code == 409
    own = client.get('/v1/consumer/privacy', headers=consumer).json()['data']['requests']
    assert own[0]['status'] == 'COMPLETED'
    assert own[0]['resolution']['summary'] == 'synthetic access response delivered'
    _, _, foreign = session('CONSUMER', 'CONSUMER')
    assert client.get('/v1/consumer/privacy', headers=foreign).json()['data']['requests'] == []
    with SessionLocal() as s:
        audits = s.scalars(select(AuditEventRow).where(AuditEventRow.action == 'PRIVACY_REQUEST_RESOLVED',
            AuditEventRow.resource_id == case['request_id']).order_by(AuditEventRow.created_at)).all()
        assert len(audits) == 2
        assert all(x.actor_id == operator and x.actor_type == 'GO_ADMIN' and role in x.roles for x in audits)
        assert audits[0].before_state == {'status': 'RECEIVED'}
        assert audits[-1].after_state == {'status': 'COMPLETED'}
        assert audits[-1].metadata_json['evidence_ref'] == 'isolated://access-response-receipt'
        assert s.get(IdentityUserRow, subject).status == 'ACTIVE'


def test_permission_downgrade_and_revoked_session_take_effect_immediately(client, monkeypatch):
    monkeypatch.setattr(settings, 'mfa_required_for_admin', False)
    uid, tokens, headers = session('GO_TRUST')
    case = privacy.submit_request('isolated-subject', 'DELETION')
    target = QUEUE + '/' + case['request_id'] + '/resolution'
    assert client.get(QUEUE, headers=headers).status_code == 200
    with SessionLocal.begin() as s: s.get(IdentityUserRow, uid).roles = ['GO_READ_ONLY']
    assert client.get(QUEUE, headers=headers).status_code == 403
    assert client.post(target, headers=headers, json=body()).status_code == 403
    with SessionLocal.begin() as s: s.get(IdentityUserRow, uid).roles = ['GO_TRUST']
    principal = identity_service.authenticate(tokens['access_token'])
    identity_service.revoke_session(principal.session_id)
    assert client.get(QUEUE, headers=headers).status_code == 401
    assert client.post(target, headers=headers, json=body()).status_code == 401


def test_cookie_resolution_requires_session_bound_csrf(client, monkeypatch):
    monkeypatch.setattr(settings, 'mfa_required_for_admin', False)
    _, tokens, _ = session('GO_TRUST')
    case = privacy.submit_request('isolated-subject', 'CORRECTION')
    target = QUEUE + '/' + case['request_id'] + '/resolution'
    client.cookies.set(settings.access_cookie_name, tokens['access_token'])
    client.cookies.set(settings.csrf_cookie_name, tokens['csrf_token'])
    assert client.post(target, json=body()).status_code == 403
    assert client.post(target, headers={settings.csrf_header_name: 'forged'}, json=body()).status_code == 403
    assert client.post(target, headers={settings.csrf_header_name: tokens['csrf_token']}, json=body()).status_code == 200


def test_audit_failure_rolls_back_resolution(client, monkeypatch):
    monkeypatch.setattr(settings, 'mfa_required_for_admin', False)
    _, _, headers = session('GO_TRUST')
    case = privacy.submit_request('isolated-subject', 'CLOSURE')
    target = QUEUE + '/' + case['request_id'] + '/resolution'
    def fail(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith('INSERT INTO audit_event'):
            raise RuntimeError('isolated audit failure')
    event.listen(engine, 'before_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError, match='isolated audit failure'):
            client.post(target, headers=headers, json=body())
    finally:
        event.remove(engine, 'before_cursor_execute', fail)
    with SessionLocal() as s:
        assert s.get(PrivacyRequestRow, case['request_id']).status == 'RECEIVED'
