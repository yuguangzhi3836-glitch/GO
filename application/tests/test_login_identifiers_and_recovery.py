"""Three-in-one login and account recovery, over the real app and a real DB.

Owner decisions under test (they supersede frozen decisions D-01 and D-11):

* One account, three login identifiers — username, email and phone — mutually
  bound and globally unique, any of which logs the same person in.
* Account recovery proves control of one of those channels with the *same*
  challenge machinery sign-up uses. There is no second security mechanism.
* ``registration_verification_test_code`` is the operator's explicit stand-in
  while no delivery is connected: it turns the runtime ready, skips delivery, and
  the fixed code is the delivery. With it off the whole surface answers 503.

Nothing here mocks authentication, cookies, CSRF, the database or the challenge
lifecycle; only the transports are synthetic.
"""
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select, update

from go_hotel.core.config import settings
from go_hotel.db.models import (
    AuthSessionRow,
    IdentityUserRow,
    RegistrationChallengeRow as Challenge,
    RegistrationRateRow as Rate,
)
from go_hotel.db.session import SessionLocal
from go_hotel.security.crypto import hash_password
from go_hotel.security.service import conflicting_identifier, identity_service, identifier_owner_id
from go_hotel.services import registration_email as mail, registration_sms as sms
from registration_terms_test_support import approved_terms_fixture, supplier_identifiers
from test_registration_verification import CHALLENGE_FIELDS, payload, send


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    """Real challenge lifecycle, synthetic email and SMS transports."""
    original_configuration = mail.configuration
    approved_terms_fixture(monkeypatch)
    monkeypatch.setattr(mail, 'configuration', original_configuration)
    monkeypatch.setattr(settings, 'jwt_signing_key', 'isolated-recovery-test-key-32-bytes-only')
    secret = tmp_path / 'existing-password'
    secret.write_text('isolated-only-password')
    cfg = tmp_path / 'mail.json'
    cfg.write_text(json.dumps({'sender': mail.SENDER, 'credential_reference': 'hk-staging-registration-email',
                               'host': 'smtp.test.invalid', 'port': 465, 'tls': 'SSL',
                               'username': mail.SENDER, 'password_file': str(secret)}))
    monkeypatch.setattr(settings, 'registration_email_config_path', str(cfg))
    sent = {'email': [], 'sms': []}
    monkeypatch.setattr(mail, 'send_code', lambda address, code: sent['email'].append((address, code)))
    monkeypatch.setattr(sms, 'send_code', lambda address, code: sent['sms'].append((address, code)))
    return sent


def supplier_account(client, delivery, email='recovery-supplier@example.test'):
    """Create a real supplier account through the product's own sign-up route."""
    body = send(client, delivery, 'supplier', email)
    response = client.post('/bff/auth/supplier/register', json=body)
    assert response.status_code == 201, response.text
    return body


def expire_code_limits():
    """Let the resend window elapse without waiting a real minute for it.

    Two independent things ration a resend inside 60 seconds: the durable
    per-address anti-abuse counters, and the sliding interval measured against the
    previous challenge row for the same (audience, identifier). A test clock has
    to move both, or it only half-simulates the minute going by. Neither is
    product state — one is a counter with its own expiry, the other a timestamp.

    The rule itself is pinned by
    ``test_one_address_cannot_be_asked_for_a_second_code_from_another_purpose``:
    one address deliberately cannot be asked for two codes inside one window, so
    the tests whose subject is *not* the limiter step over that window exactly as
    a real applicant waits it out.
    """
    with SessionLocal.begin() as s:
        s.execute(delete(Rate))
        s.execute(update(Challenge).values(created_ms=Challenge.created_ms - 60_000))


def attach_challenges(client, sent, body, pairs, audience='supplier'):
    """Issue one live challenge per ``(channel, identifier)`` and attach id + code.

    ``send()`` derives its identifiers from the address it is handed, which is not
    enough when the point of the test is that an identifier is *already taken*.
    """
    out = dict(body)
    for channel, identifier in pairs:
        request = {k: body[k] for k in CHALLENGE_FIELDS} | {
            'audience': audience, 'channel': channel, 'email': identifier}
        response = client.post('/v1/registration/challenges', json=request)
        assert response.status_code == 200, response.text
        out[f'{channel}_challenge_id'] = response.json()['data']['challenge_id']
        out[f'{channel}_verification_code'] = sent[channel][-1][1]
    return out


