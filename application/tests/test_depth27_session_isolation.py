"""Isolated HTTP acceptance; no browser or Hong Kong execution is implied."""
import pytest


def identities(client, actor='supplier_owner', password='change-me-supplier'):
    r = client.post('/v1/consumer/auth/register', json={
        'email': 'depth27@example.test', 'password': 'Isolated-Depth27-Only!',
        'display_name': 'Isolated traveler',
    })
    assert r.status_code == 200, r.text
    user = r.json()['data']['profile']['user_id']
    r = client.post('/bff/auth/login', json={'username': actor, 'password': password})
    assert r.status_code == 200, r.text
    return user


@pytest.mark.parametrize('actor,password', [
    ('supplier_owner', 'change-me-supplier'), ('go_admin', 'change-me-admin'),
])
def test_consumer_and_console_can_coexist_and_logout_independently(client, actor, password):
    user = identities(client, actor, password)
    r = client.get('/v1/consumer/me')
    assert r.status_code == 200, r.text
    assert r.json()['data']['user_id'] == user
    assert client.get('/bff/auth/me').json()['data']['username'] == actor
    r = client.post('/v1/consumer/auth/logout', headers={
        'X-CSRF-Token': client.cookies.get('go_consumer_csrf'),
    })
    assert r.status_code == 200, r.text
    assert client.get('/v1/consumer/me').status_code == 401
    assert client.get('/bff/auth/me').json()['data']['username'] == actor


def test_console_logout_does_not_fall_back_to_consumer_session(client):
    user = identities(client)
    r = client.post('/bff/auth/logout', headers={'X-CSRF-Token': client.cookies.get('go_csrf')})
    assert r.status_code == 200, r.text
    assert client.get('/bff/auth/me').status_code == 401
    assert client.get('/v1/consumer/me').json()['data']['user_id'] == user


def test_consumer_refresh_uses_own_csrf_with_console_cookie_present(client):
    identities(client)
    console_cookie = client.cookies.get('go_access')
    old = client.cookies.get('go_consumer_refresh')
    r = client.post('/v1/consumer/auth/refresh', headers={
        'X-CSRF-Token': client.cookies.get('go_consumer_csrf'),
    })
    assert r.status_code == 200, r.text
    assert client.cookies.get('go_consumer_refresh') != old
    assert client.cookies.get('go_access') == console_cookie


def test_other_scope_csrf_cannot_logout_consumer(client):
    identities(client)
    r = client.post('/v1/consumer/auth/logout', headers={
        'X-GO-Session': 'consumer', 'X-CSRF-Token': client.cookies.get('go_csrf'),
    })
    assert r.status_code == 403
    assert client.get('/v1/consumer/me').status_code == 200


def test_shared_endpoint_uses_explicit_scope_and_rejects_ambiguity(client):
    user = identities(client)
    r = client.get('/v1/auth/me', headers={'X-GO-Session': 'consumer'})
    assert r.status_code == 200, r.text
    assert r.json()['data']['user_id'] == user
    assert client.get('/v1/auth/me').status_code == 409
    assert client.get('/v1/auth/me', headers={'X-GO-Session': 'invented'}).status_code == 400


def test_header_cannot_change_fixed_route_scope_or_grant_permissions(client):
    identities(client)
    assert client.get('/v1/consumer/me', headers={'X-GO-Session': 'console'}).status_code == 400
    assert client.get('/bff/auth/me', headers={'X-GO-Session': 'consumer'}).status_code == 400
    assert client.get('/internal/v1/audit-events', headers={'X-GO-Session': 'console'}).status_code == 403


def test_expired_console_access_does_not_shadow_consumer(client):
    user = identities(client)
    for cookie in list(client.cookies.jar):
        if cookie.name == 'go_access':
            cookie.value = 'expired-isolated-fixture'
    r = client.get('/v1/consumer/me')
    assert r.status_code == 200, r.text
    assert r.json()['data']['user_id'] == user


def test_bearer_identity_stays_authoritative(client):
    identities(client)
    token = client.cookies.get('go_consumer_access')
    r = client.get('/v1/auth/me', headers={'Authorization': 'Bearer ' + token})
    assert r.status_code == 200
    assert r.json()['data']['actor_type'] == 'CONSUMER'
    assert client.get('/internal/v1/audit-events', headers={'Authorization': 'Bearer ' + token}).status_code == 403


def test_wrong_console_login_does_not_replace_existing_session(client):
    identities(client)
    old = client.cookies.get('go_access')
    r = client.post('/bff/auth/login', json={
        'username': 'go_admin', 'password': 'change-me-admin', 'expected_actor_type': 'SUPPLIER_USER',
    })
    assert r.status_code == 401
    assert r.json()['detail'] == 'ACCOUNT_TYPE_MISMATCH'
    assert not r.headers.get('set-cookie')
    assert client.cookies.get('go_access') == old
    assert client.get('/bff/auth/me').json()['data']['actor_type'] == 'SUPPLIER_USER'


def test_other_console_tab_identity_change_is_detected_before_action(client):
    identities(client)
    r = client.post('/bff/auth/login', json={
        'username': 'go_admin', 'password': 'change-me-admin', 'expected_actor_type': 'GO_ADMIN',
    })
    assert r.status_code == 200
    r = client.post('/bff/auth/logout', headers={
        'X-GO-Session': 'console', 'X-GO-Actor': 'SUPPLIER_USER',
        'X-CSRF-Token': client.cookies.get('go_csrf'),
    })
    assert r.status_code == 403
    assert r.json()['detail'] == 'ACTOR_CONTEXT_CHANGED'
    assert client.get('/bff/auth/me').json()['data']['actor_type'] == 'GO_ADMIN'
