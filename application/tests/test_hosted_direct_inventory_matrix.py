from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HostedDirectInventoryPoolRow,HostedDirectRateVariantRow
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service as svc
from go_hotel.services.aoluguya_inventory import configure_aoluguya_legacy_fixture as configure_aoluguya
def setup():
 svc.create_hotel({'supplier_name':'哈尔滨敖麓谷雅酒店','page_slug':'aoluguya-harbin'},'admin');return configure_aoluguya()
def test_real_configuration_has_five_independent_pools_and_nine_variants():
 r=setup();assert r['physical_room_pools']==5 and r['rate_variants']==9 and r['content_status']=='PUBLIC_FACTS_PENDING_HOTEL_CONFIRMATION'
def test_public_facts_are_structured_and_configuration_is_idempotent():
 setup();second=configure_aoluguya()
 from go_hotel.db.models import HostedDirectHotelRow
 with SessionLocal() as s:
  h=s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug=='aoluguya-harbin'));c=h.contact_json
  assert c['address']=='黑龙江省哈尔滨市松北区创新三路800号' and c['breakfast']['adult_price_minor']==16800 and c['deposit']['price_minor_per_night']==100000 and c['content_status']=='PUBLIC_FACTS_PENDING_HOTEL_CONFIRMATION'
 assert second['rate_variants']==9
def test_breakfast_variants_share_atomic_physical_inventory_and_restore():
 setup()
 with SessionLocal() as s:
  pool=s.scalar(select(HostedDirectInventoryPoolRow).where(HostedDirectInventoryPoolRow.physical_room_key=='ROUND_DREAM_KING'));variants=s.scalars(select(HostedDirectRateVariantRow).where(HostedDirectRateVariantRow.inventory_pool_id==pool.inventory_pool_id)).all();offers=[v.hosted_offer_id for v in variants]
 body={'guest_name':'测试','guest_contact':'0451-88800808','check_in':'2026-09-01','check_out':'2026-09-02'};r1=svc.reserve('aoluguya-harbin',{**body,'hosted_offer_id':offers[0]},'k1');r2=svc.reserve('aoluguya-harbin',{**body,'hosted_offer_id':offers[1]},'k2')
 with SessionLocal() as s:assert s.get(HostedDirectInventoryPoolRow,pool.inventory_pool_id).capacity_available==48
 svc.cancel(r1['hosted_reservation_id'],'consumer')
 with SessionLocal() as s:assert s.get(HostedDirectInventoryPoolRow,pool.inventory_pool_id).capacity_available==49
 assert r2['payment_state']=='ALIPAY_APPLICATION_PENDING_NO_CHARGE'