def login(client, identifier, password='Isolated-test-pass-123', path='/bff/auth/login'):
    return client.post(path, json={'username': identifier, 'password': password})


# --------------------------------------------------------------------------- #
# Three-in-one login                                                          #
# --------------------------------------------------------------------------- #

def test_one_account_answers_to_username_email_and_phone(client, delivery):
    body = supplier_account(client, delivery)
    # Signing in afresh each time also proves the three are not three accounts:
    # every login lands on the one supplier this sign-up created.
    for identifier in (body['username'], body['email'], body['phone']):
        response = login(client, identifier)
        assert response.status_code == 200, f'{identifier}: {response.text}'
        assert client.get('/bff/auth/me').json()['data']['actor_type'] == 'SUPPLIER_USER'
    with SessionLocal() as s:
        rows = s.scalars(select(IdentityUserRow).where(IdentityUserRow.phone == body['phone'])).all()
        assert len(rows) == 1
        assert rows[0].username == body['username'] and rows[0].email == body['email']


def test_identifier_shapes_are_normalised_not_rejected(client, delivery):
    body = supplier_account(client, delivery)
    # A padded, upper-cased address and a spaced, +86-prefixed mobile are the same
    # account, because registration and login normalise identically.
    assert login(client, '  ' + body['email'].upper() + '  ').status_code == 200
    spaced = '+86 ' + body['phone'][:3] + '-' + body['phone'][3:7] + '-' + body['phone'][7:]
    assert login(client, spaced).status_code == 200


def test_consumer_account_is_reachable_by_its_address(client, delivery):
    consumer = send(client, delivery, 'consumer', 'three-in-one-consumer@example.test')
    assert client.post('/v1/consumer/auth/register', json=consumer).status_code == 200
    # Display-cased and padded on the way in; the same account on the way out.
    response = client.post('/v1/consumer/auth/login', json={
        'email': ' Three-In-One-Consumer@Example.Test ', 'password': 'Isolated-test-pass-123'})
    assert response.status_code == 200, response.text
    with SessionLocal() as s:
        row = s.scalar(select(IdentityUserRow).where(IdentityUserRow.username == 'three-in-one-consumer@example.test'))
        assert row is not None and row.email == 'three-in-one-consumer@example.test' and row.phone is None


def test_consumer_address_cannot_be_taken_again_by_a_supplier(client, delivery):
    consumer = send(client, delivery, 'consumer', 'shared-address@example.test')
    assert client.post('/v1/consumer/auth/register', json=consumer).status_code == 200
    # Both doors write one identity namespace. Both legs run on the real routes;
    # only the resend window between them is stepped over, because the supplier
    # leg has to *prove* the address before it is entitled to learn anything about
    # it — asking with an invented challenge id would only ever say "bad code".
    expire_code_limits()
    clash = payload(client, 'supplier', 'shared-address@example.test')
    clash.update(organization_name='测试主体', **supplier_identifiers(clash))
    clash = attach_challenges(client, delivery, clash, (('email', clash['email']), ('sms', clash['phone'])))
    response = client.post('/bff/auth/supplier/register', json=clash)
    assert response.status_code == 409, response.text
    assert response.json()['detail'] == 'EMAIL_ALREADY_REGISTERED', response.text


def test_taken_mobile_is_refused_across_endpoints(client, delivery):
    owner = supplier_account(client, delivery, 'owner-one@example.test')
    expire_code_limits()
    other = payload(client, 'supplier', 'owner-two@example.test')
    other.update(organization_name='测试主体', **supplier_identifiers(other))
    other['username'] = 'owner-two-handle'     # a handle of its own, so the mobile is the only clash
    other['phone'] = owner['phone']            # the mobile another account already owns
    other = attach_challenges(client, delivery, other, (('email', other['email']), ('sms', other['phone'])))
    response = client.post('/bff/auth/supplier/register', json=other)
    assert response.status_code == 409 and response.json()['detail'] == 'PHONE_ALREADY_REGISTERED', response.text


