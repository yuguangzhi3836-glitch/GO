from datetime import date,datetime,timedelta,timezone
from sqlalchemy import select,update
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HostedDirectHotelRow,HostedDirectRoomOfferRow,HostedDirectReservationRow,HostedDirectReservationEventRow,HostedDirectInventoryPoolRow,HostedDirectRateVariantRow,HostedInventoryDayRow,HostedRateCalendarDayRow,HostedReservationStayRow,HostedReservationNightRow,HostedReservationNotificationRow
from go_hotel.services.hosted_direct_booking import ident,now,out

def dates(start,end):
 d=start
 while d<end:yield d;d+=timedelta(days=1)

class HostedReservationOperationsService:
 def bootstrap_calendar(self,hotel_id,b):
  try:start=date.fromisoformat(b['start_date']);end=date.fromisoformat(b['end_date'])
  except Exception:raise ValueError('VALID_CALENDAR_DATE_RANGE_REQUIRED')
  if end<start or (end-start).days>370:raise ValueError('CALENDAR_RANGE_1_TO_371_DAYS_REQUIRED')
  with SessionLocal() as s:
   if not s.get(HostedDirectHotelRow,hotel_id):raise ValueError('HOSTED_HOTEL_NOT_FOUND')
   pools=s.scalars(select(HostedDirectInventoryPoolRow).where(HostedDirectInventoryPoolRow.hosted_hotel_id==hotel_id)).all();created_inventory=created_rates=0
   for pool in pools:
    variants=s.scalars(select(HostedDirectRateVariantRow).where(HostedDirectRateVariantRow.inventory_pool_id==pool.inventory_pool_id)).all()
    for d in dates(start,end+timedelta(days=1)):
     ds=d.isoformat();inv=s.scalar(select(HostedInventoryDayRow).where(HostedInventoryDayRow.inventory_pool_id==pool.inventory_pool_id,HostedInventoryDayRow.stay_date==ds))
     if not inv:s.add(HostedInventoryDayRow(inventory_day_id=ident('hid'),inventory_pool_id=pool.inventory_pool_id,stay_date=ds,capacity_total=pool.capacity_total,capacity_available=pool.capacity_total,sale_state='OPEN',updated_at=now()));created_inventory+=1
     for variant in variants:
      rate=s.scalar(select(HostedRateCalendarDayRow).where(HostedRateCalendarDayRow.rate_variant_id==variant.rate_variant_id,HostedRateCalendarDayRow.stay_date==ds))
      if not rate:
       offer=s.get(HostedDirectRoomOfferRow,variant.hosted_offer_id);s.add(HostedRateCalendarDayRow(rate_calendar_day_id=ident('hrc'),rate_variant_id=variant.rate_variant_id,stay_date=ds,price_minor=offer.price_minor,sale_state='OPEN',min_stay=1,max_stay=30,advance_min_days=0,advance_max_days=365,max_adults=2,max_children=1,extra_bed_allowed=False,updated_at=now()));created_rates+=1
   s.commit();return {'inventory_days_created':created_inventory,'rate_days_created':created_rates,'payment_live':False}
 def set_inventory_day(self,pool_id,stay_date,b):
  if b.get('sale_state') not in ('OPEN','CLOSED','SOLD_OUT','STOP_SELL'):raise ValueError('VALID_INVENTORY_SALE_STATE_REQUIRED')
  with SessionLocal() as s:
   r=s.scalar(select(HostedInventoryDayRow).where(HostedInventoryDayRow.inventory_pool_id==pool_id,HostedInventoryDayRow.stay_date==stay_date))
   if not r:raise ValueError('INVENTORY_DAY_NOT_FOUND')
   total=int(b.get('capacity_total',r.capacity_total));available=int(b.get('capacity_available',r.capacity_available))
   if total<0 or available<0 or available>total:raise ValueError('VALID_DAILY_CAPACITY_REQUIRED')
   r.capacity_total=total;r.capacity_available=available;r.sale_state=b['sale_state'];r.updated_at=now();s.commit();return out(r)
 def set_rate_day(self,variant_id,stay_date,b):
  if b.get('sale_state') not in ('OPEN','CLOSED','STOP_SELL'):raise ValueError('VALID_RATE_SALE_STATE_REQUIRED')
  with SessionLocal() as s:
   r=s.scalar(select(HostedRateCalendarDayRow).where(HostedRateCalendarDayRow.rate_variant_id==variant_id,HostedRateCalendarDayRow.stay_date==stay_date))
   if not r:raise ValueError('RATE_CALENDAR_DAY_NOT_FOUND')
   for k in ('price_minor','min_stay','max_stay','advance_min_days','advance_max_days','max_adults','max_children'):
    if k in b:setattr(r,k,int(b[k]))
   if r.price_minor<=0 or r.min_stay<1 or r.max_stay<r.min_stay or r.advance_max_days<r.advance_min_days or r.max_adults<1 or r.max_children<0:raise ValueError('INVALID_RATE_RESTRICTIONS')
   r.extra_bed_allowed=bool(b.get('extra_bed_allowed',r.extra_bed_allowed));r.sale_state=b['sale_state'];r.updated_at=now();s.commit();return out(r)
 def reserve(self,slug,b,key,source='GO_PAGE',actor='CONSUMER'):
  if source not in ('GO_PAGE','PHONE'):raise ValueError('GO_PAGE_OR_PHONE_SOURCE_REQUIRED')
  try:cin=date.fromisoformat(b['check_in']);cout=date.fromisoformat(b['check_out'])
  except Exception:raise ValueError('VALID_STAY_DATES_REQUIRED')
  if cout<=cin:raise ValueError('CHECK_OUT_MUST_FOLLOW_CHECK_IN')
  with SessionLocal() as s:
   old=s.scalar(select(HostedDirectReservationRow).where(HostedDirectReservationRow.idempotency_key==key))
   if old:return out(old)
   h=s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug==slug,HostedDirectHotelRow.state=='PUBLISHED_REQUEST_ONLY'));offer=s.get(HostedDirectRoomOfferRow,b['hosted_offer_id'])
   if not h or not offer or offer.hosted_hotel_id!=h.hosted_hotel_id:raise ValueError('ACTIVE_HOSTED_OFFER_REQUIRED')
   variant=s.scalar(select(HostedDirectRateVariantRow).where(HostedDirectRateVariantRow.hosted_offer_id==offer.hosted_offer_id))
   if not variant:raise ValueError('DATED_MANAGED_RATE_REQUIRED')
   adults=int(b.get('adults',1));children=int(b.get('children',0));extra_beds=int(b.get('extra_beds',0));nights=(cout-cin).days;advance=(cin-date.today()).days
   rates=[];inventory=[]
   for d in dates(cin,cout):
    ds=d.isoformat();rate=s.scalar(select(HostedRateCalendarDayRow).where(HostedRateCalendarDayRow.rate_variant_id==variant.rate_variant_id,HostedRateCalendarDayRow.stay_date==ds));inv=s.scalar(select(HostedInventoryDayRow).where(HostedInventoryDayRow.inventory_pool_id==variant.inventory_pool_id,HostedInventoryDayRow.stay_date==ds))
    if not rate or not inv:raise ValueError('DATED_ARI_NOT_CONFIGURED')
    if rate.sale_state!='OPEN' or inv.sale_state!='OPEN':raise ValueError('DATE_CLOSED_OR_STOP_SELL')
    if nights<rate.min_stay or nights>rate.max_stay or advance<rate.advance_min_days or advance>rate.advance_max_days:raise ValueError('STAY_OR_ADVANCE_RESTRICTION_FAILED')
    if adults>rate.max_adults or children>rate.max_children or (extra_beds and not rate.extra_bed_allowed):raise ValueError('OCCUPANCY_OR_EXTRA_BED_RESTRICTION_FAILED')
    rates.append(rate);inventory.append(inv)
   for inv in inventory:
    changed=s.execute(update(HostedInventoryDayRow).where(HostedInventoryDayRow.inventory_day_id==inv.inventory_day_id,HostedInventoryDayRow.sale_state=='OPEN',HostedInventoryDayRow.capacity_available>0).values(capacity_available=HostedInventoryDayRow.capacity_available-1,updated_at=now())).rowcount
    if changed!=1:raise ValueError('NO_DATED_INVENTORY')
   amount=sum(x.price_minor for x in rates);r=HostedDirectReservationRow(hosted_reservation_id=ident('hdr'),hosted_offer_id=offer.hosted_offer_id,idempotency_key=key,guest_name=b['guest_name'],guest_contact=b['guest_contact'],check_in=b['check_in'],check_out=b['check_out'],amount_minor=amount,currency='CNY',reservation_state='PENDING_HOTEL_CONFIRMATION',payment_state='ALIPAY_APPLICATION_PENDING_NO_CHARGE',hotel_confirmation_reference=None,created_at=now(),updated_at=now());s.add(r);s.flush()
   expiry=now()+timedelta(minutes=int(b.get('confirmation_timeout_minutes',30)));s.add(HostedReservationStayRow(hosted_reservation_id=r.hosted_reservation_id,source=source,adults=adults,children=children,extra_beds=extra_beds,operational_state='PENDING_HOTEL_CONFIRMATION',confirmation_expires_at=expiry,created_by=actor,updated_at=now()))
   for rate,inv in zip(rates,inventory):s.add(HostedReservationNightRow(reservation_night_id=ident('hrn'),hosted_reservation_id=r.hosted_reservation_id,inventory_day_id=inv.inventory_day_id,stay_date=rate.stay_date,price_minor=rate.price_minor,state='HELD'))
   self._event(s,r.hosted_reservation_id,'RESERVATION_REQUESTED',actor,{'source':source,'payment_attempted':False});self._notify(s,r.hosted_reservation_id,'HOTEL','RESERVATION_REQUESTED',{'source':source});self._notify(s,r.hosted_reservation_id,'GUEST','RESERVATION_RECEIVED',{'payment_captured':False});s.commit();return out(r)
 def action(self,reservation_id,b,actor):
  action=b.get('action')
  if action not in ('CONFIRM','REJECT','CANCEL'):raise ValueError('VALID_RESERVATION_ACTION_REQUIRED')
  with SessionLocal() as s:
   r=s.get(HostedDirectReservationRow,reservation_id);stay=s.get(HostedReservationStayRow,reservation_id)
   if not r or not stay:raise ValueError('MANAGED_RESERVATION_NOT_FOUND')
   if stay.operational_state not in ('PENDING_HOTEL_CONFIRMATION','CONFIRMED'):raise ValueError('RESERVATION_ACTION_NOT_ALLOWED')
   if action=='CONFIRM':
    if stay.operational_state!='PENDING_HOTEL_CONFIRMATION':raise ValueError('RESERVATION_NOT_PENDING')
    stay.operational_state='CONFIRMED';r.reservation_state='HOTEL_CONFIRMED_AWAITING_ALIPAY_ONBOARDING';r.hotel_confirmation_reference=b.get('hotel_confirmation_reference') or ident('hotel_confirm');template='RESERVATION_CONFIRMED'
   else:
    stay.operational_state='REJECTED' if action=='REJECT' else 'CANCELLED';r.reservation_state='HOTEL_REJECTED' if action=='REJECT' else 'CANCELLED';r.payment_state='NO_PAYMENT_NO_REFUND_REQUIRED';self._release(s,reservation_id);template='RESERVATION_'+stay.operational_state
   stay.updated_at=r.updated_at=now();self._event(s,reservation_id,'HOTEL_'+action,actor,{'payment_captured':False,'refund_required':False});self._notify(s,reservation_id,'GUEST',template,{'payment_captured':False});s.commit();return out(r)
 def expire_pending(self,actor='SYSTEM'):
  with SessionLocal() as s:
   rows=s.scalars(select(HostedReservationStayRow).where(HostedReservationStayRow.operational_state=='PENDING_HOTEL_CONFIRMATION',HostedReservationStayRow.confirmation_expires_at<now())).all()
   for stay in rows:
    r=s.get(HostedDirectReservationRow,stay.hosted_reservation_id);stay.operational_state='EXPIRED';r.reservation_state='HOTEL_CONFIRMATION_TIMEOUT';r.payment_state='NO_PAYMENT_NO_REFUND_REQUIRED';stay.updated_at=r.updated_at=now();self._release(s,r.hosted_reservation_id);self._event(s,r.hosted_reservation_id,'CONFIRMATION_TIMEOUT',actor,{'inventory_released':True});self._notify(s,r.hosted_reservation_id,'GUEST','CONFIRMATION_TIMEOUT',{})
   s.commit();return {'expired_count':len(rows),'inventory_released':len(rows),'payment_live':False}
 def reschedule(self,reservation_id,b,actor):
  try:cin=date.fromisoformat(b['check_in']);cout=date.fromisoformat(b['check_out'])
  except Exception:raise ValueError('VALID_STAY_DATES_REQUIRED')
  if cout<=cin:raise ValueError('CHECK_OUT_MUST_FOLLOW_CHECK_IN')
  with SessionLocal() as s:
   r=s.get(HostedDirectReservationRow,reservation_id);stay=s.get(HostedReservationStayRow,reservation_id)
   if not r or not stay or stay.operational_state not in ('PENDING_HOTEL_CONFIRMATION','CONFIRMED'):raise ValueError('RESERVATION_NOT_RESCHEDULABLE')
   variant=s.scalar(select(HostedDirectRateVariantRow).where(HostedDirectRateVariantRow.hosted_offer_id==r.hosted_offer_id));nights=(cout-cin).days;advance=(cin-date.today()).days;new=[]
   for d in dates(cin,cout):
    ds=d.isoformat();rate=s.scalar(select(HostedRateCalendarDayRow).where(HostedRateCalendarDayRow.rate_variant_id==variant.rate_variant_id,HostedRateCalendarDayRow.stay_date==ds));inv=s.scalar(select(HostedInventoryDayRow).where(HostedInventoryDayRow.inventory_pool_id==variant.inventory_pool_id,HostedInventoryDayRow.stay_date==ds))
    if not rate or not inv:raise ValueError('DATED_ARI_NOT_CONFIGURED')
    if rate.sale_state!='OPEN' or inv.sale_state!='OPEN' or nights<rate.min_stay or nights>rate.max_stay or advance<rate.advance_min_days or advance>rate.advance_max_days:raise ValueError('RESCHEDULE_RESTRICTION_FAILED')
    if stay.adults>rate.max_adults or stay.children>rate.max_children or (stay.extra_beds and not rate.extra_bed_allowed):raise ValueError('OCCUPANCY_OR_EXTRA_BED_RESTRICTION_FAILED')
    new.append((rate,inv))
   self._release(s,reservation_id)
   for old in s.scalars(select(HostedReservationNightRow).where(HostedReservationNightRow.hosted_reservation_id==reservation_id)).all():s.delete(old)
   s.flush()
   for rate,inv in new:
    changed=s.execute(update(HostedInventoryDayRow).where(HostedInventoryDayRow.inventory_day_id==inv.inventory_day_id,HostedInventoryDayRow.sale_state=='OPEN',HostedInventoryDayRow.capacity_available>0).values(capacity_available=HostedInventoryDayRow.capacity_available-1,updated_at=now())).rowcount
    if changed!=1:raise ValueError('NO_DATED_INVENTORY')
    s.add(HostedReservationNightRow(reservation_night_id=ident('hrn'),hosted_reservation_id=reservation_id,inventory_day_id=inv.inventory_day_id,stay_date=rate.stay_date,price_minor=rate.price_minor,state='HELD'))
   r.check_in=b['check_in'];r.check_out=b['check_out'];r.amount_minor=sum(x[0].price_minor for x in new);r.updated_at=stay.updated_at=now();self._event(s,reservation_id,'RESCHEDULED',actor,{'payment_attempted':False,'refund_required':False});self._notify(s,reservation_id,'GUEST','RESERVATION_RESCHEDULED',{'check_in':r.check_in,'check_out':r.check_out});s.commit();return out(r)
 def _release(self,s,reservation_id):
  nights=s.scalars(select(HostedReservationNightRow).where(HostedReservationNightRow.hosted_reservation_id==reservation_id,HostedReservationNightRow.state=='HELD')).all()
  for n in nights:s.execute(update(HostedInventoryDayRow).where(HostedInventoryDayRow.inventory_day_id==n.inventory_day_id,HostedInventoryDayRow.capacity_available<HostedInventoryDayRow.capacity_total).values(capacity_available=HostedInventoryDayRow.capacity_available+1,updated_at=now()));n.state='RELEASED'
 def _event(self,s,rid,typ,actor,payload):s.add(HostedDirectReservationEventRow(hosted_event_id=ident('hde'),hosted_reservation_id=rid,event_type=typ,actor_id=actor,payload_json=payload,occurred_at=now()))
 def _notify(self,s,rid,recipient,template,payload):s.add(HostedReservationNotificationRow(notification_id=ident('hrnfy'),hosted_reservation_id=rid,recipient_type=recipient,channel='OPERATIONS_OUTBOX',template_key=template,delivery_state='QUEUED_NOT_SENT',payload_json=payload,created_at=now()))
 def dashboard(self,hotel_id):
  with SessionLocal() as s:
   pools=s.scalars(select(HostedDirectInventoryPoolRow).where(HostedDirectInventoryPoolRow.hosted_hotel_id==hotel_id)).all();pool_ids=[x.inventory_pool_id for x in pools];days=s.scalars(select(HostedInventoryDayRow).where(HostedInventoryDayRow.inventory_pool_id.in_(pool_ids))).all() if pool_ids else [];stays=s.scalars(select(HostedReservationStayRow)).all()
   return {'inventory_days':len(days),'closed_or_sold_out':sum(x.sale_state!='OPEN' for x in days),'reservations_by_state':{state:sum(x.operational_state==state for x in stays) for state in sorted({x.operational_state for x in stays})},'notifications_queued_not_sent':s.query(HostedReservationNotificationRow).filter_by(delivery_state='QUEUED_NOT_SENT').count(),'alipay_state':'SANDBOX_APPLICATION_NOT_CREATED','payment_live':False,'production_live':False}

hosted_reservation_operations_service=HostedReservationOperationsService()
