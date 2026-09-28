from datetime import datetime,timezone,date
import uuid
from sqlalchemy import select,func,update
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HostedDirectHotelRow,HostedDirectRoomOfferRow,HostedDirectReservationRow,HostedDirectReservationEventRow,HostedDirectPaymentReadinessRow,HostedDirectInventoryPoolRow,HostedDirectRateVariantRow
def now():return datetime.now(timezone.utc)
def ident(p):return f'{p}_{uuid.uuid4().hex}'
def out(r):
 def value(v):
  if isinstance(v,datetime):return (v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)).isoformat()
  return v
 return {c.name:value(getattr(r,c.name)) for c in r.__table__.columns}
class HostedDirectBookingService:
 def create_hotel(self,b,actor):
  if b.get('supplier_name')!='哈尔滨敖麓谷雅酒店':raise ValueError('FIRST_PILOT_SUPPLIER_LOCKED')
  with SessionLocal() as s:
   r=HostedDirectHotelRow(hosted_hotel_id=ident('hdh'),supplier_name=b['supplier_name'],page_slug=b.get('page_slug','aoluguya-harbin'),city='哈尔滨',contact_json=b.get('contact',{}),state='DRAFT',updated_at=now());s.add(r);s.flush();s.add(HostedDirectPaymentReadinessRow(hosted_hotel_id=r.hosted_hotel_id,provider='ALIPAY',merchant_account_name='哈尔滨敖麓谷雅酒店',application_state='SANDBOX_APPLICATION_NOT_CREATED',sandbox_app_id_reference=None,kms_reference=None,blockers_json=['ALIPAY_OPEN_PLATFORM_APPLICATION_REQUIRED','SANDBOX_APP_ID_REQUIRED','KMS_REFERENCE_REQUIRED'],updated_at=now()));s.commit();return out(r)
 def publish(self,hotel_id,actor):
  with SessionLocal() as s:
   h=s.get(HostedDirectHotelRow,hotel_id,with_for_update=True)
   if not h:raise ValueError('HOSTED_HOTEL_NOT_FOUND')
   from go_hotel.services.hosted_publication import require_publication
   require_publication(s,hotel_id)
   from go_hotel.security.service import Principal
   if isinstance(actor,Principal):
    from go_hotel.services.hosted_operation_authority import scoped
    scoped(s,actor,hotel_id,'admin:rules')
   count=s.scalar(select(func.count()).select_from(HostedDirectRoomOfferRow).where(HostedDirectRoomOfferRow.hosted_hotel_id==hotel_id,HostedDirectRoomOfferRow.state=='ACTIVE'))
   if not count:raise ValueError('ACTIVE_ROOM_OFFER_REQUIRED')
   h.state='PUBLISHED_REQUEST_ONLY';h.updated_at=now();s.commit();return out(h)
 def upsert_offer(self,hotel_id,b,actor):
  if b.get('price_minor',0)<=0 or b.get('inventory',0)<0:raise ValueError('VALID_PRICE_AND_INVENTORY_REQUIRED')
  with SessionLocal() as s:
   if not s.get(HostedDirectHotelRow,hotel_id):raise ValueError('HOSTED_HOTEL_NOT_FOUND')
   r=HostedDirectRoomOfferRow(hosted_offer_id=ident('hdo'),hosted_hotel_id=hotel_id,room_name=b['room_name'],rate_name=b['rate_name'],price_minor=b['price_minor'],currency=b.get('currency','CNY'),inventory=b['inventory'],cancellation_policy=b['cancellation_policy'],state='ACTIVE',updated_at=now());s.add(r);s.commit();return out(r)
 def page(self,slug):
  with SessionLocal() as s:
   h=s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug==slug,HostedDirectHotelRow.state=='PUBLISHED_REQUEST_ONLY'))
   if not h:raise ValueError('DIRECT_PAGE_NOT_PUBLISHED')
   from go_hotel.services.hosted_publication import require_publication
   publication=require_publication(s,h.hosted_hotel_id)
   offers=s.scalars(select(HostedDirectRoomOfferRow).where(HostedDirectRoomOfferRow.hosted_hotel_id==h.hosted_hotel_id,HostedDirectRoomOfferRow.state=='ACTIVE')).all();pay=s.get(HostedDirectPaymentReadinessRow,h.hosted_hotel_id)
   return {'hotel':out(h),'offers':[out(x) for x in offers],'media':[{'media_asset_id':x['media_asset_id'],'role':x['role'],'room':x['room'],'url':f"/v1/direct/{slug}/media/{x['media_asset_id']}"} for x in publication.manifest_json['media']],'publication_hash':publication.manifest_hash,'booking_mode':'RESERVATION_REQUEST_ONLY','payment':out(pay),'payment_available':False}
 def reserve(self,slug,b,key):
  if not key:raise ValueError('IDEMPOTENCY_KEY_REQUIRED')
  try:cin=date.fromisoformat(b['check_in']);cout=date.fromisoformat(b['check_out'])
  except Exception:raise ValueError('VALID_STAY_DATES_REQUIRED')
  if cout<=cin:raise ValueError('CHECK_OUT_MUST_FOLLOW_CHECK_IN')
  with SessionLocal() as s:
   old=s.scalar(select(HostedDirectReservationRow).where(HostedDirectReservationRow.idempotency_key==key))
   if old:return out(old)
   h=s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug==slug,HostedDirectHotelRow.state=='PUBLISHED_REQUEST_ONLY'));o=s.get(HostedDirectRoomOfferRow,b['hosted_offer_id'])
   if not h or not o or o.hosted_hotel_id!=h.hosted_hotel_id or o.state!='ACTIVE':raise ValueError('ACTIVE_HOSTED_OFFER_REQUIRED')
   if o.currency!='CNY':raise ValueError('HOSTED_CHECKOUT_CURRENCY_UNSUPPORTED')
   from go_hotel.services.hosted_publication import require_publication
   require_publication(s,h.hosted_hotel_id)
   v=s.scalar(select(HostedDirectRateVariantRow).where(HostedDirectRateVariantRow.hosted_offer_id==o.hosted_offer_id))
   if v:
    changed=s.execute(update(HostedDirectInventoryPoolRow).where(HostedDirectInventoryPoolRow.inventory_pool_id==v.inventory_pool_id,HostedDirectInventoryPoolRow.capacity_available>0).values(capacity_available=HostedDirectInventoryPoolRow.capacity_available-1,updated_at=now())).rowcount
    if changed!=1:raise ValueError('NO_MANAGED_INVENTORY')
   elif o.inventory<=0:raise ValueError('NO_MANAGED_INVENTORY')
   else:o.inventory-=1
   r=HostedDirectReservationRow(hosted_reservation_id=ident('hdr'),hosted_offer_id=o.hosted_offer_id,idempotency_key=key,guest_name=b['guest_name'],guest_contact=b['guest_contact'],check_in=b['check_in'],check_out=b['check_out'],amount_minor=o.price_minor*(cout-cin).days,currency=o.currency,reservation_state='PENDING_HOTEL_CONFIRMATION',payment_state='ALIPAY_APPLICATION_PENDING_NO_CHARGE',hotel_confirmation_reference=None,created_at=now(),updated_at=now());s.add(r);s.flush();self._event(s,r.hosted_reservation_id,'RESERVATION_REQUESTED','CONSUMER',{'payment_attempted':False});s.commit();return out(r)
 def hotel_decision(self,reservation_id,b,actor):
  from go_hotel.db.models import HostedReservationStayRow
  from go_hotel.services.hosted_reservation_operations import hosted_reservation_operations_service as ops
  with SessionLocal() as s:managed=s.get(HostedReservationStayRow,reservation_id) is not None
  if managed:return ops.action(reservation_id,{**b,'action':b.get('decision')},actor)
  decision=b.get('decision')
  if decision not in ('CONFIRM','REJECT'):raise ValueError('CONFIRM_OR_REJECT_REQUIRED')
  with SessionLocal() as s:
   r=s.get(HostedDirectReservationRow,reservation_id)
   if not r or r.reservation_state!='PENDING_HOTEL_CONFIRMATION':raise ValueError('RESERVATION_NOT_PENDING')
   if decision=='CONFIRM':r.reservation_state='HOTEL_CONFIRMED_AWAITING_ALIPAY_ONBOARDING';r.hotel_confirmation_reference=b.get('hotel_confirmation_reference') or ident('hotel_confirm')
   else:r.reservation_state='HOTEL_REJECTED';self._restore(s,r.hosted_offer_id)
   r.updated_at=now();self._event(s,reservation_id,'HOTEL_'+decision,actor,{'payment_captured':False});s.commit();return out(r)
 def cancel(self,reservation_id,actor):
  from go_hotel.db.models import HostedReservationStayRow
  from go_hotel.services.hosted_reservation_operations import hosted_reservation_operations_service as ops
  with SessionLocal() as s:managed=s.get(HostedReservationStayRow,reservation_id) is not None
  if managed:return ops.action(reservation_id,{'action':'CANCEL'},actor)
  with SessionLocal() as s:
   r=s.get(HostedDirectReservationRow,reservation_id)
   if not r or r.reservation_state in ('CANCELLED','HOTEL_REJECTED'):raise ValueError('RESERVATION_NOT_CANCELLABLE')
   r.reservation_state='CANCELLED';r.payment_state='NO_PAYMENT_NO_REFUND_REQUIRED';self._restore(s,r.hosted_offer_id);r.updated_at=now();self._event(s,reservation_id,'CANCELLED',actor,{'refund_required':False});s.commit();return out(r)
 def _event(self,s,rid,typ,actor,payload):s.add(HostedDirectReservationEventRow(hosted_event_id=ident('hde'),hosted_reservation_id=rid,event_type=typ,actor_id=actor,payload_json=payload,occurred_at=now()))
 def _restore(self,s,offer_id):
  v=s.scalar(select(HostedDirectRateVariantRow).where(HostedDirectRateVariantRow.hosted_offer_id==offer_id))
  if v:s.execute(update(HostedDirectInventoryPoolRow).where(HostedDirectInventoryPoolRow.inventory_pool_id==v.inventory_pool_id,HostedDirectInventoryPoolRow.capacity_available<HostedDirectInventoryPoolRow.capacity_total).values(capacity_available=HostedDirectInventoryPoolRow.capacity_available+1,updated_at=now()))
  else:s.get(HostedDirectRoomOfferRow,offer_id).inventory+=1
 def status(self,reservation_id):
  with SessionLocal() as s:
   r=s.get(HostedDirectReservationRow,reservation_id)
   if not r:raise ValueError('RESERVATION_NOT_FOUND')
   ev=s.scalars(select(HostedDirectReservationEventRow).where(HostedDirectReservationEventRow.hosted_reservation_id==reservation_id).order_by(HostedDirectReservationEventRow.occurred_at)).all();return {'reservation':out(r),'events':[out(x) for x in ev],'payment_attempted':False,'production_live':False}
 def dashboard(self):
  with SessionLocal() as s:return {'hotels':dict(s.execute(select(HostedDirectHotelRow.state,func.count()).group_by(HostedDirectHotelRow.state)).all()),'pilot_supplier':'哈尔滨敖麓谷雅酒店','alipay_state':'SANDBOX_APPLICATION_NOT_CREATED','payment_live':False,'production_live':False}
hosted_direct_booking_service=HostedDirectBookingService()
