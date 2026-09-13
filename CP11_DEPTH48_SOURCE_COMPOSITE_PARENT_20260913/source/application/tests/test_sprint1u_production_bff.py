from pathlib import Path
from go_hotel.security.mfa import totp
from go_hotel.security.service import identity_service


def csrf(client):
    return {'X-CSRF-Token':client.cookies.get('go_csrf')}

def test_bff_uses_http_only_cookies_and_no_tokens_in_payload(client):
    r=client.post('/bff/auth/login',json={'username':'supplier_owner','password':'change-me-supplier'})
    assert r.status_code==200, r.text
    assert 'access_token' not in r.text and 'refresh_token' not in r.text
    assert client.cookies.get('go_access')
    assert client.cookies.get('go_refresh')
    assert client.cookies.get('go_csrf')
    me=client.get('/bff/auth/me')
    assert me.status_code==200 and me.json()['data']['supplier_id']=='sup_mock'

def test_csrf_blocks_cookie_authenticated_mutation(client):
    client.post('/bff/auth/login',json={'username':'supplier_owner','password':'change-me-supplier'})
    blocked=client.post('/bff/auth/logout')
    assert blocked.status_code==403
    ok=client.post('/bff/auth/logout',headers=csrf(client))
    assert ok.status_code==200

def test_security_headers_are_present(client):
    r=client.get('/supplier-console/')
    assert r.headers['x-frame-options']=='DENY'
    assert "frame-ancestors 'none'" in r.headers['content-security-policy']
    assert "'unsafe-inline'" not in r.headers['content-security-policy']
    assert r.headers['x-content-type-options']=='nosniff'

def test_mfa_enrollment_and_login_enforcement(client):
    client.post('/bff/auth/login',json={'username':'go_admin','password':'change-me-admin'})
    setup=client.post('/bff/auth/mfa/setup',headers=csrf(client))
    assert setup.status_code==200, setup.text
    secret=setup.json()['data']['secret']
    confirm=client.post('/bff/auth/mfa/confirm',headers=csrf(client),json={'code':totp(secret)})
    assert confirm.status_code==200, confirm.text
    client.cookies.clear()
    missing=client.post('/bff/auth/login',json={'username':'go_admin','password':'change-me-admin'})
    assert missing.status_code==401
    good=client.post('/bff/auth/login',json={'username':'go_admin','password':'change-me-admin','totp_code':totp(secret)})
    assert good.status_code==200, good.text

def test_frontend_has_no_localstorage_auth_tokens():
    text=Path('frontend/shared/api.js').read_text()
    assert 'localStorage' not in text
    assert 'access_token' not in text
    assert 'refresh_token' not in text
    assert '/bff/auth/login' in text
