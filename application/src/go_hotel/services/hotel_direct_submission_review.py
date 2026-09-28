"""Admin reviewed, immutable direct-submission bindings. Never grants image rights.

Only the admin:rules route exposes approval/revocation. Supplier metadata and
manifest confirmation strings cannot substitute for the server review record.
"""
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4
from urllib.parse import quote
from sqlalchemy import select, func
from go_hotel.db.session import SessionLocal
from go_hotel.services.hotel_original_verification_scope import original_verification_scope
from go_hotel.db.models import (HotelPartnerChangeRequestRow, HotelPartnerPropertyRow,
    HotelPartnerRoomTypeRow, HotelCanonicalProfileRow, HotelRegistrationDirectRow, HotelAutoPageVersionRow)
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

    def list_reviews(self, property_id=None, state=None, offset=0, limit=25):
        if state is not None and state not in {'SUBMITTED', 'APPROVED', 'REVOKED'}:
            raise ValueError('DIRECT_SUBMISSION_REVIEW_STATE_INVALID')
        if not isinstance(offset, int) or offset < 0 or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError('DIRECT_SUBMISSION_REVIEW_PAGINATION_INVALID')
        filters = [HotelPartnerChangeRequestRow.field_group == FIELD_GROUP]
        if property_id: filters.append(HotelPartnerChangeRequestRow.property_id == property_id)
        if state: filters.append(HotelPartnerChangeRequestRow.state == state)
        with SessionLocal() as session:
            total = session.scalar(select(func.count()).select_from(HotelPartnerChangeRequestRow).where(*filters))
            rows = session.scalars(select(HotelPartnerChangeRequestRow).where(*filters).order_by(
                HotelPartnerChangeRequestRow.created_at.desc(), HotelPartnerChangeRequestRow.change_request_id.desc()
            ).offset(offset).limit(limit)).all()
            items = []
            for row in rows:
                item = self._public(row)
                manifest = item.pop('manifest')
                item.update(identity=manifest['identity'], counts={'rooms':len(manifest['room_mappings']), 'assets':len(manifest['assets'])})
                items.append(item)
            return {'items':items, 'total':total, 'offset':offset, 'limit':limit}

    @original_verification_scope
    def inspection(self, review_id):
        reviewed = self.get(review_id)
        manifest = reviewed['manifest']
        identity = manifest['identity']
        sid, pid, hid = identity['supplier_id'], identity['property_id'], identity['canonical_hotel_id']
        conflicts = []
        facts_sha256 = None
        try:
            verification = self.verifier.verify(sid, pid, manifest, reviewed['manifest_sha256'])
        except ValueError as exc:
            verification = {'verification_state':'BLOCKED', 'blockers':[{'code':str(exc)}], 'assets':[]}
        conflicts.extend(b for b in verification['blockers'] if b['code'] not in AUTHORITY_BLOCKERS)
        current_approval = False
        if reviewed['state'] == 'APPROVED':
            try:
                self.resolve(review_id, sid, pid)
                current_approval = True
            except ValueError as exc:
                conflicts.append({'code':str(exc)})
        with SessionLocal() as session:
            prop = session.get(HotelPartnerPropertyRow, pid)
            profile = session.get(HotelCanonicalProfileRow, hid)
            reg = session.get(HotelRegistrationDirectRow, identity['registration_id'])
            partner = session.scalars(select(HotelPartnerRoomTypeRow).where(HotelPartnerRoomTypeRow.property_id == pid)).all()
            canonical = (profile.canonical_json or {}) if profile else {}
            raw_rooms = canonical.get('rooms', [])
            canonical_rooms = {r.get('room_type_id'):r for r in raw_rooms if isinstance(r, dict)} if isinstance(raw_rooms,list) else {}
            provenance = (profile.field_provenance_json or {}) if profile else {}
            if not isinstance(provenance, dict):
                conflicts.append({'code':'CATALOG_PROVENANCE_INVALID'})
            else:
                for field in ('name','address','rooms','policies','facilities','website','direct_submission'):
                    evidence = provenance.get(field) or {}
                    if not isinstance(evidence,dict) or evidence.get('conflict_state') == 'REVIEW_REQUIRED':
                        conflicts.append({'code':field.upper()+'_CONFLICT','field':field,'current_value':canonical.get(field)})
            partner_rooms = {r.room_type_id:r for r in partner}
            if any(r.state != 'ACTIVE' or r.sale_unit != 'WHOLE_ROOM' for r in partner):
                conflicts.append({'code':'DIRECT_SUBMISSION_PHYSICAL_ROOMS_REQUIRED'})
            mappings = []
            for mapping in manifest['room_mappings']:
                room = partner_rooms.get(mapping['partner_room_id'])
                target = canonical_rooms.get(mapping['canonical_room_id']) or {}
                mappings.append(dict(mapping, partner_name=room.name_zh if room else None,
                    canonical_name=target.get('name_zh') or target.get('name'),
                    partner_exists=room is not None, canonical_exists=bool(target),
                    partner_details={k:getattr(room,k) for k in ('physical_room_count','sale_unit','state','occupancy_json','bed_configurations_json','attributes_json')} if room else {},
                    canonical_details={k:v for k,v in target.items() if k not in {'images','media','media_candidates','source_url','source_type','source_document_sha256'}}))
            version = session.scalar(select(HotelAutoPageVersionRow).where(
                HotelAutoPageVersionRow.hotel_id == hid, HotelAutoPageVersionRow.publication_state == 'PUBLISHED'
            ).order_by(HotelAutoPageVersionRow.version.desc()))
            catalog = (((version.page_json or {}).get('_catalog_evidence') or {}).get('catalog') or {}) if version else {}
            current_pointer = bool(profile and profile.page_state == 'PUBLISHED' and
                (catalog.get('direct_submission') or {}).get('review_id') == review_id)
            publication = {'current_review_version':current_pointer,
                'version':version.version if current_pointer else None,
                'page_state':profile.page_state if profile else None,
                'slug':profile.slug if profile else None,
                'live_read_verified':False, 'publicly_available':False}
            property_data = ({k:getattr(prop,k) for k in ('property_id','supplier_id','name_zh','name_en','address_json')} if prop else None)
            canonical_data = {'hotel_id':hid, **{k:canonical.get(k) for k in ('name','name_zh','name_en','address','policies','facilities','description','website')}}
            registration = ({k:getattr(reg,k) for k in ('hotel_registration_direct_id','hotel_id','supplier_id','state','reviewed_by')} if reg else None)
            if not conflicts:
                try:
                    facts_sha256 = self._current(session, manifest)
                except ValueError as exc:
                    conflicts.append({'code':str(exc)})
        if current_approval:
            from go_hotel.services.hotel_catalog_quality import quality
            proposal = dict(canonical, direct_submission={'schema':'HOTEL_DIRECT_SUBMISSION_V1',
                'review_id':review_id,'supplier_id':sid,'property_id':pid,'manifest_sha256':reviewed['manifest_sha256']})
            report = quality(proposal, provenance, [], hotel_id=hid, verify_asset=None)
            for code in report.get('reasons', []):
                if not any(c['code']==code for c in conflicts): conflicts.append({'code':code})
        if current_pointer and current_approval:
            try:
                from go_hotel.services.hotel_autopage_factory import hotel_autopage_factory_service
                hotel_autopage_factory_service.public_page(publication['slug'])
                publication.update(live_read_verified=True, publicly_available=True)
            except ValueError as exc:
                conflicts.append({'code':str(exc)})
        asset_checks = {a['asset_id']:a for a in verification.get('assets', [])}
        assets = [dict(asset, verification=asset_checks.get(asset['asset_id'], {}),
            preview_url='/internal/v1/hotel-autopage/direct-submission-reviews/'+quote(review_id, safe='')+'/media/'+quote(asset['asset_id'], safe='')) for asset in manifest['assets']]
        return {'review':reviewed, 'facts_sha256':facts_sha256, 'property':property_data, 'canonical_hotel':canonical_data,
            'registration':registration, 'room_mappings':mappings, 'assets':assets,
            'verification':verification, 'conflicts':conflicts, 'publication':publication,
            'actions':{'can_approve':reviewed['state']=='SUBMITTED' and not conflicts,
                       'can_revoke':reviewed['state']=='APPROVED',
                       'can_publish':current_approval and not conflicts}}

    def supplier_list(self, supplier_id, property_id, state=None, offset=0, limit=25):
        with SessionLocal() as session:
            core._property(session, property_id, supplier_id)
        return self.list_reviews(property_id, state, offset, limit)

    @original_verification_scope
    def supplier_get(self, supplier_id, property_id, review_id):
        with SessionLocal() as session:
            core._property(session, property_id, supplier_id)
            row = self._row(session, review_id)
            if row.property_id != property_id:
                raise ValueError('DIRECT_SUBMISSION_REVIEW_NOT_FOUND')
            result = self._public(row)
        # Suppliers receive their own proposal and state only. A proposed
        # canonical hotel ID alone never authorizes reading that hotel's facts.
        result['publication'] = {'current_review_version':False,'publicly_available':False,'live_read_verified':False}
        if result['state'] == 'APPROVED':
            try:
                self.resolve(review_id, supplier_id, property_id)
                result['publication'] = self.inspection(review_id)['publication']
            except ValueError:
                pass
        return result

    def review_original(self, review_id, asset_id):
        reviewed = self.get(review_id)
        manifest = reviewed['manifest']
        if not any(asset['asset_id'] == asset_id for asset in manifest['assets']):
            raise ValueError('DIRECT_SUBMISSION_ASSET_NOT_IN_REVIEW')
        identity = manifest['identity']
        return self.verifier.media.original(identity['supplier_id'], identity['property_id'], asset_id)

    def approve(self, review_id, actor, expected_sha256=None, expected_facts_sha256=None):
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
            if expected_facts_sha256 is not None and expected_facts_sha256 != fingerprint:
                raise ValueError('DIRECT_SUBMISSION_REVIEW_FACTS_MISMATCH')
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
                'created_at':row.created_at.isoformat(),
                'reviewed_at':row.reviewed_at.isoformat() if row.reviewed_at else None}


hotel_direct_submission_review_service=HotelDirectSubmissionReviewService()
