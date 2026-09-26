"""Physical room ownership for hosted stays; no inferred hotel confirmations."""
import hashlib
import json
import unicodedata
from sqlalchemy import select
from go_hotel.db.models import (HostedDirectInventoryPoolRow as Pool, HostedDirectRateVariantRow as Variant,
                               HostedReservationNightRow as Night, HostedInventoryDayRow as Day)


def normalized_reference(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
        raise ValueError('VALID_REGISTERED_ROOM_REFERENCE_REQUIRED')
    return unicodedata.normalize('NFKC', value.strip()).casefold()


def validated_entries(registry, hotel):
    if (not isinstance(registry, dict) or type(registry.get('version')) is not int
            or registry['version'] < 1 or not isinstance(registry.get('rooms'), list)
            or not registry['rooms'] or not isinstance(registry.get('source_reference'), str)
            or not registry['source_reference'].strip()
            or registry.get('source_state') not in {'ISOLATED_FIXTURE', 'HOTEL_CONFIRMED'}):
        raise ValueError('ROOM_REGISTRY_REQUIRED')
    if (registry['source_state'] == 'ISOLATED_FIXTURE'
            and (hotel.contact_json or {}).get('inventory_data_mode') != 'SIMULATION'):
        raise ValueError('SIMULATED_ROOM_REGISTRY_NOT_LIVE_AUTHORITY')
    seen = set()
    entries = []
    for room in registry['rooms']:
        if not isinstance(room, dict) or room.get('state') not in {'ACTIVE', 'BLOCKED'}:
            raise ValueError('INVALID_ROOM_REGISTRY_ENTRY')
        key = normalized_reference(room.get('room_reference'))
        if key in seen:
            raise ValueError('DUPLICATE_REGISTERED_ROOM_REFERENCE')
        seen.add(key)
        entries.append((key, room))
    return entries


def validate_room(s, reservation, hotel, reference):
    requested = normalized_reference(reference)
    variants = list(s.scalars(select(Variant).where(
        Variant.hosted_offer_id == reservation.hosted_offer_id)))
    if len(variants) != 1:
        raise ValueError('ROOM_OFFER_POOL_BINDING_REQUIRED')
    expected_pool = variants[0].inventory_pool_id
    # Selling a rate may stop after booking. Ownership remains bound to the
    # reserved nights, so changing the current variant cannot move the guest.
    nights = list(s.scalars(select(Night).where(
        Night.hosted_reservation_id == reservation.hosted_reservation_id, Night.state == 'HELD')))
    for night in nights:
        day = s.get(Day, night.inventory_day_id)
        if day is None or day.inventory_pool_id != expected_pool:
            raise ValueError('ROOM_POOL_RESERVATION_NIGHT_MISMATCH')
    pools = list(s.scalars(select(Pool).where(Pool.hosted_hotel_id == hotel.hosted_hotel_id)
                          .order_by(Pool.inventory_pool_id).with_for_update().execution_options(populate_existing=True)))
    target = next((pool for pool in pools if pool.inventory_pool_id == expected_pool), None)
    if target is None:
        raise ValueError('ROOM_OFFER_HOTEL_POOL_MISMATCH')
    matches = []
    for pool in pools:
        details = pool.room_details_json or {}
        registry = details.get('room_registry') if isinstance(details, dict) else None
        if registry is None and pool.inventory_pool_id != expected_pool:
            continue
        for key, room in validated_entries(registry,hotel):
            if key == requested:
                matches.append((pool, registry, room))
    if not matches:
        raise ValueError('ROOM_NOT_REGISTERED_FOR_HOTEL')
    if len(matches) != 1:
        raise ValueError('AMBIGUOUS_ROOM_POOL_BINDING')
    pool, registry, room = matches[0]
    if pool.inventory_pool_id != expected_pool:
        raise ValueError('ROOM_NOT_IN_RESERVATION_POOL')
    if room['state'] != 'ACTIVE':
        raise ValueError('REGISTERED_ROOM_NOT_ACTIVE')
    return {'room_reference': room['room_reference'].strip(),
            'normalized_room_reference': requested,
            'inventory_pool_id': expected_pool, 'room_registry_version': registry['version'],
            'room_registry_source_state': registry['source_state'],
            'room_registry_hash': hashlib.sha256(json.dumps(registry, sort_keys=True,
                separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()}


def configure_isolated_registry(pool_id, body, principal):
    """Versioned engineering registration through the existing hotel authority.

    This entry point cannot attest real hotel room data or create a live grant.
    """
    from go_hotel.services.alipay_safeguarded_settlement import transaction
    from go_hotel.db.models import (HostedDirectHotelRow as Hotel, AuditEventRow,
        GuestStayLifecycleRow as Stay, HostedDirectReservationRow as Reservation, HostedDirectRoomOfferRow as Offer)
    from go_hotel.services.hosted_operation_authority import scoped
    from go_hotel.services.hosted_direct_booking import ident, now
    with transaction() as s:
        hotel_id=s.scalar(select(Pool.hosted_hotel_id).where(Pool.inventory_pool_id==pool_id))
        if hotel_id is None:
            raise PermissionError('HOSTED_HOTEL_SCOPE_REQUIRED')
        hotel=s.get(Hotel,hotel_id,with_for_update=True)
        scoped(s,principal,hotel.hosted_hotel_id,'admin:rules',root_only=True)
        pools=list(s.scalars(select(Pool).where(Pool.hosted_hotel_id==hotel.hosted_hotel_id)
                            .order_by(Pool.inventory_pool_id).with_for_update().execution_options(populate_existing=True)))
        pool=next(row for row in pools if row.inventory_pool_id==pool_id)
        before=(pool.room_details_json or {}).get('room_registry')
        current_version=before.get('version') if isinstance(before,dict) else 0
        if type(body.get('expected_version')) is not int or body['expected_version']!=current_version:
            raise ValueError('ROOM_REGISTRY_VERSION_CONFLICT')
        if (body.get('source_state')!='ISOLATED_FIXTURE'
                or not str(body.get('source_reference') or '').startswith('isolated://')):
            raise ValueError('REAL_ROOM_REGISTRY_AUTHORITY_UNVERIFIED')
        registry={'version':current_version+1,'source_state':'ISOLATED_FIXTURE',
                  'source_reference':body['source_reference'],'rooms':body.get('rooms'),
                  'registered_by':principal.user_id,'registered_at':now().isoformat()}
        entries=validated_entries(registry,hotel)
        keys={key for key,_ in entries}
        old_keys={key for key,_ in validated_entries(before,hotel)} if before else set()
        active_keys={key for key,room in entries if room['state']=='ACTIVE'}
        occupied=s.scalars(select(Stay.assigned_room_reference).join(Reservation,
            Reservation.hosted_reservation_id==Stay.hosted_reservation_id).join(Offer,
            Offer.hosted_offer_id==Reservation.hosted_offer_id).where(
            Offer.hosted_hotel_id==hotel.hosted_hotel_id,Stay.state.in_(['ARRIVED','IN_HOUSE']),
            Stay.assigned_room_reference.is_not(None))).all()
        if any(normalized_reference(ref) in old_keys and normalized_reference(ref) not in active_keys for ref in occupied):
            raise ValueError('ROOM_REGISTRY_ACTIVE_STAY_CONFLICT')
        for other in pools:
            if other.inventory_pool_id==pool_id:continue
            other_registry=(other.room_details_json or {}).get('room_registry')
            if other_registry is not None and keys.intersection(key for key,_ in validated_entries(other_registry,hotel)):
                raise ValueError('AMBIGUOUS_ROOM_POOL_BINDING')
        pool.room_details_json={**(pool.room_details_json or {}),'room_registry':registry}
        s.add(AuditEventRow(audit_id=ident('room_audit'),actor_id=principal.user_id,actor_type='ADMIN',
            supplier_id=None,roles=['HOTEL_OPERATIONS_ADMIN'],session_id=getattr(principal,'session_id',None),
            action='HOSTED_ISOLATED_ROOM_REGISTRY_UPDATED',resource_type='HOSTED_ROOM_REGISTRY',resource_id=pool_id,
            request_id=None,client_ip=None,http_method=None,path=None,before_state=before,after_state=registry,
            decision_id=None,evidence_id=None,approval_id=None,
            metadata_json={'source_state':'ISOLATED_FIXTURE','real_hotel_confirmation':False},created_at=now()))
        s.commit()
        return {'inventory_pool_id':pool_id,'registry':registry,'real_hotel_confirmation':False}
