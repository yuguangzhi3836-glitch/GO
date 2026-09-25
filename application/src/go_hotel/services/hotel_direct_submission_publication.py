"""Reviewed direct originals join the existing canonical page/version history.

No cached approval grants ongoing access: page and original reads resolve the
persisted review again, including current ownership, inventory and image rights.
"""
from copy import deepcopy
from urllib.parse import quote
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.services.hotel_original_verification_scope import original_verification_scope
from go_hotel.db.models import HotelCanonicalProfileRow, HotelAutoPageVersionRow
from go_hotel.services import catalog_scope


def _reviews():
    from go_hotel.services.hotel_direct_submission_review import hotel_direct_submission_review_service
    return hotel_direct_submission_review_service


def resolve_catalog(catalog, hotel_id):
    marker = (catalog or {}).get('direct_submission')
    if not isinstance(marker, dict) or set(marker) != {'schema','review_id','supplier_id','property_id','manifest_sha256'}:
        raise ValueError('DIRECT_PUBLICATION_REFERENCE_INVALID')
    if marker['schema'] != 'HOTEL_DIRECT_SUBMISSION_V1':
        raise ValueError('DIRECT_PUBLICATION_REFERENCE_INVALID')
    resolved = _reviews().resolve(marker['review_id'], marker['supplier_id'], marker['property_id'])
    manifest = resolved['manifest']
    if resolved['manifest_sha256'] != marker['manifest_sha256'] or manifest['identity']['canonical_hotel_id'] != hotel_id:
        raise ValueError('DIRECT_PUBLICATION_REVIEW_MISMATCH')
    current_ids = [r.get('room_type_id') for r in (catalog or {}).get('rooms', []) if isinstance(r, dict)]
    if len(current_ids) != len(set(current_ids)) or set(current_ids) != set(manifest['inventory']['canonical_room_ids']):
        raise ValueError('DIRECT_PUBLICATION_ROOM_INVENTORY_CHANGED')
    return resolved


def direct_media(catalog, hotel_id):
    reviewed = resolve_catalog(catalog, hotel_id)
    grouped = {'hero':[], 'gallery':[], 'rooms':{}, 'dining':[], 'facility':[], 'meeting':[], 'poi':[]}
    for asset in reviewed['manifest']['assets']:
        public = {key:asset[key] for key in ('asset_id','width','height','mime_type')}
        public.update(source_type='HOTEL_DIRECT_UPLOAD',
            url='/v1/hotel-pages/direct-submissions/'+quote(reviewed['review_id'], safe='')+'/media/'+quote(asset['asset_id'], safe=''))
        role = asset['role']
        if role == 'ROOM': grouped['rooms'].setdefault(asset['canonical_room_id'], []).append(public)
        else: grouped[{'HERO':'hero','DINING':'dining','MEETING':'meeting','POI':'poi','FACILITY':'facility'}.get(role,'gallery')].append(public)
    return grouped


class HotelDirectSubmissionPublicationService:
    def publish(self, review_id, supplier_id, property_id, actor):
        resolved = _reviews().resolve(review_id, supplier_id, property_id)
        hotel_id = resolved['manifest']['identity']['canonical_hotel_id']
        with SessionLocal() as session:
            catalog_scope.require_hotel(session, hotel_id)
            profile = session.get(HotelCanonicalProfileRow, hotel_id)
            if profile is None: raise ValueError('CANONICAL_PROFILE_NOT_FOUND')
            catalog = deepcopy(profile.canonical_json or {})
            provenance = deepcopy(profile.field_provenance_json or {})
        marker = {'schema':'HOTEL_DIRECT_SUBMISSION_V1','review_id':review_id,
                  'supplier_id':supplier_id,'property_id':property_id,'manifest_sha256':resolved['manifest_sha256']}
        catalog['direct_submission'] = marker
        from go_hotel.services.hotel_catalog_quality import quality
        report = quality(catalog, provenance, [], hotel_id=hotel_id, verify_asset=None)
        if not report['passed']: raise ValueError('HOTEL_CATALOG_QUALITY_HOLD')
        from go_hotel.services.hotel_autopage_factory import hotel_autopage_factory_service as factory
        # Only the review pointer is a new fact. Keep existing hotel/room facts
        # and their source provenance; never relabel old facts as direct uploads.
        result = factory.ingest({'source_key':'hotel-direct-reviewed:'+supplier_id,
            'source_type':'HOTEL_OFFICIAL_SUBMISSION','external_hotel_id':property_id,
            'canonical_hotel_id':hotel_id,'rights_status':'HOTEL_SUBMITTED',
            'confidence_bps':10000,'payload':{'direct_submission':marker}}, actor=actor, require_publishable=True, preserve_current_facts=True)
        page = factory.public_page_by_hotel(hotel_id)
        with SessionLocal() as session:
            profile = session.get(HotelCanonicalProfileRow, hotel_id)
            latest = session.scalar(select(HotelAutoPageVersionRow).where(
                HotelAutoPageVersionRow.hotel_id==hotel_id,
                HotelAutoPageVersionRow.publication_state=='PUBLISHED').order_by(HotelAutoPageVersionRow.version.desc()))
            evidence = ((latest.page_json or {}).get('_catalog_evidence') or {}).get('catalog') if latest else None
            published = profile.page_state == 'PUBLISHED' and ((evidence or {}).get('direct_submission') or {}).get('review_id')==review_id
            if not published: raise ValueError('DIRECT_PUBLICATION_NOT_CURRENT')
        return {'hotel_id':hotel_id,'review_id':review_id,'manifest_sha256':resolved['manifest_sha256'],
                'idempotent':result['idempotent'],'published':published,'page':page}

    @original_verification_scope
    def public_content(self, review_id, asset_id):
        # Find the reference only in an existing currently published canonical
        # page. Approved submissions alone are not public image endpoints.
        with SessionLocal() as session:
            reviewed = _reviews().get(review_id)
            hotel_id = reviewed['manifest']['identity']['canonical_hotel_id']
            profile = session.get(HotelCanonicalProfileRow, hotel_id)
            found = None
            if profile and profile.page_state == 'PUBLISHED':
                version = session.scalar(select(HotelAutoPageVersionRow).where(
                    HotelAutoPageVersionRow.hotel_id==hotel_id,
                    HotelAutoPageVersionRow.publication_state=='PUBLISHED').order_by(HotelAutoPageVersionRow.version.desc()))
                catalog = ((version.page_json or {}).get('_catalog_evidence') or {}).get('catalog') if version else None
                if ((catalog or {}).get('direct_submission') or {}).get('review_id') == review_id:
                    catalog_scope.require_hotel(session, hotel_id)
                    found = (hotel_id, profile.slug, catalog)
        if found is None: raise ValueError('DIRECT_PUBLICATION_NOT_FOUND')
        from go_hotel.services.hotel_autopage_factory import hotel_autopage_factory_service as factory
        factory.public_page(found[1])
        reviewed = resolve_catalog(found[2], found[0])
        if not any(asset['asset_id']==asset_id for asset in reviewed['manifest']['assets']):
            raise ValueError('DIRECT_PUBLICATION_ASSET_NOT_FOUND')
        from go_hotel.services.hotel_partner_media_upload import hotel_partner_media_upload_service as media
        identity = reviewed['manifest']['identity']
        return media.original(identity['supplier_id'], identity['property_id'], asset_id)


hotel_direct_submission_publication_service = HotelDirectSubmissionPublicationService()
