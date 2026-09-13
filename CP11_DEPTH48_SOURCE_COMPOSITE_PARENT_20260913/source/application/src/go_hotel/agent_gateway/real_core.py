from __future__ import annotations

import hashlib, json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable

from .contracts import AgentContext, CommitRequest, Offer, OfferRequest, Order, PaymentRequest, PaymentTruth, Reservation, ReserveRequest, SupplyRoute

VERTICALS={"HOTEL","FLIGHT","RAIL","RIDE","RENTAL","ATTRACTION"}


def _jsonable(v:Any)->Any:
    if is_dataclass(v):v=asdict(v)
    return json.loads(json.dumps(v,sort_keys=True,separators=(",",":"),default=lambda x:x.isoformat() if isinstance(x,datetime) else str(x)))

def _digest(v:Any)->str:return hashlib.sha256(json.dumps(_jsonable(v),sort_keys=True,separators=(",",":")).encode()).hexdigest()
def _ref(vertical:str,raw_id:str)->str:return f"{vertical}:{raw_id}"
def _parse_ref(value:str)->tuple[str,str]:
    vertical,sep,raw=str(value).partition(":");vertical=vertical.upper()
    if not sep or vertical not in VERTICALS or not raw:raise ValueError("GO_TRANSACTION_REFERENCE_INVALID")
    return vertical,raw

def _required(data:dict[str,Any],*keys:str):
    missing=[k for k in keys if data.get(k) in (None,"")]
    if missing:raise ValueError("AGENT_SEARCH_FIELDS_REQUIRED:"+",".join(missing))
    return [data[k] for k in keys]

def _prod()->bool:
    from go_hotel.core.config import settings
    return settings.app_env.strip().lower() in {"prod","production"}


