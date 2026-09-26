"""Explicit isolated provisioning for Hosted acceptance; never a runtime bypass."""
import hashlib
import io
import uuid
from datetime import date, timedelta
from pathlib import Path
from PIL import Image
from sqlalchemy import select
from go_hotel.db import models as m
from go_hotel.db.session import SessionLocal
from go_hotel.security.service import identity_service
from go_hotel.security.mfa import totp
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service as booking, ident, now
from go_hotel.services.hosted_reservation_operations import hosted_reservation_operations_service as ops
from go_hotel.services.hosted_content_acceptance import hosted_content_acceptance_service as content
from go_hotel.services.hosted_operation_authority import ROOT_ROLE, ROOT_SOURCE
from go_hotel.services import hosted_publication as publication, hosted_fare_rules as fare

RULES = {'fare_family':'ISOLATED ACCEPTANCE','timezone':'Asia/Shanghai','check_in_hour':14,
    'cooling_off_minutes':30,'cancellation_tiers':[{'min_hours':0,'fee_basis_points':0}],
    'change_allowed':True,'change_fee_minor':0,'stay_credit_enabled':True,'stay_credit_days':365,
    'stay_credit_scope':'PROPERTY_ONLY','no_show_grace_hours':10,'no_show_fee_basis_points':0}


def identity(label, roles=None, consumer=False):
    name = label + '-' + uuid.uuid4().hex[:10]
    password = 'isolated-test-password-not-for-deployment'
    identity_service.ensure_user(name, password, 'CONSUMER' if consumer else 'GO_ADMIN', None,
                                 ['CONSUMER'] if consumer else (roles or ['GO_GOVERNANCE']))
    if consumer:
        token = identity_service.login(name, password)['access_token']
    else:
        enrollment = identity_service.begin_admin_mfa_enrollment(name, password)
        token = identity_service.confirm_admin_mfa_enrollment(enrollment['enrollment_token'], totp(enrollment['secret']))['access_token']
    return identity_service.authenticate(token), {'Authorization':'Bearer ' + token}


def provision(hotel_id, principal, content_role=True):
    with SessionLocal.begin() as s:
        for role, source in [(ROOT_ROLE, ROOT_SOURCE)] + ([('HOTEL_CONTENT_APPROVER','isolated://hosted-content-authority/v1')] if content_role else []):
            existing=s.scalar(select(m.HostedStaffRoleRow).where(m.HostedStaffRoleRow.hosted_hotel_id==hotel_id,
                m.HostedStaffRoleRow.staff_id==principal.user_id,m.HostedStaffRoleRow.role==role))
            if not existing:s.add(m.HostedStaffRoleRow(staff_role_id=ident('fixture'),hosted_hotel_id=hotel_id,
                staff_id=principal.user_id,role=role,state='ACTIVE',evidence_reference=source,created_at=now()))


def enable_mode(monkeypatch, root):
    monkeypatch.setenv('GO_HOSTED_CONTENT_AUTHORITY_MODE','ISOLATED_FIXTURE')
    monkeypatch.setenv('GO_HOSTED_OPERATIONS_AUTHORITY_MODE','ISOLATED_FIXTURE')
    monkeypatch.setenv('GO_HOSTED_ISOLATED_MEDIA_ROOT',str(root))
    root.mkdir(parents=True,exist_ok=True)


