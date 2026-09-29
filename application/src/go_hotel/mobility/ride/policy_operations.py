"""Authenticated governance for explicitly isolated engineering cancellation policies.

Uses existing commercial tables, but never the generic commercial approval gate.
This is not a verifier of supplier authority or real commercial policy approval.
"""
import json
import os
import uuid
from datetime import datetime, UTC
from hashlib import sha256
from sqlalchemy import select, text
from go_hotel.autonomy.durable import canonical, digest, db_now_ms, transaction
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import CommercialPolicyVersionRow as Policy, CommercialAuditEventRow as Event, IdentityUserRow, AuthSessionRow
from go_hotel.security.rbac import permissions_for
from go_hotel.services.travel_operational_facts import environment_allowed
from . import cancellation_policy as contract

SCOPE = 'RIDE_ISOLATED'
PREFIX = 'C05_ISOLATED:'
OFFERS = ('ride_standard', 'ride_premium')


def enabled():
    return os.getenv('GO_RIDE_ISOLATED_POLICY_REGISTRY') == '1'


def gate():
    environment_allowed('ENGINEERING')
    if not enabled():
        raise ValueError('RIDE_POLICY_REGISTRY_DISABLED')


def lock(s, offer):
    if offer not in OFFERS:
        raise ValueError('RIDE_POLICY_OFFER_INVALID')
    if s.bind.dialect.name == 'postgresql':
        key = int.from_bytes(sha256((PREFIX + offer).encode()).digest()[:8], 'big', signed=True)
        s.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})


def authorize(s, principal, permission):
    user = s.get(IdentityUserRow, principal.user_id)
    session = s.get(AuthSessionRow, principal.session_id)
    now = datetime.fromtimestamp(db_now_ms(s) / 1000, UTC)
    expires = session.expires_at.replace(tzinfo=UTC) if session and session.expires_at.tzinfo is None else session.expires_at if session else None
    if (not user or user.status != 'ACTIVE' or user.actor_type != 'GO_ADMIN'
        or not session or session.user_id != user.user_id or session.status != 'ACTIVE'
        or session.revoked_at is not None or expires <= now
        or permission not in permissions_for(user.roles)):
        raise PermissionError('RIDE_POLICY_PERMISSION_REQUIRED')
    return user.user_id


def rows(s, offer):
    return list(s.scalars(select(Policy).where(Policy.policy_key == PREFIX + offer).order_by(Policy.version_no)))


def events(s, offer):
    result = list(s.scalars(select(Event).where(Event.aggregate_id == PREFIX + offer)))
    result.sort(key=lambda e: e.payload_json.get('sequence', -1))
    previous = None
    for n, e in enumerate(result, 1):
        payload = e.payload_json
        if payload.get('sequence') != n or e.previous_hash != previous or e.event_hash != digest({'type': e.event_type, 'actor': e.actor_id, 'payload': payload, 'previous': previous}):
            raise ValueError('RIDE_POLICY_AUDIT_INTEGRITY_INVALID')
        previous = e.event_hash
    return result


def audit(s, offer, row, action, actor):
    history = events(s, offer)
    previous = history[-1].event_hash if history else None
    payload = {'sequence': len(history) + 1, 'policy_id': row.policy_version_id,
               'content_hash': row.content_hash, 'scope': SCOPE, 'offer_id': offer,
               'state': row.state, 'maker': row.requested_by, 'checker': row.approved_by,
               'occurred_ms': db_now_ms(s)}
    typ = 'C05_POLICY_' + action
    s.add(Event(commercial_audit_event_id='c05e_' + uuid.uuid4().hex, event_type=typ,
                aggregate_id=PREFIX + offer, actor_id=actor, payload_json=payload,
                previous_hash=previous, event_hash=digest({'type': typ, 'actor': actor, 'payload': payload, 'previous': previous}),
                created_at=datetime.now(UTC)))
    s.flush()