# --------------------------------------------------------------------------- #
# Account recovery                                                            #
# --------------------------------------------------------------------------- #

def issue_recovery(client, identifier, channel='email'):
    sent = client.post('/bff/auth/recovery/challenge', json={'identifier': identifier, 'channel': channel})
    assert sent.status_code == 200, sent.text
    return sent.json()['data']


def test_one_address_cannot_be_asked_for_a_second_code_from_another_purpose(client, delivery):
    """One resend window per address, whichever purpose is asking. Deliberate.

    The thing being rationed is a message delivered to a destination, and the cost
    — carrier fee, harassment, brute-force surface — is per destination. Splitting
    the bucket by purpose would let a caller reach twice the delivery rate on a
    single address by alternating purposes, which is the cheapest possible way to
    defeat the limit. Keeping it shared costs one fail-closed minute after a fresh
    sign-up, and every other test in this file steps over that minute explicitly
    rather than writing an assertion that pretends it is not there.
    """
    body = supplier_account(client, delivery)
    again = client.post('/bff/auth/recovery/challenge',
                        json={'identifier': body['email'], 'channel': 'email'})
    assert again.status_code == 429, again.text
    assert again.json()['detail'] == 'REGISTRATION_CODE_RATE_LIMITED'


def test_recovery_returns_the_accounts_username_not_the_typed_identifier(client, delivery):
    body = supplier_account(client, delivery)
    expire_code_limits()
    # The applicant types their mobile; the answer is the handle they signed up
    # with, which is the whole point of "which account is mine".
    challenge = issue_recovery(client, body['phone'], 'sms')
    code = delivery['sms'][-1][1]
    response = client.post('/bff/auth/recovery/username', json={
        'identifier': body['phone'], 'channel': 'sms',
        'challenge_id': challenge['challenge_id'], 'verification_code': code})
    assert response.status_code == 200, response.text
    assert response.json()['data']['username'] == body['username']
    with SessionLocal() as s:
        assert s.scalar(select(Challenge).where(Challenge.challenge_id == challenge['challenge_id'])).state == 'CONSUMED'


def test_recovery_resets_password_and_revokes_every_session(client, delivery):
    body = supplier_account(client, delivery)
    expire_code_limits()
    assert login(client, body['email']).status_code == 200          # an existing live session
    challenge = issue_recovery(client, body['email'], 'email')
    response = client.post('/bff/auth/recovery/password', json={
        'identifier': body['email'], 'channel': 'email',
        'challenge_id': challenge['challenge_id'], 'verification_code': delivery['email'][-1][1],
        'new_password': 'Replacement-pass-456', 'confirm_password': 'Replacement-pass-456'})
    assert response.status_code == 200, response.text
    assert response.json()['data'] == {'status': 'PASSWORD_RESET', 'username': body['username']}
    with SessionLocal() as s:
        account = s.scalar(select(IdentityUserRow).where(IdentityUserRow.username == body['username']))
        assert account.token_version == 2
        assert not s.scalars(select(AuthSessionRow).where(
            AuthSessionRow.user_id == account.user_id, AuthSessionRow.status == 'ACTIVE')).all()
        assert s.scalar(select(Challenge).where(Challenge.challenge_id == challenge['challenge_id'])).state == 'CONSUMED'
    assert login(client, body['email'], 'Isolated-test-pass-123').status_code == 401
    assert login(client, body['phone'], 'Replacement-pass-456').status_code == 200


def test_recovery_password_requires_two_matching_entries(client, delivery):
    body = supplier_account(client, delivery)
    expire_code_limits()
    challenge = issue_recovery(client, body['email'])
    response = client.post('/bff/auth/recovery/password', json={
        'identifier': body['email'], 'challenge_id': challenge['challenge_id'],
        'verification_code': delivery['email'][-1][1],
        'new_password': 'Replacement-pass-456', 'confirm_password': 'Replacement-pass-999'})
    assert response.status_code == 422
    assert response.json()['detail'] == 'PASSWORD_CONFIRMATION_MISMATCH'
    with SessionLocal() as s:
        # The challenge is untouched, so the applicant can simply try again.
        assert s.scalar(select(Challenge).where(Challenge.challenge_id == challenge['challenge_id'])).state == 'SENT'
    assert login(client, body['email'], 'Isolated-test-pass-123').status_code == 200


