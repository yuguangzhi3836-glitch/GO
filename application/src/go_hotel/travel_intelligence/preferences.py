"""Explicit owner preferences over the existing encrypted profile/consent store.

C07 provides purpose-bound evidence. These records never constitute C09 scores,
ranking, admission or recommendation truth. Session signals are never promoted.
"""
from datetime import datetime, timezone
import hashlib
import json

from sqlalchemy import select

from go_hotel.db.models import (ProfileAccessAuditRow, ProfileConsentRow, ProfileFactRow,
    TravelerProfileRow, TravelIntentRow, TravelBehaviorEventRow)
from go_hotel.domain.models import new_id
from go_hotel.security.crypto import encrypt_secret, decrypt_secret
from go_hotel.services.personal_vault_management import mutation_session, owned_traveler, permission

PREFERENCE_KEYS = frozenset({"HOTEL_ROOM", "FLIGHT_SEAT", "RAIL_SEAT", "DIETARY",
    "ACCESSIBILITY", "TRAVEL_PACE", "RENTAL_VEHICLE"})
FIELD = "C07_TRAVEL_PREFERENCE"
PROVIDER = "C07_EXPLICIT_PREFERENCE"
CONSENT_TYPE = "EXPLICIT_TRAVEL_PREFERENCE"


def _now():
    return datetime.now(timezone.utc)


