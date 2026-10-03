"""Registration privacy controls. Evidence is operator supplied, never self-approved."""
import hashlib
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import select, delete
from go_hotel.core.config import settings
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (RegistrationChallengeRow, RegistrationRateRow,
    RegistrationDecisionRow, RegistrationMaintenanceRow, PrivacyRequestRow, AuditEventRow)
from go_hotel.domain.models import new_id

DAY = 86_400_000
# GO engineering policy, not a claim that every category has a statutory 3-year term.
DECISION_DAYS = 1095
CLEANUP_MAX_AGE_MS = 120_000
logger = logging.getLogger(__name__)


def now_ms():
    return int(datetime.now(timezone.utc).timestamp()*1000)


def required_decisions(policy):
    deferred = set(policy.get('deferred') or ())
    return {k: ('NOTICE_ACKNOWLEDGED' if k == 'privacy_policy' else
                'DEFERRED' if k in deferred else 'CONTRACT_ACCEPTED')
            for k in policy['versions']}


def validate_decisions(policy, decisions):
    if decisions != required_decisions(policy):
        raise ValueError('REGISTRATION_SEPARATE_DECISIONS_REQUIRED')
    return dict(decisions)


def record_decisions(session, user_id, audience, policy, decisions):
    decisions = validate_decisions(policy, decisions)
    t = now_ms()
    session.add(RegistrationDecisionRow(decision_id=new_id('rd'),user_id=user_id,
        audience=audience,decisions=decisions,versions=dict(policy['versions']),
        hashes=dict(policy['term_hashes']),created_ms=t,expires_ms=t+DECISION_DAYS*DAY))


def cleanup_once(*, invalidate_challenges=False):
    """Independent of registration traffic; atomic cleanup + success heartbeat.

    Run by the already deployed reconciliation service every 30 seconds. A missing,
    failed or stale heartbeat closes new registrations instead of claiming cleanup.
    Expiry-based replay also removes restored expired rows before worker readiness.
    """
    t = now_ms()
    with SessionLocal.begin() as s:
        counts = {}
        if invalidate_challenges:
            s.execute(delete(RegistrationChallengeRow))
        for model, name in ((RegistrationChallengeRow,'challenges'),(RegistrationRateRow,'rate_buckets'),(RegistrationDecisionRow,'decisions')):
            result = s.execute(delete(model).where(model.expires_ms <= t))
            counts[name] = result.rowcount
        cutoff = datetime.fromtimestamp((t-DECISION_DAYS*DAY)/1000,timezone.utc)
        s.execute(delete(AuditEventRow).where(AuditEventRow.action.in_([
            'CONSUMER_REGISTRATION_TERMS_ACCEPTED','SUPPLIER_REGISTRATION_TERMS_ACCEPTED','PRIVACY_REQUEST_RESOLVED']),AuditEventRow.created_at <= cutoff))
        # Unresolved rights cases must not vanish; escalate them to the operator.
        s.execute(delete(PrivacyRequestRow).where(PrivacyRequestRow.status.in_(['COMPLETED','REJECTED']),PrivacyRequestRow.updated_ms <= t-DECISION_DAYS*DAY))
        from go_hotel.services.registration_verification import insert_for
        stmt=insert_for(s,RegistrationMaintenanceRow).values(key='cleanup',success_ms=t)
        s.execute(stmt.on_conflict_do_update(index_elements=['key'],set_={'success_ms':t}))
        overdue=len(s.scalars(select(PrivacyRequestRow.request_id).where(PrivacyRequestRow.status.in_(['RECEIVED','IN_REVIEW','RESTRICTED_RETENTION']),PrivacyRequestRow.due_ms<t).limit(100)).all())
    if overdue:
        logger.warning('PRIVACY_REQUESTS_OVERDUE count_capped=%d',overdue)
    return counts


