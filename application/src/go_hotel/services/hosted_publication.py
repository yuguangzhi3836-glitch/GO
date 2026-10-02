"""Version-bound Hosted publication; engineering acceptance is never live rights.

Original bytes are read from an explicitly configured isolated object directory.
No caller-supplied rights label, path or URL is an approval. Real commercial
authority stays HOLD until a separately verified hotel delegation is available.
"""
import hashlib
import io
import os
from pathlib import Path
import re
from PIL import Image
from sqlalchemy import select
from go_hotel.db import models as m
from go_hotel.db.session import SessionLocal
from go_hotel.autonomy.durable import transaction
from go_hotel.services.hosted_content_acceptance import (
    authority_mode, binding_checked, binding_hash, digest, principal_checked,
    user_checked, now, ident, snapshot_checked, latest_decision, hosted_content_acceptance_service,
)


def original(asset):
    authority_mode()
    match = re.fullmatch(r'isolated-media://([a-f0-9]{64})\.(png|jpg|webp)', asset.storage_reference)
    root_name = os.getenv('GO_HOSTED_ISOLATED_MEDIA_ROOT')
    if not match or not root_name:
        raise ValueError('HOSTED_ORIGINAL_BYTES_REQUIRED')
    root = Path(root_name).resolve()
    path = root / (match[1] + '.' + match[2])
    if path.is_symlink() or path.resolve().parent != root:
        raise ValueError('HOSTED_ORIGINAL_PATH_INVALID')
    try:
        if path.stat().st_size > 10 * 1024 * 1024: raise ValueError('HOSTED_ORIGINAL_TOO_LARGE')
        raw = path.read_bytes()
    except OSError:
        raise ValueError('HOSTED_ORIGINAL_BYTES_REQUIRED') from None
    if hashlib.sha256(raw).hexdigest() != match[1]:
        raise ValueError('HOSTED_ORIGINAL_HASH_MISMATCH')
    try:
        with Image.open(io.BytesIO(raw)) as image:
            fmt, size = image.format, image.size
            if fmt not in {'PNG', 'JPEG', 'WEBP'} or size[0] * size[1] > 40_000_000:
                raise ValueError()
            image.verify()
    except Exception:
        raise ValueError('HOSTED_ORIGINAL_IMAGE_INVALID') from None
    return raw, {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}[fmt], match[1]


