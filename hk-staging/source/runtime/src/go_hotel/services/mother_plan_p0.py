from __future__ import annotations
from datetime import datetime,timezone,timedelta
import hashlib,json,uuid
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import FlightOrderRow,MobilityRideOrderRow,FlightCheckInStateRow,FlightCheckInEventRow,RideFlightTrackingBindingRow,RideFlightSyncEventRow,GoOfferRequirementRow,GoOfferQuoteRow,HotelPartnerGoOfferAuthorityRow,HotelPartnerPropertyRow,GoOfferPrebookRow,GoOfferOrderHandoffRow,GoOfferLifecycleEventRow

CHECKIN={'CHECK_IN_NOT_OPEN','CHECK_IN_OPEN','CHECKED_IN','BOARDING_PASS_AVAILABLE'}
CHECKIN_RANK={'CHECK_IN_NOT_OPEN':0,'CHECK_IN_OPEN':1,'CHECKED_IN':2,'BOARDING_PASS_AVAILABLE':3}
FLIGHT_EVENTS={'DELAYED','EARLY','LANDED'}
def now():return datetime.now(timezone.utc)
def as_utc(value):
 if value is None:return None
 return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
def ident(p):return f'{p}_{uuid.uuid4().hex}'
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
def out(r):return {c.name:(getattr(r,c.name).isoformat() if isinstance(getattr(r,c.name),datetime) else getattr(r,c.name)) for c in r.__table__.columns}
def parse_dt(v):return datetime.fromisoformat(v.replace('Z','+00:00'))