def maintenance_status():
    try:
        with SessionLocal() as s:
            row=s.get(RegistrationMaintenanceRow,'cleanup')
            fresh=bool(row and 0 <= now_ms()-row.success_ms <= CLEANUP_MAX_AGE_MS)
        return {'ready':fresh,'max_age_seconds':CLEANUP_MAX_AGE_MS//1000}
    except Exception:
        return {'ready':False,'max_age_seconds':CLEANUP_MAX_AGE_MS//1000}


EVIDENCE_CATEGORIES = ('operator','data_inventory','smtp_processor','cross_border',
                       'retention_schedule','backups','rights_operations')


def operational_evidence_status():
    """Validate completeness/binding only, NOT authenticity or legal sufficiency.

    The fixed operator-mounted file must be reviewed before use. Hash references
    bind real records; this code cannot manufacture contracts or legal approval.
    No payload is exposed publicly; no credential is part of this file.
    """
    try:
        raw=Path(settings.registration_privacy_evidence_path).read_bytes()
        value=json.loads(raw)
        if value.get('schema_version')!=1 or value.get('status')!='APPROVED':
            raise ValueError()
        if value.get('terms_version')!=settings.registration_terms_version:
            raise ValueError()
        expiry=datetime.fromisoformat(value['valid_until'])
        if expiry.tzinfo is None or expiry<=datetime.now(timezone.utc):
            raise ValueError()
        for name in EVIDENCE_CATEGORIES:
            entry=value[name]
            if not isinstance(entry,dict) or not all(entry.get(k) for k in ('reviewer','reviewed_at','evidence_ref','sha256','scope')):
                raise ValueError()
            if len(entry['sha256'])!=64 or any(c not in '0123456789abcdef' for c in entry['sha256']):
                raise ValueError()
            reviewed=datetime.fromisoformat(entry['reviewed_at'])
            if reviewed.tzinfo is None or reviewed>datetime.now(timezone.utc):
                raise ValueError()
        return {'ready':True,'digest':hashlib.sha256(raw).hexdigest()}
    except (OSError,ValueError,KeyError,TypeError):
        return {'ready':False,'digest':None}


def ready():
    return operational_evidence_status()['ready'] and maintenance_status()['ready']


def own_history(user_id):
    with SessionLocal() as s:
        rows=s.scalars(select(RegistrationDecisionRow).where(RegistrationDecisionRow.user_id==user_id).order_by(RegistrationDecisionRow.created_ms)).all()
        return [dict(id=x.decision_id,decisions=x.decisions,versions=x.versions,hashes=x.hashes,created_ms=x.created_ms) for x in rows]


KINDS={'ACCESS','CORRECTION','DELETION','WITHDRAWAL','CLOSURE','RESTRICTION','TRANSFER'}


def case_view(x):
    return dict(request_id=x.request_id,kind=x.kind,status=x.status,created_ms=x.created_ms,due_ms=x.due_ms,resolution=x.resolution)


def submit_request(user_id,kind):
    if kind not in KINDS:
        raise ValueError('PRIVACY_REQUEST_KIND_INVALID')
    t=now_ms()
    with SessionLocal.begin() as s:
        # Bound duplicates; actual handling remains visible, never auto-completed.
        active=s.scalar(select(PrivacyRequestRow).where(PrivacyRequestRow.user_id==user_id,PrivacyRequestRow.kind==kind,PrivacyRequestRow.status.in_(['RECEIVED','IN_REVIEW','RESTRICTED_RETENTION'])))
        if active:return case_view(active)
        item=PrivacyRequestRow(request_id=new_id('prv'),user_id=user_id,kind=kind,status='RECEIVED',created_ms=t,due_ms=t+15*DAY,updated_ms=t,resolution={})
        s.add(item)
        return case_view(item)


def requests_for(user_id):
    with SessionLocal() as s:
        return [case_view(x) for x in s.scalars(select(PrivacyRequestRow).where(PrivacyRequestRow.user_id==user_id).order_by(PrivacyRequestRow.created_ms.desc()).limit(100))]
