"""C04 synthetic obligations: consent/source authority, not money receipts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from copy import deepcopy

import pytest
from sqlalchemy import select, func
from go_hotel.db.models import JourneyRecoveryEvidenceChainRow as EvidenceRow, OmnichannelMoneyMovementRow as Movement
from go_hotel.db.session import SessionLocal
from go_hotel.mobility.rental import deposit_authority as authority, damage
from tests.test_rental_damage_disputes import order, OWNER, MAKER, CHECKER, principal, ev, Order


@pytest.fixture
def eligible(order):
    with SessionLocal.begin() as s: s.get(Order, order).status = 'CONFIRMED'
    return order


def accepted(oid):
    proposed = authority.propose(OWNER, oid, 'propose')
    return authority.accept(OWNER, oid, proposed['obligation_id'], 'accept', 1, proposed['source_hash'], True)


def resolve(oid, obligation, **kwargs):
    with SessionLocal.begin() as s:
        return authority.resolve_obligation(s, oid, obligation['obligation_id'], obligation['revision'], obligation['source_hash'], **kwargs)


def test_server_fixture_full_source_and_explicit_consent(eligible):
    p = authority.propose(OWNER, eligible, 'propose')
    assert p['source']['amount_minor'] == 200000
    assert p['source']['payee_verification']['real_payee_verified'] is False
    assert p['source']['data_mode'] == 'ISOLATED_CONTRACT_FIXTURE'
    assert p['financial_state'] == 'NO_FINANCIAL_FACT_ASSERTED'
    with pytest.raises(ValueError, match='ACCEPTANCE_REQUIRED'): resolve(eligible, p)
    a = authority.accept(OWNER, eligible, p['obligation_id'], 'accept', 1, p['source_hash'], True)
    fact = resolve(eligible, a)
    assert fact['state'] == 'ACTIVATED' and fact['revision'] == 2
    assert fact['source_hash'] == p['source_hash'] and fact['consent']['source_hash'] == p['source_hash']
    assert fact['consent']['terms_hash'] == fact['terms_hash']
    with SessionLocal() as s: assert s.scalar(select(func.count()).select_from(Movement)) == 0


@pytest.mark.parametrize('accepted_value', [False, None, 1, 'true'])
def test_consent_cannot_be_inferred(eligible, accepted_value):
    p = authority.propose(OWNER, eligible, 'propose')
    with pytest.raises(ValueError, match='EXPLICIT_ACCEPTANCE'):
        authority.accept(OWNER, eligible, p['obligation_id'], 'accept', 1, p['source_hash'], accepted_value)


def test_replay_stale_and_forged_source_conflicts(eligible):
    p = authority.propose(OWNER, eligible, 'propose')
    assert authority.propose(OWNER, eligible, 'propose') == p
    with pytest.raises(ValueError, match='ALREADY_EXISTS'): authority.propose(OWNER, eligible, 'other-key')
    with pytest.raises(ValueError, match='VERSION_CONFLICT'):
        authority.accept(OWNER, eligible, p['obligation_id'], 'accept', 1, '0'*64, True)
    a = authority.accept(OWNER, eligible, p['obligation_id'], 'accept', 1, p['source_hash'], True)
    assert authority.accept(OWNER, eligible, p['obligation_id'], 'accept', 1, p['source_hash'], True) == a
    with pytest.raises(ValueError, match='IDEMPOTENCY_CONFLICT'):
        authority.accept(OWNER, eligible, p['obligation_id'], 'accept', 2, p['source_hash'], True)
    with pytest.raises(ValueError, match='VERSION_CONFLICT'): resolve(eligible, p)


@pytest.mark.parametrize('field,value', [('deposit_minor', 1), ('currency', 'USD'), ('vehicle_class', 'UNREGISTERED'), ('insurance', {'type':'BASIC','excess_minor':1})])
def test_arbitrary_order_values_do_not_approve_fixture(eligible, field, value):
    with SessionLocal.begin() as s: setattr(s.get(Order, eligible), field, value)
    with pytest.raises(ValueError, match='SOURCE_UNAVAILABLE'): authority.propose(OWNER, eligible, 'propose')


def test_tenant_admin_supplier_denied_consumer_consent(eligible):
    p = authority.propose(OWNER, eligible, 'propose')
    for actor in [MAKER, principal('other', 'CONSUMER'), principal('supplier', 'SUPPLIER_USER')]:
        with pytest.raises(ValueError, match='NOT_FOUND'):
            authority.accept(actor, eligible, p['obligation_id'], 'accept', 1, p['source_hash'], True)
    with pytest.raises(ValueError, match='NOT_FOUND'): authority.get_obligation(principal('other', 'CONSUMER'), eligible)


def test_expiry_and_source_drift_fail_closed(eligible, monkeypatch):
    p = accepted(eligible)
    original_now = authority.now
    monkeypatch.setattr(authority, 'now', lambda: original_now() + timedelta(days=2))
    with pytest.raises(ValueError, match='EXPIRED'): resolve(eligible, p)
    assert resolve(eligible, p, allow_expired=True)['state'] == 'ACTIVATED'
    with SessionLocal.begin() as s: s.get(Order, eligible).deposit_minor = 1
    with pytest.raises(ValueError, match='SOURCE_DRIFT'): resolve(eligible, p, allow_expired=True)


def test_consumer_must_reconfirm_before_expiry(eligible, monkeypatch):
    p = authority.propose(OWNER, eligible, 'propose'); original_now = authority.now
    monkeypatch.setattr(authority, 'now', lambda: original_now() + timedelta(days=2))
    with pytest.raises(ValueError, match='EXPIRED'):
        authority.accept(OWNER, eligible, p['obligation_id'], 'accept', 1, p['source_hash'], True)


def test_unique_anchor_concurrency_and_replay(eligible):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: authority.propose(OWNER, eligible, 'propose'), range(2)))
    assert results[0] == results[1]
    with SessionLocal() as s:
        assert s.get(EvidenceRow, results[0]['obligation_id']) is not None
        assert s.scalar(select(func.count()).select_from(EvidenceRow).where(EvidenceRow.evidence_kind == authority.KIND)) == 1


def test_consent_flush_crash_rolls_back_retry(eligible, monkeypatch):
    p = authority.propose(OWNER, eligible, 'propose'); original = authority.append_vertical_evidence
    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('CRASH')
    monkeypatch.setattr(authority, 'append_vertical_evidence', crash)
    with pytest.raises(RuntimeError): authority.accept(OWNER, eligible, p['obligation_id'], 'accept', 1, p['source_hash'], True)
    assert authority.get_obligation(OWNER, eligible)['state'] == 'PROPOSED'
    monkeypatch.setattr(authority, 'append_vertical_evidence', original)
    assert authority.accept(OWNER, eligible, p['obligation_id'], 'accept', 1, p['source_hash'], True)['state'] == 'ACTIVATED'


def test_tamper_or_wrong_anchor_cannot_resolve(eligible):
    a = accepted(eligible)
    with SessionLocal.begin() as s:
        row = s.get(EvidenceRow, a['obligation_id'])
        row.evidence_chain_id = 'unbound-anchor'
    with pytest.raises(ValueError, match='INTEGRITY_INVALID'): resolve(eligible, a)


def test_damage_decision_bound_before_open_and_appeal_holds_c11(eligible):
    a = accepted(eligible)
    with SessionLocal.begin() as s: s.get(Order, eligible).status = 'COMPLETED'
    c = damage.open_case(MAKER, eligible, 'case', 10000, 'CNY', ev('a'), ev('b'))
    assert c['deposit_obligation']['obligation_id'] == a['obligation_id']
    damage.respond(OWNER, eligible, c['case_id'], 'respond', 1, 'DISPUTE', ev('c'))
    damage.adjudicate(CHECKER, eligible, c['case_id'], 'decide', 2, 5000, 'partial', ev('d'))
    d = authority.decision_preview(CHECKER, eligible, a['obligation_id'], c['case_id'])
    with SessionLocal.begin() as s:
        fact = authority.resolve_decision(s, eligible, a['obligation_id'], c['case_id'], 3, d['decision_hash'])
        assert fact['awarded_minor'] == 5000 and fact['held'] is False
    damage.appeal(OWNER, eligible, c['case_id'], 'appeal', 3, 'recheck', ev('e'))
    with SessionLocal.begin() as s, pytest.raises(ValueError, match='DECISION_HELD'):
        authority.resolve_decision(s, eligible, a['obligation_id'], c['case_id'], 3, d['decision_hash'])


def test_returned_order_cannot_manufacture_prior_deposit_consent(order):
    with pytest.raises(ValueError, match='NOT_ELIGIBLE'): authority.propose(OWNER, order, 'propose')
    c = damage.open_case(MAKER, order, 'case', 10000, 'CNY', ev('a'), ev('b'))
    assert c['deposit_obligation'] is None
    with pytest.raises(ValueError, match='CASE_UNBOUND'):
        authority.decision_preview(CHECKER, order, 'fake-obligation', c['case_id'])


def test_http_server_fields_rejected_owner_discovery(eligible):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from go_hotel.api.routes.rental_deposit import router
    from go_hotel.security.deps import current_principal
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[current_principal] = lambda: OWNER
    path = f'/v1/mobility/rentals/orders/{eligible}/deposit-obligation'
    with TestClient(app) as client:
        assert client.get(path).json()['data'] is None
        assert client.post(path, json={'amount_minor':1}, headers={'Idempotency-Key':'propose'}).status_code == 422
        r = client.post(path, json={}, headers={'Idempotency-Key':'propose'})
        assert r.status_code == 200, r.text
        p = r.json()['data']
        r = client.post(path + '/' + p['obligation_id'] + '/accept', json={'expected_revision':1,'expected_source_hash':p['source_hash'],'accepted':True}, headers={'Idempotency-Key':'accept'})
        assert r.status_code == 200 and r.json()['data']['state'] == 'ACTIVATED'
        assert client.get(f'/v1/mobility/rentals/orders/{eligible}/damage-cases').json()['data']['items'] == []
        app.dependency_overrides[current_principal] = lambda: principal('other', 'CONSUMER')
        assert client.get(path).status_code == 404
        assert client.get(f'/v1/mobility/rentals/orders/{eligible}/damage-cases').status_code == 404


def test_expired_unaccepted_proposal_renewal_requires_new_hash_consent(eligible, monkeypatch):
    p = authority.propose(OWNER, eligible, 'propose'); original_now = authority.now
    with pytest.raises(ValueError, match='NOT_DUE'):
        authority.renew(OWNER, eligible, p['obligation_id'], 'renew', 1, p['source_hash'])
    monkeypatch.setattr(authority, 'now', lambda: original_now() + timedelta(days=2))
    r = authority.renew(OWNER, eligible, p['obligation_id'], 'renew', 1, p['source_hash'])
    assert r['source_hash'] != p['source_hash'] and r['revision'] == 2 and r['state'] == 'PROPOSED'
    assert r['obligation_id'] == p['obligation_id'] and r['consent'] is None
    assert authority.renew(OWNER, eligible, p['obligation_id'], 'renew', 1, p['source_hash']) == r
    with pytest.raises(ValueError, match='VERSION_CONFLICT'):
        authority.accept(OWNER, eligible, p['obligation_id'], 'accept-old', 1, p['source_hash'], True)
    a = authority.accept(OWNER, eligible, r['obligation_id'], 'accept-new', 2, r['source_hash'], True)
    assert a['revision'] == 3 and resolve(eligible, a)['state'] == 'ACTIVATED'
    with pytest.raises(ValueError, match='IMMUTABLE'):
        authority.renew(OWNER, eligible, a['obligation_id'], 'renew-accepted', 3, a['source_hash'])


def test_concurrent_renewals_cannot_fork_proposal(eligible, monkeypatch):
    p = authority.propose(OWNER, eligible, 'propose'); original_now = authority.now
    monkeypatch.setattr(authority, 'now', lambda: original_now() + timedelta(days=2))
    def run(key):
        try:
            authority.renew(OWNER, eligible, p['obligation_id'], key, 1, p['source_hash'])
            return 'PASS'
        except ValueError as e:
            assert 'VERSION_CONFLICT' in str(e)
            return 'CONFLICT'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, ['r1','r2'])) == ['CONFLICT','PASS']


def test_normal_return_admin_fact_releases_source_without_fake_case(eligible):
    a = accepted(eligible)
    with SessionLocal.begin() as s: s.get(Order, eligible).status = 'COMPLETED'
    with SessionLocal.begin() as s, pytest.raises(ValueError, match='FACT_REQUIRED'):
        authority.resolve_release(s, eligible, a['obligation_id'], 1, '0'*64)
    args = (MAKER, eligible, a['obligation_id'], 'return-review', 2, a['source_hash'], ev('a'))
    fact = authority.close_return(*args)
    assert authority.close_return(*args) == fact
    assert fact['reason'] == 'NO_DAMAGE_RETURN' and fact['financial_state'] == 'NO_FINANCIAL_FACT_ASSERTED'
    with SessionLocal.begin() as s:
        assert authority.resolve_release(s, eligible, a['obligation_id'], 1, fact['release_hash']) == fact
        assert damage._history(s, eligible) == []
        assert s.scalar(select(func.count()).select_from(Movement)) == 0
    with pytest.raises(ValueError, match='RETURN_FINALIZED'):
        damage.open_case(MAKER, eligible, 'case', 10000, 'CNY', ev('b'), ev('c'))


def test_consumer_or_pending_case_cannot_finalize_return(eligible):
    a = accepted(eligible)
    with SessionLocal.begin() as s: s.get(Order, eligible).status = 'COMPLETED'
    with pytest.raises(PermissionError):
        authority.close_return(OWNER, eligible, a['obligation_id'], 'return', 2, a['source_hash'], ev('a'))
    damage.open_case(MAKER, eligible, 'case', 10000, 'CNY', ev('b'), ev('c'))
    with pytest.raises(ValueError, match='REQUIRES_SETTLEMENT'):
        authority.close_return(MAKER, eligible, a['obligation_id'], 'return', 2, a['source_hash'], ev('a'))


def test_unproven_cancel_state_is_not_release_authority(eligible):
    a = accepted(eligible)
    with SessionLocal.begin() as s: s.get(Order, eligible).status = 'REFUNDED'
    with pytest.raises(ValueError, match='PROVEN_CANCELLATION_REQUIRED'):
        authority.close_return(MAKER, eligible, a['obligation_id'], 'return', 2, a['source_hash'], ev('a'))


def test_release_fact_after_expiry_and_wrong_version_rejected(eligible, monkeypatch):
    a = accepted(eligible); original_now = authority.now
    monkeypatch.setattr(authority, 'now', lambda: original_now() + timedelta(days=2))
    with SessionLocal.begin() as s: s.get(Order, eligible).status = 'COMPLETED'
    fact = authority.close_return(MAKER, eligible, a['obligation_id'], 'return', 2, a['source_hash'], ev('a'))
    with SessionLocal.begin() as s:
        assert authority.resolve_release(s, eligible, a['obligation_id'], 1, fact['release_hash'])['state'] == 'RELEASE_APPROVED'
    with SessionLocal.begin() as s, pytest.raises(ValueError, match='VERSION_CONFLICT'):
        authority.resolve_release(s, eligible, a['obligation_id'], 2, fact['release_hash'])


def test_return_finalize_crash_and_competing_claim_are_atomic(eligible, monkeypatch):
    a = accepted(eligible)
    with SessionLocal.begin() as s: s.get(Order, eligible).status = 'COMPLETED'
    original = authority.append_vertical_evidence
    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('RETURN_CRASH')
    monkeypatch.setattr(authority, 'append_vertical_evidence', crash)
    with pytest.raises(RuntimeError):
        authority.close_return(MAKER, eligible, a['obligation_id'], 'return', 2, a['source_hash'], ev('a'))
    monkeypatch.setattr(authority, 'append_vertical_evidence', original)
    def run(action):
        try:
            if action == 'RETURN': authority.close_return(MAKER, eligible, a['obligation_id'], 'return', 2, a['source_hash'], ev('a'))
            else: damage.open_case(MAKER, eligible, 'case', 10000, 'CNY', ev('b'), ev('c'))
            return 'PASS'
        except ValueError as e:
            assert any(x in str(e) for x in ['RETURN_FINALIZED','REQUIRES_SETTLEMENT'])
            return 'CONFLICT'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, ['RETURN','CLAIM'])) == ['CONFLICT','PASS']


def test_proven_original_rental_cancel_allows_release_source(client):
    from tests.test_depth06_rental_settlement import paid
    from go_hotel.mobility.rental.service import rental_service
    account, oid, _ = paid(client)
    owner = principal(account, 'CONSUMER', set())
    p = authority.propose(owner, oid, 'propose')
    a = authority.accept(owner, oid, p['obligation_id'], 'accept', 1, p['source_hash'], True)
    result = rental_service.cancel(account, oid)
    assert result['status'] == 'REFUND_COMPLETED'
    fact = authority.close_return(MAKER, oid, a['obligation_id'], 'cancel-review', 2, a['source_hash'], ev('a'))
    assert fact['reason'] == 'CANCELLED_REFUNDED'
    with SessionLocal.begin() as s:
        assert authority.resolve_release(s, oid, a['obligation_id'], 1, fact['release_hash']) == fact


def test_http_renew_and_admin_return_review(eligible, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from go_hotel.api.routes.rental_deposit import router
    from go_hotel.security.deps import current_principal
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[current_principal] = lambda: OWNER
    p = authority.propose(OWNER, eligible, 'propose'); original_now = authority.now
    monkeypatch.setattr(authority, 'now', lambda: original_now() + timedelta(days=2))
    base = f'/v1/mobility/rentals/orders/{eligible}/deposit-obligation/{p["obligation_id"]}'
    with TestClient(app) as client:
        r = client.post(base + '/renew', json={'expected_revision':1,'expected_source_hash':p['source_hash']}, headers={'Idempotency-Key':'renew'})
        assert r.status_code == 200, r.text
        p = r.json()['data']
        a = authority.accept(OWNER, eligible, p['obligation_id'], 'accept', 2, p['source_hash'], True)
        with SessionLocal.begin() as s: s.get(Order, eligible).status = 'COMPLETED'
        url = '/internal/v1/admin' + base[3:] + '/return-review'
        body = {'expected_revision':3,'expected_source_hash':a['source_hash'],'evidence':ev('a')}
        assert client.post(url,json=body,headers={'Idempotency-Key':'return'}).status_code == 403
        app.dependency_overrides[current_principal] = lambda: MAKER
        r = client.post(url,json=body,headers={'Idempotency-Key':'return'})
        assert r.status_code == 200, r.text
        assert r.json()['data']['state'] == 'RELEASE_APPROVED'
