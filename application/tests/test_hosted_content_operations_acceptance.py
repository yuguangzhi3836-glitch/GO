import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HostedDirectHotelRow,HostedDirectInventoryPoolRow
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service as booking
from go_hotel.services.aoluguya_inventory import configure_aoluguya_legacy_fixture as configure_aoluguya
from go_hotel.services.hosted_content_acceptance import hosted_content_acceptance_service as svc
from test_c01_hosted_content_authority import setup_authority, approval_body

def setup_hotel():
 booking.create_hotel({'supplier_name':'哈尔滨敖麓谷雅酒店','page_slug':'aoluguya-harbin'},'admin')
 configure_aoluguya()
 with SessionLocal() as s:return s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug=='aoluguya-harbin')).hosted_hotel_id

def test_snapshot_preserves_pending_source_and_is_versioned(monkeypatch):
 hotel_id=setup_hotel();maker,_,_=setup_authority(hotel_id,monkeypatch);a=svc.snapshot(hotel_id,maker);b=svc.snapshot(hotel_id,maker)
 assert a['source_status']=='PUBLIC_FACTS_PENDING_HOTEL_CONFIRMATION' and b['version']==2 and len(b['content_hash'])==64

def test_only_hotel_authorized_operator_can_approve_with_evidence(monkeypatch):
 hotel_id=setup_hotel();maker,checker,_=setup_authority(hotel_id,monkeypatch);snap=svc.snapshot(hotel_id,maker)
 with pytest.raises(PermissionError,match='AUTHENTICATED_PRINCIPAL'):svc.approve(snap['content_snapshot_id'],{'approver_role':'HOTEL_AUTHORIZED_OPERATOR','decision':'APPROVE','evidence_reference':'ev'},'admin')
 with pytest.raises(ValueError,match='DECISION_AND_EVIDENCE_REQUIRED'):svc.approve(snap['content_snapshot_id'],{'decision':'APPROVE'},checker)

def test_non_hotel_owned_media_is_rejected():
 hotel_id=setup_hotel()
 with pytest.raises(ValueError,match='HOTEL_OWNED_MEDIA_RIGHTS_EVIDENCE_REQUIRED'):svc.media(hotel_id,{'asset_role':'HERO','storage_reference':'ctrip-screenshot','rights_owner':'携程','rights_evidence_reference':'share-link'},'admin')

def test_actual_gate_remains_blocked_without_owned_media(monkeypatch):
 hotel_id=setup_hotel();maker,checker,_=setup_authority(hotel_id,monkeypatch);snap=svc.snapshot(hotel_id,maker);svc.approve(snap['content_snapshot_id'],approval_body(snap),checker)
 gate=svc.gate(hotel_id)
 assert gate['state']=='BLOCKED_PENDING_CONTENT_AND_MEDIA' and 'HOTEL_OWNED_HERO_IMAGE_REQUIRED' in gate['blockers'] and len(gate['missing_room_images'])==5 and gate['production_live'] is False

def test_gate_contract_opens_only_after_complete_rights_verified_test_fixture(monkeypatch):
 hotel_id=setup_hotel();maker,checker,_=setup_authority(hotel_id,monkeypatch);snap=svc.snapshot(hotel_id,maker);svc.approve(snap['content_snapshot_id'],approval_body(snap),checker)
 common={'rights_owner':'哈尔滨敖麓谷雅酒店','rights_evidence_reference':'test://hotel-media-license'}
 svc.media(hotel_id,{**common,'asset_role':'HERO','storage_reference':'test://owned/hero.jpg'},'hotel')
 with SessionLocal() as s:keys=[x.physical_room_key for x in s.scalars(select(HostedDirectInventoryPoolRow).where(HostedDirectInventoryPoolRow.hosted_hotel_id==hotel_id)).all()]
 for key in keys:svc.media(hotel_id,{**common,'asset_role':'ROOM','physical_room_key':key,'storage_reference':f'test://owned/{key}.jpg'},'hotel')
 gate=svc.gate(hotel_id)
 assert gate['state']=='OPERATIONS_ACCEPTED' and gate['blockers']==[] and gate['payment_live'] is False and gate['production_live'] is False
