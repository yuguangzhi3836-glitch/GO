"""Authenticated original-file intake. Declarations are not publication approval.

Uses the existing durable local media cache and transactional SQLite metadata.
These drafts are property-scoped, not implicitly bound to a canonical hotel.
"""
from __future__ import annotations
import base64
import binascii
import hashlib
import io
import json
import os
from pathlib import Path
import uuid
import warnings

from PIL import Image
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HotelPartnerRoomTypeRow, HotelPartnerPropertyRow, HotelPartnerChangeRequestRow
from go_hotel.services.hotel_partner_core import hotel_partner_core_service as core, now, ident, out
from go_hotel.services.media_harvester import (
    MediaHarvesterService, ALLOWED_ROLES, MAX_IMAGE_BYTES, now_iso, _rights_publishable,
)


class HotelPartnerMediaUploadService:
    def __init__(self, cache=None):
        self._cache = cache

    @property
    def cache(self):
        if self._cache is None:
            self._cache = MediaHarvesterService()
        return self._cache

    def _authorize(self, supplier_id, pid, room_id=None):
        with SessionLocal() as s:
            core._property(s, pid, supplier_id)
            if room_id:
                room = s.get(HotelPartnerRoomTypeRow, room_id)
                if room is None or room.property_id != pid:
                    raise ValueError('ROOM_TYPE_NOT_FOUND')

    @staticmethod
    def _public(rec, deduplicated=False):
        return {k: rec.get(k) for k in (
            'asset_id', 'property_id', 'room_type_id', 'role', 'sha256',
            'width', 'height', 'byte_size', 'mime_type', 'state', 'revision', 'rights_state',
        )} | {'publishable': False, 'deduplicated': deduplicated,
             'rights_approved': _rights_publishable(rec),
             'original_url': f"/v1/supplier/properties/{rec['property_id']}/media-uploads/{rec['asset_id']}/original"}

    def upload(self, supplier_id, actor, pid, body):
        room_id = body.get('room_type_id')
        if room_id is not None and (not isinstance(room_id, str) or not room_id.strip()):
            raise ValueError('MEDIA_ROOM_TYPE_ID_REQUIRED')
        self._authorize(supplier_id, pid, room_id)
        if set(body) - {'content_base64', 'role', 'room_type_id', 'rights'}:
            raise ValueError('MEDIA_UPLOAD_FIELDS_INVALID')
        role = body.get('role')
        if not isinstance(role, str) or role not in ALLOWED_ROLES:
            raise ValueError('MEDIA_ROLE_INVALID')
        if role == 'ROOM' and not room_id:
            raise ValueError('MEDIA_ROOM_TYPE_ID_REQUIRED')
        if room_id and role != 'ROOM':
            raise ValueError('MEDIA_ROOM_ROLE_REQUIRED')
        rights = body.get('rights')
        if not isinstance(rights, dict) or set(rights) - {'rights_holder', 'evidence_reference', 'usage_scope', 'expires_at'}:
            raise ValueError('MEDIA_RIGHTS_EVIDENCE_REQUIRED')
        if not all(isinstance(rights.get(k), str) and 0 < len(rights[k].strip()) <= 512 for k in ('rights_holder', 'evidence_reference')):
            raise ValueError('MEDIA_RIGHTS_EVIDENCE_REQUIRED')
        if rights.get('usage_scope') != ['DISTRIBUTE_ON_GO']:
            raise ValueError('MEDIA_DISTRIBUTION_SCOPE_REQUIRED')
        core._validate_media_rights([{'source_reference': 'direct-upload'}],
            rights | {'status': 'HOTEL_SUBMITTED', 'applies_to_all_assets': True})
        encoded = body.get('content_base64')
        if not isinstance(encoded, str) or not encoded:
            raise ValueError('MEDIA_UPLOAD_BYTES_REQUIRED')
        if len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
            raise ValueError('MEDIA_IMAGE_TOO_LARGE')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError('MEDIA_CONTENT_NOT_VALID_IMAGE') from exc
        if not raw or len(raw) > MAX_IMAGE_BYTES:
            raise ValueError('MEDIA_IMAGE_TOO_LARGE')
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            try:
                with Image.open(io.BytesIO(raw)) as im:
                    fmt = im.format
                    width, height = im.size
                    if width * height > 40_000_000:
                        raise ValueError('MEDIA_IMAGE_PIXEL_LIMIT')
                    if fmt not in {'JPEG', 'PNG', 'WEBP'}:
                        raise ValueError('MEDIA_IMAGE_FORMAT_NOT_ALLOWED')
                    if getattr(im, 'n_frames', 1) != 1:
                        raise ValueError('MEDIA_ANIMATION_NOT_ALLOWED')
                    if min(width, height) < 720 or max(width, height) < 1280:
                        raise ValueError('MEDIA_IMAGE_TOO_SMALL')
                    im.verify()
                with Image.open(io.BytesIO(raw)) as im:
                    im.load()  # Reject truncated pixel data, not just valid headers.
            except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
                raise ValueError('MEDIA_IMAGE_PIXEL_LIMIT') from exc
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError('MEDIA_CONTENT_NOT_VALID_IMAGE') from exc
        digest = hashlib.sha256(raw).hexdigest()
        binding = json.dumps([supplier_id, pid, room_id, role, digest, rights], sort_keys=True, separators=(',', ':'))
        asset_id = 'media_' + hashlib.sha256(binding.encode()).hexdigest()[:48]
        ext, mime = {'JPEG': ('.jpg', 'image/jpeg'), 'PNG': ('.png', 'image/png'), 'WEBP': ('.webp', 'image/webp')}[fmt]
        cache = self.cache
        destination = cache.files_dir / (digest + ext)
        temporary = cache.cache_dir / ('upload-' + uuid.uuid4().hex + '.part')
        rec = dict(asset_id=asset_id, hotel_id=pid, property_id=pid, supplier_id=supplier_id,
            room_type_id=room_id, role=role, sha256=digest, width=width, height=height,
            byte_size=len(raw), mime_type=mime, cache_file=destination.name,
            cache_state='VALIDATED', state='DRAFT', rights_state='RIGHTS_UNKNOWN',
            rights_history=[], rights_declaration=rights, source_type='HOTEL_DIRECT_UPLOAD',
            submitted_by=actor, downloaded_at=now_iso(), publishable=False)
        try:
            with temporary.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            # Same transaction serializes dedup and metadata admission across workers.
            with cache._index.transaction() as db:
                existing = db.execute('SELECT 1 FROM media_assets WHERE asset_id=?', (asset_id,)).fetchone()
                if existing:
                    prior = cache._index.load(db, asset_id)
                    self._read_bytes(prior)
                    return self._public(prior, True)
                cache._admit_file(temporary, destination, digest)
                cache._index.save(db, rec, revision=1)
                cache._index.bump(db)
            return self._public(rec)
        finally:
            temporary.unlink(missing_ok=True)

    def list_uploads(self, supplier_id, pid):
        self._authorize(supplier_id, pid)
        with SessionLocal() as s:
            bindings = (core._property(s, pid, supplier_id).operations_json or {}).get('direct_media_bindings', {})
        return [self._public(r) | {'bound': r['asset_id'] in bindings} for r in self.cache._index.snapshot()['assets'].values()
                if r.get('property_id') == pid and r.get('supplier_id') == supplier_id
                and r.get('source_type') == 'HOTEL_DIRECT_UPLOAD']

    def _owned_asset(self, supplier_id, pid, asset_id):
        rec = self.cache._index.get(asset_id)
        if rec.get('property_id') != pid or rec.get('supplier_id') != supplier_id or rec.get('source_type') != 'HOTEL_DIRECT_UPLOAD':
            raise ValueError('MEDIA_ASSET_NOT_FOUND')
        return rec

    def bind(self, supplier_id, actor, pid, asset_id, body):
        """Attach an original to this property's draft; a changed role creates a new identity.

        Rights on a previous role/room are never copied to the new binding. No
        canonical hotel or canonical room identity is inferred from a partner id.
        """
        self._authorize(supplier_id, pid)
        if set(body) - {'expected_revision', 'role', 'room_type_id'}:
            raise ValueError('MEDIA_BINDING_FIELDS_INVALID')
        rec = self._owned_asset(supplier_id, pid, asset_id)
        if type(body.get('expected_revision')) is not int or body['expected_revision'] != rec['revision']:
            raise ValueError('MEDIA_ASSET_REVISION_CONFLICT')
        role, room_id = body.get('role'), body.get('room_type_id')
        if not isinstance(role, str) or role not in ALLOWED_ROLES:
            raise ValueError('MEDIA_ROLE_INVALID')
        if room_id is not None and (not isinstance(room_id, str) or not room_id.strip()):
            raise ValueError('MEDIA_ROOM_TYPE_ID_REQUIRED')
        if role == 'ROOM' and not room_id:
            raise ValueError('MEDIA_ROOM_TYPE_ID_REQUIRED')
        if room_id and role != 'ROOM':
            raise ValueError('MEDIA_ROOM_ROLE_REQUIRED')
        self._authorize(supplier_id, pid, room_id)
        raw = self._read_bytes(rec)
        if (role, room_id) != (rec['role'], rec.get('room_type_id')):
            derived = self.upload(supplier_id, actor, pid, {
                'content_base64': base64.b64encode(raw).decode(), 'role': role,
                'room_type_id': room_id, 'rights': rec['rights_declaration'],
            })
            rec = self._owned_asset(supplier_id, pid, derived['asset_id'])
        with SessionLocal() as s:
            prop = s.scalar(select(HotelPartnerPropertyRow).where(
                HotelPartnerPropertyRow.property_id == pid).with_for_update())
            if prop is None or prop.supplier_id != supplier_id:
                raise ValueError('PROPERTY_NOT_FOUND')
            room = s.get(HotelPartnerRoomTypeRow, room_id) if room_id else None
            if room_id and (room is None or room.property_id != pid):
                raise ValueError('ROOM_TYPE_NOT_FOUND')
            ops = dict(prop.operations_json or {})
            bindings = dict(ops.get('direct_media_bindings') or {})
            binding = {'asset_id': rec['asset_id'], 'role': role, 'room_type_id': room_id,
                       'sha256': rec['sha256'], 'state': 'DRAFT', 'bound_by': actor}
            bindings[rec['asset_id']] = binding
            ops['direct_media_bindings'] = bindings
            prop.operations_json = ops
            prop.updated_at = now()
            if room:
                media = list(room.media_json or [])
                if not any(isinstance(x, dict) and x.get('asset_id') == rec['asset_id'] for x in media):
                    room.media_json = media + [binding]
                    room.updated_at = now()
            core._audit(s, pid, 'MEDIA_DRAFT_BOUND', 'MEDIA_ASSET', rec['asset_id'],
                        {'role': role, 'room_type_id': room_id, 'sha256': rec['sha256']}, actor)
            s.commit()
        return self._public(rec) | {'bound': True}

    def _request_view(self, supplier_id, pid, request):
        blockers = []
        for item in request['proposed_value_json']['assets']:
            try:
                rec = self._owned_asset(supplier_id, pid, item['asset_id'])
                self._read_bytes(rec)
                if rec['sha256'] != item['sha256']:
                    raise ValueError('MEDIA_CACHE_INTEGRITY_FAILED')
                if not _rights_publishable(rec):
                    blockers.append({'asset_id': item['asset_id'], 'code': 'RIGHTS_REVIEW_REQUIRED', 'label': '图片使用授权待审核'})
            except ValueError:
                blockers.append({'asset_id': item['asset_id'], 'code': 'ORIGINAL_UNAVAILABLE', 'label': '图片原文件需重新核验'})
        blockers.append({'code': 'CANONICAL_PUBLICATION_REVIEW_REQUIRED', 'label': '待管理员核验正式酒店、房型对应关系并通过网页发布门禁'})
        status = 'PUBLISH_REQUESTED' if request['state'] == 'SUBMITTED' else 'REVIEW_' + request['state']
        return request | {'publication_state': status, 'published': False,
                          'blockers': blockers, 'supplier_can_publish': False}

    def request_publication(self, supplier_id, actor, pid, body):
        self._authorize(supplier_id, pid)
        if set(body) - {'asset_ids', 'confirmed'} or body.get('confirmed') is not True:
            raise ValueError('MEDIA_PUBLICATION_CONFIRMATION_REQUIRED')
        ids = body.get('asset_ids')
        if not isinstance(ids, list) or not 0 < len(ids) <= 500 or any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != len(ids):
            raise ValueError('MEDIA_PUBLICATION_ASSETS_REQUIRED')
        with SessionLocal() as s:
            prop = s.scalar(select(HotelPartnerPropertyRow).where(
                HotelPartnerPropertyRow.property_id == pid).with_for_update())
            if prop is None or prop.supplier_id != supplier_id:
                raise ValueError('PROPERTY_NOT_FOUND')
            bindings = (prop.operations_json or {}).get('direct_media_bindings') or {}
            assets = []
            for asset_id in sorted(ids):
                rec = self._owned_asset(supplier_id, pid, asset_id)
                if asset_id not in bindings:
                    raise ValueError('MEDIA_BINDING_REQUIRED')
                self._read_bytes(rec)
                room = s.get(HotelPartnerRoomTypeRow, rec['room_type_id']) if rec.get('room_type_id') else None
                if rec.get('room_type_id') and (room is None or room.property_id != pid):
                    raise ValueError('ROOM_TYPE_NOT_FOUND')
                assets.append({key: rec.get(key) for key in ('asset_id', 'sha256', 'revision', 'role', 'room_type_id')})
            proposal = {'assets': assets, 'scope': 'PARTNER_DRAFT_MEDIA', 'requires_canonical_review': True}
            fingerprint = hashlib.sha256(json.dumps(proposal, sort_keys=True).encode()).hexdigest()
            existing = s.scalars(select(HotelPartnerChangeRequestRow).where(
                HotelPartnerChangeRequestRow.property_id == pid,
                HotelPartnerChangeRequestRow.field_group == 'MEDIA_PUBLICATION',
                HotelPartnerChangeRequestRow.state == 'SUBMITTED')).all()
            for item in existing:
                if item.proposed_value_json.get('fingerprint') == fingerprint:
                    return self._request_view(supplier_id, pid, out(item)) | {'deduplicated': True}
            request = HotelPartnerChangeRequestRow(change_request_id=ident('hcr'), property_id=pid,
                field_group='MEDIA_PUBLICATION', proposed_value_json=proposal | {'fingerprint': fingerprint},
                evidence_json=[], state='SUBMITTED', requested_by=actor, created_at=now())
            s.add(request)
            core._audit(s, pid, 'MEDIA_PUBLICATION_REQUESTED', 'CHANGE_REQUEST', request.change_request_id,
                        {'asset_count': len(assets), 'fingerprint': fingerprint}, actor)
            s.commit()
            return self._request_view(supplier_id, pid, out(request)) | {'deduplicated': False}

    def publication_requests(self, supplier_id, pid):
        self._authorize(supplier_id, pid)
        with SessionLocal() as s:
            rows = s.scalars(select(HotelPartnerChangeRequestRow).where(
                HotelPartnerChangeRequestRow.property_id == pid,
                HotelPartnerChangeRequestRow.field_group == 'MEDIA_PUBLICATION')
                .order_by(HotelPartnerChangeRequestRow.created_at.desc())).all()
            return [self._request_view(supplier_id, pid, out(row)) for row in rows]

    def _read_bytes(self, rec):
        name = rec.get('cache_file', '')
        path = self.cache.files_dir / name
        if not name or Path(name).name != name or path.is_symlink() or path.resolve().parent != self.cache.files_dir:
            raise ValueError('MEDIA_CACHE_PATH_INVALID')
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ValueError('MEDIA_CACHE_FILE_MISSING') from exc
        if hashlib.sha256(raw).hexdigest() != rec['sha256']:
            raise ValueError('MEDIA_CACHE_INTEGRITY_FAILED')
        return raw

    def original(self, supplier_id, pid, asset_id):
        self._authorize(supplier_id, pid)
        rec = self.cache._index.get(asset_id)
        if rec.get('property_id') != pid or rec.get('supplier_id') != supplier_id or rec.get('source_type') != 'HOTEL_DIRECT_UPLOAD':
            raise ValueError('MEDIA_ASSET_NOT_FOUND')
        self._authorize(supplier_id, pid, rec.get('room_type_id'))
        return self._read_bytes(rec), rec['mime_type']


hotel_partner_media_upload_service = HotelPartnerMediaUploadService()
