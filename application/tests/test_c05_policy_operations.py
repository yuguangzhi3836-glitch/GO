import json
from dataclasses import replace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import CommercialPolicyVersionRow as Policy, CommercialAuditEventRow as Event, AuthSessionRow
from go_hotel.security.service import identity_service
from go_hotel.mobility.ride import policy_operations as ops, cancellation_policy as contract
from go_hotel.mobility.ride.service import ride_service
from go_hotel.api.routes.ride_policy_operations import router
from go_hotel.services.commercial_constitution import commercial_constitution_service as generic
from ride_cancellation_fixture import envelope, accepted_body

BODY={'offer_id':'ride_standard','pickup':'A','dropoff':'B','pickup_at':'2030-01-01T12:00:00Z','currency':'CNY','passengers':[{'full_name':'TEST'}]}


def principal(name, role='GO_GOVERNANCE'):
    identity_service.ensure_user(name,'isolated-test-pass','GO_ADMIN',None,[role])
    tokens=identity_service.login(name,'isolated-test-pass')
    return identity_service.authenticate(tokens['access_token']), tokens['access_token']


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv('GO_RIDE_ISOLATED_POLICY_REGISTRY','1')
    return principal('policy-maker')[0], principal('policy-checker')[0]


def policy(version='v1', **changes):
    return json.loads(envelope(version=version)['raw_payload']) | changes


def active(env, version='v1', **changes):
    draft=ops.create(env[0],policy(version,**changes))
    return ops.transition(env[1],draft['policy_id'],draft['revision'],'activate')


def test_draft_hold_then_different_authenticated_checker_activates(env):
    d=ops.create(env[0],policy())
    assert ride_service.search('A','B',BODY['pickup_at'])[0]['cancellation']['state']=='POLICY_UNAVAILABLE'
    with pytest.raises(ValueError,match='MAKER_CHECKER'):ops.transition(env[0],d['policy_id'],d['revision'],'activate')
    a=ops.transition(env[1],d['policy_id'],d['revision'],'activate')
    assert a['state']=='ACTIVE'
    report=ops.diagnose(env[0]); assert report['offers'][0]['state']=='ISOLATED_READY'
    assert report['real_policy_state']=='HOLD_UNVERIFIED'
    assert report['offers'][0]['audit_count']==2


def test_revocation_between_quote_and_booking_rejects_and_no_fixture_fallback(env,monkeypatch):
    a=active(env); body=accepted_body(ride_service,BODY)
    monkeypatch.setenv('GO_RIDE_ISOLATED_CANCELLATION_POLICY_FILE','scripts/fixtures/ride-cancellation.synthetic.json')
    ops.transition(env[0],a['policy_id'],a['revision'],'revoke')
    with pytest.raises(ValueError,match='POLICY_UNAVAILABLE'):ride_service.create('owner',body)
    assert ops.resolve('ride_standard') is None


def test_existing_snapshot_is_immutable_after_new_version_and_revoke(env):
    a=active(env,before_fee_minor=123,after_fee_minor=456)
    order=ride_service.create('owner',accepted_body(ride_service,BODY))
    from go_hotel.db.models import MobilityRideOrderRow
    with SessionLocal() as s: before=contract.accepted_in(s,s.get(MobilityRideOrderRow,order['order_id']))
    newer=active(env,'v2',before_fee_minor=200,after_fee_minor=900)
    ops.transition(env[0],newer['policy_id'],newer['revision'],'revoke')
    with SessionLocal() as s:
        row=s.get(MobilityRideOrderRow,order['order_id'])
        assert contract.accepted_in(s,row)==before
        assert contract.refund_terms_in(s,row)['fee_minor']==123


def test_revision_changed_and_terminal_reactivation_rejected(env):
    a=active(env)
    with pytest.raises(ValueError,match='REVISION_CHANGED'):ops.transition(env[0],a['policy_id'],'0'*64,'revoke')
    revoked=ops.transition(env[0],a['policy_id'],a['revision'],'revoke')
    with pytest.raises(ValueError,match='STATE_CONFLICT'):ops.transition(env[1],a['policy_id'],revoked['revision'],'activate')


