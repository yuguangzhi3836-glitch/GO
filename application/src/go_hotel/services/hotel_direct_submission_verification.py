"""Read-only inspection of a direct-submission proposal against current server facts.

This read-only endpoint never grants rights or publication authority.
Trusted review is held separately from supplier-editable metadata.
Supplier-editable JSON and strings in the manifest cannot clear this blocker.
"""
from datetime import datetime, timezone
from PIL import Image
from go_hotel.services.hotel_original_verification_scope import original_facts
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HotelPartnerRoomTypeRow, HotelRegistrationDirectRow, HotelCanonicalProfileRow
from go_hotel.services.hotel_partner_core import hotel_partner_core_service as core
from go_hotel.services.hotel_partner_media_upload import hotel_partner_media_upload_service
from go_hotel.services.hotel_direct_submission_manifest import validate_direct_submission_manifest
from go_hotel.services.media_harvester import _rights_publishable


class HotelDirectSubmissionVerificationService:
    def __init__(self, media=None):
        self.media = media or hotel_partner_media_upload_service

    def verify(self, supplier_id, property_id, manifest, expected_sha256=None):
        # Authenticate ownership before parsing any untrusted submission identities.
        self.media._authorize(supplier_id, property_id)
        validated = validate_direct_submission_manifest(manifest, expected_sha256=expected_sha256)
        data = validated['manifest']
        identity = data['identity']
        if identity['supplier_id'] != supplier_id or identity['property_id'] != property_id:
            raise ValueError('DIRECT_SUBMISSION_IDENTITY_MISMATCH')
        blockers = []
        def block(code, asset_id=None):
            entry = {'code': code}
            if asset_id is not None: entry['asset_id'] = asset_id
            if entry not in blockers: blockers.append(entry)
        with SessionLocal() as session:
            core._property(session, property_id, supplier_id)
            registration = session.get(HotelRegistrationDirectRow, identity['registration_id'])
            association_matches = bool(registration and registration.supplier_id == supplier_id
                and registration.hotel_id == identity['canonical_hotel_id']
                and (registration.official_supplement_json or {}).get('property_id') == property_id)
            if not association_matches:
                block('REGISTRATION_ASSOCIATION_NOT_FOUND')
            # Presence of reviewer metadata is not an approval of this manifest.
            if not (association_matches and registration.state == 'APPROVED' and registration.reviewed_by and registration.reviewed_at):
                block('REGISTRATION_REVIEW_NOT_VERIFIED')
            profile = session.get(HotelCanonicalProfileRow, identity['canonical_hotel_id']) if association_matches else None
            if profile is None: block('CANONICAL_PROFILE_NOT_FOUND')
            elif profile.go_direct_state not in {'GO_DIRECT_VERIFIED', 'GO_DIRECT_LIVE'}:
                block('CANONICAL_REGISTRATION_NOT_ACTIVE')
            canonical_rooms = (profile.canonical_json or {}).get('rooms', []) if profile else []
            if not isinstance(canonical_rooms, list): canonical_rooms = []
            canonical_ids = [r.get('room_type_id') for r in canonical_rooms if isinstance(r, dict)]
            if (not canonical_ids or len(canonical_ids) != len(canonical_rooms)
                    or any(not isinstance(r, str) or not r for r in canonical_ids)
                    or len(set(canonical_ids)) != len(canonical_ids)
                    or set(canonical_ids) != set(data['inventory']['canonical_room_ids'])):
                block('CANONICAL_ROOM_INVENTORY_MISMATCH')
            rooms = set(session.scalars(select(HotelPartnerRoomTypeRow.room_type_id).where(
                HotelPartnerRoomTypeRow.property_id == property_id)).all())
            if rooms != set(data['inventory']['partner_room_ids']):
                block('PARTNER_ROOM_INVENTORY_MISMATCH')
        # No trust is placed in supplier-editable operations/supplement metadata.
        block('CANONICAL_ROOM_MAPPING_AUTHORITY_UNAVAILABLE')
        block('ASSOCIATION_AND_INVENTORY_EVIDENCE_UNVERIFIED')
        results = []
        for asset in data['assets']:
            aid = asset['asset_id']
            result = {'asset_id': aid, 'original_verified': False, 'current_rights_verified': False}
            results.append(result)
            try:
                rec = self.media._owned_asset(supplier_id, property_id, aid)
            except ValueError:
                block('ASSET_NOT_FOUND_IN_PROPERTY', aid)
                continue
            if rec.get('role') != asset['role'] or rec.get('room_type_id') != asset['partner_room_id']:
                block('ASSET_BINDING_MISMATCH', aid)
            try:
                self.media._authorize(supplier_id, property_id, rec.get('room_type_id'))
                facts = original_facts(self.media, rec)
                if any(asset[key] != value for key,value in facts.items()):
                    block('ORIGINAL_FACTS_MISMATCH', aid)
                else: result['original_verified'] = True
            except (ValueError, OSError, KeyError, Image.DecompressionBombError):
                block('ORIGINAL_UNAVAILABLE_OR_INVALID', aid)
            rights = asset['rights']
            declaration = rec.get('rights_declaration') or {}
            declaration_matches = all(rights[key] == declaration.get(key) for key in ('rights_holder','evidence_reference','usage_scope','expires_at'))
            if not declaration_matches:
                block('RIGHTS_DECLARATION_MISMATCH', aid)
            declaration_current = (rights['expires_at'] is None or datetime.fromisoformat(rights['expires_at'].replace('Z','+00:00')) > datetime.now(timezone.utc))
            current = (declaration_matches and declaration_current and _rights_publishable(rec)
                and rec.get('rights_owner') == rights['rights_holder']
                and rec.get('rights_evidence_reference') == rights['review_evidence_reference']
                and rec.get('rights_scope') == 'DISTRIBUTE_ON_GO'
                and bool(rec.get('rights_decided_by')) and bool(rec.get('rights_decided_at')))
            result['current_rights_verified'] = bool(current)
            if not current: block('CURRENT_RIGHTS_REVIEW_NOT_VERIFIED', aid)
        return {'manifest_sha256': validated['manifest_sha256'],
                'verification_state':'BLOCKED', 'checked_at':datetime.now(timezone.utc).isoformat(),
                'blockers':blockers, 'assets':results, 'rights_granted':False,
                'publishable':False, 'published':False,
                'verification_scope':'POINT_IN_TIME_READ_ONLY_NOT_PUBLICATION_AUTHORITY'}


hotel_direct_submission_verification_service = HotelDirectSubmissionVerificationService()