def _aware(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def _purpose(value):
    # Do not silently normalize a requested purpose into a different grant.
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 128:
        raise ValueError("TRAVEL_PREFERENCE_PURPOSE_INVALID")
    return value


def _active_consents(session, traveler, purpose, consent_type):
    # Share the consent-row lock with the existing vault's revocation UPDATE.
    # Retain it through preference projection/write and its audit transaction.
    rows = session.scalars(select(ProfileConsentRow).where(
        ProfileConsentRow.user_id == traveler.user_id,
        ProfileConsentRow.traveler_id == traveler.traveler_id,
        ProfileConsentRow.consent_type == consent_type,
        ProfileConsentRow.purpose == purpose,
        ProfileConsentRow.status == "ACTIVE",
        ProfileConsentRow.revoked_at.is_(None)).order_by(ProfileConsentRow.consent_id).with_for_update()).all()
    t = _now()
    return {c.consent_id:c for c in rows
        if c.expires_at is not None and _aware(c.granted_at) <= t < _aware(c.expires_at)}


def _audit(session, traveler, actor_id, actor_type, action, purpose, keys, metadata):
    # Payload values and session text must never enter audit metadata.
    session.add(ProfileAccessAuditRow(access_id=new_id("pva"), user_id=traveler.user_id,
        traveler_id=traveler.traveler_id, actor_id=actor_id, actor_type=actor_type,
        action=action, purpose=purpose, fields_json=keys, metadata_json=metadata, created_at=_now()))


def _self(traveler):
    if traveler.relationship_type != "SELF":
        raise ValueError("TRAVEL_PREFERENCE_SELF_REQUIRED")


def _payload(row):
    value = json.loads(decrypt_secret(row.value_ciphertext))
    if not isinstance(value, dict):
        return None
    if value.get("key") not in PREFERENCE_KEYS or set(value) != {"key", "value", "purpose"}:
        return None
    return value


def _projection(row, payload):
    return {"preference_id":row.fact_id, "preference_key":payload["key"], "value":payload["value"],
        "purpose":payload["purpose"], "consent_id":row.source_reference, "status":"ACTIVE",
        "source":"EXPLICIT_USER_CONFIRMATION"}


def _facts(session, traveler):
    return session.scalars(select(ProfileFactRow).where(
        ProfileFactRow.user_id == traveler.user_id, ProfileFactRow.traveler_id == traveler.traveler_id,
        ProfileFactRow.field_type == FIELD, ProfileFactRow.source_provider == PROVIDER,
        ProfileFactRow.source_type == "MANUAL", ProfileFactRow.user_confirmed.is_(True),
        ProfileFactRow.verification_status == "USER_CONFIRMED",
        ProfileFactRow.verification_method == "EXPLICIT_PREFERENCE_CONFIRMATION",
        ProfileFactRow.status == "ACTIVE").order_by(ProfileFactRow.created_at, ProfileFactRow.fact_id)).all()


def _read_preferences(session, traveler, purpose):
    grants = _active_consents(session, traveler, purpose, CONSENT_TYPE)
    result = []
    for row in _facts(session, traveler):
        grant = grants.get(row.source_reference)
        if not grant:
            continue
        payload = _payload(row)
        if not payload or payload["purpose"] != purpose:
            continue
        if "TRAVEL_PREFERENCE:" + payload["key"] not in (grant.scope_json or []):
            continue
        result.append(_projection(row, payload))
    return result


class TravelPreferenceMixin:
    def save_preference(self, user_id, traveler_id, *, preference_key, value, purpose,
                        consent_id, confirmed, expected_preference_id=None):
        if confirmed is not True:
            raise ValueError("TRAVEL_PREFERENCE_CONFIRMATION_REQUIRED")
        purpose = _purpose(purpose)
        if preference_key not in PREFERENCE_KEYS:
            raise ValueError("TRAVEL_PREFERENCE_KEY_INVALID")
        if value is None or value == "" or value == {} or value == []:
            raise ValueError("TRAVEL_PREFERENCE_VALUE_INVALID")
        try:
            raw = json.dumps({"key":preference_key, "value":value, "purpose":purpose},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError):
            raise ValueError("TRAVEL_PREFERENCE_VALUE_INVALID") from None
        if len(raw.encode()) > 4096:
            raise ValueError("TRAVEL_PREFERENCE_VALUE_INVALID")
        digest = hashlib.sha256(raw.encode()).hexdigest()
        with mutation_session() as s:
            tr = owned_traveler(s, user_id, traveler_id, edit=True)
            _self(tr)
            grant = _active_consents(s, tr, purpose, CONSENT_TYPE).get(consent_id)
            if not grant or "TRAVEL_PREFERENCE:" + preference_key not in (grant.scope_json or []):
                raise ValueError("TRAVEL_PREFERENCE_CONSENT_REQUIRED")
            current = []
            for row in _facts(s, tr):
                payload = _payload(row)
                if payload and payload["purpose"] == purpose and payload["key"] == preference_key:
                    current.append(row)
            if len(current) > 1:
                raise ValueError("TRAVEL_PREFERENCE_REVISION_CONFLICT")
            old = current[0] if current else None
            if old and old.normalized_value_hash == digest and old.source_reference == consent_id:
                return _projection(old, json.loads(raw))
            if (old.fact_id if old else None) != expected_preference_id:
                raise ValueError("TRAVEL_PREFERENCE_REVISION_CONFLICT")
            t = _now()
            row = ProfileFactRow(fact_id=new_id("pff"), user_id=user_id, traveler_id=traveler_id,
                field_type=FIELD, value_ciphertext=encrypt_secret(raw), normalized_value_hash=digest,
                sensitive=True, source_type="MANUAL", source_provider=PROVIDER, source_reference=consent_id,
                source_fingerprint=None, confidence_bps=10000, user_confirmed=True,
                trust_level="L1_USER_CONFIRMED", verification_status="USER_CONFIRMED",
                verification_method="EXPLICIT_PREFERENCE_CONFIRMATION", status="ACTIVE",
                created_at=t, updated_at=t)
            s.add(row)
            if old:
                old.status="SUPERSEDED"; old.superseded_by=row.fact_id; old.updated_at=t
            _audit(s, tr, user_id, "CONSUMER", "TRAVEL_PREFERENCE_SAVED", purpose, [preference_key],
                {"preference_id":row.fact_id, "consent_id":consent_id, "supersedes":old.fact_id if old else None})
            return _projection(row, json.loads(raw))

    def revoke_preference(self, user_id, traveler_id, preference_id):
        # The immutable preference ID is the expected revision: an old revision
        # cannot withdraw a later value created under a different ID.
        with mutation_session() as s:
            tr = owned_traveler(s, user_id, traveler_id, edit=True)
            _self(tr)
            row = s.get(ProfileFactRow, preference_id, with_for_update=True)
            if not row or row.user_id != user_id or row.traveler_id != traveler_id or row.field_type != FIELD or row.source_provider != PROVIDER:
                raise ValueError("TRAVEL_PREFERENCE_NOT_FOUND")
            result = {"preference_id":preference_id, "status":"REVOKED"}
            if row.status == "REVOKED":
                return result
            if row.status != "ACTIVE":
                raise ValueError("TRAVEL_PREFERENCE_REVISION_CONFLICT")
            payload = _payload(row)
            row.status="REVOKED"; row.updated_at=_now()
            row.value_ciphertext=encrypt_secret("null")
            row.normalized_value_hash=hashlib.sha256(b"REVOKED").hexdigest()
            _audit(s, tr, user_id, "CONSUMER", "TRAVEL_PREFERENCE_REVOKED", payload["purpose"] if payload else None,
                [payload["key"]] if payload else [], {"preference_id":preference_id})
            return result

    def preferences(self, traveler_id, *, purpose, actor_id="C07", actor_type="GO_SYSTEM", user_id=None):
        purpose = _purpose(purpose)
        # SQLite needs BEGIN IMMEDIATE because its legacy SELECT handling does
        # not otherwise retain a transaction that serializes consent withdrawal.
        with mutation_session() as s:
            tr = s.get(TravelerProfileRow, traveler_id)
            if not tr or tr.status != "ACTIVE" or (user_id is not None and tr.user_id != user_id):
                raise ValueError("TRAVELER_NOT_FOUND")
            _self(tr)
            if not permission(s, tr.user_id, tr, "VIEW"):
                raise ValueError("TRAVELER_VIEW_PERMISSION_REQUIRED")
            preferences = _read_preferences(s, tr, purpose)
            _audit(s, tr, actor_id, actor_type, "TRAVEL_PREFERENCES_READ", purpose,
                [x["preference_key"] for x in preferences], {"released_count":len(preferences)})
            return {"traveler_id":traveler_id, "purpose":purpose, "preferences":preferences,
                "projection":"EXPLICIT_PURPOSE_BOUND_V1"}

    def preference_graph(self, traveler_id, *, purpose, actor_id="C07", actor_type="GO_SYSTEM"):
        purpose = _purpose(purpose)
        with mutation_session() as s:
            tr = s.get(TravelerProfileRow, traveler_id)
            if not tr or tr.status != "ACTIVE":
                raise ValueError("TRAVELER_NOT_FOUND")
            _self(tr)
            if not permission(s, tr.user_id, tr, "VIEW"):
                raise ValueError("TRAVELER_VIEW_PERMISSION_REQUIRED")
            grants = _active_consents(s, tr, purpose, "TRAVELER_CONTEXT")
            scope = {field for c in grants.values() for field in (c.scope_json or [])}
            identity = {"relationship_type":tr.relationship_type, "nationality":tr.nationality} if "TRAVELER_IDENTITY" in scope else {}
            intents = []
            if "TRAVEL_INTENTS" in scope:
                rows = s.scalars(select(TravelIntentRow).where(TravelIntentRow.traveler_id == traveler_id,
                    TravelIntentRow.status == "ACTIVE").order_by(TravelIntentRow.updated_at.desc()).limit(20)).all()
                intents = [r.normalized_intent for r in rows if purpose in (r.consent_scope or [])]
            count = 0
            if "TRAVEL_BEHAVIOR" in scope:
                rows = s.scalars(select(TravelBehaviorEventRow).where(TravelBehaviorEventRow.traveler_id == traveler_id)
                    .order_by(TravelBehaviorEventRow.occurred_at.desc()).limit(100)).all()
                count = sum(1 for r in rows if (r.payload or {}).get("purpose") == purpose)
            # The traveler graph is a context projection. A separate explicit-
            # preference grant authorizes the standalone preference projection,
            # but must not silently broaden a journey context grant. The caller
            # must opt this graph purpose into preference context explicitly.
            preferences = _read_preferences(s, tr, purpose) if "TRAVEL_PREFERENCES" in scope else []
            _audit(s, tr, actor_id, actor_type, "TRAVELER_CONTEXT_READ", purpose, sorted(scope),
                {"preference_count":len(preferences), "intent_count":len(intents), "behavior_count":count})
            return {"traveler_id":traveler_id, "purpose":purpose, "identity":identity,
                "recent_intents":intents, "behavior_evidence_count":count, "durable_preferences":preferences,
                "policy":"SESSION_SIGNAL_NEVER_AUTO_PROMOTES_TO_PERMANENT_PREFERENCE"}
