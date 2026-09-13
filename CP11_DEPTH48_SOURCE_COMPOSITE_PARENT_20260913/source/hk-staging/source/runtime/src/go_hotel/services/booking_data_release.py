from __future__ import annotations

from datetime import timezone

from sqlalchemy import select

from go_hotel.core.config import settings
from go_hotel.db.models import (
    ProfileConsentRow,
    ProfileDataReleaseAuditRow,
    ProfileTravelerPermissionRow,
    TravelerProfileRow,
)
from go_hotel.db.session import SessionLocal
from go_hotel.services.personal_travel_vault import personal_travel_vault_service, now

_PROD = {'prod','production'}
_FIELDS = {
    'HOTEL': ['LEGAL_NAME', 'MOBILE'],
    'FLIGHT': ['LEGAL_NAME'],
    'RAIL': ['LEGAL_NAME'],
    'RIDE': ['LEGAL_NAME', 'MOBILE'],
    'RENTAL': ['LEGAL_NAME', 'DRIVER_LICENSE_NUMBER'],
    'ATTRACTION': ['LEGAL_NAME'],
}
_DESTINATION = {
    'HOTEL': 'HOTEL_BOOKING_ADAPTER',
    'FLIGHT': 'FLIGHT_BOOKING_ADAPTER',
    'RAIL': 'RAIL_BOOKING_ADAPTER',
    'RIDE': 'RIDE_BOOKING_ADAPTER',
    'RENTAL': 'RENTAL_BOOKING_ADAPTER',
    'ATTRACTION': 'ATTRACTION_BOOKING_ADAPTER',
}


def _prod() -> bool:
    return settings.app_env.strip().lower() in _PROD


def _normalize(vertical: str, released: dict) -> dict:
    name = released.get('LEGAL_NAME')
    if vertical == 'HOTEL':
        return {'full_name': name, 'mobile': released.get('MOBILE')}
    if vertical in {'FLIGHT','RAIL'}:
        return {'full_name': name, 'type': 'ADT'}
    if vertical == 'RIDE':
        return {'full_name': name, 'mobile': released.get('MOBILE')}
    if vertical == 'RENTAL':
        return {'full_name': name, 'driver_license_number': released.get('DRIVER_LICENSE_NUMBER')}
    if vertical == 'ATTRACTION':
        return {'full_name': name}
    raise ValueError('BOOKING_DATA_VERTICAL_UNSUPPORTED')


def _active_consent(s, row: ProfileDataReleaseAuditRow) -> None:
    if not row.consent_id:
        return
    c = s.get(ProfileConsentRow, row.consent_id)
    if not c or c.user_id != row.user_id or c.status != 'ACTIVE':
        raise ValueError('VAULT_RELEASE_CONSENT_INACTIVE')
    exp = c.expires_at
    if exp and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp and exp <= now():
        raise ValueError('VAULT_RELEASE_CONSENT_EXPIRED')
    if c.traveler_id not in {None, row.traveler_id}:
        raise ValueError('VAULT_RELEASE_CONSENT_TRAVELER_MISMATCH')
    if c.purpose not in {row.purpose, 'TRAVEL_BOOKING', 'ANY_TRAVEL_BOOKING'}:
        raise ValueError('VAULT_RELEASE_CONSENT_PURPOSE_MISMATCH')
    scope = set(c.scope_json or [])
    released = set(row.released_fields_json or [])
    if '*' not in scope and not released.issubset(scope):
        raise ValueError('VAULT_RELEASE_CONSENT_SCOPE_MISMATCH')