def manifest(session, hotel_id):
    authority_mode()
    hotel = session.get(m.HostedDirectHotelRow, hotel_id)
    if not hotel: raise ValueError('HOSTED_HOTEL_NOT_FOUND')
    content = hosted_content_acceptance_service.gate(hotel_id, _session=session, _content_only=True)
    if not content['content_approval_verified']:
        raise ValueError('HOSTED_CONTENT_APPROVAL_REQUIRED')
    snap = session.get(m.HostedContentSnapshotRow, content['snapshot_id'])
    approval = latest_decision(session, snap.content_snapshot_id)
    body = snapshot_checked(session, snap)
    pools = session.scalars(select(m.HostedDirectInventoryPoolRow).where(
        m.HostedDirectInventoryPoolRow.hosted_hotel_id == hotel_id).order_by(m.HostedDirectInventoryPoolRow.inventory_pool_id)).all()
    if not pools: raise ValueError('HOSTED_ROOM_CONFIGURATION_REQUIRED')
    for pool in pools:
        capacity = (pool.room_details_json or {}).get('max_occupancy')
        if type(capacity) is not int or not 1 <= capacity <= 30:
            raise ValueError('HOSTED_ROOM_CAPACITY_REQUIRED')
    assets = session.scalars(select(m.HostedMediaAssetRow).where(
        m.HostedMediaAssetRow.hosted_hotel_id == hotel_id,
        m.HostedMediaAssetRow.state == 'PENDING_RIGHTS_REVIEW').order_by(m.HostedMediaAssetRow.media_asset_id)).all()
    media = []
    for asset in assets:
        if not asset.submitted_by or not asset.submitter_binding_hash:raise ValueError('HOSTED_MEDIA_SUBMITTER_UNVERIFIED')
        user_checked(session,asset.submitted_by,'admin:rules')
        submitter=binding_checked(session,hotel_id,asset.submitted_by)
        if binding_hash(submitter)!=asset.submitter_binding_hash:raise ValueError('HOSTED_MEDIA_SUBMITTER_AUTHORITY_CHANGED')
        _, mime, sha = original(asset)
        media.append({'media_asset_id': asset.media_asset_id, 'submitted_by':asset.submitted_by, 'submitter_binding_hash':asset.submitter_binding_hash, 'role': asset.asset_role,
            'room': asset.physical_room_key, 'sha256': sha, 'mime_type': mime,
            'storage_reference': asset.storage_reference, 'rights_owner': asset.rights_owner,
            'rights_evidence_reference': asset.rights_evidence_reference})
    if not any(x['role'] == 'HERO' for x in media): raise ValueError('HOTEL_OWNED_HERO_IMAGE_REQUIRED')
    missing = {p.physical_room_key for p in pools} - {x['room'] for x in media if x['role'] == 'ROOM'}
    if missing: raise ValueError('HOTEL_OWNED_ROOM_IMAGES_REQUIRED')
    offers = session.scalars(select(m.HostedDirectRoomOfferRow).where(
        m.HostedDirectRoomOfferRow.hosted_hotel_id == hotel_id,
        m.HostedDirectRoomOfferRow.state == 'ACTIVE').order_by(m.HostedDirectRoomOfferRow.hosted_offer_id)).all()
    if not offers: raise ValueError('ACTIVE_ROOM_OFFER_REQUIRED')
    fares = []
    for offer in offers:
        fare = session.scalar(select(m.HostedFareRuleVersionRow).where(
            m.HostedFareRuleVersionRow.hosted_offer_id == offer.hosted_offer_id).order_by(m.HostedFareRuleVersionRow.version.desc()))
        if not fare: raise ValueError('HOSTED_FARE_RULE_REQUIRED')
        from go_hotel.services.omnichannel_payment import digest as fare_digest
        if fare_digest(fare.rules_json)!=fare.rule_hash:raise ValueError('HOSTED_FARE_RULE_HASH_MISMATCH')
        variant=session.scalar(select(m.HostedDirectRateVariantRow).where(m.HostedDirectRateVariantRow.hosted_offer_id==offer.hosted_offer_id))
        if variant and variant.inventory_pool_id not in {p.inventory_pool_id for p in pools}:raise ValueError('HOSTED_VARIANT_SCOPE_MISMATCH')
        fares.append({'offer_id': offer.hosted_offer_id, 'rule_hash': fare.rule_hash, 'rule_version_id':fare.rule_version_id,
            'variant':{'id':variant.rate_variant_id,'pool':variant.inventory_pool_id,'state':variant.state,'payment_mode':variant.payment_mode,'benefits':variant.benefits_json,'breakfast_count':variant.breakfast_count} if variant else None,
            'room_name': offer.room_name, 'rate_name': offer.rate_name, 'currency': offer.currency})
    return {'schema': 'HOSTED_PUBLICATION_V1', 'mode': 'ISOLATED_FIXTURE', 'hotel_id': hotel_id,
        'content_snapshot_id': snap.content_snapshot_id, 'content_hash': snap.content_hash,
        'content_decision_id': approval.content_approval_id, 'maker': body['created_by'],
        'rooms': [{'pool_id': p.inventory_pool_id, 'room': p.physical_room_key, 'details': p.room_details_json} for p in pools],
        'offers': fares, 'media': media}


def latest(session, hotel_id):
    return session.scalar(select(m.HostedPublicationReviewRow).where(
        m.HostedPublicationReviewRow.hosted_hotel_id == hotel_id).order_by(
        m.HostedPublicationReviewRow.decided_at.desc(), m.HostedPublicationReviewRow.publication_review_id.desc()))


def accepted(session, hotel_id):
    row = latest(session, hotel_id)
    if not row or row.decision != 'APPROVE': raise ValueError('HOSTED_PUBLICATION_APPROVAL_REQUIRED')
    current = manifest(session, hotel_id)
    if digest(current) != row.manifest_hash or row.manifest_json != current:
        raise ValueError('HOSTED_PUBLICATION_VERSION_CHANGED')
    user_checked(session, row.reviewer_id, 'admin:approve')
    binding = binding_checked(session, hotel_id, row.reviewer_id)
    if row.binding_hash != binding_hash(binding) or row.reviewer_id in {current['maker'],*[x['submitted_by'] for x in current['media']]}:
        raise ValueError('HOSTED_PUBLICATION_AUTHORITY_CHANGED')
    return row


