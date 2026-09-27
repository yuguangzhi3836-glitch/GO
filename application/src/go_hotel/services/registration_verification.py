"""Durable, email/purpose/policy-bound, single-use registration challenges."""
import hashlib
import hmac
import json
import re
import secrets
import time
from sqlalchemy import select, update, delete
from go_hotel.core.config import settings
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import RegistrationChallengeRow as Challenge, RegistrationRateRow as Rate
from go_hotel.services import registration_email

TTL_MS = 600_000
MAX_ATTEMPTS = 5


def now_ms():
    return int(time.time() * 1000)


def normalize_email(value):
    value = value.strip().lower()
    if len(value) > 128 or not re.fullmatch(r'[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+', value):
        raise ValueError('VALID_EMAIL_REQUIRED')
    return value


def digest(value):
    key = settings.jwt_signing_key
    if len(key) < 32 or key.startswith('dev-'):
        raise ValueError('REGISTRATION_VERIFICATION_NOT_READY')
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


def ready():
    try:
        digest('readiness')
        return registration_email.ready()
    except ValueError:
        return False


def policy_digest(policy):
    return hashlib.sha256(json.dumps({'versions': policy['versions'], 'hashes': policy['term_hashes']}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def subject(audience, email):
    if audience not in ('consumer', 'supplier'):
        raise ValueError('REGISTRATION_AUDIENCE_INVALID')
    return digest(audience + '\0' + normalize_email(email))


def insert_for(session, table):
    if session.bind.dialect.name == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    elif session.bind.dialect.name == 'sqlite':
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise ValueError('REGISTRATION_DATABASE_UNSUPPORTED')
    return insert(table)


def issue(audience, email, client_ip, policy):
    if not ready():
        raise ValueError('REGISTRATION_VERIFICATION_NOT_READY')
    email = normalize_email(email)
    key, t = subject(audience, email), now_ms()
    challenge_id, code = secrets.token_urlsafe(24), f'{secrets.randbelow(1_000_000):06d}'
    with SessionLocal.begin() as s:
        # Shared durable limits: per address, per transport peer and globally.
        # Never trust an arbitrary forwarded-for header here.
        s.execute(delete(Rate).where(Rate.expires_ms < t))
        s.execute(delete(Challenge).where(Challenge.expires_ms < t - 86_400_000))
        for name, identity, window, limit in (
            ('cooldown', email, 60_000, 1), ('email', email, 3_600_000, 5),
            ('peer', client_ip or 'unknown', 3_600_000, 20), ('global', 'all', 3_600_000, 500),
        ):
            bucket = digest(f'{name}\0{identity}\0{t // window}')
            s.execute(insert_for(s, Rate).values(bucket_key=bucket, count=0, expires_ms=(t // window + 1) * window).on_conflict_do_nothing(index_elements=['bucket_key']))
            if s.execute(update(Rate).where(Rate.bucket_key == bucket, Rate.count < limit).values(count=Rate.count + 1)).rowcount != 1:
                raise ValueError('REGISTRATION_CODE_RATE_LIMITED')
        # Sliding resend interval as well as fixed-window anti-abuse counters.
        old = s.scalar(select(Challenge).where(Challenge.subject_key == key))
        if old and old.created_ms > t - 60_000:
            raise ValueError('REGISTRATION_CODE_RATE_LIMITED')
        values = dict(subject_key=key, challenge_id=challenge_id, code_digest=digest(challenge_id + '\0' + code), policy_digest=policy_digest(policy), state='SENDING', attempts=0, expires_ms=t + TTL_MS, created_ms=t, consumed_by=None)
        stmt = insert_for(s, Challenge).values(**values)
        # INSERT rowcount is not portable across drivers. RETURNING also yields
        # no row when the concurrent resend predicate rejects the update.
        written = s.scalar(stmt.on_conflict_do_update(index_elements=['subject_key'], set_=values, where=Challenge.created_ms <= t - 60_000).returning(Challenge.challenge_id))
        if written != challenge_id:
            raise ValueError('REGISTRATION_CODE_RATE_LIMITED')
    try:
        registration_email.send_code(email, code)
    except ValueError:
        with SessionLocal.begin() as s:
            s.execute(update(Challenge).where(Challenge.challenge_id == challenge_id).values(state='FAILED'))
        raise
    with SessionLocal.begin() as s:
        if s.execute(update(Challenge).where(Challenge.challenge_id == challenge_id, Challenge.state == 'SENDING').values(state='SENT')).rowcount != 1:
            raise ValueError('REGISTRATION_CODE_REPLACED')
    return {'challenge_id': challenge_id, 'expires_in': 600, 'resend_after': 60, 'status': 'SENT'}


def check(audience, email, challenge_id, code, policy):
    """Wrong attempts commit independently; successful proof is not yet consumed."""
    if not ready():
        raise ValueError('REGISTRATION_VERIFICATION_NOT_READY')
    key, t = subject(audience, email), now_ms()
    valid = False
    with SessionLocal.begin() as s:
        row = s.scalar(select(Challenge).where(Challenge.subject_key == key, Challenge.challenge_id == challenge_id))
        if row and row.state == 'SENT' and row.expires_ms > t and row.attempts < MAX_ATTEMPTS:
            valid = (hmac.compare_digest(row.code_digest, digest(challenge_id + '\0' + code)) and row.policy_digest == policy_digest(policy))
            if not valid:
                s.execute(update(Challenge).where(Challenge.challenge_id == challenge_id, Challenge.attempts < MAX_ATTEMPTS).values(attempts=Challenge.attempts + 1))
    if not valid:
        raise ValueError('REGISTRATION_CODE_INVALID_OR_EXPIRED')
    return {'subject_key': key, 'challenge_id': challenge_id, 'code_digest': digest(challenge_id + '\0' + code), 'policy_digest': policy_digest(policy)}


def consume(session, proof, user_id):
    """Same transaction as account+audit: commit together or rollback together."""
    result = session.execute(update(Challenge).where(
        Challenge.subject_key == proof['subject_key'], Challenge.challenge_id == proof['challenge_id'],
        Challenge.code_digest == proof['code_digest'], Challenge.policy_digest == proof['policy_digest'],
        Challenge.state == 'SENT', Challenge.expires_ms > now_ms(), Challenge.attempts < MAX_ATTEMPTS,
    ).values(state='CONSUMED', consumed_by=user_id))
    if result.rowcount != 1:
        raise ValueError('REGISTRATION_CODE_INVALID_OR_EXPIRED')