def test_wrong_or_missing_recovery_code_changes_nothing(client, delivery):
    body = supplier_account(client, delivery)
    expire_code_limits()
    challenge = issue_recovery(client, body['email'])
    assert client.post('/bff/auth/recovery/username', json={
        'identifier': body['email'], 'challenge_id': challenge['challenge_id'],
        'verification_code': 'wrong'}).status_code == 409
    assert client.post('/bff/auth/recovery/username', json={
        'identifier': body['email'], 'challenge_id': challenge['challenge_id']}).status_code == 422
    assert login(client, body['email'], 'Isolated-test-pass-123').status_code == 200


def test_a_proved_username_code_cannot_be_reused_to_reset_the_password(client, delivery):
    body = supplier_account(client, delivery)
    expire_code_limits()
    challenge = issue_recovery(client, body['email'])
    code = delivery['email'][-1][1]
    assert client.post('/bff/auth/recovery/username', json={
        'identifier': body['email'], 'challenge_id': challenge['challenge_id'],
        'verification_code': code}).status_code == 200
    replay = client.post('/bff/auth/recovery/password', json={
        'identifier': body['email'], 'challenge_id': challenge['challenge_id'],
        'verification_code': code, 'new_password': 'Replacement-pass-456',
        'confirm_password': 'Replacement-pass-456'})
    assert replay.status_code == 409, replay.text
    assert login(client, body['email'], 'Isolated-test-pass-123').status_code == 200


def test_recovery_code_is_bound_to_its_channel(client, delivery):
    body = supplier_account(client, delivery)
    expire_code_limits()
    challenge = issue_recovery(client, body['email'], 'email')
    # Same account, same code, wrong channel: the challenge was issued for the
    # address on the email channel and cannot be spent against the mobile.
    response = client.post('/bff/auth/recovery/username', json={
        'identifier': body['phone'], 'channel': 'sms',
        'challenge_id': challenge['challenge_id'], 'verification_code': delivery['email'][-1][1]})
    assert response.status_code == 409, response.text


def test_unknown_identifier_is_named_only_in_the_operator_test_mode(client, delivery):
    response = client.post('/bff/auth/recovery/challenge',
                           json={'identifier': 'nobody@example.test', 'channel': 'email'})
    assert response.status_code == 404
    assert response.json()['detail'] == 'RECOVERY_ACCOUNT_NOT_FOUND'


def test_recovery_fails_closed_before_looking_at_anything(client, delivery, monkeypatch):
    # Arrange first: the account has to exist *before* the runtime is switched
    # off, or the test would only be proving that sign-up is closed too.
    known = supplier_account(client, delivery)
    monkeypatch.setattr(settings, 'registration_verification_enabled', False)
    monkeypatch.setattr(settings, 'registration_email_config_path', '')
    monkeypatch.setattr(settings, 'registration_verification_test_code', '')
    requests = (
        ('/bff/auth/recovery/challenge', {'identifier': known['email'], 'channel': 'email'}),
        ('/bff/auth/recovery/challenge', {'identifier': 'nobody@example.test', 'channel': 'email'}),
        ('/bff/auth/recovery/challenge', {'identifier': known['phone'], 'channel': 'sms'}),
        ('/bff/auth/recovery/username', {'identifier': known['email'], 'challenge_id': 'x', 'verification_code': '1'}),
        ('/bff/auth/recovery/password', {'identifier': known['email'], 'challenge_id': 'x', 'verification_code': '1',
                                         'new_password': 'Replacement-pass-456',
                                         'confirm_password': 'Replacement-pass-456'}),
    )
    # A known account, an unknown account and a half-filled request all get the
    # same answer, and it is the one that says "this surface is not switched on".
    # Nothing about which accounts exist can leak out of a door that never opens.
    for path, body in requests:
        response = client.post(path, json=body)
        assert response.status_code == 503, f'{path}: {response.text}'
        assert response.json()['detail'] == 'REGISTRATION_VERIFICATION_NOT_READY'


