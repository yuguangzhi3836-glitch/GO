from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HostedDirectHotelRow,HostedDirectRoomOfferRow,HostedDirectInventoryPoolRow,HostedDirectRateVariantRow
from go_hotel.services.hosted_direct_booking import ident,now
ROOMS=[('ROUND_DREAM_KING','摄罗子·圆梦大床房',[(0,69800),(1,79800),(2,89800)]),('ROUND_DREAM_TWIN','摄罗子·圆梦双床房',[(0,69800),(1,79800),(2,89800)]),('PILLOW_MOON_KING','摄罗子·枕月大床房',[(2,99800)]),('PILLOW_MOON_TWIN','摄罗子·枕月双床房',[(2,99800)]),('SLEEPING_CLOUD_TWIN','摄罗子·卧云双床房',[(2,119800)])]
def configure_aoluguya_legacy_fixture():
 with SessionLocal() as s:
  h=s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug=='aoluguya-harbin'))
  if not h:raise ValueError('AOLUGUYA_HOSTED_HOTEL_REQUIRED')
  h.contact_json={'front_desk_phone':'0451-88800808','reservation_phone':'0451-88800808','check_in':'14:00','check_out':'12:00 next day','address':'黑龙江省哈尔滨市松北区创新三路800号','opened_year':2020,'front_desk_hours':'24小时','minimum_check_in_age':18,'pets':'不可携带宠物','wedding_room_booking':'不接受','facilities':['SPA','室内泳池','行政酒廊','中餐厅','全日制餐厅','咖啡厅','健身中心','免费公共停车场','免费班车服务','Wi-Fi'],'breakfast':{'style':'自助餐','hours':'06:30-13:00','adult_price_minor':16800,'child_under_1_2m_price_minor':0,'child_1_2_to_1_4m_price_minor':8400,'child_1_4m_and_above_price_minor':16800},'extra_bed':{'price_minor_per_night':42000,'baby_cot_free':True},'deposit':{'price_minor_per_night':100000,'methods':['信用卡','借记卡','第三方支付','现金'],'refund':'退房后原路退还'},'content_status':'PUBLIC_FACTS_PENDING_HOTEL_CONFIRMATION','source_refs':['https://hotels.ctrip.com/hotels/2670932.html']}
  existing=s.scalar(select(HostedDirectInventoryPoolRow).where(HostedDirectInventoryPoolRow.hosted_hotel_id==h.hosted_hotel_id))
  if existing:h.updated_at=now();s.commit();return {'physical_room_pools':5,'rate_variants':9,'inventory_each':50,'alipay':'SANDBOX_APPLICATION_NOT_CREATED','content_status':'PUBLIC_FACTS_PENDING_HOTEL_CONFIRMATION'}
  variants=0
  for key,name,rates in ROOMS:
   pool=HostedDirectInventoryPoolRow(inventory_pool_id=ident('hip'),hosted_hotel_id=h.hosted_hotel_id,physical_room_key=key,physical_room_name=name,room_details_json={},capacity_total=50,capacity_available=50,updated_at=now());s.add(pool);s.flush()
   for breakfast,price in rates:
    o=HostedDirectRoomOfferRow(hosted_offer_id=ident('hdo'),hosted_hotel_id=h.hosted_hotel_id,room_name=name,rate_name=['无早餐','1份早餐','2份早餐'][breakfast],price_minor=price,currency='CNY',inventory=50,cancellation_policy='酒店确认后30分钟内免费取消',state='ACTIVE',updated_at=now());s.add(o);s.flush();s.add(HostedDirectRateVariantRow(rate_variant_id=ident('hrv'),inventory_pool_id=pool.inventory_pool_id,hosted_offer_id=o.hosted_offer_id,breakfast_count=breakfast,benefits_json=['连住2晚下午茶'] if key=='SLEEPING_CLOUD_TWIN' else [],payment_mode='ALIPAY_PENDING_NO_CHARGE',state='ACTIVE'));variants+=1
  h.state='PUBLISHED_REQUEST_ONLY';s.commit();return {'physical_room_pools':5,'rate_variants':variants,'inventory_each':50,'alipay':'SANDBOX_APPLICATION_NOT_CREATED','content_status':'PUBLIC_FACTS_PENDING_HOTEL_CONFIRMATION'}


def configure_aoluguya():
 from go_hotel.services.official_hotel_catalog import configure_official_hotel
 return configure_official_hotel()