def validate_booking_release_refs(
    account_id: str,
    vertical: str,
    traveler_ids: list[str] | None,
    release_ids: list[str] | None,
    *,
    requester_id: str | None = None,
) -> dict:
    vertical = vertical.upper()
    if vertical not in _FIELDS:
        raise ValueError('BOOKING_DATA_VERTICAL_UNSUPPORTED')
    tids = [str(x).strip() for x in (traveler_ids or []) if str(x).strip()]
    rids = [str(x).strip() for x in (release_ids or []) if str(x).strip()]
    if not tids and not rids:
        return {'traveler_ids': [], 'release_ids': [], 'minimum_necessary': True}
    if len(tids) != len(rids) or not tids:
        raise ValueError('VAULT_RELEASE_TRAVELER_PAIR_REQUIRED')
    required = set(_FIELDS[vertical])
    destination = _DESTINATION[vertical]
    with SessionLocal() as s:
        for tid, rid in zip(tids, rids):
            tr = s.get(TravelerProfileRow, tid)
            if not tr or tr.user_id != account_id or tr.status != 'ACTIVE':
                raise ValueError('VAULT_RELEASE_TRAVELER_MISMATCH')
            if not tr.booking_permission:
                raise ValueError('TRAVELER_BOOKING_PERMISSION_REQUIRED')
            if tr.relationship_type != 'SELF':
                perm = s.scalar(select(ProfileTravelerPermissionRow).where(
                    ProfileTravelerPermissionRow.user_id == account_id,
                    ProfileTravelerPermissionRow.traveler_id == tid,
                    ProfileTravelerPermissionRow.permission_type == 'USE_FOR_BOOKING',
                ))
                if not perm or not perm.allowed:
                    raise ValueError('TRAVELER_BOOKING_PERMISSION_REQUIRED')
            row = s.get(ProfileDataReleaseAuditRow, rid)
            if not row or row.decision != 'ALLOW':
                raise ValueError('VAULT_RELEASE_NOT_ALLOWED')
            if row.user_id != account_id:
                raise ValueError('VAULT_RELEASE_ACCOUNT_MISMATCH')
            if row.traveler_id != tid:
                raise ValueError('VAULT_RELEASE_TRAVELER_MISMATCH')
            if row.requester_type != 'CONSUMER' or (row.requester_id and row.requester_id != (requester_id or account_id)):
                raise ValueError('VAULT_RELEASE_REQUESTER_MISMATCH')
            if row.vertical != vertical:
                raise ValueError('VAULT_RELEASE_VERTICAL_MISMATCH')
            if row.purpose != 'TRAVEL_BOOKING':
                raise ValueError('VAULT_RELEASE_PURPOSE_MISMATCH')
            if row.destination != destination:
                raise ValueError('VAULT_RELEASE_DESTINATION_MISMATCH')
            released = set(row.released_fields_json or [])
            requested = set(row.requested_fields_json or [])
            if not required.issubset(released):
                raise ValueError('VAULT_RELEASE_MINIMUM_SCOPE_MISSING')
            if not released.issubset(required) or not requested.issubset(required):
                raise ValueError('VAULT_RELEASE_OVER_COLLECTION')
            _active_consent(s, row)
    return {'traveler_ids': tids, 'release_ids': rids, 'minimum_necessary': True}


def release_booking_data(
    account_id: str,
    vertical: str,
    traveler_ids: list[str] | None,
    raw_payload: list[dict] | None,
    *,
    vault_release_ids: list[str] | None = None,
    requester_id: str | None = None,
) -> dict:
    vertical = vertical.upper()
    if vertical not in _FIELDS:
        raise ValueError('BOOKING_DATA_VERTICAL_UNSUPPORTED')
    ids = [str(x).strip() for x in (traveler_ids or []) if str(x).strip()]
    raw = list(raw_payload or [])
    existing = [str(x).strip() for x in (vault_release_ids or []) if str(x).strip()]
    if existing:
        refs = validate_booking_release_refs(account_id, vertical, ids, existing, requester_id=requester_id)
        # Consumer-confirmed transaction payload wins; Vault data is not re-read here.
        return {'items': raw, 'release_ids': refs['release_ids'], 'traveler_ids': refs['traveler_ids'], 'vault_backed': True, 'minimum_necessary': True}
    if not ids:
        if _prod():
            raise ValueError('VAULT_TRAVELER_REFERENCE_REQUIRED')
        return {'items': raw, 'release_ids': [], 'traveler_ids': [], 'vault_backed': False, 'minimum_necessary': True}

    items=[]; release_ids=[]
    for tid in ids:
        result=personal_travel_vault_service.release(
            account_id,
            {
                'traveler_id': tid,
                'requested_fields': _FIELDS[vertical],
                'vertical': vertical,
                'purpose': 'TRAVEL_BOOKING',
                'destination': _DESTINATION[vertical],
            },
            requester_id=requester_id or account_id,
            requester_type='CONSUMER',
        )
        missing=[x for x in _FIELDS[vertical] if x not in result['released_fields']]
        if missing:
            raise ValueError('VAULT_REQUIRED_FIELD_MISSING:'+','.join(missing))
        items.append(_normalize(vertical,result['released_fields']))
        release_ids.append(result['release_id'])
    return {'items': items, 'release_ids': release_ids, 'traveler_ids': ids, 'vault_backed': True, 'minimum_necessary': True}