def prepare_publication(hotel_id, maker, checker, root, *, add_rules=True):
    """Create actual approved content, stored bytes and independent review rows."""
    provision(hotel_id,maker);provision(hotel_id,checker)
    buffer=io.BytesIO();Image.new('RGB',(1280,720),(34,55,89)).save(buffer,format='PNG')
    raw=buffer.getvalue();sha=hashlib.sha256(raw).hexdigest();Path(root,sha+'.png').write_bytes(raw)
    with SessionLocal.begin() as s:
        pools=list(s.scalars(select(m.HostedDirectInventoryPoolRow).where(m.HostedDirectInventoryPoolRow.hosted_hotel_id==hotel_id)))
        rooms=[p.physical_room_key for p in pools]
        for pool in pools:
            pool.room_details_json={**(pool.room_details_json or {}),'max_occupancy':3}
        offers=list(s.scalars(select(m.HostedDirectRoomOfferRow.hosted_offer_id).where(m.HostedDirectRoomOfferRow.hosted_hotel_id==hotel_id,m.HostedDirectRoomOfferRow.state=='ACTIVE')))
    if add_rules:
        for offer in offers:fare.publish(offer,RULES,'isolated://fare-rule',maker.user_id)
    with SessionLocal() as s:
        existing=list(s.scalars(select(m.HostedMediaAssetRow).where(m.HostedMediaAssetRow.hosted_hotel_id==hotel_id)))
    for role,room in [('HERO',None)]+[('ROOM',x) for x in rooms]:
        if not any(x.asset_role==role and x.physical_room_key==room and x.storage_reference=='isolated-media://'+sha+'.png' for x in existing):
            content.media(hotel_id,{'asset_role':role,**({'physical_room_key':room} if room else {}),
                'storage_reference':'isolated-media://'+sha+'.png','rights_owner':'哈尔滨敖麓谷雅酒店',
                'rights_evidence_reference':'isolated://synthetic-original'},maker)
    snap=content.snapshot(hotel_id,maker)
    content.approve(snap['content_snapshot_id'],{'decision':'APPROVE','evidence_reference':'isolated://content-review','expected_content_hash':snap['content_hash']},checker)
    before=publication.preview(hotel_id,maker)
    with SessionLocal() as s:previous=publication.latest(s,hotel_id);prior_id=previous.publication_review_id if previous else None
    return publication.review(hotel_id,{'decision':'APPROVE','evidence_reference':'isolated://publication-review',
        'expected_manifest_hash':before['manifest_hash'],'expected_review_id':prior_id},checker)


def hotel_fixture(monkeypatch, root, *, ready=False):
    enable_mode(monkeypatch,root)
    maker,maker_headers=identity('maker');checker,checker_headers=identity('checker')
    customer,customer_headers=identity('customer',consumer=True)
    with SessionLocal() as s:exists=s.scalar(select(m.HostedDirectHotelRow).where(m.HostedDirectHotelRow.page_slug=='aoluguya-harbin'))
    slug='acceptance-'+uuid.uuid4().hex[:10] if exists else 'aoluguya-harbin'
    h=booking.create_hotel({'supplier_name':'哈尔滨敖麓谷雅酒店','page_slug':slug,'contact':{'inventory_data_mode':'SIMULATION'}},'fixture')['hosted_hotel_id']
    o=booking.upsert_offer(h,{'room_name':'Synthetic room','rate_name':'Synthetic rate','price_minor':50000,
        'inventory':5,'cancellation_policy':'Free isolated cancellation'},'fixture')['hosted_offer_id']
    pool,variant=ident('pool'),ident('rate')
    with SessionLocal.begin() as s:
        s.add(m.HostedDirectInventoryPoolRow(inventory_pool_id=pool,hosted_hotel_id=h,physical_room_key='SYNTHETIC',
            physical_room_name='Synthetic room',room_details_json={'max_occupancy':3},capacity_total=5,capacity_available=5,updated_at=now()))
        s.add(m.HostedDirectRateVariantRow(rate_variant_id=variant,inventory_pool_id=pool,hosted_offer_id=o,
            breakfast_count=0,benefits_json=[],payment_mode='CONTRACT_SIMULATOR',state='ACTIVE'))
    provision(h,maker);provision(h,checker)
    day=date.today()+timedelta(days=2);end=day+timedelta(days=1)
    ops.bootstrap_calendar(h,{'start_date':day.isoformat(),'end_date':end.isoformat()})
    body={'hosted_offer_id':o,'check_in':day.isoformat(),'check_out':end.isoformat(),
          'guest_name':'SYNTHETIC GUEST','guest_contact':'synthetic@example.invalid'}
    if ready:
        prepare_publication(h,maker,checker,root)
        booking.publish(h,maker)
        with SessionLocal() as s:
            body['expected_fare_rule_hash']=s.scalar(select(m.HostedFareRuleVersionRow).where(m.HostedFareRuleVersionRow.hosted_offer_id==o).order_by(m.HostedFareRuleVersionRow.version.desc())).rule_hash
    return dict(hotel=h,offer=o,pool=pool,variant=variant,slug=slug,day=day,end=end,body=body,
        maker=maker,checker=checker,customer=customer,maker_headers=maker_headers,
        checker_headers=checker_headers,customer_headers=customer_headers,root=root)


