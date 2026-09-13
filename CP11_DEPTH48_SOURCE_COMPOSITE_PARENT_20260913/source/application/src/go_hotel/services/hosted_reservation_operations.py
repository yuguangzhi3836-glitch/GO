from datetime import date,datetime,timedelta,timezone
from sqlalchemy import select,update,text
from contextlib import contextmanager,nullcontext
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HostedDirectHotelRow,HostedDirectRoomOfferRow,HostedDirectReservationRow,HostedDirectReservationEventRow,HostedDirectInventoryPoolRow,HostedDirectRateVariantRow,HostedInventoryDayRow,HostedRateCalendarDayRow,HostedReservationStayRow,HostedReservationNightRow,HostedReservationNotificationRow
from go_hotel.services.hosted_direct_booking import ident,now,out
from go_hotel.db.models import AlipayAuthorizationRow

def dates(start,end):
 d=start
 while d<end:yield d;d+=timedelta(days=1)

@contextmanager
def managed_session():
 """Serialize SQLite writers; PostgreSQL uses row and conditional-update locks."""
 with SessionLocal() as session:
  if session.bind.dialect.name=='sqlite':
   session.execute(text('BEGIN IMMEDIATE'))
  try:
   yield session
  except BaseException:
   session.rollback()
   raise

def aware(value):
 return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

def payment_clear_for_inventory_change(session, reservation):
 if reservation.payment_state not in {'ALIPAY_APPLICATION_PENDING_NO_CHARGE','NO_PAYMENT_NO_REFUND_REQUIRED'}:
  return False
 auth=session.scalar(select(AlipayAuthorizationRow).where(AlipayAuthorizationRow.hosted_reservation_id==reservation.hosted_reservation_id,AlipayAuthorizationRow.state!='CONTRACT_RELEASED_NOT_ALIPAY'))
 return auth is None


