"""Official room facts, independent from supplier-managed prices and inventory."""
from datetime import date, timedelta
import json
from pathlib import Path

from sqlalchemy import select

from go_hotel.core.config import settings
from go_hotel.db.models import (HostedDirectHotelRow, HostedDirectInventoryPoolRow,
    HostedDirectRoomOfferRow, HostedDirectRateVariantRow)
from go_hotel.db.session import SessionLocal
from go_hotel.services.hosted_direct_booking import ident, now

DATA = Path(__file__).parents[1] / 'data' / 'aoluguya'


def official_catalog():
    catalog = json.loads((DATA / 'rooms.json').read_text(encoding='utf-8'))
    catalog['rooms'].sort(key=lambda r: (next(x['range']['min'] for x in r['floor_size'] if x['unit']=='SQUARE_METERS'), r['name']))
    return catalog


def configure_official_hotel():
    """Import official facts without inventing availability, prices or policies."""
    catalog = official_catalog()
    with SessionLocal.begin() as s:
        hotel = s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug=='aoluguya-harbin').with_for_update())
        if hotel is None:
            raise ValueError('AOLUGUYA_HOSTED_HOTEL_REQUIRED')
        # Preserve operational provenance, never promote old OTA policy text to official facts.
        operational_keys = {'environment_marker', 'inventory_status', 'quote_status',
            'inventory_data_mode', 'payment_status', 'publication_scope', 'official_rate_map'}
        operational = {k:v for k,v in (hotel.contact_json or {}).items()
            if k in operational_keys or k.startswith('supply_truth_')}
        hotel.contact_json = {**operational,
            'address':'黑龙江省哈尔滨市松北区创新三路800号',
            'reservation_phone':'+86 451 8880 0808',
            'front_desk_phone':'+86 451 8880 0808',
            'source_refs':[catalog['source_url']],
            'content_status':'OFFICIAL_FACTS_CAPTURED',
            'official_room_count':catalog['official_room_count']}
        # Retire unmatched legacy offers from sale, retaining historical orders.
        existing = s.scalars(select(HostedDirectInventoryPoolRow).where(HostedDirectInventoryPoolRow.hosted_hotel_id==hotel.hosted_hotel_id)).all()
        codes = {r['room_code'] for r in catalog['rooms']}
        for pool in existing:
            if pool.physical_room_key not in codes:
                variants = s.scalars(select(HostedDirectRateVariantRow).where(HostedDirectRateVariantRow.inventory_pool_id==pool.inventory_pool_id)).all()
                for variant in variants:
                    variant.state='RETIRED'
                    offer=s.get(HostedDirectRoomOfferRow,variant.hosted_offer_id)
                    if offer:offer.state='RETIRED'
        for room in catalog['rooms']:
            pool=next((p for p in existing if p.physical_room_key==room['room_code']),None)
            if pool is None:
                pool=HostedDirectInventoryPoolRow(inventory_pool_id=ident('hip'),hosted_hotel_id=hotel.hosted_hotel_id,physical_room_key=room['room_code'],physical_room_name=room['name'],room_details_json={},capacity_total=0,capacity_available=0,updated_at=now())
                s.add(pool)
            pool.physical_room_name=room['name']
            pool.room_details_json={**room,'source_url':catalog['source_url'],'source_sha256':catalog['source_sha256']}
            pool.updated_at=now()
        hotel.updated_at=now()
        return {'hosted_hotel_id':hotel.hosted_hotel_id,'physical_room_pools':17,'content_status':'OFFICIAL_FACTS_CAPTURED','inventory_mode':'SUPPLIER_CONFIGURATION_REQUIRED','payment_live':False}


def seed_demo_inventory(hotel_id, start_date=None, days=90):
    """Explicit isolated demonstration data; forbidden outside local/test/demo."""
    if settings.app_env.lower() not in {'local','test','demo'}:
        raise ValueError('DEMO_INVENTORY_FORBIDDEN_IN_THIS_ENVIRONMENT')
    start=date.fromisoformat(start_date) if start_date else date.today()
    if not 1<=days<=365:raise ValueError('DEMO_DAY_RANGE_INVALID')
    with SessionLocal.begin() as s:
        hotel=s.get(HostedDirectHotelRow,hotel_id)
        if hotel is None:raise ValueError('HOSTED_HOTEL_NOT_FOUND')
        pools=s.scalars(select(HostedDirectInventoryPoolRow).where(HostedDirectInventoryPoolRow.hosted_hotel_id==hotel_id)).all()
        for pool in pools:
            if not pool.room_details_json.get('official_id'):continue
            existing=s.scalar(select(HostedDirectRateVariantRow).where(HostedDirectRateVariantRow.inventory_pool_id==pool.inventory_pool_id))
            if existing:continue
            pool.capacity_total=pool.capacity_available=8
            area=next(x['range']['min'] for x in pool.room_details_json['floor_size'] if x['unit']=='SQUARE_METERS')
            for breakfast in (0,2):
                price=(600+area*5+breakfast*50)*100
                offer=HostedDirectRoomOfferRow(hosted_offer_id=ident('hdo'),hosted_hotel_id=hotel_id,room_name=pool.physical_room_name,rate_name='测试·'+('含双早' if breakfast else '仅客房'),price_minor=price,currency='CNY',inventory=8,cancellation_policy='测试规则：酒店确认前可取消',state='ACTIVE',updated_at=now())
                s.add(offer);s.flush()
                s.add(HostedDirectRateVariantRow(rate_variant_id=ident('hrv'),inventory_pool_id=pool.inventory_pool_id,hosted_offer_id=offer.hosted_offer_id,breakfast_count=breakfast,benefits_json=[],payment_mode='CONTRACT_SIMULATOR',state='ACTIVE'))
        hotel.contact_json={**hotel.contact_json,'inventory_data_mode':'SIMULATION'}
        hotel.state='PUBLISHED_REQUEST_ONLY'
    from go_hotel.services.hosted_reservation_operations import hosted_reservation_operations_service
    return hosted_reservation_operations_service.bootstrap_calendar(hotel_id,{'start_date':start.isoformat(),'end_date':(start+timedelta(days=days-1)).isoformat()})