class GoTransactionCore:
    """Thin adapter over GO native inventory, money, supplier and order truth."""

    async def _idempotent(self,operation:str,key:str,payload:dict[str,Any],fn:Callable[[],Awaitable[dict[str,Any]]]):
        from go_hotel.repositories.sql import repo
        payload=_jsonable(payload);state,rec=repo.claim_idempotency(operation,key,payload)
        if state=="REPLAY":return rec["response"]
        if state=="IN_PROGRESS":raise ValueError("IDEMPOTENCY_IN_PROGRESS")
        try:
            out=await fn();return repo.complete_idempotency(operation,key,payload,_jsonable(out),out.get("order_id") or out.get("reserve_id") or out.get("payment_truth_id"))
        except BaseException:
            repo.release_idempotency_claim(operation,key,payload);raise

    async def find_offers(self,ctx:AgentContext,req:OfferRequest)->list[Offer]:
        v=req.product_type.upper();s=dict(req.search)
        if v not in VERTICALS:raise ValueError("AGENT_PRODUCT_TYPE_NOT_SUPPORTED")
        if v=="HOTEL":
            city,cin,cout=_required(s,"city_code","check_in","check_out")
            from go_hotel.services.booking import booking_service
            rows=await booking_service.search(city,cin,cout,s.get("currency","CNY"))
        elif v=="FLIGHT":
            origin,dest,day=_required(s,"origin","destination","departure_date")
            from go_hotel.flight.service import flight_service
            rows=flight_service.search(origin,dest,day,s.get("cabin","ECONOMY"),s.get("currency","CNY"),int(s.get("adults",1)))
        elif v=="RAIL":
            origin,dest,day=_required(s,"origin_station","destination_station","travel_date")
            from go_hotel.rail.service import rail_service
            rows=rail_service.search(origin,dest,day,s.get("currency","CNY"))
        elif v=="RIDE":
            pickup,dropoff,at=_required(s,"pickup","dropoff","pickup_at")
            from go_hotel.mobility.ride.service import ride_service
            rows=ride_service.search(pickup,dropoff,at,s.get("currency","CNY"))
        elif v=="RENTAL":
            pickup,ret,at,back=_required(s,"pickup_location","return_location","pickup_at","return_at")
            from go_hotel.mobility.rental.service import rental_service
            rows=rental_service.search(pickup,ret,at,back,s.get("currency","CNY"))
        else:
            dest,day=_required(s,"destination","visit_date")
            from go_hotel.attractions.service import attraction_service
            rows=attraction_service.search(dest,day,s.get("product_type"),s.get("currency","CNY"))
        return [self._offer(v,r,s) for r in rows]

    def _offer(self,v:str,raw:Any,search:dict[str,Any])->Offer:
        x=_jsonable(raw)
        if v=="HOTEL":
            rid=x["offer_id"];supplier=x.get("supplier_id") or x.get("connector_id") or "HOTEL_OFFICIAL";product=x.get("room_type_id") or x.get("hotel_id");units=x.get("inventory_units");cancel={"refundable":bool(x.get("refundable")),"deadline":x.get("cancellation_deadline"),"fare_rule_id":x.get("fare_rule_id")};route=SupplyRoute.OFFICIAL_DIRECT if x.get("official_direct",True) else SupplyRoute.AUTHORIZED_FALLBACK
        elif v=="FLIGHT":
            rid=x["offer_id"];supplier=x.get("carrier_code") or "AIRLINE_OFFICIAL";product=f"{x.get('carrier_code','')}{x.get('flight_number','')}";units=None;cancel=x.get("refund_policy") or {};route=SupplyRoute.OFFICIAL_DIRECT
        elif v=="RAIL":
            rid=x["offer_id"];supplier="RAIL_OPERATOR";product=f"{x.get('train_no','')}:{x.get('seat_class','')}";units=x.get("inventory_left");cancel=x.get("refund_policy") or {};route=SupplyRoute.OFFICIAL_DIRECT
        elif v=="RIDE":
            rid=x["offer_id"];supplier="FLEET_OFFICIAL";product=rid;units=None;cancel=x.get("cancellation") or {};route=SupplyRoute.OFFICIAL_DIRECT
        elif v=="RENTAL":
            rid=x["offer_id"];supplier="RENTAL_COMPANY_OFFICIAL";product=rid;units=None;cancel=x.get("cancellation") or {};route=SupplyRoute.OFFICIAL_DIRECT
        else:
            rid=x["offer_id"];supplier="ATTRACTION_OFFICIAL";product=x.get("product_id") or rid;units=x.get("inventory_units");cancel={"refundable":bool(x.get("refundable")),"changeable":bool(x.get("changeable"))};route=SupplyRoute.OFFICIAL_DIRECT
        quote={"vertical":v,"raw_offer":x,"search":search};qh=_digest(quote);available=units is None or int(units)>0
        return Offer(_ref(v,rid),v,str(supplier),str(product),route,int(x["total_amount_minor"]),str(x.get("currency","CNY")),x.get("expires_at"),"AVAILABLE" if available else "SOLD_OUT",qh,available,_jsonable(cancel),qh,_jsonable(search),{"native_offer_id":rid,"external_live":bool(x.get("external_live",False)),"data_mode":x.get("data_mode")})

    async def _assert_quote(self,ctx:AgentContext,req:ReserveRequest):
        v,rid=_parse_ref(req.offer_id);s=dict(req.search)
        if v=="HOTEL":
            from go_hotel.repositories.sql import repo
            raw=repo.get_offer(rid)
            if not raw:raise ValueError("OFFER_NOT_FOUND")
            current=self._offer(v,raw,s)
        elif v=="FLIGHT":
            from go_hotel.flight.service import flight_service
            current=self._offer(v,flight_service.get_offer(rid),s)
        elif v=="RAIL":
            from go_hotel.rail.service import rail_service
            current=self._offer(v,rail_service.get_offer(rid),s)
        else:
            current=next((o for o in await self.find_offers(ctx,OfferRequest(v,s)) if o.offer_id==req.offer_id),None)
            if current is None:raise ValueError("OFFER_NOT_FOUND")
        if current.quote_hash!=req.quote_hash:raise ValueError("OFFER_CHANGED_RECONFIRM_REQUIRED")
        if not current.machine_bookable:raise ValueError("OFFER_NOT_MACHINE_BOOKABLE")
        return v,rid,current

    async def reserve(self,ctx:AgentContext,req:ReserveRequest)->Reservation:
        account=ctx.require_traveler();v,rid,current=await self._assert_quote(ctx,req);booking=dict(req.booking)
        payload={"account":account,"offer_id":req.offer_id,"quote_hash":req.quote_hash,"search":dict(req.search),"booking":booking}
        async def execute():
            expiry=current.expires_at;evidence={"quote_hash":req.quote_hash,"native_offer_id":rid}
            if v=="HOTEL":
                from go_hotel.services.booking import booking_service
                pb=await booking_service.prebook(rid);order=await booking_service.create_order(pb.prebook_id,account,booking.get("expected_fare_rule_hash"),bool(booking.get("fare_confirmed")),simulation_fixture=bool(booking.get("simulation_fixture",False)) and not _prod())
                oid=order.order_id;status=str(order.status);total=int(order.total_amount_minor);currency=order.currency;expiry=pb.expires_at.isoformat();evidence|={"prebook_id":pb.prebook_id,"inventory_held":bool(pb.inventory_held),"hold_type":pb.hold_type}
            elif v=="FLIGHT":
                from go_hotel.flight.service import flight_service
                pb=flight_service.prebook(rid);order=flight_service.create_order(account,pb["prebook_id"],booking.get("passengers") or []);oid=order["order_id"];status=order["status"];total=int(order["total_amount_minor"]);currency=order["currency"];expiry=pb.get("expires_at");evidence|={"prebook_id":pb["prebook_id"],"inventory_confirmed":bool(pb.get("inventory_confirmed")),"price_locked":bool(pb.get("price_locked"))}
            elif v=="RAIL":
                from go_hotel.rail.service import rail_service
                passengers=booking.get("passengers") or [];q=int(booking.get("quantity") or len(passengers) or 1);pb=rail_service.prebook(rid,q,account);order=rail_service.create_order(account,pb["prebook_id"],passengers,booking.get("traveler_ids"));oid=order["order_id"];status=order["status"];total=int(order["total_amount_minor"]);currency=order["currency"];expiry=pb.get("expires_at");evidence|={"prebook_id":pb["prebook_id"],"inventory_confirmed":bool(pb.get("inventory_confirmed")),"capacity_reserved":True}
            elif v=="ATTRACTION":
                from go_hotel.attractions.service import attraction_service
                q=int(booking.get("quantity") or len(booking.get("attendees") or []) or 1);pb=attraction_service.prebook(rid,dict(req.search)["visit_date"],q,current.currency,booking.get("session_time"),account);body={"prebook_id":pb["prebook_id"],"offer_id":rid,"visit_date":dict(req.search)["visit_date"],"session_time":booking.get("session_time") or pb.get("session_time"),"quantity":q,"currency":current.currency,"attendees":booking.get("attendees") or [],"traveler_ids":booking.get("traveler_ids")};order=attraction_service.create_order(account,body);oid=order["order_id"];status=order["status"];total=int(order["total_amount_minor"]);currency=order["currency"];expiry=pb.get("expires_at");evidence|={"prebook_id":pb["prebook_id"],"inventory_confirmed":True,"capacity_reserved":True}
            elif v=="RIDE":
                from go_hotel.mobility.ride.service import ride_service
                order=ride_service.create(account,{**dict(req.search),**booking,"offer_id":rid,"currency":current.currency});oid=order["order_id"];status=order["status"];total=int(order["total_amount_minor"]);currency=order["currency"];evidence|={"provider_inventory_reserved":False,"native_order_created":True}
            else:
                from go_hotel.mobility.rental.service import rental_service
                order=rental_service.create(account,{**dict(req.search),**booking,"offer_id":rid,"currency":current.currency});oid=order["order_id"];status=order["status"];total=int(order["total_amount_minor"]);currency=order["currency"];evidence|={"provider_inventory_reserved":False,"native_order_created":True}
            if total!=current.total_minor and v not in {"RAIL","ATTRACTION"}:raise ValueError("ORDER_AMOUNT_CHANGED_RECONFIRM_REQUIRED")
            reserve_id=_ref(v,oid);return asdict(Reservation(reserve_id,req.offer_id,v,status,expiry,req.quote_hash,total,currency,reserve_id,evidence))
        return Reservation(**await self._idempotent("AGENT_RESERVE",req.idempotency_key,payload,execute))

    async def _native_order(self,account:str,v:str,oid:str)->dict[str,Any]:
        if v=="HOTEL":
            from go_hotel.repositories.sql import repo
            o=repo.get_order(oid)
            if not o or o.account_id!=account:raise ValueError("ORDER_NOT_FOUND")
            return _jsonable(o)
        if v=="FLIGHT":
            from go_hotel.flight.service import flight_service
            return _jsonable(flight_service.order(account,oid))
        if v=="RAIL":
            from go_hotel.rail.service import rail_service
            return _jsonable(rail_service.order(account,oid))
        if v=="RIDE":
            from go_hotel.mobility.ride.service import ride_service
            return _jsonable(ride_service.get(account,oid))
        if v=="RENTAL":
            from go_hotel.mobility.rental.service import rental_service
            return _jsonable(rental_service.get(account,oid))
        from go_hotel.attractions.service import attraction_service
        return _jsonable(attraction_service.get(account,oid))

    async def prepare_payment(self,ctx:AgentContext,req:PaymentRequest)->PaymentTruth:
        account=ctx.require_traveler();v,oid=_parse_ref(req.reserve_id);order=await self._native_order(account,v,oid);total=int(order["total_amount_minor"]);currency=str(order["currency"])
        if (req.expected_total_minor,req.currency)!=(total,currency):raise ValueError("ORDER_AMOUNT_CHANGED_RECONFIRM_REQUIRED")
        payload={"account":account,"reserve_id":req.reserve_id,"expected_total_minor":total,"currency":currency,"payment_method_id":req.payment_method_id}
        async def execute():
            if v=="HOTEL":
                from go_hotel.services.booking import booking_service
                p=await booking_service.pay(oid,total,currency,req.payment_method_id);state=str(p.status)
                return asdict(PaymentTruth(p.payment_id,req.reserve_id,v,state,total,currency,state=="CAPTURED",False,{"native_payment_id":p.payment_id,"truth_type":"HOTEL_AUTHORIZATION"}))
            if v=="FLIGHT":
                from go_hotel.flight.service import flight_service
                flight_service.checkout(account,oid,req.payment_method_id)
            elif v=="RAIL":
                from go_hotel.rail.service import rail_service
                rail_service.checkout(account,oid,req.payment_method_id)
            else:
                from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge
                source={"RIDE":"FLEET","RENTAL":"RENTAL_COMPANY","ATTRACTION":"ATTRACTION_OPERATOR"}[v];vertical_transaction_bridge.checkout_contract(v,oid,account,source,f"agent-payment://{v}/{oid}",req.payment_method_id)
            from sqlalchemy import select
            from go_hotel.db.session import SessionLocal
            from go_hotel.db.models import OmnichannelPaymentIntentRow as Intent,OmnichannelMoneyMovementRow as Movement
            with SessionLocal() as s:
                i=s.scalar(select(Intent).where(Intent.business_type==f"{v}_ORDER",Intent.business_id==oid))
                if not i:raise ValueError("PAYMENT_TRUTH_NOT_FOUND")
                captured=sum(x.amount_minor for x in s.scalars(select(Movement).where(Movement.root_payment_intent_id==i.payment_intent_id,Movement.movement_type=="CAPTURE",Movement.state=="CONFIRMED")).all())
                if i.state!="SUCCEEDED" or captured!=i.amount_minor:raise ValueError("FULL_CAPTURED_PAYMENT_TRUTH_REQUIRED")
                return asdict(PaymentTruth(i.payment_intent_id,req.reserve_id,v,i.state,int(i.amount_minor),i.currency,True,False,{"captured_minor":captured,"business_type":i.business_type,"business_id":i.business_id}))
        return PaymentTruth(**await self._idempotent("AGENT_PAYMENT",req.idempotency_key,payload,execute))

    async def _payment_state(self,v:str,oid:str):
        if v=="HOTEL":
            from go_hotel.repositories.sql import repo
            p=repo.get_authorized_payment_for_order(oid);return (str(p.status) if p else "NOT_FOUND",p.payment_id if p else None)
        from sqlalchemy import select
        from go_hotel.db.session import SessionLocal
        from go_hotel.db.models import OmnichannelPaymentIntentRow as Intent
        with SessionLocal() as s:
            i=s.scalar(select(Intent).where(Intent.business_type==f"{v}_ORDER",Intent.business_id==oid));return (i.state if i else "NOT_FOUND",i.payment_intent_id if i else None)

    async def commit(self,ctx:AgentContext,req:CommitRequest)->Order:
        account=ctx.require_traveler();v,oid=_parse_ref(req.reserve_id);payload={"account":account,"reserve_id":req.reserve_id,"payment_truth_id":req.payment_truth_id}
        async def execute():
            state,pid=await self._payment_state(v,oid)
            if pid!=req.payment_truth_id:raise ValueError("PAYMENT_TRUTH_ORDER_MISMATCH")
            if v=="HOTEL":
                if state not in {"AUTHORIZED","CAPTURED"}:raise ValueError("PAYMENT_AUTHORIZATION_REQUIRED")
                from go_hotel.services.booking import booking_service
                await booking_service.confirm(oid)
            else:
                if state!="SUCCEEDED":raise ValueError("PAYMENT_SUCCESS_REQUIRED")
                from sqlalchemy import select
                from go_hotel.db.session import SessionLocal
                from go_hotel.db.models import OrderSupplierFulfillmentRow as Fulfillment
                with SessionLocal() as s:
                    f=s.scalar(select(Fulfillment).where(Fulfillment.payment_intent_id==pid))
                    if not f:raise ValueError("SUPPLIER_FULFILLMENT_REQUIRED")
                    fid,fstate=f.order_supplier_fulfillment_id,f.state
                if fstate!="SUPPLIER_CONFIRMED":
                    if _prod():raise ValueError("AGENT_SUPPLIER_EXECUTOR_REQUIRED")
                    native=await self._native_order(account,v,oid);ref=f"AGENT-SIM-{oid}";fact={"state":"SUPPLIER_CONFIRMED","supplier_confirmation_reference":ref,"external_operation_id":ref,"evidence_reference":f"agent-contract-simulator://{v}/{oid}"}
                    if v in {"FLIGHT","RAIL"}:
                        people=native.get("passengers") or [];legs=len(native.get("itinerary") or []) if v=="FLIGHT" else 1;fact["ticket_numbers"]=[f"{ref}-L{leg+1}-P{person+1}" for leg in range(max(1,legs)) for person in range(len(people))]
                    if v=="ATTRACTION":fact["voucher_code"]=ref
                    from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service
                    order_supplier_fulfillment_service.record_supplier_fact(fid,fact)
            return asdict(await self.get_order(ctx,req.reserve_id))
        return Order(**await self._idempotent("AGENT_COMMIT",req.idempotency_key,payload,execute))

    async def get_order(self,ctx:AgentContext,order_id:str)->Order:
        account=ctx.require_traveler();v,oid=_parse_ref(order_id);native=await self._native_order(account,v,oid);state,pid=await self._payment_state(v,oid);supplier=native.get("supplier_confirmation_no") or native.get("pnr") or native.get("booking_reference") or native.get("supplier_reference");status=str(native["status"]);total=int(native["total_amount_minor"]);currency=str(native["currency"]);version=_digest({"vertical":v,"order":native,"payment_state":state,"payment_id":pid,"supplier_confirmation":supplier})
        return Order(order_id,order_id,v,status,supplier,state,version,total,currency,{"native_order_id":oid,"payment_truth_id":pid,"native":native})

    async def release(self,ctx:AgentContext,reserve_id:str,idempotency_key:str):
        v,_=_parse_ref(reserve_id)
        raise ValueError(f"AGENT_RELEASE_NATIVE_BINDING_REQUIRED:{v}")
