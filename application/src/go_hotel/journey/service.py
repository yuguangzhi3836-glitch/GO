import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import exists, func, or_, select, tuple_
from go_hotel.core.config import settings
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    GoJourneyRow,GoJourneyItemRow,OrderRow,FlightOrderRow,RailOrderRow,
    MobilityRideOrderRow,MobilityRentalOrderRow,AttractionOrderRow,ConsumerTripMemberRow
)

VERTICALS={
 "HOTEL":(OrderRow,"OrderDetail"),"FLIGHT":(FlightOrderRow,"FlightTripDetail"),"RAIL":(RailOrderRow,"RailTripDetail"),
 "RIDE":(MobilityRideOrderRow,"MobilityTripDetail"),"RENTAL":(MobilityRentalOrderRow,"MobilityTripDetail"),
 "ATTRACTION":(AttractionOrderRow,"AttractionTripDetail"),
}

def _growth_trip_created(account_id,journey_id):
 try:
  from go_hotel.services.consumer_growth_direct_value import consumer_growth_direct_value_service
  consumer_growth_direct_value_service.record_event(account_id,'TRIP_CREATED',source_surface='GO_TRIPS',object_type='JOURNEY',object_id=journey_id,journey_id=journey_id)
 except Exception: pass

def now(): return datetime.now(timezone.utc)