def test_recovery_endpoints_are_exempt_from_the_session_middleware():
    from go_hotel.main import Sprint1USecurityMiddleware
    for path in ('/bff/auth/recovery/challenge', '/bff/auth/recovery/username', '/bff/auth/recovery/password'):
        assert path in Sprint1USecurityMiddleware.EXEMPT
    # A control: the middleware really does have a list, and this is not a
    # vacuous loop over a set that accepts everything.
    assert '/v1/supplier/properties' not in Sprint1USecurityMiddleware.EXEMPT


# --------------------------------------------------------------------------- #
# The operator's test-code switch                                             #
# --------------------------------------------------------------------------- #

@pytest.fixture
def test_code(monkeypatch):
    """The explicit stand-in used for local demos: no transport, fixed code."""
    approved_terms_fixture(monkeypatch)
    monkeypatch.setattr(settings, 'jwt_signing_key', 'isolated-testcode-key-32-bytes-long!!')
    monkeypatch.setattr(settings, 'registration_verification_enabled', False)
    monkeypatch.setattr(settings, 'registration_email_config_path', '')
    monkeypatch.setattr(settings, 'registration_verification_test_code', '8888')
    sent = {'email': [], 'sms': []}
    monkeypatch.setattr(mail, 'send_code', lambda address, code: sent['email'].append((address, code)))
    monkeypatch.setattr(sms, 'send_code', lambda address, code: sent['sms'].append((address, code)))
    return sent


def test_test_code_makes_the_runtime_ready_without_any_transport(client, test_code):
    from go_hotel.services import registration_verification as verification
    assert verification.ready() is True
    assert client.get('/bff/auth/supplier/registration-terms').json()['data']['enabled'] is True


def test_test_code_is_returned_and_delivery_is_skipped(client, test_code):
    from test_registration_verification import CHALLENGE_FIELDS
    body = payload(client, 'supplier', 'testcode@example.test')
    body.update(supplier_identifiers(body))
    for channel, identifier in (('email', body['email']), ('sms', body['phone'])):
        request = {k: body[k] for k in CHALLENGE_FIELDS} | {
            'audience': 'supplier', 'channel': channel, 'email': identifier}
        response = client.post('/v1/registration/challenges', json=request)
        assert response.status_code == 200, response.text
        assert response.json()['data']['test_code'] == '8888'
    assert test_code['email'] == [] and test_code['sms'] == []


def test_the_fixed_code_creates_the_account_and_then_resets_it(client, test_code):
    body = payload(client, 'supplier', 'testcode-account@example.test')
    body.update(organization_name='测试主体', **supplier_identifiers(body))
    body.update(email_verification_code='8888', sms_verification_code='8888')
    # The challenge ids still have to come from a real issue, so a caller cannot
    # invent one alongside the fixed code.
    from test_registration_verification import CHALLENGE_FIELDS
    for channel, identifier, key in (('email', body['email'], 'email_challenge_id'),
                                     ('sms', body['phone'], 'sms_challenge_id')):
        response = client.post('/v1/registration/challenges', json={
            **{k: body[k] for k in CHALLENGE_FIELDS}, 'audience': 'supplier',
            'channel': channel, 'email': identifier})
        assert response.status_code == 200, response.text
        body[key] = response.json()['data']['challenge_id']
    created = client.post('/bff/auth/supplier/register', json=body)
    assert created.status_code == 201, created.text
    assert login(client, body['phone']).status_code == 200
    client.post('/bff/auth/logout')
    expire_code_limits()
    challenge = issue_recovery(client, body['email'])
    reset = client.post('/bff/auth/recovery/password', json={
        'identifier': body['email'], 'challenge_id': challenge['challenge_id'],
        'verification_code': '8888', 'new_password': 'Reset-via-fixed-code-1',
        'confirm_password': 'Reset-via-fixed-code-1'})
    assert reset.status_code == 200, reset.text
    assert login(client, body['username'], 'Reset-via-fixed-code-1').status_code == 200


