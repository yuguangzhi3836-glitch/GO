#!/usr/bin/env python3
"""Controlled, idempotent AOLUGUYA Hosted Direct bootstrap for STAGING only.

No Alembic changes. No OTA benchmark is persisted as live inventory/official price.
Creates clearly-labelled draft test offers; publication requires independent review.
"""
import argparse, json, os
from sqlalchemy import select, delete
from go_hotel.core.config import settings
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    HostedDirectHotelRow, HostedDirectRoomOfferRow, HostedDirectPaymentReadinessRow,
    HostedDirectInventoryPoolRow, HostedDirectRateVariantRow, HostedDirectReservationRow,
)
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service as booking, now
from go_hotel.services.aoluguya_inventory import configure_aoluguya_legacy_fixture as configure_aoluguya

SLUG='aoluguya-harbin'
SUPPLIER='哈尔滨敖麓谷雅酒店'
TEST_MARKER='STAGING_TEST_NOT_OFFICIAL'
STAGING_RATE_PREFIX='Staging测试｜'
EXPECTED_POOL_COUNT=5
EXPECTED_OFFER_COUNT=9

def require_staging():
    env=(os.getenv('APP_ENV') or settings.app_env or '').strip().lower()
    if env not in {'staging','stage','hk-staging','hong-kong-staging'}:
        raise SystemExit(f'REFUSED_NON_STAGING_ENV: APP_ENV={env!r}')

def hotel(s): return s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug==SLUG))

def expected_bootstrap_graph(s,h,allow_unlabelled_initial=False):
    """Return only the known R8.2 test graph; never mutate an unexpected graph."""
    pools=s.scalars(select(HostedDirectInventoryPoolRow).where(HostedDirectInventoryPoolRow.hosted_hotel_id==h.hosted_hotel_id)).all()
    offers=s.scalars(select(HostedDirectRoomOfferRow).where(HostedDirectRoomOfferRow.hosted_hotel_id==h.hosted_hotel_id)).all()
    if len(pools)!=EXPECTED_POOL_COUNT or len(offers)!=EXPECTED_OFFER_COUNT:
        raise SystemExit('REFUSED_UNEXPECTED_BOOTSTRAP_GRAPH')
    labelled=all(o.rate_name.startswith(STAGING_RATE_PREFIX) for o in offers)
    initial=allow_unlabelled_initial and all(not o.rate_name.startswith(STAGING_RATE_PREFIX) for o in offers) and all(o.state=='ACTIVE' for o in offers)
    if not labelled and not initial:
        raise SystemExit('REFUSED_UNLABELLED_BOOTSTRAP_OFFERS')
    return offers,initial

def inspect():
    with SessionLocal() as s:
        h=hotel(s)
        if not h:return {'slug':SLUG,'exists':False}
        offers=s.scalars(select(HostedDirectRoomOfferRow).where(HostedDirectRoomOfferRow.hosted_hotel_id==h.hosted_hotel_id)).all()
        pools=s.scalars(select(HostedDirectInventoryPoolRow).where(HostedDirectInventoryPoolRow.hosted_hotel_id==h.hosted_hotel_id)).all()
        pay=s.get(HostedDirectPaymentReadinessRow,h.hosted_hotel_id)
        return {'slug':SLUG,'exists':True,'hotel_id':h.hosted_hotel_id,'state':h.state,'test_marker':h.contact_json.get('environment_marker'),'offers':len(offers),'active_offers':sum(x.state=='ACTIVE' for x in offers),'pools':len(pools),'payment_available':False,'payment_state':pay.application_state if pay else None}

