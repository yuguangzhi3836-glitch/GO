from go_hotel.core.config import settings
from go_hotel.security.mfa import totp


def test_admin_first_mfa_enrollment_login_logout_relogin(client):
    old = settings.mfa_required_for_admin
    settings.mfa_required_for_admin = True
    try:
        # Password-only admin login is intentionally blocked until MFA enrollment.
        r = client.post('/bff/auth/login', json={
            'username': settings.bootstrap_admin_username,
            'password': settings.bootstrap_admin_password,
        })
        assert r.status_code == 401
        assert r.json()['detail'] == 'MFA_ENROLLMENT_REQUIRED'

        # Password-gated, purpose-bound enrollment bootstrap.
        r = client.post('/bff/auth/mfa/enroll/start', json={
            'username': settings.bootstrap_admin_username,
            'password': settings.bootstrap_admin_password,
        })
        assert r.status_code == 200
        enroll = r.json()['data']
        assert enroll['enrollment_token']
        assert enroll['secret']
        assert enroll['provisioning_uri'].startswith('otpauth://totp/')
        assert enroll['expires_in'] == 600

        # Confirming the first TOTP both enables MFA and creates an MFA-verified session.
        r = client.post('/bff/auth/mfa/enroll/confirm', json={
            'enrollment_token': enroll['enrollment_token'],
            'code': totp(enroll['secret']),
        })
        assert r.status_code == 200
        assert r.json()['data']['authenticated'] is True
        assert r.json()['data']['mfa_enrolled'] is True

        r = client.get('/bff/auth/me')
        assert r.status_code == 200
        assert r.json()['data']['actor_type'] == 'GO_ADMIN'

        # Logout closes that session.
        csrf=client.cookies.get(settings.csrf_cookie_name)
        r = client.post('/bff/auth/logout', headers={settings.csrf_header_name:csrf})
        assert r.status_code == 200

        # Subsequent password-only login remains blocked; MFA is never bypassed.
        r = client.post('/bff/auth/login', json={
            'username': settings.bootstrap_admin_username,
            'password': settings.bootstrap_admin_password,
        })
        assert r.status_code == 401
        assert r.json()['detail'] == 'MFA_REQUIRED_OR_INVALID'

        # Subsequent username + password + TOTP login succeeds.
        r = client.post('/bff/auth/login', json={
            'username': settings.bootstrap_admin_username,
            'password': settings.bootstrap_admin_password,
            'totp_code': totp(enroll['secret']),
        })
        assert r.status_code == 200
        assert r.json()['data']['authenticated'] is True
        r = client.get('/bff/auth/me')
        assert r.status_code == 200
        assert r.json()['data']['actor_type'] == 'GO_ADMIN'
    finally:
        settings.mfa_required_for_admin = old