def test_a_code_no_one_could_receive_never_leaks_when_the_switch_is_off(client, delivery):
    body = payload(client, 'consumer', 'no-leak@example.test')
    from test_registration_verification import CHALLENGE_FIELDS
    response = client.post('/v1/registration/challenges', json={
        **{k: body[k] for k in CHALLENGE_FIELDS}, 'audience': 'consumer', 'email': body['email']})
    assert response.status_code == 200
    assert response.json()['data']['test_code'] is None
    assert 'code' not in response.json()['data']


# --------------------------------------------------------------------------- #
# One namespace across all three columns                                      #
#                                                                             #
# "A username may not be a phone number" has two halves. The shape rule (a     #
# handle must contain a letter) makes the three shapes disjoint so a *new*      #
# account can no longer create the overlap. The collision check has to cover    #
# all three columns anyway, because databases already hold rows written before  #
# that rule existed — those rows are what these tests model.                    #
# --------------------------------------------------------------------------- #

def legacy_account(user_id, *, password='Legacy-account-pass-123', **columns):
    """Write an ``identity_user`` row the way one was written *before* the shapes
    were made disjoint.

    Sign-up cannot produce these rows any more, so a fixture that goes through the
    sign-up door could never exercise the cross-column arm of the check. Only the
    row is synthesised: every assertion below still runs through the real route,
    the real service and the real transaction.
    """
    stamp = datetime.now(timezone.utc)
    with SessionLocal.begin() as s:
        s.add(IdentityUserRow(
            user_id=user_id, username=columns.pop('username'), password_hash=hash_password(password),
            actor_type='SUPPLIER_USER', supplier_id='sup_' + user_id, roles=['SUPPLIER_OWNER'],
            status='ACTIVE', token_version=1, created_at=stamp, updated_at=stamp, **columns))
    return password


def test_a_handle_must_contain_a_letter_so_it_can_never_be_eleven_digits(client, delivery):
    """The shape rule, through the door a human actually uses.

    ``13354147708`` used to satisfy the username rule *and* the phone rule, which
    is what let one account's handle be another account's mobile number. The
    refusal names the field so the form marks that one box.
    """
    body = send(client, delivery, 'supplier', 'shape-owner@example.test')
    body['username'] = '13354147708'
    refused = client.post('/bff/auth/supplier/register', json=body)
    assert refused.status_code == 409, refused.text
    assert refused.json()['detail'] == 'VALID_USERNAME_REQUIRED', refused.text
    # Nothing was created and — because validation runs before the challenge is
    # consumed — nothing was spent either.
    with SessionLocal() as s:
        assert s.scalar(select(IdentityUserRow).where(IdentityUserRow.email == body['email'])) is None
        assert s.scalar(select(Challenge).where(Challenge.state == 'SENT')) is not None


def test_a_handle_may_still_contain_digits_as_long_as_it_has_a_letter(client, delivery):
    """The rule is "not all digits", not "no digits" — a hotel may be ``hk2026``."""
    body = send(client, delivery, 'supplier', 'digit-handle@example.test')
    body['username'] = 'hk-2026-owner'
    created = client.post('/bff/auth/supplier/register', json=body)
    assert created.status_code == 201, created.text
    assert login(client, 'hk-2026-owner').status_code == 200


def test_a_new_sign_up_cannot_take_a_mobile_that_is_somebody_elses_handle(client, delivery):
    """The cross-column arm, on the rows a live database already contains.

    An account whose *handle* is ``13900000001`` is the whole reason the check has
    to compare each supplied value against all three columns: the applicant's
    mobile is not in anybody's ``phone`` column, so a same-column-only check
    accepts it and the account is created sharing a value with another account.
    """
    legacy_account('usr_legacy_handle', username='13900000001')
    body = payload(client, 'supplier', 'second-owner@example.test')
    body.update(organization_name='测试主体', **supplier_identifiers(body))
    body['username'] = 'second-owner-handle'      # a handle of its own, so the mobile is the only clash
    body['phone'] = '13900000001'                 # already another account's handle
    body = attach_challenges(client, delivery, body, (('email', body['email']), ('sms', body['phone'])))
    refused = client.post('/bff/auth/supplier/register', json=body)
    assert refused.status_code == 409, refused.text
    assert refused.json()['detail'] == 'PHONE_ALREADY_REGISTERED', refused.text
    with SessionLocal() as s:
        assert s.scalar(select(IdentityUserRow).where(IdentityUserRow.phone == '13900000001')) is None


