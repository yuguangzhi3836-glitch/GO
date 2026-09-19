"""Reversible catalog visibility scope; immutable history is never deleted.

Nationwide expansion retains archived identities and retired work until explicit review.
Operational orders, accounts, inventory and money are outside this service.
"""
from datetime import datetime, timezone
import hashlib
import json
import uuid
from sqlalchemy import select, func, and_, or_
from go_hotel.db.models import HotelAutoPageEventRow as Event, HotelCanonicalProfileRow as Profile, RegionalQueueRow as Queue
from go_hotel.autonomy.durable import transaction
from go_hotel.db.session import SessionLocal

PROTECTED_IDS = frozenset({'hotel_ac72aa53c89d4c3984b72436cb85f617', 'hotel_d17851be16724affb355375cacc5e58c'})
KINDS = ('CATALOG_SCOPE_ACTIVATED', 'CATALOG_SCOPE_RELEASED', 'CATALOG_SCOPE_NATIONWIDE_ACTIVATED')
LOCK = 72486016240531

def scope_lock(session):
    if session.bind.dialect.name == 'postgresql':
        session.execute(select(func.pg_advisory_xact_lock(LOCK)))

def state(session):
    event = session.scalar(select(Event).where(Event.event_type.in_(KINDS)).order_by(Event.created_at.desc(), Event.hotel_auto_page_event_id.desc()).limit(1))
    return event.evidence_json if event and event.event_type != KINDS[1] else None

def aoluguya_name(value):
    name = ''.join(str(value or '').lower().split())
    return '敖麓谷雅' in name or 'aoluguya' in name

def visible_hotel(session, hotel_id):
    active = state(session)
    return (not active or (hotel_id not in active['archived_ids'] if active.get('mode') == 'NATIONWIDE'
                           else hotel_id in active['protected_ids']))

def require_hotel(session, hotel_id):
    if not visible_hotel(session, hotel_id):
        raise ValueError('CATALOG_RECORD_ARCHIVED')

def visible_events(session, rows):
    active = state(session)
    if not active:
        return list(rows)
    jobs, runs = set(active['retired_job_ids']), set(active['retired_run_ids'])
    return [r for r in rows if (not r.hotel_id or visible_hotel(session, r.hotel_id))
            and (r.evidence_json or {}).get('job_id') not in jobs
            and (r.evidence_json or {}).get('run_id') not in runs]

def require_job(session, job_id):
    active = state(session)
    if active and job_id in active['retired_job_ids']:
        raise ValueError('CATALOG_JOB_ARCHIVED')

def require_seed(session, seed):
    active = state(session)
    if active and active.get('mode') != 'NATIONWIDE' and not aoluguya_name(seed.get('name') or seed.get('name_zh') or seed.get('name_en')):
        raise ValueError('CATALOG_AOLUGUYA_ONLY')

def require_run(session, payload):
    active = state(session)
    if active and (payload.get('run_id') in active['retired_run_ids'] or
            (active.get('mode') != 'NATIONWIDE' and not aoluguya_name(payload.get('target_name') or (payload.get('seed') or {}).get('name')))):
        raise ValueError('CATALOG_RUN_ARCHIVED')

def plan(session):
    profiles = session.scalars(select(Profile).order_by(Profile.hotel_id)).all()
    existing = {p.hotel_id for p in profiles}
    if not PROTECTED_IDS <= existing:
        raise ValueError('CATALOG_PROTECTED_IDENTITY_MISSING')
    protected = PROTECTED_IDS | {p.hotel_id for p in profiles if any(aoluguya_name((p.canonical_json or {}).get(k)) for k in ('name','name_zh','name_en'))}
    events = session.scalars(select(Event).order_by(Event.created_at, Event.hotel_auto_page_event_id)).all()
    protected_jobs = {(e.evidence_json or {}).get('job_id') for e in events if e.hotel_id in protected}
    for e in events:
        if aoluguya_name(((e.evidence_json or {}).get('seed') or {}).get('name')):
            protected_jobs.add((e.evidence_json or {}).get('job_id'))
    jobs = {(e.evidence_json or {}).get('job_id') for e in events} - protected_jobs - {None}
    runs = {(e.evidence_json or {}).get('run_id') for e in events} - {None}
    protected_runs = {(e.evidence_json or {}).get('run_id') for e in events if e.event_type == 'REGIONAL_BUILD_CREATED' and aoluguya_name((e.evidence_json or {}).get('target_name'))}
    queues = session.scalars(select(Queue).order_by(Queue.message_id)).all()
    runs |= {q.run_id for q in queues}
    result = {'version': 1, 'mode': 'AOLUGUYA_ONLY', 'protected_ids': sorted(protected),
              'archived_ids': sorted(existing - protected), 'retired_job_ids': sorted(jobs),
              'retired_run_ids': sorted(runs - protected_runs),
              'physical_deletion': False, 'immutable_audit_retained': True}
    fingerprint = {'scope': result, 'profiles': [(p.hotel_id, p.version) for p in profiles],
                   'queue': [(q.message_id,q.status,q.lease_token,q.updated_ms) for q in queues],
                   'events': [e.hotel_auto_page_event_id for e in events if e.event_type not in KINDS]}
    result['scope_sha256'] = hashlib.sha256(json.dumps(fingerprint, sort_keys=True, separators=(',',':')).encode()).hexdigest()
    result['running_queue_count'] = sum(q.status == 'RUNNING' for q in queues)
    return result