class HostedReservationOperationsService:
 def availability(self,slug,b):
  try:cin=date.fromisoformat(b['check_in']);cout=date.fromisoformat(b['check_out'])
  except Exception:raise ValueError('VALID_STAY_DATES_REQUIRED')
  if cin<date.today() or not 1<=(cout-cin).days<=30:raise ValueError('VALID_STAY_DATES_REQUIRED')
  adults=int(b.get('adults',1));children=int(b.get('children',0))
  if adults<1 or children<0:raise ValueError('INVALID_OCCUPANCY_OR_STAY_LENGTH')
  with SessionLocal() as s:
   hotel=s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug==slug))
   if not hotel:raise ValueError('HOSTED_HOTEL_NOT_FOUND')
   offers=s.scalars(select(HostedDirectRoomOfferRow).where(HostedDirectRoomOfferRow.hosted_hotel_id==hotel.hosted_hotel_id,HostedDirectRoomOfferRow.state=='ACTIVE')).all()
   items=[]
   for offer in offers:
    variant=s.scalar(select(HostedDirectRateVariantRow).where(HostedDirectRateVariantRow.hosted_offer_id==offer.hosted_offer_id,HostedDirectRateVariantRow.state=='ACTIVE'))
    if not variant:continue
    pool=s.get(HostedDirectInventoryPoolRow,variant.inventory_pool_id)
    prices=[];available=[];reasons=[]
    for day in dates(cin,cout):
     ds=day.isoformat()
     rate=s.scalar(select(HostedRateCalendarDayRow).where(HostedRateCalendarDayRow.rate_variant_id==variant.rate_variant_id,HostedRateCalendarDayRow.stay_date==ds))
     inv=s.scalar(select(HostedInventoryDayRow).where(HostedInventoryDayRow.inventory_pool_id==variant.inventory_pool_id,HostedInventoryDayRow.stay_date==ds))
     if not rate or not inv:reasons.append('DATED_ARI_NOT_CONFIGURED');continue
     if rate.sale_state!='OPEN' or inv.sale_state!='OPEN' or inv.capacity_available<1:reasons.append('NO_DATED_INVENTORY')
     if not rate.min_stay<=(cout-cin).days<=rate.max_stay or not rate.advance_min_days<=(cin-date.today()).days<=rate.advance_max_days:reasons.append('STAY_OR_ADVANCE_RESTRICTION_FAILED')
     if adults>rate.max_adults or children>rate.max_children:reasons.append('OCCUPANCY_OR_EXTRA_BED_RESTRICTION_FAILED')
     prices.append({'stay_date':ds,'price_minor':rate.price_minor});available.append(inv.capacity_available)
    from go_hotel.db.models import HostedFareRuleVersionRow
    fare=s.scalar(select(HostedFareRuleVersionRow).where(HostedFareRuleVersionRow.hosted_offer_id==offer.hosted_offer_id).order_by(HostedFareRuleVersionRow.version.desc()))
    items.append({**out(offer),'fare_rule':{'rule_hash':fare.rule_hash,'rules':fare.rules_json} if fare else None,'room_code':pool.physical_room_key,'room':pool.room_details_json,'nights':prices,'total_amount_minor':sum(p['price_minor'] for p in prices) if len(prices)==(cout-cin).days else None,'inventory_available':min(available) if available else 0,'bookable':not reasons,'unavailable_reasons':sorted(set(reasons))})
   return {'check_in':b['check_in'],'check_out':b['check_out'],'adults':adults,'children':children,'items':items,'data_mode':hotel.contact_json.get('inventory_data_mode','SUPPLIER_MANAGED'),'currency':'CNY'}
 def bootstrap_calendar(self,hotel_id,b):
  try:start=date.fromisoformat(b['start_date']);end=date.fromisoformat(b['end_date'])
  except Exception:raise ValueError('VALID_CALENDAR_DATE_RANGE_REQUIRED')
  if end<start or (end-start).days>370:raise ValueError('CALENDAR_RANGE_1_TO_371_DAYS_REQUIRED')
  with managed_session() as s:
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
  with managed_session() as s:
   r=s.scalar(select(HostedInventoryDayRow).where(HostedInventoryDayRow.inventory_pool_id==pool_id,HostedInventoryDayRow.stay_date==stay_date).with_for_update())
   if not r:raise ValueError('INVENTORY_DAY_NOT_FOUND')
   total=int(b.get('capacity_total',r.capacity_total));available=int(b.get('capacity_available',r.capacity_available))
   if total<0 or available<0 or available>total:raise ValueError('VALID_DAILY_CAPACITY_REQUIRED')
   held=s.scalars(select(HostedReservationNightRow).where(HostedReservationNightRow.inventory_day_id==r.inventory_day_id,HostedReservationNightRow.state=='HELD')).all()
   if total<available+len(held):raise ValueError('CAPACITY_CONFLICTS_WITH_HELD_RESERVATIONS')
   r.capacity_total=total;r.capacity_available=available;r.sale_state=b['sale_state'];r.updated_at=now();s.commit();return out(r)
 def set_rate_day(self,variant_id,stay_date,b):
  if b.get('sale_state') not in ('OPEN','CLOSED','STOP_SELL'):raise ValueError('VALID_RATE_SALE_STATE_REQUIRED')
  with managed_session() as s:
   r=s.scalar(select(HostedRateCalendarDayRow).where(HostedRateCalendarDayRow.rate_variant_id==variant_id,HostedRateCalendarDayRow.stay_date==stay_date))
   if not r:raise ValueError('RATE_CALENDAR_DAY_NOT_FOUND')
   for k in ('price_minor','min_stay','max_stay','advance_min_days','advance_max_days','max_adults','max_children'):
    if k in b:setattr(r,k,int(b[k]))
   if r.price_minor<=0 or r.min_stay<1 or r.max_stay<r.min_stay or r.advance_min_days<0 or r.advance_max_days<r.advance_min_days or r.max_adults<1 or r.max_children<0:raise ValueError('INVALID_RATE_RESTRICTIONS')
   r.extra_bed_allowed=bool(b.get('extra_bed_allowed',r.extra_bed_allowed));r.sale_state=b['sale_state'];r.updated_at=now();s.commit();return out(r)
 def reserve(self,slug,b,key,source='GO_PAGE',actor='CONSUMER',_session=None):
  if not key or len(str(key))>128:raise ValueError('IDEMPOTENCY_KEY_REQUIRED')
  if source not in ('GO_PAGE','PHONE'):raise ValueError('GO_PAGE_OR_PHONE_SOURCE_REQUIRED')
  try:cin=date.fromisoformat(b['check_in']);cout=date.fromisoformat(b['check_out'])
  except Exception:raise ValueError('VALID_STAY_DATES_REQUIRED')
  if cout<=cin:raise ValueError('CHECK_OUT_MUST_FOLLOW_CHECK_IN')
  with (nullcontext(_session) if _session is not None else managed_session()) as s:
   old=s.scalar(select(HostedDirectReservationRow).where(HostedDirectReservationRow.idempotency_key==key))
   if old:
    expected={'hosted_offer_id':b['hosted_offer_id'],'check_in':b['check_in'],'check_out':b['check_out'],'guest_name':b.get('guest_name'),'guest_contact':b.get('guest_contact')}
    if any(getattr(old,k)!=v for k,v in expected.items()):raise ValueError('IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST')
    existing_stay=s.get(HostedReservationStayRow,old.hosted_reservation_id)
    if existing_stay and (existing_stay.created_by!=actor or existing_stay.adults!=int(b.get('adults',1)) or existing_stay.children!=int(b.get('children',0)) or existing_stay.extra_beds!=int(b.get('extra_beds',0))):raise ValueError('IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST')
    return out(old)
   h=s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug==slug,HostedDirectHotelRow.state=='PUBLISHED_REQUEST_ONLY'));offer=s.get(HostedDirectRoomOfferRow,b['hosted_offer_id'],with_for_update=True)
   if not h or not offer or offer.hosted_hotel_id!=h.hosted_hotel_id or offer.state!='ACTIVE':raise ValueError('ACTIVE_HOSTED_OFFER_REQUIRED')
   variant=s.scalar(select(HostedDirectRateVariantRow).where(HostedDirectRateVariantRow.hosted_offer_id==offer.hosted_offer_id))
   if not variant or variant.state!='ACTIVE':raise ValueError('DATED_MANAGED_RATE_REQUIRED')
   from go_hotel.db.models import HostedFareRuleVersionRow
   current_rule=s.scalar(select(HostedFareRuleVersionRow).where(HostedFareRuleVersionRow.hosted_offer_id==offer.hosted_offer_id).order_by(HostedFareRuleVersionRow.version.desc()))
   if current_rule and b.get('expected_fare_rule_hash')!=current_rule.rule_hash:raise ValueError('FARE_RULE_CHANGED_RECONFIRM_REQUIRED')
   adults=int(b.get('adults',1));children=int(b.get('children',0));extra_beds=int(b.get('extra_beds',0));nights=(cout-cin).days;advance=(cin-date.today()).days
   if adults<1 or children<0 or extra_beds<0 or nights>370:raise ValueError('INVALID_OCCUPANCY_OR_STAY_LENGTH')
   if not str(b.get('guest_name','')).strip() or not str(b.get('guest_contact','')).strip():raise ValueError('GUEST_NAME_AND_CONTACT_REQUIRED')
   timeout=int(b.get('confirmation_timeout_minutes',30))
   if not 1<=timeout<=120:raise ValueError('CONFIRMATION_TIMEOUT_1_TO_120_REQUIRED')
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
   amount=sum(x.price_minor for x in rates)
   if b.get('expected_total_minor') is not None and b['expected_total_minor']!=amount:raise ValueError('PRICE_CHANGED_RECONFIRM_REQUIRED')
   r=HostedDirectReservationRow(hosted_reservation_id=ident('hdr'),hosted_offer_id=offer.hosted_offer_id,idempotency_key=key,guest_name=b['guest_name'],guest_contact=b['guest_contact'],check_in=b['check_in'],check_out=b['check_out'],amount_minor=amount,currency=offer.currency,reservation_state='PENDING_HOTEL_CONFIRMATION',payment_state='ALIPAY_APPLICATION_PENDING_NO_CHARGE',hotel_confirmation_reference=None,created_at=now(),updated_at=now());s.add(r);s.flush()
   expiry=now()+timedelta(minutes=int(b.get('confirmation_timeout_minutes',30)));s.add(HostedReservationStayRow(hosted_reservation_id=r.hosted_reservation_id,source=source,adults=adults,children=children,extra_beds=extra_beds,operational_state='PENDING_HOTEL_CONFIRMATION',confirmation_expires_at=expiry,created_by=actor,updated_at=now()))
   for rate,inv in zip(rates,inventory):s.add(HostedReservationNightRow(reservation_night_id=ident('hrn'),hosted_reservation_id=r.hosted_reservation_id,inventory_day_id=inv.inventory_day_id,stay_date=rate.stay_date,price_minor=rate.price_minor,state='HELD'))
   from go_hotel.services.hosted_fare_rules import snapshot_in_session
   snapshot_in_session(s,r)
   self._event(s,r.hosted_reservation_id,'RESERVATION_REQUESTED',actor,{'source':source,'payment_attempted':False});self._notify(s,r.hosted_reservation_id,'HOTEL','RESERVATION_REQUESTED',{'source':source});self._notify(s,r.hosted_reservation_id,'GUEST','RESERVATION_RECEIVED',{'payment_captured':False});
   if _session is None:s.commit()
   return out(r)
 def action(self,reservation_id,b,actor,expected_owner=None,pending_only=False,release_simulated=False):
  action=b.get('action')
  if action not in ('CONFIRM','REJECT','CANCEL'):raise ValueError('VALID_RESERVATION_ACTION_REQUIRED')
  with managed_session() as s:
   stay=s.get(HostedReservationStayRow,reservation_id,with_for_update=True);r=s.get(HostedDirectReservationRow,reservation_id,with_for_update=True)
   if not r or not stay:raise ValueError('MANAGED_RESERVATION_NOT_FOUND')
   if expected_owner is not None and stay.created_by!=expected_owner:raise ValueError('MANAGED_RESERVATION_NOT_FOUND')
   terminal={'CANCEL':'CANCELLED','REJECT':'REJECTED','CONFIRM':'CONFIRMED'}[action]
   if stay.operational_state==terminal:return out(r)
   from go_hotel.db.models import HostedOrderFareSnapshotRow
   if action=='CANCEL' and stay.operational_state=='CONFIRMED' and s.get(HostedOrderFareSnapshotRow,reservation_id):raise ValueError('CONFIRMED_CANCELLATION_FARE_QUOTE_REQUIRED')
   if pending_only and stay.operational_state!='PENDING_HOTEL_CONFIRMATION':raise ValueError('RESERVATION_NOT_PENDING')
   if stay.operational_state not in ('PENDING_HOTEL_CONFIRMATION','CONFIRMED'):raise ValueError('RESERVATION_ACTION_NOT_ALLOWED')
   if action=='REJECT' and stay.operational_state!='PENDING_HOTEL_CONFIRMATION':raise ValueError('RESERVATION_NOT_PENDING')
   if action=='CONFIRM' and aware(stay.confirmation_expires_at)<=now():raise ValueError('RESERVATION_CONFIRMATION_EXPIRED')
   if action=='CONFIRM':
    if stay.operational_state!='PENDING_HOTEL_CONFIRMATION':raise ValueError('RESERVATION_NOT_PENDING')
    stay.operational_state='CONFIRMED';r.reservation_state='HOTEL_CONFIRMED_AWAITING_ALIPAY_ONBOARDING';r.hotel_confirmation_reference=b.get('hotel_confirmation_reference') or ident('hotel_confirm');template='RESERVATION_CONFIRMED'
   else:
    if (release_simulated or action=='REJECT') and r.payment_state=='CONTRACT_AUTHORIZED_NOT_ALIPAY':
     from go_hotel.services.hosted_checkout import release_contract_in_session
     release_contract_in_session(s,r,'FREE_CANCELLATION' if action=='CANCEL' else 'HOTEL_REJECTED')
    if not payment_clear_for_inventory_change(s,r):raise ValueError('PAYMENT_RELEASE_OR_REFUND_REQUIRED')
    stay.operational_state='REJECTED' if action=='REJECT' else 'CANCELLED';r.reservation_state='HOTEL_REJECTED' if action=='REJECT' else 'CANCELLED';r.payment_state='NO_PAYMENT_NO_REFUND_REQUIRED';self._release(s,reservation_id);template='RESERVATION_'+stay.operational_state
   stay.updated_at=r.updated_at=now();self._event(s,reservation_id,'HOTEL_'+action,actor,{'payment_captured':False,'refund_required':False});self._notify(s,reservation_id,'GUEST',template,{'payment_captured':False});s.commit();return out(r)
 def expire_pending(self,actor='SYSTEM'):
  with managed_session() as s:
   rows=s.scalars(select(HostedReservationStayRow).where(HostedReservationStayRow.operational_state=='PENDING_HOTEL_CONFIRMATION',HostedReservationStayRow.confirmation_expires_at<now()).with_for_update()).all()
   processed=blocked=0
   for stay in rows:
    reservation=s.get(HostedDirectReservationRow,stay.hosted_reservation_id)
    if reservation.payment_state=='CONTRACT_AUTHORIZED_NOT_ALIPAY':
     from go_hotel.services.hosted_checkout import release_contract_in_session
     try:release_contract_in_session(s,reservation,'CONFIRMATION_TIMEOUT')
     except ValueError:blocked+=1;continue
    if not payment_clear_for_inventory_change(s,reservation):blocked+=1;continue
    processed+=1
    r=s.get(HostedDirectReservationRow,stay.hosted_reservation_id);stay.operational_state='EXPIRED';r.reservation_state='HOTEL_CONFIRMATION_TIMEOUT';r.payment_state='NO_PAYMENT_NO_REFUND_REQUIRED';stay.updated_at=r.updated_at=now();self._release(s,r.hosted_reservation_id);self._event(s,r.hosted_reservation_id,'CONFIRMATION_TIMEOUT',actor,{'inventory_released':True});self._notify(s,r.hosted_reservation_id,'GUEST','CONFIRMATION_TIMEOUT',{})
   s.commit();return {'expired_count':processed,'inventory_released':processed,'payment_reconciliation_required':blocked,'payment_live':False}
 def reschedule(self,reservation_id,b,actor):
  try:cin=date.fromisoformat(b['check_in']);cout=date.fromisoformat(b['check_out'])
  except Exception:raise ValueError('VALID_STAY_DATES_REQUIRED')
  if cout<=cin:raise ValueError('CHECK_OUT_MUST_FOLLOW_CHECK_IN')
  with managed_session() as s:
   stay=s.get(HostedReservationStayRow,reservation_id,with_for_update=True);r=s.get(HostedDirectReservationRow,reservation_id,with_for_update=True)
   if not r or not stay or stay.operational_state not in ('PENDING_HOTEL_CONFIRMATION','CONFIRMED'):raise ValueError('RESERVATION_NOT_RESCHEDULABLE')
   if stay.operational_state=='PENDING_HOTEL_CONFIRMATION' and aware(stay.confirmation_expires_at)<=now():raise ValueError('RESERVATION_CONFIRMATION_EXPIRED')
   from go_hotel.db.models import GuestStayLifecycleRow
   guest=s.scalar(select(GuestStayLifecycleRow).where(GuestStayLifecycleRow.hosted_reservation_id==reservation_id))
   if guest and guest.state!='PRE_ARRIVAL':raise ValueError('RESCHEDULE_REQUIRES_PRE_ARRIVAL')
   if not payment_clear_for_inventory_change(s,r):raise ValueError('PAYMENT_ADJUSTMENT_REQUIRED')
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
  for n in nights:
   claimed=s.execute(update(HostedReservationNightRow).where(HostedReservationNightRow.reservation_night_id==n.reservation_night_id,HostedReservationNightRow.state=='HELD').values(state='RELEASED')).rowcount
   if claimed:
    changed=s.execute(update(HostedInventoryDayRow).where(HostedInventoryDayRow.inventory_day_id==n.inventory_day_id,HostedInventoryDayRow.capacity_available<HostedInventoryDayRow.capacity_total).values(capacity_available=HostedInventoryDayRow.capacity_available+1,updated_at=now())).rowcount
    if changed!=1:raise ValueError('INVENTORY_RELEASE_INVARIANT_FAILED')
 def _event(self,s,rid,typ,actor,payload):
  s.add(HostedDirectReservationEventRow(hosted_event_id=ident('hde'),hosted_reservation_id=rid,event_type=typ,actor_id=actor,payload_json=payload,occurred_at=now()))
  from go_hotel.services.hosted_money import project
  project(s,s.get(HostedDirectReservationRow,rid),typ)
 def _notify(self,s,rid,recipient,template,payload):s.add(HostedReservationNotificationRow(notification_id=ident('hrnfy'),hosted_reservation_id=rid,recipient_type=recipient,channel='OPERATIONS_OUTBOX',template_key=template,delivery_state='QUEUED_NOT_SENT',payload_json=payload,created_at=now()))
 def dashboard(self,hotel_id):
  with managed_session() as s:
   pools=s.scalars(select(HostedDirectInventoryPoolRow).where(HostedDirectInventoryPoolRow.hosted_hotel_id==hotel_id)).all();pool_ids=[x.inventory_pool_id for x in pools];days=s.scalars(select(HostedInventoryDayRow).where(HostedInventoryDayRow.inventory_pool_id.in_(pool_ids))).all() if pool_ids else [];reservation_ids=select(HostedDirectReservationRow.hosted_reservation_id).join(HostedDirectRoomOfferRow,HostedDirectRoomOfferRow.hosted_offer_id==HostedDirectReservationRow.hosted_offer_id).where(HostedDirectRoomOfferRow.hosted_hotel_id==hotel_id);stays=s.scalars(select(HostedReservationStayRow).where(HostedReservationStayRow.hosted_reservation_id.in_(reservation_ids))).all()
   return {'inventory_days':len(days),'closed_or_sold_out':sum(x.sale_state!='OPEN' for x in days),'reservations_by_state':{state:sum(x.operational_state==state for x in stays) for state in sorted({x.operational_state for x in stays})},'notifications_queued_not_sent':s.query(HostedReservationNotificationRow).filter(HostedReservationNotificationRow.delivery_state=='QUEUED_NOT_SENT',HostedReservationNotificationRow.hosted_reservation_id.in_(reservation_ids)).count(),'alipay_state':'SANDBOX_APPLICATION_NOT_CREATED','payment_live':False,'production_live':False}

hosted_reservation_operations_service=HostedReservationOperationsService()