def test_login_picks_the_account_by_password_when_a_value_sits_in_two_rows(client, delivery):
    """A value shared across two legacy rows must not decide *who* logs in.

    ``scalar()`` used to return whichever row the database happened to order
    first, so one of the two accounts became unreachable and the automatic login
    at the end of sign-up answered 500 on an account it had just created. The
    password — which the caller must know anyway — now picks the row.
    """
    handle_password = legacy_account('usr_legacy_handle', username='13911112222',
                                     password='Legacy-handle-pass-123')
    phone_password = legacy_account('usr_legacy_phone', username='legacy-phone-owner', phone='13911112222',
                                    password='Legacy-mobile-pass-456')
    assert handle_password != phone_password

    assert login(client, '13911112222', handle_password).status_code == 200
    assert client.get('/bff/auth/me').json()['data']['user_id'] == 'usr_legacy_handle'
    client.post('/bff/auth/logout')

    assert login(client, '13911112222', phone_password).status_code == 200
    assert client.get('/bff/auth/me').json()['data']['user_id'] == 'usr_legacy_phone'

    # A password that belongs to neither row is still refused: ambiguity widens
    # which *account* a value may mean, never which passwords are accepted.
    client.post('/bff/auth/logout')
    assert login(client, '13911112222', 'not-anybodys-password').status_code == 401


def test_sign_up_reports_the_account_it_created_even_if_the_first_session_fails(client, delivery, monkeypatch):
    """Registration must not be able to answer 5xx after the account exists.

    Unreachable through sign-up now that the collision check covers all three
    columns, which is exactly why the guard is asserted directly: if the session
    cannot be minted, the applicant must be told the account exists rather than
    sent back to a form that now says the identifier is taken — by the account
    they just made.
    """
    def refuse(*args, **kwargs):
        raise ValueError('INVALID_CREDENTIALS')

    body = send(client, delivery, 'supplier', 'guard-owner@example.test')
    monkeypatch.setattr(identity_service, 'login', refuse)
    response = client.post('/bff/auth/supplier/register', json=body)
    assert response.status_code == 201, response.text
    assert response.json()['data']['authenticated'] is False
    with SessionLocal() as s:
        assert s.scalar(select(IdentityUserRow).where(IdentityUserRow.email == body['email'])) is not None


def test_the_collision_check_can_exclude_the_account_itself_for_a_future_rebind(client, delivery):
    """Reserved for 换绑: an account changing its own mobile must not collide with itself.

    The parameter is not decoration — without it, "is this mobile free?" answers
    no for the very account that already owns it, and a rebind could never be
    accepted. ``identifier_owner_id`` answers the companion question ("who owns
    it?") that a rebind needs to tell "already mine" from "somebody else's".
    """
    body = supplier_account(client, delivery, 'rebind-owner@example.test')
    with SessionLocal() as s:
        owner = s.scalar(select(IdentityUserRow).where(IdentityUserRow.email == body['email']))
        mine = dict(username=owner.username, email=owner.email, phone=owner.phone)
        # Checked as a fresh sign-up would check them, the account collides with itself…
        assert conflicting_identifier(s, **mine) == 'username'
        # …and excluding itself is what a rebind relies on.
        assert conflicting_identifier(s, **mine, exclude_user_id=owner.user_id) is None
        assert identifier_owner_id(s, owner.phone) == owner.user_id
        assert identifier_owner_id(s, owner.phone, exclude_user_id=owner.user_id) is None
        # Another account's value is still refused, which is the whole point.
        assert conflicting_identifier(s, phone=owner.phone, exclude_user_id='usr_somebody_else') == 'phone'