def verify(s, row, history):
    policy = contract.validate_policy(row.rule_json)
    if row.scope != SCOPE or row.policy_key != PREFIX + policy['offer_id'] or row.content_hash != digest({'scope': SCOPE, 'policy': policy}):
        raise ValueError('RIDE_POLICY_CONTENT_INTEGRITY_INVALID')
    own = [e for e in history if e.payload_json.get('policy_id') == row.policy_version_id]
    if not own or any(e.payload_json['content_hash'] != row.content_hash for e in own) or own[-1].payload_json['state'] != row.state:
        raise ValueError('RIDE_POLICY_ACTIVATION_UNVERIFIED')
    created = own[0]
    maker = s.get(IdentityUserRow, row.requested_by)
    if created.event_type != 'C05_POLICY_DRAFTED' or created.actor_id != row.requested_by or not maker or maker.actor_type != 'GO_ADMIN':
        raise ValueError('RIDE_POLICY_ACTIVATION_UNVERIFIED')
    if row.state == 'ACTIVE':
        approved = own[-1]
        checker = s.get(IdentityUserRow, row.approved_by) if row.approved_by else None
        if (approved.event_type != 'C05_POLICY_ACTIVATED' or approved.actor_id != row.approved_by
            or not checker or checker.actor_type != 'GO_ADMIN' or row.approved_by == row.requested_by
            or approved.payload_json['maker'] != row.requested_by):
            raise ValueError('RIDE_POLICY_ACTIVATION_UNVERIFIED')
    return policy


def revision(row):
    return digest({'id': row.policy_version_id, 'hash': row.content_hash, 'state': row.state, 'checker': row.approved_by})


def view(row, reason=None):
    return {'policy_id': row.policy_version_id, 'version_no': row.version_no, 'state': row.state,
            'policy': row.rule_json, 'revision': revision(row), 'maker': row.requested_by,
            'checker': row.approved_by, 'hold_reason': reason, 'real_commercial_approval': False}


def create(principal, policy):
    gate()
    policy = contract.validate_policy(policy)
    offer = policy['offer_id']
    with transaction(SessionLocal) as s:
        actor = authorize(s, principal, 'admin:rules')
        lock(s, offer)
        existing = rows(s, offer)
        if any(r.rule_json.get('version') == policy['version'] for r in existing):
            raise ValueError('RIDE_POLICY_VERSION_EXISTS')
        if max(policy['before_fee_minor'], policy['after_fee_minor']) > {'ride_standard': 16800, 'ride_premium': 26800}[offer]:
            raise ValueError('RIDE_POLICY_FEE_EXCEEDS_FARE')
        row = Policy(policy_version_id='c05p_' + uuid.uuid4().hex, policy_key=PREFIX + offer,
                     version_no=max((r.version_no for r in existing), default=0) + 1,
                     scope=SCOPE, rule_json=policy, content_hash=digest({'scope': SCOPE, 'policy': policy}),
                     state='DRAFT', requested_by=actor, created_at=datetime.now(UTC))
        s.add(row); s.flush()
        audit(s, offer, row, 'DRAFTED', actor)
        return view(row)


