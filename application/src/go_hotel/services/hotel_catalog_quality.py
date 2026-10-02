"""One publication contract for the factory, batch counters and public reads."""
from __future__ import annotations

import math
import re
from urllib.parse import urlsplit

OFFICIAL_SOURCES = {'HOTEL_OFFICIAL_SUBMISSION', 'OFFICIAL_WEBSITE', 'GROUP_OFFICIAL'}
VERSION = 'OFFICIAL_CATALOG_REPLICATION_V1'


def positive(value):
    try:
        return not isinstance(value, bool) and math.isfinite(float(value)) and float(value) > 0
    except (ValueError, TypeError):
        return False


def valid_url(value):
    try:
        u = urlsplit(str(value or ''))
        return u.scheme == 'https' and bool(u.hostname) and not u.username and not u.password
    except ValueError:
        return False


def quality(catalog, provenance, assets, *, hotel_id, verify_asset):
    """Do not accept counts alone, raw URLs, shared CDNs or cached metadata.

    Full source inventory verification must bind the exact declared IDs to a
    separately reviewed source reference. Collector completeness is insufficient.
    """
    c = catalog or {}
    if isinstance(c, dict) and 'direct_submission' in c:
        return direct_submission_quality(c, hotel_id, provenance)
    p = provenance or {}
    invalid={'rule_version':VERSION,'passed':False,'page_eligible':False,'build_state':'NEEDS_ENRICHMENT',
             'reasons':['CATALOG_STRUCTURE_INVALID'],'room_count':0,'declared_room_count':0,
             'room_fact_gaps':[],'room_photo_counts':{},'room_photo_parity':{},'verified_asset_count':0,
             'live_replication_accepted':False}
    if not isinstance(c,dict) or not isinstance(p,dict) or any(not isinstance(v,dict) for v in p.values()):return invalid
    for field in ('rooms','media_candidates'):
        if field in c and (not isinstance(c[field],list) or any(not isinstance(x,dict) for x in c[field])):return invalid
    raw_manifest=c.get('catalog_manifest',{})
    if not isinstance(raw_manifest,dict):return invalid
    for field in ('declared_room_ids','captured_room_ids'):
        value=raw_manifest.get(field,[])
        if not isinstance(value,list) or any(not isinstance(x,str) for x in value):return invalid
    docs=raw_manifest.get('documents',[])
    if not isinstance(docs,list) or any(not isinstance(d,dict) or not isinstance(d.get('url'),str) for d in docs):return invalid
    for room in c.get('rooms',[]):
        if any(room.get(k) is not None and not isinstance(room[k],str) for k in ('room_type_id','official_id','source_url','source_document_sha256')):return invalid
        urls=room.get('official_image_urls',[])
        if not isinstance(urls,list) or any(not valid_url(u) for u in urls):return invalid
    reasons = []
    def require(ok, code):
        if not ok and code not in reasons:
            reasons.append(code)
        return bool(ok)
    for field in ('name', 'address', 'website', 'rooms', 'policies', 'facilities', 'catalog_manifest', 'media_candidates'):
        require(bool(c.get(field)), field.upper() + '_MISSING')
        evidence = p.get(field) or {}
        if c.get(field):
            require(evidence.get('source_type') in OFFICIAL_SOURCES and valid_url(evidence.get('source_url')),
                    field.upper() + '_OFFICIAL_SOURCE_REQUIRED')
            require(evidence.get('conflict_state') != 'REVIEW_REQUIRED', field.upper() + '_CONFLICT')
    require(valid_url(c.get('website')), 'OFFICIAL_WEBSITE_REQUIRED')
    manifest = c.get('catalog_manifest') if isinstance(c.get('catalog_manifest'), dict) else {}
    declared = manifest.get('declared_room_ids')
    captured = manifest.get('captured_room_ids')
    declared = declared if isinstance(declared, list) else []
    captured = captured if isinstance(captured, list) else []
    rooms = c.get('rooms') if isinstance(c.get('rooms'), list) else []
    room_ids = [r.get('official_id') for r in rooms if isinstance(r, dict)]
    stable_ids = [r.get('room_type_id') for r in rooms if isinstance(r, dict)]
    good_ids = bool(declared) and all(isinstance(x, str) and valid_url(x) for x in declared)
    require(good_ids and len(declared) == len(set(declared)), 'DECLARED_ROOM_IDENTITIES_REQUIRED')
    require(bool(rooms) and len(room_ids) == len(rooms) and all(isinstance(x,str) and x for x in room_ids)
            and len(set(room_ids)) == len(room_ids) and all(stable_ids)
            and all(isinstance(x,str) for x in stable_ids) and len(set(stable_ids)) == len(stable_ids), 'ROOM_IDENTITIES_NOT_UNIQUE')
    require(good_ids and all(isinstance(x,str) for x in captured+room_ids) and set(declared) == set(captured) == set(room_ids)
            and manifest.get('declared_catalog_captured') is True and not manifest.get('failures'),
            'DECLARED_ROOM_PARITY_INCOMPLETE')
    verification = manifest.get('inventory_verification') or {}
    require(isinstance(verification, dict)
            and verification.get('kind') in {'HOTEL_CONFIRMED_ROOM_TYPE_INVENTORY', 'OFFICIAL_ROOM_INDEX_REVIEW'}
            and valid_url(verification.get('source_url'))
            and bool(re.fullmatch(r'[0-9a-f]{64}', str(verification.get('source_sha256') or '')))
            and good_ids and verification.get('reviewed_room_ids') == sorted(declared)
            and bool(verification.get('reviewed_by')),
            'FULL_ROOM_TYPE_INVENTORY_NOT_VERIFIED')
    documents = {d.get('url'): d.get('sha256') for d in docs}
    require(isinstance(verification,dict) and documents.get(verification.get('source_url'))==verification.get('source_sha256')
            and bool(verification.get('source_sha256')), 'INVENTORY_REVIEW_DOCUMENT_MISMATCH')
    bound = {}
    photo_parity = {}
    facts_gaps = []
    valid_assets = []
    for asset in assets:
        if asset.get('hotel_id') != hotel_id or not asset.get('publishable') or asset.get('source_type') not in OFFICIAL_SOURCES:
            continue
        if not re.fullmatch(r'[0-9a-f]{64}', str(asset.get('sha256') or '')):
            continue
        try:
            verify_asset(asset['asset_id'])
        except (ValueError, KeyError, OSError):
            continue
        valid_assets.append(asset)
    expected_hero = {x.get('source_url') for x in c.get('media_candidates', [])
                     if isinstance(x, dict) and x.get('role') == 'HERO'}
    require(any(a.get('role') == 'HERO' and a.get('source_url') in expected_hero for a in valid_assets),
            'VERIFIED_OFFICIAL_HERO_MISSING')
    for room in rooms:
        if not isinstance(room, dict):
            continue
        rid = room.get('room_type_id')
        floor = room.get('floor_size')
        occupancy = room.get('occupancy')
        floor_ok = isinstance(floor, dict) and floor.get('unitCode') in {'MTK', 'FTK', 'YDK'} and (
            positive(floor.get('value')) or positive(floor.get('minValue')) and positive(floor.get('maxValue'))
            and float(floor['maxValue']) >= float(floor['minValue']))
        occupancy_ok = isinstance(occupancy, dict) and positive(occupancy.get('maxValue', occupancy.get('value')))
        if not room.get('name') or not floor_ok or not room.get('bed') or not occupancy_ok:
            facts_gaps.append(rid)
        require(valid_url(room.get('source_url')) and documents.get(room.get('source_url')) == room.get('source_document_sha256')
                and bool(re.fullmatch(r'[0-9a-f]{64}', str(room.get('source_document_sha256') or ''))),
                'ROOM_DOCUMENT_EVIDENCE_MISMATCH')
        expected_images = room.get('official_image_urls') or []
        hashes = {a['sha256'] for a in valid_assets if a.get('role') == 'ROOM'
                  and a.get('room_type_id') == rid and a.get('source_url') in expected_images}
        bound[rid] = len(hashes)
        covered={a.get('source_url') for a in valid_assets if a.get('role')=='ROOM'
                 and a.get('room_type_id')==rid and a.get('source_url') in expected_images}
        # Source parity takes precedence over an invented three-photo minimum.
        # If the official room has only two photos, require those two; never fill
        # the third position with an unrelated room or an OTA image.
        photo_parity[rid]=bool(expected_images) and covered==set(expected_images) and len(hashes)>=min(3,len(set(expected_images)))
    require(not facts_gaps, 'ROOM_CORE_FACTS_INCOMPLETE')
    require(bool(photo_parity) and all(photo_parity.values()), 'ROOM_OFFICIAL_PHOTO_PARITY_INCOMPLETE')
    return {'rule_version': VERSION, 'passed': not reasons, 'page_eligible': not reasons,
            'build_state': 'READY' if not reasons else 'NEEDS_ENRICHMENT',
            'reasons': reasons, 'room_count': len(rooms), 'declared_room_count': len(declared),
            'room_fact_gaps': facts_gaps, 'room_photo_counts': bound,
            'room_photo_parity':photo_parity,
            'verified_asset_count': len(valid_assets), 'live_replication_accepted': False}