def legacy_publication(hotel_id, *, add_rules=True):
    """Explicit upgrade of a legacy TEST fixture, never called by a business API."""
    import os,tempfile
    from go_hotel.core.config import settings
    assert settings.app_env.lower() in {'local','test','demo'}
    root=Path(tempfile.gettempdir())/'go-isolated-publication-test-objects'
    class Environment:
        def setenv(self,key,value):os.environ[key]=value
    enable_mode(Environment(),root)
    maker,_=identity('fixture-maker');checker,_=identity('fixture-checker')
    with SessionLocal.begin() as s:
        pool=s.scalar(select(m.HostedDirectInventoryPoolRow).where(m.HostedDirectInventoryPoolRow.hosted_hotel_id==hotel_id))
        if not pool:
            s.add(m.HostedDirectInventoryPoolRow(inventory_pool_id=ident('fixture-pool'),hosted_hotel_id=hotel_id,
                physical_room_key='LEGACY_TEST_ROOM',physical_room_name='Legacy synthetic room',
                room_details_json={'max_occupancy':3},capacity_total=0,capacity_available=0,updated_at=now()))
    prepare_publication(hotel_id,maker,checker,root,add_rules=add_rules)
    booking.publish(hotel_id,maker)
    return maker,checker


def fare_hash(offer_id):
    with SessionLocal() as s:
        row=s.scalar(select(m.HostedFareRuleVersionRow).where(m.HostedFareRuleVersionRow.hosted_offer_id==offer_id).order_by(m.HostedFareRuleVersionRow.version.desc()))
        return row.rule_hash if row else None


def register_isolated_rooms(hotel_id, offer_id, references):
    """Explicit synthetic room ownership; never a runtime registration bypass."""
    from go_hotel.core.config import settings
    assert settings.app_env.lower() in {'local', 'test', 'demo'}
    with SessionLocal.begin() as s:
        hotel=s.get(m.HostedDirectHotelRow,hotel_id)
        hotel.contact_json={**(hotel.contact_json or {}),'inventory_data_mode':'SIMULATION'}
        variant=s.scalar(select(m.HostedDirectRateVariantRow).where(m.HostedDirectRateVariantRow.hosted_offer_id==offer_id))
        pool=s.get(m.HostedDirectInventoryPoolRow,variant.inventory_pool_id) if variant else s.scalar(
            select(m.HostedDirectInventoryPoolRow).where(m.HostedDirectInventoryPoolRow.hosted_hotel_id==hotel_id))
        assert pool and pool.hosted_hotel_id==hotel_id
        if variant is None:
            s.add(m.HostedDirectRateVariantRow(rate_variant_id=ident('fixture-rate'),inventory_pool_id=pool.inventory_pool_id,
                hosted_offer_id=offer_id,breakfast_count=0,benefits_json=[],payment_mode='CONTRACT_SIMULATOR',state='ACTIVE'))
        pool.room_details_json={**(pool.room_details_json or {}),'room_registry':{
            'version':1,'source_state':'ISOLATED_FIXTURE','source_reference':'isolated://explicit-room-registry',
            'rooms':[{'room_reference':ref,'state':'ACTIVE'} for ref in references]}}