def test_superseded_not_reactivated_and_only_one_active(env):
    a=active(env); active(env,'v2')
    report=ops.diagnose(env[0])['offers'][0]['versions']
    assert [r['state'] for r in report]==['SUPERSEDED','ACTIVE']
    with pytest.raises(ValueError,match='STATE_CONFLICT'):ops.transition(env[1],a['policy_id'],report[0]['revision'],'activate')


def test_generic_approval_does_not_create_authority(env):
    d=ops.create(env[0],policy())
    generic.approve_policy(d['policy_id'],env[1].user_id)
    assert ride_service.search('A','B',BODY['pickup_at'])[0]['cancellation']['state']=='POLICY_UNAVAILABLE'
    assert ops.diagnose(env[0])['offers'][0]['state']=='HOLD'


@pytest.mark.parametrize('mutation',['content','audit','actor'])
def test_tampered_authority_holds(env,mutation):
    a=active(env)
    with SessionLocal.begin() as s:
        row=s.get(Policy,a['policy_id'])
        if mutation=='content':row.rule_json=dict(row.rule_json,before_fee_minor=5)
        elif mutation=='actor':row.approved_by='fabricated-admin'
        else:
            event=s.scalar(select(Event).where(Event.event_type=='C05_POLICY_ACTIVATED'))
            event.payload_json=dict(event.payload_json,sequence=10)
    assert ride_service.search('A','B',BODY['pickup_at'])[0]['cancellation']['state']=='POLICY_UNAVAILABLE'


def test_expired_policy_cannot_activate(env):
    d=ops.create(env[0],policy(effective_until='2021-01-01T00:00:00Z'))
    with pytest.raises(ValueError,match='NOT_EFFECTIVE'):ops.transition(env[1],d['policy_id'],d['revision'],'activate')
    assert ops.diagnose(env[0])['offers'][0]['versions'][0]['hold_reason']=='NOT_EFFECTIVE'


def test_real_policy_and_duplicate_version_rejected(env):
    with pytest.raises(ValueError,match='POLICY_INVALID'):ops.create(env[0],policy(data_mode='PRODUCTION',source_reference='approved-by-boss'))
    ops.create(env[0],policy())
    with pytest.raises(ValueError,match='VERSION_EXISTS'):ops.create(env[0],policy(before_fee_minor=20))


def test_revoked_session_and_readonly_role_cannot_mutate(env):
    readonly=principal('read-only','GO_READ_ONLY')[0]
    with pytest.raises(PermissionError):ops.create(readonly,policy())
    with SessionLocal.begin() as s:s.get(AuthSessionRow,env[0].session_id).status='REVOKED'
    with pytest.raises(PermissionError):ops.create(env[0],policy())


def test_fake_principal_session_cannot_authorize(env):
    with pytest.raises(PermissionError):ops.create(replace(env[0],session_id='claimed'),policy())


def test_disabled_registry_and_production_environment(env,monkeypatch):
    monkeypatch.delenv('GO_RIDE_ISOLATED_POLICY_REGISTRY')
    with pytest.raises(ValueError,match='DISABLED'):ops.create(env[0],policy())
    monkeypatch.setenv('GO_RIDE_ISOLATED_POLICY_REGISTRY','1')
    from go_hotel.core.config import settings
    monkeypatch.setattr(settings,'app_env','production')
    with pytest.raises(ValueError,match='LIVE_PROVIDER'):ops.create(env[0],policy())
    assert ops.diagnose(env[0])['registry_enabled'] is False


def test_admin_api_real_auth_and_forbidden_caller_authority_fields(env):
    app=FastAPI();app.include_router(router); client=TestClient(app)
    assert client.get('/internal/v1/ride-policy-operations').status_code==401
    p,token=principal('api-maker','GO_RULE_ADMIN'); headers={'Authorization':'Bearer '+token}
    assert client.post('/internal/v1/ride-policy-operations/drafts',json={'policy':policy(),'approved_by':'boss'},headers=headers).status_code==422
    draft=client.post('/internal/v1/ride-policy-operations/drafts',json={'policy':policy()},headers=headers)
    assert draft.status_code==200,draft.text
    row=draft.json()['data']
    assert client.post('/internal/v1/ride-policy-operations/'+row['policy_id']+'/activate',json={'revision':row['revision']},headers=headers).status_code==403