def create():
    require_staging()
    # Safety boundary: an existing slug may only be mutated when it is already this
    # controlled Staging bootstrap graph. Never adopt a non-bootstrap hotel silently.
    with SessionLocal() as s:
        h=hotel(s)
        if h and (h.contact_json or {}).get('environment_marker') != TEST_MARKER:
            raise SystemExit('REFUSED_EXISTING_NON_BOOTSTRAP_HOTEL')
        if h:
            has_pool=s.scalar(select(HostedDirectInventoryPoolRow.inventory_pool_id).where(HostedDirectInventoryPoolRow.hosted_hotel_id==h.hosted_hotel_id).limit(1)) is not None
            has_offer=s.scalar(select(HostedDirectRoomOfferRow.hosted_offer_id).where(HostedDirectRoomOfferRow.hosted_hotel_id==h.hosted_hotel_id).limit(1)) is not None
            if has_pool or has_offer:
                # Refuse before configure_aoluguya() writes any hotel metadata.
                expected_bootstrap_graph(s,h)
    if not h:
        booking.create_hotel({'supplier_name':SUPPLIER,'page_slug':SLUG,'contact':{'environment_marker':TEST_MARKER}},'staging-bootstrap')

    result=configure_aoluguya()

    # Relabel and restore only this bootstrap graph. configure_aoluguya() is idempotent
    # when pools exist, so create must explicitly recover offers after a prior disable.
    with SessionLocal() as s:
        h=hotel(s)
        if not h:
            raise SystemExit('BOOTSTRAP_HOTEL_MISSING_AFTER_CONFIGURE')
        c=dict(h.contact_json or {})
        c.update({
            'environment_marker':TEST_MARKER,
            'inventory_status':'STAGING_TEST_INVENTORY',
            'quote_status':'STAGING_TEST_QUOTE_NOT_OFFICIAL',
            'payment_status':'NOT_CONNECTED',
            'publication_scope':'RESERVATION_REQUEST_ONLY',
        })
        h.contact_json=c
        h.state='DRAFT'
        h.updated_at=now()
        offers,initial=expected_bootstrap_graph(s,h,allow_unlabelled_initial=True)
        for o in offers:
            o.state='ACTIVE'
            o.updated_at=now()
            if initial:
                o.rate_name=STAGING_RATE_PREFIX+o.rate_name
        s.commit()
    return {'action':'create_or_confirm','configured':result,'status':inspect()}

def disable():
    require_staging()
    with SessionLocal() as s:
        h=hotel(s)
        if not h:return {'action':'disable','changed':False,'reason':'NOT_FOUND'}
        if (h.contact_json or {}).get('environment_marker')!=TEST_MARKER:
            raise SystemExit('REFUSED_NON_BOOTSTRAP_HOTEL')
        offers,_=expected_bootstrap_graph(s,h)
        h.state='DRAFT';h.updated_at=now()
        for o in offers:o.state='INACTIVE';o.updated_at=now()
        s.commit()
    return {'action':'disable','changed':True,'status':inspect()}

def rollback():
    """Delete only this bootstrap's unused test graph; refuse if reservations exist."""
    require_staging()
    with SessionLocal() as s:
        h=hotel(s)
        if not h:return {'action':'rollback','changed':False,'reason':'NOT_FOUND'}
        if (h.contact_json or {}).get('environment_marker')!=TEST_MARKER:raise SystemExit('REFUSED_NON_BOOTSTRAP_HOTEL')
        expected_bootstrap_graph(s,h)
        offer_ids=list(s.scalars(select(HostedDirectRoomOfferRow.hosted_offer_id).where(HostedDirectRoomOfferRow.hosted_hotel_id==h.hosted_hotel_id)))
        if offer_ids and s.scalar(select(HostedDirectReservationRow).where(HostedDirectReservationRow.hosted_offer_id.in_(offer_ids)).limit(1)):
            raise SystemExit('REFUSED_ROLLBACK_RESERVATIONS_EXIST: use disable')
        pool_ids=list(s.scalars(select(HostedDirectInventoryPoolRow.inventory_pool_id).where(HostedDirectInventoryPoolRow.hosted_hotel_id==h.hosted_hotel_id)))
        if offer_ids:s.execute(delete(HostedDirectRateVariantRow).where(HostedDirectRateVariantRow.hosted_offer_id.in_(offer_ids)));s.execute(delete(HostedDirectRoomOfferRow).where(HostedDirectRoomOfferRow.hosted_offer_id.in_(offer_ids)))
        if pool_ids:s.execute(delete(HostedDirectInventoryPoolRow).where(HostedDirectInventoryPoolRow.inventory_pool_id.in_(pool_ids)))
        s.execute(delete(HostedDirectPaymentReadinessRow).where(HostedDirectPaymentReadinessRow.hosted_hotel_id==h.hosted_hotel_id));s.delete(h);s.commit()
    return {'action':'rollback','changed':True,'status':inspect()}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['inspect','create','disable','rollback']);a=p.parse_args()
    print(json.dumps({'inspect':inspect,'create':create,'disable':disable,'rollback':rollback}[a.action](),ensure_ascii=False,indent=2))
