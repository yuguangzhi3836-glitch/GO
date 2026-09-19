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
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HotelPartnerRoomTypeRow
from go_hotel.services.hotel_partner_core import hotel_partner_core_service as core
from go_hotel.services.media_harvester import (
    MediaHarvesterService, ALLOWED_ROLES, MAX_IMAGE_BYTES, now_iso,
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
            'width', 'height', 'byte_size', 'mime_type', 'state',
        )} | {'publishable': False, 'deduplicated': deduplicated,
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
        return [self._public(r) for r in self.cache._index.snapshot()['assets'].values()
                if r.get('property_id') == pid and r.get('supplier_id') == supplier_id
                and r.get('source_type') == 'HOTEL_DIRECT_UPLOAD']

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
