from __future__ import annotations

from go_hotel.core.config import settings
from go_hotel.services.personal_travel_vault import personal_travel_vault_service

_PROD = {'prod','production'}
class BookingDataReleaseError(ValueError):
    """A denied or incomplete consumer booking data release."""
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


def release_booking_data(
    account_id: str,
    vertical: str,
    traveler_ids: list[str] | None,
    raw_payload: list[dict] | None,
    *,
    requester_id: str | None = None,
) -> dict:
    vertical = vertical.upper()
    if vertical not in _FIELDS:
        raise ValueError('BOOKING_DATA_VERTICAL_UNSUPPORTED')
    ids = [str(x).strip() for x in (traveler_ids or []) if str(x).strip()]
    if len(ids)!=len(set(ids)):raise BookingDataReleaseError('BOOKING_TRAVELER_DUPLICATE')
    raw = list(raw_payload or [])
    if not ids:
        if _prod():
            raise ValueError('VAULT_TRAVELER_REFERENCE_REQUIRED')
        return {'items': raw, 'release_ids': [], 'vault_backed': False}

    items=[]; release_ids=[]
    for tid in ids:
        try:
            result=personal_travel_vault_service.release(
            account_id,
            {
                'traveler_id': tid,
                'requested_fields': _FIELDS[vertical],
                'vertical': vertical,
                'purpose': f'{vertical}_BOOKING',
                'destination': _DESTINATION[vertical],
            },
            requester_id=requester_id or account_id,
            requester_type='CONSUMER',
            )
        except ValueError as exc:raise BookingDataReleaseError(str(exc)) from exc
        missing=[x for x in _FIELDS[vertical] if x not in result['released_fields']]
        if missing:
            raise BookingDataReleaseError('VAULT_REQUIRED_FIELD_MISSING:'+','.join(missing))
        items.append(_normalize(vertical,result['released_fields']))
        release_ids.append(result['release_id'])
    return {'items': items, 'release_ids': release_ids, 'vault_backed': True}