class JourneyService:
 def _order(self,s,account_id,vertical,order_id):
  v=vertical.upper()
  if v not in VERTICALS: raise ValueError("UNSUPPORTED_VERTICAL")
  row=s.get(VERTICALS[v][0],order_id)
  if not row or row.account_id!=account_id: raise ValueError("ORDER_NOT_FOUND")
  return row
 def _default_snapshot(self,v,row):
  if v=="HOTEL": return f"酒店 · {row.hotel_id}", row.supplier_confirmation_no or "住宿订单", None, {"hotel_id":row.hotel_id,"amount_minor":row.total_amount_minor,"currency":row.currency}
  if v=="FLIGHT":
   it=row.current_itinerary or []; seg=it[0] if isinstance(it,list) and it else {}
   return f"航班 · {seg.get('flight_number') or row.pnr or 'Flight'}", f"PNR {row.pnr or '—'}", f"{seg.get('origin','')} → {seg.get('destination','')}", {"pnr":row.pnr,"tickets":row.ticket_numbers,"flight_number":seg.get("flight_number"),"origin":seg.get("origin"),"destination":seg.get("destination"),"amount_minor":row.total_amount_minor,"currency":row.currency}
  if v=="RAIL":
   j=row.current_journey or {}; return f"铁路 · {j.get('train_no') or row.booking_reference or 'Rail'}", f"{j.get('seat_class','')} · {row.booking_reference or ''}", f"{j.get('origin_station','')} → {j.get('destination_station','')}", {"booking_reference":row.booking_reference,"tickets":row.ticket_numbers,"amount_minor":row.total_amount_minor,"currency":row.currency}
  if v=="RIDE": return f"接送 · {row.vehicle_class}", row.pickup_at, f"{row.pickup} → {row.dropoff}", {"flight_no":row.flight_no,"amount_minor":row.total_amount_minor,"currency":row.currency}
  if v=="RENTAL": return f"租车 · {row.vehicle_class}", f"{row.pickup_at} → {row.return_at}", f"{row.pickup_location} → {row.return_location}", {"deposit_minor":row.deposit_minor,"amount_minor":row.total_amount_minor,"currency":row.currency}
  return f"门票/体验 · {row.product_name}", f"{row.visit_date} {row.session_time or ''}".strip(), row.destination, {"voucher_type":row.voucher_type,"voucher_code":row.voucher_code,"quantity":row.quantity,"amount_minor":row.total_amount_minor,"currency":row.currency}
 def create(self,account_id,payload):
  with SessionLocal() as s:
   j=GoJourneyRow(journey_id=f"jny_{uuid4().hex[:18]}",account_id=account_id,title=payload.get("title") or "我的旅行",destination_summary=payload.get("destination_summary"),starts_at=payload.get("starts_at"),ends_at=payload.get("ends_at"),status="UPCOMING",created_at=now(),updated_at=now());s.add(j);s.flush()
   for x in payload.get("items",[]): self._attach(s,j,x)
   s.commit();return self._serialize(s,j)
 def _attach(self,s,j,x):
  v=str(x["vertical"]).upper();row=self._order(s,j.account_id,v,x["order_id"])
  exists=s.execute(select(GoJourneyItemRow).where(GoJourneyItemRow.account_id==j.account_id,GoJourneyItemRow.vertical==v,GoJourneyItemRow.order_id==x["order_id"])).scalar_one_or_none()
  if exists: raise ValueError("ORDER_ALREADY_IN_JOURNEY")
  title,sub,loc,facts=self._default_snapshot(v,row);starts=x.get("starts_at") or getattr(row,"pickup_at",None) or getattr(row,"visit_date",None);ends=x.get("ends_at") or getattr(row,"return_at",None)
  # Caller notes may extend the snapshot; canonical order facts retain priority.
  item=GoJourneyItemRow(item_id=f"jit_{uuid4().hex[:18]}",journey_id=j.journey_id,account_id=j.account_id,vertical=v,order_id=row.order_id,title=x.get("title") or title,subtitle=x.get("subtitle") or sub,location=x.get("location") or loc,starts_at=starts,ends_at=ends,status_snapshot=row.status,facts_json={**(x.get("facts") or {}),**facts},detail_route=VERTICALS[v][1],sort_key=x.get("sort_key") or starts or row.created_at.isoformat(),created_at=now());s.add(item);return item
 def attach(self,account_id,journey_id,x):
  with SessionLocal() as s:
   j=s.get(GoJourneyRow,journey_id)
   if not j or j.account_id!=account_id: raise ValueError("JOURNEY_NOT_FOUND")
   self._attach(s,j,x);j.updated_at=now();s.commit();return self._serialize(s,j)
 def list(self,account_id):
  with SessionLocal() as s:
   owned=s.execute(select(GoJourneyRow).where(GoJourneyRow.account_id==account_id)).scalars().all()
   member_ids=s.execute(select(ConsumerTripMemberRow.journey_id).where(ConsumerTripMemberRow.user_id==account_id,ConsumerTripMemberRow.status=='ACTIVE')).scalars().all()
   shared=s.execute(select(GoJourneyRow).where(GoJourneyRow.journey_id.in_(member_ids))).scalars().all() if member_ids else []
   rows={x.journey_id:x for x in [*owned,*shared]}.values()
   rows=sorted(rows,key=lambda x:(x.starts_at or '',x.created_at))
   # Fetch each item once and current states in bounded owner/order batches.
   # Projection remains read-only and retains historical attachment facts.
   items_by_journey={x.journey_id:[] for x in rows}
   journey_ids=list(items_by_journey)
   for offset in range(0,len(journey_ids),400):
    items=s.execute(select(GoJourneyItemRow).where(GoJourneyItemRow.journey_id.in_(journey_ids[offset:offset+400])).order_by(GoJourneyItemRow.sort_key,GoJourneyItemRow.created_at)).scalars().all()
    for item in items: items_by_journey[item.journey_id].append(item)
   statuses=self._batch_order_statuses(s,rows,items_by_journey)
   return [self._serialize(s,x,refresh=True,items=items_by_journey[x.journey_id],statuses=statuses) for x in rows]
 def _cursor_scope(self, account_id, normalized):
  return hashlib.sha256(f"{account_id}\0{normalized}".encode()).hexdigest()
 def _encode_cursor(self, account_id, normalized, row):
  value={"v":1,"scope":self._cursor_scope(account_id,normalized),"starts_at":row.starts_at,"created_at":(row.created_at if row.created_at.tzinfo is not None else row.created_at.replace(tzinfo=timezone.utc)).isoformat(),"journey_id":row.journey_id}
  raw=json.dumps(value,sort_keys=True,separators=(",",":")).encode()
  sig=hmac.new(settings.jwt_signing_key.encode(),raw,hashlib.sha256).digest()
  return base64.urlsafe_b64encode(raw+sig).decode().rstrip("=")
 def _decode_cursor(self, token, account_id, normalized):
  try:
   packed=base64.urlsafe_b64decode(token+"="*(-len(token)%4))
   if len(packed)<=32: raise ValueError
   raw,sig=packed[:-32],packed[-32:]
   expected=hmac.new(settings.jwt_signing_key.encode(),raw,hashlib.sha256).digest()
   if not hmac.compare_digest(sig,expected): raise ValueError
   value=json.loads(raw)
   if value.get("v")!=1 or value.get("scope")!=self._cursor_scope(account_id,normalized): raise ValueError
   created_at=datetime.fromisoformat(value["created_at"])
   if created_at.tzinfo is None: created_at=created_at.replace(tzinfo=timezone.utc)
   return (value.get("starts_at") or "\uffff",created_at,value["journey_id"])
  except (ValueError,TypeError,KeyError,json.JSONDecodeError):
   raise ValueError("JOURNEY_CURSOR_INVALID") from None
 def list_page(self,account_id,limit=20,offset=0,query=None,cursor=None):
  """Return one bounded, deterministic Journey page.

  Offset pagination is explicit for the first contract version. The stable
  tie-breaker prevents duplicate ordering inside a fixed snapshot; callers
  receive has_more/next_offset and never a full-result count query.
  """
  limit=max(1,min(int(limit),100));offset=max(0,min(int(offset),10000))
  normalized=(query or '').strip().lower()
  if cursor and offset:
   raise ValueError("JOURNEY_CURSOR_OFFSET_CONFLICT")
  cursor_key=self._decode_cursor(cursor,account_id,normalized) if cursor else None
  with SessionLocal() as s:
   active_member=exists(select(ConsumerTripMemberRow.trip_member_id).where(
    ConsumerTripMemberRow.journey_id==GoJourneyRow.journey_id,
    ConsumerTripMemberRow.user_id==account_id,
    ConsumerTripMemberRow.status=='ACTIVE',
   ))
   statement=select(GoJourneyRow).where(or_(GoJourneyRow.account_id==account_id,active_member))
   if normalized:
    pattern=f"%{normalized}%"
    statement=statement.where(or_(
     func.lower(GoJourneyRow.title).like(pattern),
     func.lower(func.coalesce(GoJourneyRow.destination_summary,'')).like(pattern),
    ))
   sort_start=func.coalesce(GoJourneyRow.starts_at,'\uffff')
   if cursor_key:
    statement=statement.where(tuple_(sort_start,GoJourneyRow.created_at,GoJourneyRow.journey_id)>cursor_key)
   ordered=statement.order_by(sort_start.asc(),GoJourneyRow.created_at.asc(),GoJourneyRow.journey_id.asc())
   rows=s.execute(ordered.offset(0 if cursor_key else offset).limit(limit+1)).scalars().all()
   has_more=len(rows)>limit;rows=rows[:limit]
   items_by_journey={x.journey_id:[] for x in rows}
   journey_ids=list(items_by_journey)
   if journey_ids:
    items=s.execute(select(GoJourneyItemRow).where(GoJourneyItemRow.journey_id.in_(journey_ids)).order_by(
     GoJourneyItemRow.journey_id,GoJourneyItemRow.sort_key,GoJourneyItemRow.created_at
    )).scalars().all()
    for item in items: items_by_journey[item.journey_id].append(item)
   statuses=self._batch_order_statuses(s,rows,items_by_journey)
   return {
    "items":[self._serialize(s,x,refresh=True,items=items_by_journey[x.journey_id],statuses=statuses) for x in rows],
    "page":{"limit":limit,"offset":None if cursor else offset,"has_more":has_more,"next_offset":None if cursor else (offset+limit if has_more else None),"next_cursor":self._encode_cursor(account_id,normalized,rows[-1]) if has_more and rows else None},
    "query":normalized or None,
   }
 def _batch_order_statuses(self,s,journeys,items_by_journey):
  keys_by_vertical={}
  for journey in journeys:
   for item in items_by_journey[journey.journey_id]:
    vertical=item.vertical.upper()
    if vertical in VERTICALS:
     keys_by_vertical.setdefault(vertical,set()).add((journey.account_id,item.order_id))
  statuses={}
  for vertical,keys in keys_by_vertical.items():
   model=VERTICALS[vertical][0];keys=sorted(keys)
   # Composite owner/order keys prevent a shared-trip member or corrupted
   # attachment from projecting another account's private order state.
   for offset in range(0,len(keys),400):
    values=s.execute(select(model.account_id,model.order_id,model.status).where(tuple_(model.account_id,model.order_id).in_(keys[offset:offset+400]))).all()
    for owner,order_id,status in values: statuses[(vertical,owner,order_id)]=status
  return statuses
 def get(self,account_id,journey_id):
  with SessionLocal() as s:
   j=s.get(GoJourneyRow,journey_id)
   member=s.scalar(select(ConsumerTripMemberRow).where(ConsumerTripMemberRow.journey_id==journey_id,ConsumerTripMemberRow.user_id==account_id,ConsumerTripMemberRow.status=='ACTIVE')) if j else None
   if not j or (j.account_id!=account_id and not member): raise ValueError("JOURNEY_NOT_FOUND")
   return self._serialize(s,j,refresh=True)
 def _serialize(self,s,j,refresh=False,items=None,statuses=None):
  if items is None:
   items=s.execute(select(GoJourneyItemRow).where(GoJourneyItemRow.journey_id==j.journey_id).order_by(GoJourneyItemRow.sort_key,GoJourneyItemRow.created_at)).scalars().all()
  out=[]
  for x in items:
   status=x.status_snapshot
   if refresh:
    if statuses is not None:
     status=statuses.get((x.vertical.upper(),j.account_id,x.order_id),status)
    else:
     try: status=self._order(s,j.account_id,x.vertical,x.order_id).status
     except ValueError: pass
   out.append({"item_id":x.item_id,"vertical":x.vertical,"order_id":x.order_id,"title":x.title,"subtitle":x.subtitle,"location":x.location,"starts_at":x.starts_at,"ends_at":x.ends_at,"status":status,"facts":x.facts_json,"detail_route":x.detail_route})
  return {"journey_id":j.journey_id,"title":j.title,"destination_summary":j.destination_summary,"starts_at":j.starts_at,"ends_at":j.ends_at,"status":j.status,"item_count":len(out),"verticals":sorted(set(x["vertical"] for x in out)),"timeline":out}

journey_service=JourneyService()