def preview():
    with SessionLocal() as session:
        return plan(session)

def activate(expected_sha256, actor):
    with transaction(SessionLocal) as session:
        scope_lock(session)
        active = state(session)
        if active and active['scope_sha256'] == expected_sha256:
            return {**active, 'idempotent': True}
        result = plan(session)
        if result['scope_sha256'] != expected_sha256:
            raise ValueError('CATALOG_SCOPE_CHANGED_REVIEW_AGAIN')
        if result['running_queue_count']:
            raise ValueError('CATALOG_ACTIVE_BUILD_MUST_FINISH')
        session.add(Event(hotel_auto_page_event_id='hape_'+uuid.uuid4().hex, hotel_id=None,
                          event_type=KINDS[0], evidence_json=result, actor=actor,
                          created_at=datetime.now(timezone.utc)))
        return result

def release(expected_sha256, actor, reason):
    """Explicit rollback; immutable activation and all original catalog data remain."""
    if not str(reason or '').strip():
        raise ValueError('CATALOG_SCOPE_RELEASE_REASON_REQUIRED')
    with transaction(SessionLocal) as session:
        scope_lock(session)
        active=state(session)
        if not active or active['scope_sha256'] != expected_sha256:
            raise ValueError('CATALOG_SCOPE_CHANGED_REVIEW_AGAIN')
        evidence={'scope_sha256':expected_sha256,'reason':str(reason),'physical_deletion':False}
        session.add(Event(hotel_auto_page_event_id='hape_'+uuid.uuid4().hex,hotel_id=None,
                          event_type=KINDS[1],evidence_json=evidence,actor=actor,
                          created_at=datetime.now(timezone.utc)))
        return evidence


def event_filter(session):
    """Apply before LIMIT, so archived rows cannot displace retained history."""
    active=state(session)
    if not active:return True
    job=Event.evidence_json['job_id'].as_string()
    run=Event.evidence_json['run_id'].as_string()
    return and_(or_(Event.hotel_id.is_(None),hotel_filter(session, Event.hotel_id)),
                or_(job.is_(None),job.not_in(active['retired_job_ids'])),
                or_(run.is_(None),run.not_in(active['retired_run_ids'])))


def hotel_filter(session, column):
    """SQL visibility predicate; apply before pagination."""
    active = state(session)
    if not active:
        return True
    return column.not_in(active['archived_ids']) if active.get('mode') == 'NATIONWIDE' else column.in_(active['protected_ids'])


def status():
    with SessionLocal() as session:
        active = state(session)
        return {**(active or {}), 'mode': (active or {}).get('mode', 'UNRESTRICTED'),
                'scope_active': bool(active), 'nationwide_new_catalog_allowed': not active or active.get('mode') == 'NATIONWIDE'}


def nationwide_plan(session):
    active = state(session)
    latest = session.scalar(select(Event).where(Event.event_type.in_(KINDS)).order_by(Event.created_at.desc(), Event.hotel_auto_page_event_id.desc()).limit(1))
    result = {'version': 2, 'mode': 'NATIONWIDE', 'country': 'CN',
              'protected_ids': sorted((active or {}).get('protected_ids', [])),
              'archived_ids': sorted((active or {}).get('archived_ids', [])),
              'retired_job_ids': sorted((active or {}).get('retired_job_ids', [])),
              'retired_run_ids': sorted((active or {}).get('retired_run_ids', [])),
              'physical_deletion': False, 'immutable_audit_retained': True,
              'restores_archived_records': False, 'auto_publishes': False,
              'previous_scope_event_id': latest.hotel_auto_page_event_id if latest else None}
    result['scope_sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    result['already_active'] = bool(active and active.get('mode') == 'NATIONWIDE')
    return result


def nationwide_preview():
    with SessionLocal() as session:
        return nationwide_plan(session)


def activate_nationwide(expected_sha256, actor, reason):
    if not str(reason or '').strip():
        raise ValueError('CATALOG_SCOPE_REASON_REQUIRED')
    with transaction(SessionLocal) as session:
        scope_lock(session)
        active = state(session)
        if active and active.get('mode') == 'NATIONWIDE' and active['scope_sha256'] == expected_sha256:
            return {**active, 'idempotent': True}
        result = nationwide_plan(session)
        if result['scope_sha256'] != expected_sha256:
            raise ValueError('CATALOG_SCOPE_CHANGED_REVIEW_AGAIN')
        if result['already_active']:
            return {**active, 'idempotent': True}
        result = {**result, 'reason': str(reason).strip(), 'activated_by': actor}
        session.add(Event(hotel_auto_page_event_id='hape_'+uuid.uuid4().hex, hotel_id=None,
                          event_type=KINDS[2], evidence_json=result, actor=actor,
                          created_at=datetime.now(timezone.utc)))
        return result