def direct_submission_quality(catalog, hotel_id, provenance=None):
    """Separate reviewed upload contract; official-web parity stays unchanged."""
    reasons = []
    if not isinstance(provenance or {},dict):
        reasons.append('CATALOG_PROVENANCE_INVALID')
    else:
        for field in ('name','address','rooms','policies','facilities','website','direct_submission'):
            evidence=(provenance or {}).get(field) or {}
            if not isinstance(evidence,dict) or evidence.get('conflict_state')=='REVIEW_REQUIRED':
                reasons.append(field.upper()+'_CONFLICT')
    rooms = catalog.get('rooms') or []
    valid = []
    try:
        from go_hotel.services.hotel_direct_submission_publication import resolve_catalog
        resolved = resolve_catalog(catalog, hotel_id)
        valid = resolved['manifest']['assets']
    except (ValueError, KeyError, TypeError, OSError):
        reasons.append('DIRECT_SUBMISSION_REVIEW_NOT_CURRENT')
    for field in ('name','address','rooms','policies','facilities'):
        if not catalog.get(field): reasons.append(field.upper()+'_MISSING')
    gaps = []
    if not isinstance(rooms,list):
        rooms = []
        reasons.append('ROOM_STRUCTURE_INVALID')
    for room in rooms:
        if not isinstance(room,dict):
            gaps.append(None)
            continue
        floor = room.get('floor_size')
        occupancy = room.get('occupancy')
        floor_ok = isinstance(floor,dict) and floor.get('unitCode') in {'MTK','FTK','YDK'} and (
            positive(floor.get('value')) or positive(floor.get('minValue')) and positive(floor.get('maxValue'))
            and float(floor['maxValue']) >= float(floor['minValue']))
        occupancy_ok = isinstance(occupancy,dict) and positive(occupancy.get('maxValue',occupancy.get('value')))
        if not room.get('name') or not room.get('bed') or not floor_ok or not occupancy_ok:
            gaps.append(room.get('room_type_id'))
    if gaps: reasons.append('ROOM_CORE_FACTS_INCOMPLETE')
    counts = {r.get('room_type_id'):sum(1 for a in valid if a['role']=='ROOM' and a['canonical_room_id']==r.get('room_type_id')) for r in rooms if isinstance(r,dict)}
    return {'rule_version':'HOTEL_DIRECT_SUBMISSION_V1','passed':not reasons,'page_eligible':not reasons,
        'build_state':'READY' if not reasons else 'NEEDS_ENRICHMENT','reasons':reasons,
        'room_count':len(rooms),'declared_room_count':len(rooms),'room_fact_gaps':gaps,
        'room_photo_counts':counts,'room_photo_parity':{k:v>0 for k,v in counts.items()},
        'verified_asset_count':len(valid),'live_replication_accepted':False}
