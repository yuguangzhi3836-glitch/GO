"""Account recovery: find the username, or set a new password.

A partner who cannot get in has two questions — "which account is mine?" and "how
do I get back in?" — and both are answered by proving control of one of the
account's contact channels (email or SMS) with the same durable challenge the
sign-up flow uses. There is no second security mechanism here.

Boundary, stated plainly: **delivery is not connected in this environment**, so
the only code that can be checked is the operator's explicit stand-in
(``registration_verification_test_code``). With that switch off the whole surface
answers 503 before it looks at anything else — it never accepts a code nobody
could have received, and it cannot be used to probe which accounts exist.

Because the switch is an explicit *test* mode, these endpoints do report whether
an account exists (``RECOVERY_ACCOUNT_NOT_FOUND``). Uniform responses and uniform
timing, so that a stranger cannot enumerate accounts, is a listed prerequisite
for connecting a real transport — this stub does not silently pretend to have it.
"""
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from go_hotel.db.session import SessionLocal
from go_hotel.security.service import identity_service
from go_hotel.services import registration_verification as verification

router = APIRouter(tags=['account-recovery'])

# Recovery binds no terms, so its policy digest binds the empty policy. It is a
# constant on purpose: issue and check must agree exactly, and a caller must never
# be able to weaken the binding by supplying its own policy.
RECOVERY_POLICY = {'versions': {}, 'term_hashes': {}, 'deferred': [], 'account_stage': False}

Channel = Literal['email', 'sms']


class RecoveryChallengeBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    identifier: str = Field(min_length=3, max_length=128)
    channel: Channel = 'email'


class RecoveryUsernameBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    identifier: str = Field(min_length=3, max_length=128)
    channel: Channel = 'email'
    challenge_id: str = Field(min_length=1, max_length=64)
    verification_code: str = Field(min_length=1, max_length=6)


class RecoveryPasswordBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    identifier: str = Field(min_length=3, max_length=128)
    channel: Channel = 'email'
    challenge_id: str = Field(min_length=1, max_length=64)
    verification_code: str = Field(min_length=1, max_length=6)
    new_password: str = Field(min_length=10, max_length=128)
    confirm_password: str = Field(min_length=10, max_length=128)


def _require_runtime():
    """Fail closed, and do it before anything else can leak.

    With no delivery configured — and no explicit test code — every request gets
    the same 503, whether or not the account exists.
    """
    if not verification.ready():
        raise HTTPException(503, detail='REGISTRATION_VERIFICATION_NOT_READY')


def _account(identifier):
    account = identity_service.resolve_identifier(identifier)
    if account is None:
        raise HTTPException(404, detail='RECOVERY_ACCOUNT_NOT_FOUND')
    return account


def _issue_status(error):
    if error == 'REGISTRATION_CODE_RATE_LIMITED':
        return 429
    if error in ('REGISTRATION_VERIFICATION_NOT_READY', 'REGISTRATION_EMAIL_SEND_FAILED', 'REGISTRATION_SMS_NOT_READY'):
        return 503
    return 422


def _prove(identifier, channel, challenge_id, code):
    try:
        return verification.check('recovery', identifier, challenge_id, code, RECOVERY_POLICY, channel)
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc


@router.post('/bff/auth/recovery/challenge')
def recovery_challenge(body: RecoveryChallengeBody, request: Request, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    _require_runtime()
    _account(body.identifier)
    try:
        data = verification.issue('recovery', body.identifier, request.client.host if request.client else None, RECOVERY_POLICY, body.channel)
    except ValueError as exc:
        error = str(exc)
        status = _issue_status(error)
        raise HTTPException(status, detail=error, headers={'Retry-After': '60'} if status == 429 else None) from None
    return {'data': data}


@router.post('/bff/auth/recovery/username')
def recovery_username(body: RecoveryUsernameBody, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    _require_runtime()
    account = _account(body.identifier)
    proof = _prove(body.identifier, body.channel, body.challenge_id, body.verification_code)
    # Consume here too: a code proved for "show me my username" must not stay
    # usable for "set a new password".
    with SessionLocal.begin() as session:
        verification.consume(session, proof, account['user_id'])
    return {'data': {'username': account['username']}}


@router.post('/bff/auth/recovery/password')
def recovery_password(body: RecoveryPasswordBody, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    _require_runtime()
    if body.new_password != body.confirm_password:
        raise HTTPException(422, detail='PASSWORD_CONFIRMATION_MISMATCH')
    account = _account(body.identifier)
    proof = _prove(body.identifier, body.channel, body.challenge_id, body.verification_code)
    # One transaction: the challenge is spent *and* the password changes, or
    # neither happens. `set_password` also revokes every existing session.
    try:
        with SessionLocal.begin() as session:
            verification.consume(session, proof, account['user_id'])
            identity_service.set_password(session, account['user_id'], body.new_password)
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    return {'data': {'status': 'PASSWORD_RESET', 'username': account['username']}}