def test_concurrent_versions_and_activations_leave_one_active(env):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as executor:
        drafts=list(executor.map(lambda v:ops.create(env[0],policy(v)),['parallel-a','parallel-b']))
    assert sorted(d['version_no'] for d in drafts)==[1,2]
    with ThreadPoolExecutor(max_workers=2) as executor:
        def activate_draft(d):
            try: return ops.transition(env[1],d['policy_id'],d['revision'],'activate')['state']
            except ValueError as exc:
                assert str(exc)=='RIDE_POLICY_STALE_VERSION'
                return 'STALE'
        results=list(executor.map(activate_draft,drafts))
    assert 'ACTIVE' in results
    versions=ops.diagnose(env[0])['offers'][0]['versions']
    assert sum(r['state']=='ACTIVE' for r in versions)==1
    assert next(r for r in versions if r['state']=='ACTIVE')['version_no']==2
    assert ops.resolve('ride_standard') is not None


def test_failed_activation_rolls_back_superseding_and_audit(env,monkeypatch):
    old=active(env)
    new=ops.create(env[0],policy('next'))
    original=ops.audit
    def failure(s,offer,row,action,actor):
        if action=='ACTIVATED':raise RuntimeError('crash before commit')
        return original(s,offer,row,action,actor)
    monkeypatch.setattr(ops,'audit',failure)
    with pytest.raises(RuntimeError,match='crash'):ops.transition(env[1],new['policy_id'],new['revision'],'activate')
    versions=ops.diagnose(env[0])['offers'][0]['versions']
    assert [(r['policy_id'],r['state']) for r in versions]==[(old['policy_id'],'ACTIVE'),(new['policy_id'],'DRAFT')]
    assert ops.diagnose(env[0])['offers'][0]['audit_count']==3


def test_approver_session_expiry_does_not_retroactively_withdraw_policy(env):
    active(env)
    with SessionLocal.begin() as s:s.get(AuthSessionRow,env[1].session_id).status='REVOKED'
    assert ops.resolve('ride_standard') is not None
    draft=ops.create(env[0],policy('v2'))
    with pytest.raises(PermissionError):ops.transition(env[1],draft['policy_id'],draft['revision'],'activate')


def test_supplier_cannot_read_or_mutate_admin_policy_api(env):
    identity_service.ensure_user('policy-supplier','isolated-test-pass','SUPPLIER_USER','tenant-a',['SUPPLIER_OWNER'])
    token=identity_service.login('policy-supplier','isolated-test-pass')['access_token']
    app=FastAPI();app.include_router(router);client=TestClient(app)
    headers={'Authorization':'Bearer '+token}
    assert client.get('/internal/v1/ride-policy-operations',headers=headers).status_code==403
    assert client.post('/internal/v1/ride-policy-operations/drafts',headers=headers,json={'policy':policy()}).status_code==403


def test_older_draft_cannot_replace_newer_active_version(env):
    old=ops.create(env[0],policy('older'))
    active(env,'newer')
    with pytest.raises(ValueError,match='STALE_VERSION'):ops.transition(env[1],old['policy_id'],old['revision'],'activate')
    assert ops.diagnose(env[0])['offers'][0]['versions'][1]['state']=='ACTIVE'


def test_diagnostics_capabilities_are_authoritative_for_maker_checker_readonly(env):
    ops.create(env[0],policy())
    maker=ops.diagnose(env[0]);checker=ops.diagnose(env[1])
    assert maker['can_create'] is True
    assert maker['offers'][0]['versions'][0]['can_activate'] is False
    assert maker['offers'][0]['versions'][0]['can_revoke'] is True
    assert checker['offers'][0]['versions'][0]['can_activate'] is True
    reader=principal('diagnostic-reader','GO_READ_ONLY')[0]
    read=ops.diagnose(reader)
    assert read['can_create'] is False
    assert read['offers'][0]['versions'][0]['can_activate'] is False
    assert read['offers'][0]['versions'][0]['can_revoke'] is False