def require_publication(session, hotel_id):
    try: return accepted(session, hotel_id)
    except (ValueError, PermissionError) as exc:
        raise ValueError('HOSTED_PUBLICATION_BLOCKED:' + str(exc)) from None


def preview(hotel_id, principal):
    with transaction(SessionLocal) as session:
        principal_checked(session, principal, 'admin:rules')
        binding_checked(session, hotel_id, principal.user_id)
        session.get(m.HostedDirectHotelRow, hotel_id, with_for_update=True)
        body = manifest(session, hotel_id)
        return {'manifest': body, 'manifest_hash': digest(body), 'real_hotel_authority_state': 'HOLD_UNVERIFIED'}


def review(hotel_id, body, principal):
    with transaction(SessionLocal) as session:
        actor = principal_checked(session, principal, 'admin:approve')
        session.get(m.HostedDirectHotelRow, hotel_id, with_for_update=True)
        binding = binding_checked(session, hotel_id, actor)
        if set(body) - {'decision', 'evidence_reference', 'expected_manifest_hash', 'expected_review_id'}:
            raise ValueError('HOSTED_PUBLICATION_REVIEW_FIELDS_INVALID')
        decision, reference = body.get('decision'), body.get('evidence_reference')
        if decision not in {'APPROVE', 'REJECT'} or not isinstance(reference, str) or not 1 <= len(reference.strip()) <= 512:
            raise ValueError('HOSTED_PUBLICATION_REVIEW_REQUIRED')
        previous = latest(session, hotel_id)
        # Revocation must remain possible when bytes/content are no longer readable.
        current = manifest(session, hotel_id) if decision == 'APPROVE' else (previous.manifest_json if previous else None)
        if current is None: raise ValueError('HOSTED_PUBLICATION_APPROVAL_REQUIRED')
        fingerprint = digest(current)
        if body.get('expected_manifest_hash') != fingerprint: raise ValueError('HOSTED_PUBLICATION_VERSION_CHANGED')
        if actor in {current['maker'],*[x['submitted_by'] for x in current['media']]}: raise PermissionError('HOSTED_PUBLICATION_MAKER_CHECKER_REQUIRED')
        if previous and (previous.decision, previous.manifest_hash, previous.reviewer_id, previous.evidence_reference) == (decision, fingerprint, actor, reference.strip()):
            return {'publication_review_id': previous.publication_review_id, 'decision': previous.decision, 'manifest_hash': fingerprint}
        if body.get('expected_review_id') != (previous.publication_review_id if previous else None):
            raise ValueError('HOSTED_PUBLICATION_REVIEW_CHANGED')
        stamp = now()
        if previous:
            from datetime import timedelta
            from go_hotel.services.hosted_content_acceptance import aware
            stamp = max(stamp, aware(previous.decided_at) + timedelta(microseconds=1))
        row = m.HostedPublicationReviewRow(publication_review_id=ident('hpr'), hosted_hotel_id=hotel_id,
            manifest_json=current, manifest_hash=fingerprint, reviewer_id=actor, binding_hash=binding_hash(binding),
            decision=decision, evidence_reference=reference.strip(), decided_at=stamp)
        session.add(row); session.flush()
        return {'publication_review_id': row.publication_review_id, 'decision': decision,
            'manifest_hash': fingerprint, 'authority_mode': 'ISOLATED_FIXTURE', 'real_hotel_authority_state': 'HOLD_UNVERIFIED'}


def public_original(slug, media_id):
    with SessionLocal() as session:
        hotel = session.scalar(select(m.HostedDirectHotelRow).where(
            m.HostedDirectHotelRow.page_slug == slug, m.HostedDirectHotelRow.state == 'PUBLISHED_REQUEST_ONLY'))
        if not hotel: raise ValueError('DIRECT_PAGE_NOT_PUBLISHED')
        approved = require_publication(session, hotel.hosted_hotel_id)
        if media_id not in {x['media_asset_id'] for x in approved.manifest_json['media']}:
            raise ValueError('HOSTED_MEDIA_NOT_FOUND')
        return original(session.get(m.HostedMediaAssetRow, media_id))[:2]