def transition(principal, policy_id, expected_revision, action):
    gate()
    with transaction(SessionLocal) as s:
        actor = authorize(s, principal, 'admin:approve' if action == 'activate' else 'admin:rules')
        row = s.get(Policy, policy_id)
        if not row or row.scope != SCOPE:
            raise ValueError('RIDE_POLICY_NOT_FOUND')
        offer = row.rule_json['offer_id']; lock(s, offer)
        s.refresh(row, with_for_update=True)
        history = events(s, offer); policy = verify(s, row, history)
        if revision(row) != expected_revision:
            raise ValueError('RIDE_POLICY_REVISION_CHANGED')
        if action == 'activate':
            if row.state != 'DRAFT': raise ValueError('RIDE_POLICY_STATE_CONFLICT')
            if actor == row.requested_by: raise ValueError('RIDE_POLICY_MAKER_CHECKER_REQUIRED')
            if not contract.instant(policy['effective_from']) <= db_now_ms(s) < contract.instant(policy['effective_until']):
                raise ValueError('RIDE_POLICY_NOT_EFFECTIVE')
            versions = rows(s, offer)
            if any(old.version_no > row.version_no and old.state != 'DRAFT' for old in versions):
                raise ValueError('RIDE_POLICY_STALE_VERSION')
            for old in versions:
                if old.state == 'ACTIVE':
                    verify(s, old, history)
                    old.state = 'SUPERSEDED'; audit(s, offer, old, 'SUPERSEDED', actor)
            row.state = 'ACTIVE'; row.approved_by = actor; row.effective_at = datetime.now(UTC)
            audit(s, offer, row, 'ACTIVATED', actor)
        elif action == 'revoke':
            if row.state not in {'DRAFT', 'ACTIVE'}: raise ValueError('RIDE_POLICY_STATE_CONFLICT')
            row.state = 'REVOKED'; audit(s, offer, row, 'REVOKED', actor)
        else:
            raise ValueError('RIDE_POLICY_ACTION_INVALID')
        return view(row)


def resolve_in(s, offer):
    gate(); lock(s, offer)
    active = [r for r in rows(s, offer) if r.state == 'ACTIVE']
    if not active: return None
    if len(active) != 1: raise ValueError('RIDE_POLICY_MULTIPLE_ACTIVE')
    policy = verify(s, active[0], events(s, offer))
    raw = canonical(policy).encode()
    return {'raw_payload': raw, 'raw_sha256': sha256(raw).hexdigest()}


def resolve(offer):
    with transaction(SessionLocal) as s:
        return resolve_in(s, offer)


def diagnose(principal):
    with SessionLocal() as s:
        actor = authorize(s, principal, 'admin:read')
        permissions = permissions_for(s.get(IdentityUserRow, actor).roles)
        result = []
        try: gate(); allowed = True
        except ValueError: allowed = False
        for offer in OFFERS:
            try:
                history = events(s, offer)
                versions = []
                for row in rows(s, offer):
                    reason = None
                    try:
                        policy = verify(s, row, history)
                        if not contract.instant(policy['effective_from']) <= db_now_ms(s) < contract.instant(policy['effective_until']): reason = 'NOT_EFFECTIVE'
                    except ValueError as exc: reason = str(exc)
                    versions.append(view(row, reason))
                for item in versions:
                    if item['state'] == 'DRAFT' and any(other['version_no'] > item['version_no'] and other['state'] != 'DRAFT' for other in versions):
                        item['hold_reason'] = 'STALE_VERSION'
                    item['can_activate'] = bool(allowed and not item['hold_reason'] and item['state'] == 'DRAFT' and item['maker'] != actor and 'admin:approve' in permissions)
                    item['can_revoke'] = bool(allowed and item['state'] in {'DRAFT', 'ACTIVE'} and 'admin:rules' in permissions and item['hold_reason'] not in {'RIDE_POLICY_CONTENT_INTEGRITY_INVALID', 'RIDE_POLICY_ACTIVATION_UNVERIFIED', 'RIDE_POLICY_AUDIT_INTEGRITY_INVALID'})
                active = [r for r in versions if r['state'] == 'ACTIVE' and not r['hold_reason']]
                state = 'ISOLATED_READY' if allowed and len(active) == 1 else 'HOLD'
                result.append({'offer_id': offer, 'state': state, 'versions': versions,
                               'reason': None if state == 'ISOLATED_READY' else 'NO_VERIFIED_CURRENT_ISOLATED_POLICY',
                               'audit_count': len(history)})
            except ValueError as exc:
                result.append({'offer_id': offer, 'state': 'HOLD', 'reason': str(exc), 'versions': []})
        return {'registry_enabled': allowed, 'can_create': allowed and 'admin:rules' in permissions, 'real_policy_state': 'HOLD_UNVERIFIED', 'external_live': False,
                'accepted_orders_unchanged': True, 'offers': result}
