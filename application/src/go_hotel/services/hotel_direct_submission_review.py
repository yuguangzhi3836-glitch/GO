"""Admin reviewed, immutable direct-submission bindings. Never grants image rights.

Only the admin:rules route exposes approval/revocation. Supplier metadata and
manifest confirmation strings cannot substitute for the server review record.
"""
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (HotelPartnerChangeRequestRow, HotelPartnerPropertyRow,
    HotelPartnerRoomTypeRow, HotelCanonicalProfileRow, HotelRegistrationDirectRow)
from go_hotel.services.hotel_partner_core import hotel_partner_core_service as core
from go_hotel.services.hotel_direct_submission_manifest import validate_direct_submission_manifest
from go_hotel.services.hotel_direct_submission_verification import hotel_direct_submission_verification_service

FIELD_GROUP = 'DIRECT_SUBMISSION_BINDING'
AUTHORITY_BLOCKERS = {'CANONICAL_ROOM_MAPPING_AUTHORITY_UNAVAILABLE',
                      'ASSOCIATION_AND_INVENTORY_EVIDENCE_UNVERIFIED'}

def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str).encode()).hexdigest()


class HotelDirectSubmissionReviewService:
    def __init__(self, verifier=None):
        self.verifier = verifier or hotel_direct_submission_verification_service

    def _row(self, session, review_id, lock=False):
        statement = select(HotelPartnerChangeRequestRow).where(HotelPartnerChangeRequestRow.change_request_id == review_id)
        if lock: statement = statement.with_for_update()
        row = session.execute(statement).scalar_one_or_none()
        if not row or row.field_group != FIELD_GROUP:
            raise ValueError('DIRECT_SUBMISSION_REVIEW_NOT_FOUND')
        return row

    def _current(self, session, manifest):
        identity = manifest['identity']
        pid, sid = identity['property_id'], identity['supplier_id']
        prop = core._property(session, pid, sid)
        result = self.verifier.verify(sid, pid, manifest)
        if any(b['code'] not in AUTHORITY_BLOCKERS for b in result['blockers']):
            raise ValueError('DIRECT_SUBMISSION_CURRENT_FACTS_BLOCKED')
        registration = session.get(HotelRegistrationDirectRow, identity['registration_id'])
        profile = session.get(HotelCanonicalProfileRow, identity['canonical_hotel_id'])
        rooms = session.scalars(select(HotelPartnerRoomTypeRow).where(HotelPartnerRoomTypeRow.property_id == pid)).all()
        if any(r.state != 'ACTIVE' or r.sale_unit != 'WHOLE_ROOM' for r in rooms):
            raise ValueError('DIRECT_SUBMISSION_PHYSICAL_ROOMS_REQUIRED')
        # Stable identity/physical facts only: publication adds image metadata.
        canonical_rooms = sorted([{k: v for k, v in r.items() if k not in
            {'images', 'media', 'media_candidates', 'source_url', 'source_type', 'source_document_sha256'}}
            for r in profile.canonical_json['rooms']], key=lambda r: r['room_type_id'])
        facts = {'property': {k:getattr(prop,k) for k in ('property_id','supplier_id','name_zh','name_en','property_type','address_json')},
            'registration': {k:getattr(registration,k) for k in ('hotel_registration_direct_id','hotel_id','supplier_id','state','reviewed_by','reviewed_at')},
            'canonical_hotel':{k:profile.canonical_json.get(k) for k in ('name','name_zh','name_en','address','policies','facilities','description','website')},
            'canonical_rooms':canonical_rooms,
            'partner_rooms':sorted([{k:getattr(r,k) for k in ('room_type_id','property_id','name_zh','name_en','sale_unit','physical_room_count','occupancy_json','bed_configurations_json','attributes_json','state')} for r in rooms],key=lambda r:r['room_type_id'])}
        return _hash(facts)

    def submit(self, supplier_id, actor, property_id, manifest, expected_sha256=None):
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 64:
            raise ValueError('DIRECT_SUBMISSION_ACTOR_REQUIRED')
        self.verifier.media._authorize(supplier_id, property_id)
        validated = validate_direct_submission_manifest(manifest, expected_sha256=expected_sha256)
        identity = validated['manifest']['identity']
        if identity['supplier_id'] != supplier_id or identity['property_id'] != property_id:
            raise ValueError('DIRECT_SUBMISSION_IDENTITY_MISMATCH')
        with SessionLocal() as session:
            core._property(session, property_id, supplier_id)
            row = HotelPartnerChangeRequestRow(change_request_id='hdsr_'+uuid4().hex,
                property_id=property_id,field_group=FIELD_GROUP,
                proposed_value_json={'manifest':validated['manifest'],'manifest_sha256':validated['manifest_sha256']},
                evidence_json=[],state='SUBMITTED',requested_by=actor,created_at=datetime.now(timezone.utc))
            session.add(row)
            core._audit(session,property_id,'DIRECT_SUBMISSION_SUBMITTED','CHANGE_REQUEST',row.change_request_id,{'manifest_sha256':validated['manifest_sha256']},actor)
            session.commit()
            return self._public(row)

    def get(self, review_id):
        with SessionLocal() as session:
            return self._public(self._row(session,review_id))

    def approve(self, review_id, actor, expected_sha256=None):
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 64:
            raise ValueError('DIRECT_SUBMISSION_ACTOR_REQUIRED')
        with SessionLocal() as session:
            row = self._row(session,review_id,lock=True)
            session.execute(select(HotelPartnerPropertyRow).where(HotelPartnerPropertyRow.property_id==row.property_id).with_for_update()).scalar_one()
            if row.state != 'SUBMITTED': raise ValueError('DIRECT_SUBMISSION_REVIEW_NOT_REVIEWABLE')
            if not expected_sha256: raise ValueError('DIRECT_SUBMISSION_REVIEW_HASH_REQUIRED')
            value = row.proposed_value_json
            validated = validate_direct_submission_manifest(value['manifest'],expected_sha256=expected_sha256)
            if validated['manifest_sha256'] != value['manifest_sha256']: raise ValueError('DIRECT_SUBMISSION_REVIEW_HASH_MISMATCH')
            fingerprint = self._current(session,validated['manifest'])
            row.evidence_json=[{'facts_sha256':fingerprint,'manifest_sha256':validated['manifest_sha256']}]
            row.state='APPROVED';row.reviewed_by=actor;row.reviewed_at=datetime.now(timezone.utc)
            core._audit(session,row.property_id,'DIRECT_SUBMISSION_APPROVED','CHANGE_REQUEST',review_id,{'manifest_sha256':validated['manifest_sha256'],'facts_sha256':fingerprint},actor)
            session.commit()
            return self._public(row)

    def revoke(self, review_id, actor):
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 64:
            raise ValueError('DIRECT_SUBMISSION_ACTOR_REQUIRED')
        with SessionLocal() as session:
            row=self._row(session,review_id,lock=True)
            if row.state == 'REVOKED': return self._public(row)
            if row.state != 'APPROVED': raise ValueError('DIRECT_SUBMISSION_REVIEW_NOT_APPROVED')
            row.state='REVOKED'
            core._audit(session,row.property_id,'DIRECT_SUBMISSION_REVOKED','CHANGE_REQUEST',review_id,{'manifest_sha256':row.proposed_value_json['manifest_sha256']},actor)
            session.commit();return self._public(row)

    def resolve(self, review_id, supplier_id, property_id):
        with SessionLocal() as session:
            core._property(session,property_id,supplier_id)
            row=self._row(session,review_id)
            if row.property_id != property_id: raise ValueError('DIRECT_SUBMISSION_REVIEW_NOT_FOUND')
            if row.state != 'APPROVED' or not row.reviewed_by or not row.reviewed_at:
                raise ValueError('DIRECT_SUBMISSION_REVIEW_NOT_APPROVED')
            value=row.proposed_value_json
            validated=validate_direct_submission_manifest(value['manifest'],expected_sha256=value['manifest_sha256'])
            identity=validated['manifest']['identity']
            if identity['supplier_id']!=supplier_id or identity['property_id']!=property_id:
                raise ValueError('DIRECT_SUBMISSION_IDENTITY_MISMATCH')
            fingerprint=self._current(session,validated['manifest'])
            if row.evidence_json != [{'facts_sha256':fingerprint,'manifest_sha256':validated['manifest_sha256']}]:
                raise ValueError('DIRECT_SUBMISSION_REVIEW_STALE')
            return {'review_id':review_id,'manifest':validated['manifest'],'manifest_sha256':validated['manifest_sha256'],
                    'reviewed_by':row.reviewed_by,'reviewed_at':row.reviewed_at.isoformat()}

    @staticmethod
    def _public(row):
        return {'review_id':row.change_request_id,'property_id':row.property_id,'state':row.state,
                'manifest':row.proposed_value_json['manifest'],'manifest_sha256':row.proposed_value_json['manifest_sha256'],
                'requested_by':row.requested_by,'reviewed_by':row.reviewed_by,
                'reviewed_at':row.reviewed_at.isoformat() if row.reviewed_at else None}


hotel_direct_submission_review_service=HotelDirectSubmissionReviewService()
