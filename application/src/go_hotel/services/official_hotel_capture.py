"""Bounded official JSON-LD capture, with explicit hotel/room relationships.

This adapter captures the room entries *declared* by the source. It cannot prove
that a site's JSON-LD lists every room type. Independent inventory parity is a
separate gate. Unsupported sites remain incomplete rather than guessed.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from urllib.parse import urldefrag, urljoin, urlsplit

VERSION = 'OFFICIAL_STRUCTURED_CATALOG_V1'
HOTEL_TYPES = {'hotel', 'resort', 'lodgingbusiness'}
ROOM_TYPES = {'hotelroom', 'suite'}


def norm(value):
    return re.sub(r'[^0-9a-z\u4e00-\u9fff]', '', unicodedata.normalize('NFKC', str(value or '')).lower())


def types(node):
    value = node.get('@type', [])
    return {str(x).rstrip('/').split('/')[-1].lower() for x in (value if isinstance(value, list) else [value])}


def items(value):
    return value if isinstance(value, list) else ([] if value is None else [value])


def absolute(value, base):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('OFFICIAL_REFERENCE_REQUIRED')
    result = urljoin(base, value.strip())
    u = urlsplit(result)
    if u.scheme != 'https' or not u.hostname or u.username or u.password:
        raise ValueError('OFFICIAL_HTTPS_REFERENCE_REQUIRED')
    return result


def origin(url):
    u = urlsplit(url)
    return u.scheme, u.hostname, u.port or 443


def nodes(html):
    from .hotel_discovery_orchestrator import _HotelHTMLParser
    parser = _HotelHTMLParser()
    parser.feed(html)
    out = []
    def walk(value, depth=0):
        if depth > 32:
            raise ValueError('OFFICIAL_STRUCTURED_DATA_TOO_DEEP')
        if isinstance(value, dict):
            if '@type' in value or '@id' in value:
                out.append(value)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    walk(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                walk(child, depth + 1)
    for raw in parser.jsonld_parts:
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            continue
        walk(value)
    if len(out) > 4000:
        raise ValueError('OFFICIAL_STRUCTURED_DATA_TOO_LARGE')
    return out


def images(value, base):
    out = []
    for image in items(value):
        raw = image.get('contentUrl') or image.get('url') if isinstance(image, dict) else image
        try:
            resolved = absolute(raw, base)
        except ValueError:
            continue
        if resolved not in out:
            out.append(resolved)
    return out[:30]


def capture_catalog(fetch, url, seed, *, max_pages=32, max_seconds=90):
    """fetch must enforce the application's network policy on every request.

    Only same-origin room references declared by the selected hotel are fetched.
    CDN images are recorded as candidates, with the exact referring room; this
    function neither downloads them nor decides their publication eligibility.
    """
    if not 1 <= max_pages <= 64 or not 1 <= max_seconds <= 120:
        raise ValueError('OFFICIAL_CAPTURE_BUDGET_INVALID')
    start = time.monotonic()
    root = absolute(url, url)
    allowed_origin = origin(root)
    documents = {}
    failures = []

    def read(target):
        target = urldefrag(absolute(target, root))[0]
        if origin(target) != allowed_origin:
            raise ValueError('OFFICIAL_ROOM_CROSS_ORIGIN')
        if target in documents:
            return documents[target]
        remaining = max_seconds - (time.monotonic() - start)
        if len(documents) >= max_pages or remaining <= 0:
            raise ValueError('OFFICIAL_CAPTURE_BUDGET_EXHAUSTED')
        final, html, size, network = fetch(target, timeout_seconds=min(12.0, remaining))
        if origin(final) != allowed_origin:
            raise ValueError('OFFICIAL_REDIRECT_ORIGIN_CHANGED')
        doc = {'url': final, 'sha256': hashlib.sha256(html.encode('utf-8')).hexdigest(),
               'bytes': size, 'nodes': nodes(html), 'network_audit': network}
        documents[target] = doc
        return doc

    doc = read(root)
    candidates = [n for n in doc['nodes'] if types(n) & HOTEL_TYPES and n.get('name')]
    exact = [n for n in candidates if norm(n['name']) == norm(seed.get('name'))]
    # Even on a page containing only one hotel, a mismatching name is not evidence
    # that the caller selected that hotel. Brand aliases require explicit review.
    unique = {json.dumps(n, sort_keys=True, ensure_ascii=False): n for n in exact}
    if len(unique) != 1:
        raise ValueError('OFFICIAL_HOTEL_IDENTITY_NOT_UNIQUE')
    hotel = next(iter(unique.values()))
    official_id = absolute(hotel.get('@id') or hotel.get('url') or root, doc['url'])
    if origin(official_id) != allowed_origin:
        raise ValueError('OFFICIAL_HOTEL_IDENTITY_ORIGIN_MISMATCH')
    from .hotel_discovery_orchestrator import _address
    payload = {'name': hotel['name'], 'address': _address(hotel.get('address')),
               'website': urldefrag(root)[0], 'rooms': [], 'media_candidates': []}
    geo = hotel.get('geo')
    if isinstance(geo, dict):
        payload.update(latitude=geo.get('latitude'), longitude=geo.get('longitude'))
    payload['facilities'] = [str(a['name']) for a in items(hotel.get('amenityFeature'))
                             if isinstance(a, dict) and a.get('name') and a.get('value', True) not in (False, 'false', 0)]
    payload['policies'] = [{'type': kind, 'value': hotel[field]} for field, kind in
                          [('checkinTime', 'CHECK_IN'), ('checkoutTime', 'CHECK_OUT')] if hotel.get(field)]
    for field in ('telephone', 'email'):
        if hotel.get(field):
            payload['phone' if field == 'telephone' else field] = hotel[field]
    for i, image in enumerate(images(hotel.get('image'), doc['url'])):
        payload['media_candidates'].append({'source_url': image, 'source_page_url': doc['url'],
            'source_document_sha256': doc['sha256'], 'role': 'HERO' if i == 0 else 'GALLERY',
            'rights_state': 'RIGHTS_UNKNOWN'})

    declared = []
    for ref in items(hotel.get('containsPlace')):
        if not isinstance(ref, dict):
            failures.append('ROOM_REFERENCE_INVALID')
            continue
        # Non-accommodation places explicitly typed by the hotel are not rooms.
        if types(ref) and not types(ref) & ROOM_TYPES:
            continue
        try:
            rid = absolute(ref.get('@id') or ref.get('url'), doc['url'])
        except ValueError as exc:
            failures.append(str(exc))
            continue
        if rid not in declared:
            declared.append(rid)
    if len(declared) > 200:
        raise ValueError('OFFICIAL_ROOM_CATALOG_TOO_LARGE')
    for rid in declared:
        try:
            if origin(rid) != allowed_origin:
                raise ValueError('OFFICIAL_ROOM_CROSS_ORIGIN')
            room_doc = doc
            matches = [n for n in doc['nodes'] if types(n) & ROOM_TYPES
                       and absolute(n.get('@id') or n.get('url'), doc['url']) == rid]
            if not matches:
                room_doc = read(rid)
                matches = [n for n in room_doc['nodes'] if types(n) & ROOM_TYPES
                           and absolute(n.get('@id') or n.get('url'), room_doc['url']) == rid]
            unique_rooms = {json.dumps(n, sort_keys=True, ensure_ascii=False): n for n in matches}
            if len(unique_rooms) != 1:
                raise ValueError('OFFICIAL_ROOM_IDENTITY_NOT_UNIQUE')
            room = next(iter(unique_rooms.values()))
            parent = room.get('containedInPlace')
            if parent:
                parent_id = parent.get('@id') or parent.get('url') if isinstance(parent, dict) else parent
                if absolute(parent_id, room_doc['url']) != official_id:
                    raise ValueError('OFFICIAL_ROOM_BELONGS_TO_ANOTHER_HOTEL')
            room_id = 'room_' + hashlib.sha256((official_id + '\n' + rid).encode()).hexdigest()[:24]
            image_urls = images(room.get('image'), room_doc['url'])
            captured = {'room_type_id': room_id, 'official_id': rid, 'name': room.get('name'),
                'source_url': room_doc['url'], 'source_document_sha256': room_doc['sha256'],
                'floor_size': room.get('floorSize'), 'bed': room.get('bed'),
                'occupancy': room.get('occupancy'), 'floor_level': room.get('floorLevel'),
                'facilities': room.get('amenityFeature', []), 'official_image_urls': image_urls}
            payload['rooms'].append(captured)
            for image in image_urls:
                payload['media_candidates'].append({'source_url': image, 'source_page_url': room_doc['url'],
                    'source_document_sha256': room_doc['sha256'], 'room_type_id': room_id,
                    'role': 'ROOM', 'rights_state': 'RIGHTS_UNKNOWN'})
        except ValueError as exc:
            failures.append({'official_id': rid, 'code': str(exc)})
    payload['catalog_manifest'] = {
        'extractor_version': VERSION, 'hotel_official_id': official_id,
        'declared_room_ids': declared,
        'captured_room_ids': [r['official_id'] for r in payload['rooms']],
        'declared_catalog_captured': bool(declared) and not failures and len(declared) == len(payload['rooms']),
        # containsPlace need not enumerate all room types. Never turn its length
        # or numberOfRooms (physical room count) into a completeness assertion.
        'full_room_type_inventory_verified': False,
        'failures': failures,
        'documents': [{k: v for k, v in d.items() if k != 'nodes'} for d in documents.values()],
    }
    return payload, {'extractor_version': VERSION, 'pages_fetched': len(documents),
                     'declared_rooms': len(declared), 'captured_rooms': len(payload['rooms']),
                     'seconds': round(time.monotonic() - start, 4)}