class MotherPlanP0Service:
 def _offer_event(self,s,rid,event,actor,payload):
  h=digest({'requirement_id':rid,'event_type':event,'actor_id':actor,'payload':payload})
  s.add(GoOfferLifecycleEventRow(go_offer_lifecycle_event_id=ident('goev'),requirement_id=rid,event_type=event,actor_id=actor,payload_json=payload,evidence_hash=h,occurred_at=now()))
 def checkin(self,account,order_id):
  with SessionLocal.begin() as s:
   o=s.get(FlightOrderRow,order_id)
   if not o or o.account_id!=account:raise ValueError('FLIGHT_ORDER_NOT_FOUND')
   r=s.scalar(select(FlightCheckInStateRow).where(FlightCheckInStateRow.flight_order_id==order_id))
   if not r:
    r=FlightCheckInStateRow(flight_check_in_state_id=ident('fcis'),flight_order_id=order_id,state='CHECK_IN_NOT_OPEN',check_in_opens_at=None,official_check_in_url=None,boarding_pass_reference=None,source_type='GO_DERIVED_INITIAL',source_authority_reference=None,source_fact_hash=None,updated_at=now());s.add(r);s.flush()
   return out(r)|{'external_check_in_only':True,'go_does_not_fabricate_success':True}
 def ingest_checkin(self,order_id,b,actor):
  state=b['state'];source=b.get('source_type')
  if state not in CHECKIN:raise ValueError('INVALID_FLIGHT_CHECK_IN_STATE')
  if source not in {'AIRLINE_OFFICIAL','AUTHORIZED_AIRLINE_PROVIDER'} or not b.get('source_authority_reference'):raise ValueError('AUTHORIZED_CHECK_IN_FACT_REQUIRED')
  if state=='BOARDING_PASS_AVAILABLE' and not b.get('boarding_pass_reference'):raise ValueError('BOARDING_PASS_REFERENCE_REQUIRED')
  payload={k:b.get(k) for k in ('state','check_in_opens_at','official_check_in_url','boarding_pass_reference','source_type','source_authority_reference')}
  with SessionLocal.begin() as s:
   if not s.get(FlightOrderRow,order_id):raise ValueError('FLIGHT_ORDER_NOT_FOUND')
   r=s.scalar(select(FlightCheckInStateRow).where(FlightCheckInStateRow.flight_order_id==order_id));prev=r.state if r else None
   if prev and CHECKIN_RANK[state]<CHECKIN_RANK[prev]:raise ValueError('FLIGHT_CHECK_IN_STATE_REGRESSION_FORBIDDEN')
   vals=dict(state=state,check_in_opens_at=parse_dt(b['check_in_opens_at']) if b.get('check_in_opens_at') else None,official_check_in_url=b.get('official_check_in_url'),boarding_pass_reference=b.get('boarding_pass_reference'),source_type=source,source_authority_reference=b['source_authority_reference'],source_fact_hash=digest(payload),updated_at=now())
   if not r:r=FlightCheckInStateRow(flight_check_in_state_id=ident('fcis'),flight_order_id=order_id,**vals);s.add(r)
   else:
    for k,v in vals.items():setattr(r,k,v)
   s.add(FlightCheckInEventRow(flight_check_in_event_id=ident('fciev'),flight_order_id=order_id,previous_state=prev,current_state=state,payload_hash=digest(payload),source_type=source,source_authority_reference=b['source_authority_reference'],occurred_at=now()));s.flush();return out(r)
 def bind_ride(self,account,ride_id,b):
  if not b.get('flight_no'):raise ValueError('FLIGHT_NUMBER_REQUIRED')
  included=max(0,int(b.get('included_wait_minutes',60)));extra=max(0,int(b.get('delay_protection_free_wait_minutes',0)));cap=max(included,int(b.get('max_free_wait_minutes',included+extra)))
  with SessionLocal.begin() as s:
   ride=s.get(MobilityRideOrderRow,ride_id)
   if not ride or ride.account_id!=account:raise ValueError('MOBILITY_ORDER_NOT_FOUND')
   r=s.scalar(select(RideFlightTrackingBindingRow).where(RideFlightTrackingBindingRow.ride_order_id==ride_id));vals=dict(flight_no=b['flight_no'].upper().replace(' ',''),tracking_enabled=bool(b.get('tracking_enabled',True)),original_pickup_at=ride.pickup_at,current_pickup_at=ride.pickup_at,included_wait_minutes=included,delay_protection_enabled=bool(b.get('delay_protection_enabled',False)),delay_protection_free_wait_minutes=extra,max_free_wait_minutes=cap,supplier_rule_snapshot_json=b.get('supplier_rule_snapshot',{}),sync_state='TRACKING_ACTIVE',updated_at=now())
   if not r:r=RideFlightTrackingBindingRow(ride_flight_tracking_binding_id=ident('rftb'),ride_order_id=ride_id,**vals);s.add(r)
   else:
    for k,v in vals.items():setattr(r,k,v)
   s.flush();return out(r)
 def ingest_flight_event(self,b,actor):
  typ=b['event_type'];authority=b.get('source_authority_reference');flight=b['flight_no'].upper().replace(' ','')
  if typ not in FLIGHT_EVENTS:raise ValueError('INVALID_VERIFIED_FLIGHT_EVENT')
  if not authority:raise ValueError('VERIFIED_FLIGHT_AUTHORITY_REQUIRED')
  verified=b.get('verified_arrival_at')
  if not verified:raise ValueError('VERIFIED_ARRIVAL_TIME_REQUIRED')
  idem=b.get('idempotency_key') or digest({'flight':flight,'type':typ,'at':verified,'authority':authority})
  with SessionLocal.begin() as s:
   bindings=s.scalars(select(RideFlightTrackingBindingRow).where(RideFlightTrackingBindingRow.flight_no==flight,RideFlightTrackingBindingRow.tracking_enabled.is_(True))).all();events=[]
   for x in bindings:
    event_key=idem+':'+x.ride_order_id
    existing=s.scalar(select(RideFlightSyncEventRow).where(RideFlightSyncEventRow.idempotency_key==event_key))
    if existing:events.append(out(existing));continue
    ride=s.get(MobilityRideOrderRow,x.ride_order_id);previous=ride.pickup_at
    adjusted=verified if typ in {'DELAYED','EARLY','LANDED'} else previous
    ride.pickup_at=adjusted;ride.updated_at=now();x.current_pickup_at=adjusted;x.sync_state='PENDING_EXTERNAL_CONFIRMATION';x.updated_at=now()
    free=min(x.max_free_wait_minutes,x.included_wait_minutes+(x.delay_protection_free_wait_minutes if x.delay_protection_enabled else 0))
    evidence={'flight_no':flight,'event_type':typ,'verified_arrival_at':verified,'previous_pickup_at':previous,'adjusted_pickup_at':adjusted,'authority':authority,'rule_snapshot':x.supplier_rule_snapshot_json}
    e=RideFlightSyncEventRow(ride_flight_sync_event_id=ident('rfse'),ride_order_id=ride.order_id,flight_event_type=typ,verified_flight_time=verified,previous_pickup_at=previous,adjusted_pickup_at=adjusted,free_wait_minutes=free,external_mutation_invoked=False,external_confirmation_state='PENDING_EXTERNAL_CONFIRMATION',source_authority_reference=authority,idempotency_key=event_key,evidence_hash=digest(evidence),created_at=now());s.add(e);s.flush();events.append(out(e))
   return {'events':events,'matched_rides':len(events),'production_fleet_mutation_live':False,'supplier_confirmation_required':True}
 def ride_tracking(self,account,ride_id):
  with SessionLocal() as s:
   ride=s.get(MobilityRideOrderRow,ride_id)
   if not ride or ride.account_id!=account:raise ValueError('MOBILITY_ORDER_NOT_FOUND')
   b=s.scalar(select(RideFlightTrackingBindingRow).where(RideFlightTrackingBindingRow.ride_order_id==ride_id));ev=s.scalars(select(RideFlightSyncEventRow).where(RideFlightSyncEventRow.ride_order_id==ride_id).order_by(RideFlightSyncEventRow.created_at)).all()
   return {'binding':out(b) if b else None,'events':[out(x) for x in ev]}
 def create_requirement(self,account,b):
  if any(k in b for k in ('voice','audio','microphone_input')):raise ValueError('MICROPHONE_FORBIDDEN_ON_REQUIREMENT_BUILDER')
  required={'destination','check_in','check_out','rooms','adults'}
  if not required.issubset(b):raise ValueError('STRUCTURED_REQUIREMENT_FIELDS_REQUIRED')
  typ=b.get('requirement_type') or ('MEETING_OR_EVENT' if b.get('meeting') or b.get('event') else 'ROOM_ONLY')
  if typ not in {'ROOM_ONLY','MEETING_OR_EVENT'}:raise ValueError('INVALID_GO_OFFER_REQUIREMENT_TYPE')
  prop=b.get('property_id');mode=None;state='SUBMITTED';quote=None
  with SessionLocal.begin() as s:
   auth=s.scalar(select(HotelPartnerGoOfferAuthorityRow).where(HotelPartnerGoOfferAuthorityRow.property_id==prop,HotelPartnerGoOfferAuthorityRow.requirement_type==typ,HotelPartnerGoOfferAuthorityRow.state=='ACTIVE')) if prop else None
   if auth:mode=auth.quote_mode
   state='AWAITING_MANUAL_QUOTE' if mode=='MANUAL_QUOTE' else 'SYSTEM_QUOTE_READY' if mode=='SYSTEM_GENERATED' else 'AWAITING_HOTEL_CONFIGURATION'
   t=now();r=GoOfferRequirementRow(go_offer_requirement_id=ident('goreq'),account_id=account,property_id=prop,requirement_type=typ,structured_requirement_json=b,quote_mode=mode,state=state,microphone_input_allowed=False,created_at=t,updated_at=t);s.add(r);s.flush()
   if auth and mode=='SYSTEM_GENERATED':
    floor=auth.price_floor_json or {};amount=int(floor.get('amount_minor') or floor.get('amount') or 0);valid=auth.validity_json or {};mins=int(valid.get('minutes',30));pkg=(auth.packages_json or [{}])[0] if isinstance(auth.packages_json,list) else auth.packages_json
    q=GoOfferQuoteRow(go_offer_quote_id=ident('goq'),go_offer_requirement_id=r.go_offer_requirement_id,property_id=prop,quote_mode=mode,amount_minor=amount,currency=b.get('currency','CNY'),package_json=pkg or {},conditions_json=auth.conditions_json or {},expires_at=t+timedelta(minutes=mins),state='QUOTED',source_scope='GO_OFFER_DEDICATED',created_at=t);s.add(q);s.flush();quote=out(q)
   return {'requirement':out(r),'quote':quote,'ordinary_bar_member_inventory_used':False}
 def requirement(self,account,rid):
  with SessionLocal() as s:
   r=s.get(GoOfferRequirementRow,rid)
   if not r or r.account_id!=account:raise ValueError('GO_OFFER_REQUIREMENT_NOT_FOUND')
   qs=s.scalars(select(GoOfferQuoteRow).where(GoOfferQuoteRow.go_offer_requirement_id==rid)).all();return {'requirement':out(r),'quotes':[out(x) for x in qs]}
 def manual_quote(self,supplier,rid,b):
  with SessionLocal.begin() as s:
   r=s.get(GoOfferRequirementRow,rid)
   if not r or not r.property_id:raise ValueError('GO_OFFER_REQUIREMENT_NOT_FOUND')
   prop=s.get(HotelPartnerPropertyRow,r.property_id)
   if not prop or prop.supplier_id!=supplier:raise ValueError('GO_OFFER_REQUIREMENT_NOT_FOUND')
   auth=s.scalar(select(HotelPartnerGoOfferAuthorityRow).where(HotelPartnerGoOfferAuthorityRow.property_id==r.property_id,HotelPartnerGoOfferAuthorityRow.requirement_type==r.requirement_type,HotelPartnerGoOfferAuthorityRow.state=='ACTIVE'))
   if not auth or auth.quote_mode!='MANUAL_QUOTE':raise ValueError('MANUAL_QUOTE_NOT_AUTHORIZED')
   if int(b.get('amount_minor',0))<=0:raise ValueError('VALID_QUOTE_AMOUNT_REQUIRED')
   t=now();q=GoOfferQuoteRow(go_offer_quote_id=ident('goq'),go_offer_requirement_id=rid,property_id=r.property_id,quote_mode='MANUAL_QUOTE',amount_minor=int(b['amount_minor']),currency=b.get('currency','CNY'),package_json=b.get('package',{}),conditions_json=b.get('conditions',{}),expires_at=t+timedelta(minutes=int(b.get('validity_minutes',30))),state='QUOTED',source_scope='GO_OFFER_DEDICATED',created_at=t);s.add(q);r.state='QUOTE_READY';r.updated_at=t;s.flush();return out(q)
 def accept_quote(self,account,rid,qid):
  with SessionLocal.begin() as s:
   r=s.get(GoOfferRequirementRow,rid);q=s.get(GoOfferQuoteRow,qid)
   if not r or r.account_id!=account or not q or q.go_offer_requirement_id!=rid:raise ValueError('GO_OFFER_QUOTE_NOT_FOUND')
   if q.state!='QUOTED' or (q.expires_at and q.expires_at.replace(tzinfo=q.expires_at.tzinfo or timezone.utc)<=now()):raise ValueError('GO_OFFER_QUOTE_NOT_ACCEPTABLE')
   for other in s.scalars(select(GoOfferQuoteRow).where(GoOfferQuoteRow.go_offer_requirement_id==rid)).all():
    if other.go_offer_quote_id!=qid and other.state=='QUOTED':other.state='NOT_SELECTED'
   q.state='SELECTED';r.state='SELECTED_QUOTE_REQUIRES_PREBOOK_REVALIDATION';r.updated_at=now();self._offer_event(s,rid,'QUOTE_SELECTED',account,{'quote_id':qid,'booking_created':False});s.flush();return {'requirement':out(r),'quote':out(q),'booking_created':False,'revalidation_required':True}
 def start_prebook(self,account,rid,qid,b):
  idem=b.get('idempotency_key')
  if not idem:raise ValueError('IDEMPOTENCY_KEY_REQUIRED')
  with SessionLocal.begin() as s:
   old=s.scalar(select(GoOfferPrebookRow).where(GoOfferPrebookRow.idempotency_key==idem))
   if old:
    if old.account_id!=account or old.requirement_id!=rid or old.quote_id!=qid:raise ValueError('IDEMPOTENCY_KEY_CONFLICT')
    return out(old)
   r=s.get(GoOfferRequirementRow,rid);q=s.get(GoOfferQuoteRow,qid)
   if not r or r.account_id!=account or not q or q.go_offer_requirement_id!=rid or q.state!='SELECTED':raise ValueError('SELECTED_GO_OFFER_QUOTE_REQUIRED')
   t=now()
   if q.expires_at and q.expires_at.replace(tzinfo=q.expires_at.tzinfo or timezone.utc)<=t:q.state='EXPIRED';r.state='QUOTE_EXPIRED';raise ValueError('GO_OFFER_QUOTE_EXPIRED')
   snap={'requirement':r.structured_requirement_json,'quote':out(q)};state='PENDING_SUPPLIER_REVALIDATION';amount=None;evidence=None;confirmation=None
   auth=s.scalar(select(HotelPartnerGoOfferAuthorityRow).where(HotelPartnerGoOfferAuthorityRow.property_id==q.property_id,HotelPartnerGoOfferAuthorityRow.requirement_type==r.requirement_type,HotelPartnerGoOfferAuthorityRow.state=='ACTIVE'))
   if q.quote_mode=='SYSTEM_GENERATED':
    if not auth or auth.quote_mode!='SYSTEM_GENERATED':raise ValueError('GO_OFFER_DEDICATED_AUTHORITY_NOT_ACTIVE')
    current=int((auth.price_floor_json or {}).get('amount_minor') or (auth.price_floor_json or {}).get('amount') or 0)
    if current!=q.amount_minor:r.state='REVALIDATION_PRICE_CHANGED';state='PRICE_CHANGED';amount=current
    else:r.state='PREBOOK_REVALIDATED';state='REVALIDATED';amount=current;confirmation='SYSTEM_DEDICATED_AUTHORITY_REVALIDATED';evidence=digest({'authority_id':auth.go_offer_authority_id,'quote_id':qid,'amount_minor':current,'conditions':auth.conditions_json})
   else:r.state='PENDING_SUPPLIER_REVALIDATION'
   p=GoOfferPrebookRow(go_offer_prebook_id=ident('gopb'),requirement_id=rid,quote_id=qid,account_id=account,state=state,quoted_amount_minor=int(q.amount_minor or 0),revalidated_amount_minor=amount,currency=q.currency,quote_snapshot_hash=digest(snap),revalidation_evidence_hash=evidence,supplier_confirmation_reference=confirmation,idempotency_key=idem,expires_at=min(as_utc(q.expires_at),t+timedelta(minutes=15)) if q.expires_at else t+timedelta(minutes=15),created_at=t,updated_at=t);s.add(p);r.updated_at=t;self._offer_event(s,rid,'PREBOOK_REVALIDATION_STARTED',account,{'prebook_id':p.go_offer_prebook_id,'state':state});s.flush();return out(p)
 def supplier_revalidate(self,supplier,prebook_id,b,actor):
  with SessionLocal.begin() as s:
   p=s.get(GoOfferPrebookRow,prebook_id)
   if not p:raise ValueError('GO_OFFER_PREBOOK_NOT_FOUND')
   r=s.get(GoOfferRequirementRow,p.requirement_id);q=s.get(GoOfferQuoteRow,p.quote_id);prop=s.get(HotelPartnerPropertyRow,q.property_id)
   if not prop or prop.supplier_id!=supplier:raise ValueError('GO_OFFER_PREBOOK_NOT_FOUND')
   if p.state!='PENDING_SUPPLIER_REVALIDATION':raise ValueError('GO_OFFER_PREBOOK_STATE_CONFLICT')
   if p.expires_at and p.expires_at.replace(tzinfo=p.expires_at.tzinfo or timezone.utc)<=now():p.state='EXPIRED';r.state='PREBOOK_EXPIRED';raise ValueError('GO_OFFER_PREBOOK_EXPIRED')
   ref=b.get('supplier_confirmation_reference')
   if not ref:raise ValueError('SUPPLIER_CONFIRMATION_REFERENCE_REQUIRED')
   available=bool(b.get('available'));amount=int(b.get('amount_minor',0));ev={'available':available,'amount_minor':amount,'currency':b.get('currency',p.currency),'conditions':b.get('conditions',{}),'supplier_confirmation_reference':ref}
   p.revalidated_amount_minor=amount;p.supplier_confirmation_reference=ref;p.revalidation_evidence_hash=digest(ev);p.updated_at=now()
   if not available:p.state='INVENTORY_CHANGED';r.state='REVALIDATION_INVENTORY_CHANGED'
   elif amount!=p.quoted_amount_minor:p.state='PRICE_CHANGED';r.state='REVALIDATION_PRICE_CHANGED'
   elif b.get('conditions_changed'):p.state='TERMS_CHANGED';r.state='REVALIDATION_TERMS_CHANGED'
   else:p.state='REVALIDATED';r.state='PREBOOK_REVALIDATED'
   r.updated_at=now();self._offer_event(s,r.go_offer_requirement_id,'SUPPLIER_PREBOOK_REVALIDATED',actor,{'prebook_id':prebook_id,'state':p.state,'evidence_hash':p.revalidation_evidence_hash});s.flush();return out(p)
 def order_handoff(self,account,prebook_id,b):
  idem=b.get('idempotency_key')
  if not idem:raise ValueError('IDEMPOTENCY_KEY_REQUIRED')
  with SessionLocal.begin() as s:
   old=s.scalar(select(GoOfferOrderHandoffRow).where(GoOfferOrderHandoffRow.idempotency_key==idem))
   if old:
    if old.account_id!=account or old.go_offer_prebook_id!=prebook_id:raise ValueError('IDEMPOTENCY_KEY_CONFLICT')
    return out(old)
   p=s.get(GoOfferPrebookRow,prebook_id)
   if not p or p.account_id!=account:raise ValueError('GO_OFFER_PREBOOK_NOT_FOUND')
   if p.state!='REVALIDATED':raise ValueError('GO_OFFER_PREBOOK_REVALIDATION_REQUIRED')
   if p.expires_at and p.expires_at.replace(tzinfo=p.expires_at.tzinfo or timezone.utc)<=now():p.state='EXPIRED';raise ValueError('GO_OFFER_PREBOOK_EXPIRED')
   r=s.get(GoOfferRequirementRow,p.requirement_id);payload={'requirement_id':p.requirement_id,'quote_id':p.quote_id,'prebook_id':prebook_id,'amount_minor':p.revalidated_amount_minor,'currency':p.currency,'traveler_ids':b.get('traveler_ids',[]),'checkout_required':True}
   h=GoOfferOrderHandoffRow(go_offer_order_handoff_id=ident('gooh'),go_offer_prebook_id=prebook_id,account_id=account,state='READY_FOR_CHECKOUT',downstream_order_id=None,checkout_payload_json=payload,idempotency_key=idem,evidence_hash=digest(payload),created_at=now(),updated_at=now());s.add(h);p.state='HANDED_OFF_TO_ORDER';p.updated_at=now();r.state='ORDER_HANDOFF_READY_FOR_CHECKOUT';r.updated_at=now();self._offer_event(s,r.go_offer_requirement_id,'ORDER_HANDOFF_CREATED',account,{'handoff_id':h.go_offer_order_handoff_id,'booking_confirmed':False,'payment_captured':False});s.flush();return out(h)|{'booking_confirmed':False,'payment_captured':False}
 def supplier_requirements(self,supplier):
  with SessionLocal() as s:
   props=s.scalars(select(HotelPartnerPropertyRow).where(HotelPartnerPropertyRow.supplier_id==supplier)).all();ids=[x.property_id for x in props]
   if not ids:return []
   return [out(x) for x in s.scalars(select(GoOfferRequirementRow).where(GoOfferRequirementRow.property_id.in_(ids)).order_by(GoOfferRequirementRow.updated_at.desc())).all()]
 def admin_offer_status(self):
  with SessionLocal() as s:
   rs=s.scalars(select(GoOfferRequirementRow).order_by(GoOfferRequirementRow.updated_at.desc())).all();ps=s.scalars(select(GoOfferPrebookRow).order_by(GoOfferPrebookRow.updated_at.desc())).all();hs=s.scalars(select(GoOfferOrderHandoffRow).order_by(GoOfferOrderHandoffRow.updated_at.desc())).all();return {'requirements':[out(x) for x in rs],'prebooks':[out(x) for x in ps],'handoffs':[out(x) for x in hs]}
mother_plan_p0_service=MotherPlanP0Service()
