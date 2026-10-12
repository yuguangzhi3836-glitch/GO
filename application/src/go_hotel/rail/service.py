from __future__ import annotations
from go_hotel.services import vertical_reservation_expiry as reservation_expiry

from datetime import UTC, datetime, timedelta, date
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import RailOfferRow, RailPrebookRow, RailOrderRow, RailChangeQuoteRow, RailRefundRow
from go_hotel.domain.models import new_id
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence, list_vertical_evidence
from go_hotel.services.vertical_lifecycle_projection import project_vertical_lifecycle
from go_hotel.services.vertical_money_bridge import vertical_money_bridge
from go_hotel.core.production_truth_gate import production_truth_required
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge
from go_hotel.autonomy.durable import transaction,db_now_ms
from go_hotel.services import vertical_prebook_contract as contracts
from go_hotel.services import vertical_refund_recovery
from go_hotel.services import vertical_capacity as capacity
from go_hotel.db.models import VerticalPrebookContractRow



def _utc_iso(value):
    """SQLite stores UTC without an offset; PostgreSQL returns aware values."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()

def now(): return datetime.now(UTC).replace(tzinfo=None)

class RailService:
    def _terms(self,s,order):
        row=s.get(VerticalPrebookContractRow,order.prebook_id)
        if not row or row.vertical!='RAIL' or row.owner_id!=order.account_id or row.order_id!=order.order_id or row.state!='CONSUMED' or row.terms_hash!=contracts.digest(contracts._identity(row)):
            raise ValueError('RAIL_LEGACY_TERMS_REVIEW_REQUIRED')
        if len(order.passengers or [])!=row.terms_json['quantity']:raise ValueError('RAIL_ORDER_PARTY_INTEGRITY_INVALID')
        return row.terms_json
    def search(self, origin_station:str, destination_station:str, travel_date:str, currency:str="CNY"):
        production_truth_required("RAIL", "SEARCH")
        if currency!='CNY':raise ValueError('RAIL_ENGINEERING_CURRENCY_INVALID')
        try:
            if date.fromisoformat(travel_date).isoformat()!=travel_date:raise ValueError()
        except (ValueError,TypeError):raise ValueError('RAIL_DATE_INVALID') from None
        if not str(origin_station).strip() or not str(destination_station).strip() or origin_station.strip().upper()==destination_station.strip().upper():
            raise ValueError('RAIL_STATION_PAIR_INVALID')
        templates=[
            ("G7315","SECOND_CLASS",7350,"08:05","08:50",45,18,{"allowed":True,"fee_minor":500},{"allowed":True,"fee_minor":800}),
            ("G7501","FIRST_CLASS",11800,"09:30","10:18",48,8,{"allowed":True,"fee_minor":500},{"allowed":True,"fee_minor":800}),
            ("G165","BUSINESS_CLASS",21900,"11:10","11:56",46,3,{"allowed":True,"fee_minor":0},{"allowed":True,"fee_minor":800}),
        ]
        out=[]
        with transaction(SessionLocal) as s:
            for train,seat,total,dep,arr,dur,left,change,refund in templates:
                left=capacity.available_in(s,'RAIL',capacity.rail_resource({'train_no':train,'travel_date':travel_date,'seat_class':seat}),left)
                oid=new_id("rail_off")
                stations=[{"station_code":origin_station,"sequence":1,"departure_time":dep},{"station_code":destination_station,"sequence":2,"arrival_time":arr}]
                r=RailOfferRow(offer_id=oid,origin_station=origin_station,destination_station=destination_station,travel_date=travel_date,train_no=train,seat_class=seat,total_amount_minor=total,currency=currency,departure_time=dep,arrival_time=arr,duration_minutes=dur,stations=stations,change_policy=change,refund_policy=refund,inventory_left=left,expires_at=now()+timedelta(minutes=15),created_at=now())
                s.add(r); out.append(self._offer(r) | {"external_live": False})
        return out
    def _offer(self,r):
        return {"offer_id":r.offer_id,"origin_station":r.origin_station,"destination_station":r.destination_station,"travel_date":r.travel_date,"train_no":r.train_no,"seat_class":r.seat_class,"total_amount_minor":r.total_amount_minor,"currency":r.currency,"departure_time":r.departure_time,"arrival_time":r.arrival_time,"duration_minutes":r.duration_minutes,"stations":r.stations,"change_policy":r.change_policy,"refund_policy":r.refund_policy,"inventory_left":r.inventory_left,"price_basis":"PER_ADULT","unit_amount_minor":r.total_amount_minor,"expires_at":r.expires_at.isoformat()}
    def get_offer(self,offer_id):
        with SessionLocal() as s:
            r=s.get(RailOfferRow,offer_id)
            if not r: raise ValueError("RAIL_OFFER_NOT_FOUND")
            return self._offer(r)
    def prebook(self,offer_id,quantity=1,account=None):
        production_truth_required("RAIL", "PREBOOK")
        contracts.party_count(quantity)
        with transaction(SessionLocal) as s:
            off=s.get(RailOfferRow,offer_id)
            if not off or off.expires_at.replace(tzinfo=off.expires_at.tzinfo or UTC).timestamp()*1000<=db_now_ms(s) or off.inventory_left<quantity:
                raise ValueError("RAIL_OFFER_EXPIRED_OR_SOLD_OUT")
            if off.currency!='CNY':raise ValueError('RAIL_ENGINEERING_CURRENCY_INVALID')
            journey={"origin_station":off.origin_station,"destination_station":off.destination_station,"travel_date":off.travel_date,
                "train_no":off.train_no,"seat_class":off.seat_class,"departure_time":off.departure_time,
                "arrival_time":off.arrival_time,"duration_minutes":off.duration_minutes,"stations":off.stations}
            left=capacity.available_in(s,'RAIL',capacity.rail_resource(journey),capacity.RAIL_LIMITS[off.seat_class])
            if left<quantity:raise ValueError('RAIL_OFFER_EXPIRED_OR_SOLD_OUT')
            terms={'offer_id':offer_id,'quantity':quantity,'unit_amount_minor':off.total_amount_minor,
                'total_amount_minor':off.total_amount_minor*quantity,'currency':off.currency,'journey':journey,
                'change_policy':off.change_policy,'refund_policy':off.refund_policy,'fare_kind':'ADT',
                'inventory_observed_units':left,'inventory_reserved':False}
            lifetime=min(600000,int(off.expires_at.replace(tzinfo=off.expires_at.tzinfo or UTC).timestamp()*1000)-db_now_ms(s))
            if lifetime<1000:raise ValueError('RAIL_OFFER_EXPIRED_OR_SOLD_OUT')
            contract=contracts.issue_in(s,'RAIL',new_id('rail_pb'),terms,lifetime_ms=lifetime,account=account)
            expires=datetime.fromtimestamp(contract.expires_ms/1000,UTC).replace(tzinfo=None)
            p=RailPrebookRow(prebook_id=contract.prebook_id,offer_id=offer_id,total_amount_minor=terms['total_amount_minor'],
                currency=off.currency,status='CONFIRMED',price_locked=True,inventory_confirmed=True,expires_at=expires,created_at=now())
            s.add(p);s.flush()
            return contracts.projection(contract)|{'status':p.status,'price_locked':True,'inventory_confirmed':True,'expires_at':expires.isoformat()}
    def create_order(self,account_id,prebook_id,passengers,traveler_ids=None):
        production_truth_required('RAIL','CREATE_ORDER')
        with transaction(SessionLocal) as s:
            request={'passengers':passengers,'traveler_ids':contracts.party_refs(traveler_ids,len(passengers))}
            contract,replay=contracts.current_in(s,'RAIL',prebook_id,account_id,request)
            if replay:
                old=s.get(RailOrderRow,contract.order_id)
                if not old or old.account_id!=account_id:raise ValueError('RAIL_PREBOOK_ORDER_INTEGRITY_INVALID')
                return self._order(old)
            terms=contract.terms_json
            people=contracts.named_party(passengers,terms['quantity'],adults_only=True)
            p=s.get(RailPrebookRow,prebook_id)
            if not p or p.status!='CONFIRMED' or p.total_amount_minor!=terms['total_amount_minor'] or p.currency!=terms['currency'] or p.offer_id!=terms['offer_id']:
                raise ValueError('RAIL_PREBOOK_INVALID')
            o=RailOrderRow(order_id=new_id('rail_ord'),account_id=account_id,prebook_id=prebook_id,status='PAYMENT_PENDING',
                total_amount_minor=terms['total_amount_minor'],currency=terms['currency'],passengers=people,payment_method_id=None,
                booking_reference=None,ticket_numbers=[],current_journey=terms['journey'],created_at=now(),updated_at=now())
            capacity.reserve_in(s,'RAIL',o.order_id,'ORIGINAL',capacity.rail_resource(terms['journey']),capacity.RAIL_LIMITS[terms['journey']['seat_class']],terms['quantity'])
            s.add(o);s.flush();reservation_expiry.issue_in(s,'RAIL',o);contracts.consume_in(s,contract,account_id,o.order_id,request);p.status='CONSUMED'
            append_vertical_evidence(s,'RAIL',o.order_id,'ORDER_CREATED',o.status,{'prebook_id':prebook_id,
                'terms_hash':contract.terms_hash,'passenger_count':terms['quantity'],'unit_amount_minor':terms['unit_amount_minor']})
            return self._order(o)
    def checkout(self,account_id,order_id,payment_method_id):
        production_truth_required("RAIL", "CHECKOUT")
        with transaction(SessionLocal) as s:
            o=s.get(RailOrderRow,order_id,with_for_update=True)
            if not o or o.account_id!=account_id: raise ValueError("RAIL_ORDER_NOT_FOUND")
            if o.status not in {"PAYMENT_PENDING","PAYMENT_AUTHORIZED"}: return self._order(o)
            reservation_expiry.guard_payment_in(s,'RAIL',o)
            o.payment_method_id=payment_method_id; o.updated_at=now(); s.flush()
            order_id=o.order_id; account=o.account_id
        tx=vertical_transaction_bridge.checkout_contract('RAIL',order_id,account,'RAIL_OPERATOR',f'rail-order://{order_id}',payment_method_id)
        with SessionLocal.begin() as s:
            o=s.get(RailOrderRow,order_id); o.status=tx['state']; o.updated_at=now(); append_vertical_evidence(s,'RAIL',order_id,'PAYMENT_CAPTURED',o.status,{'payment_intent_id':tx['payment_intent_id'],'capture_id':tx['capture_id'],'external_live':False}); s.flush(); return self._order(o)
    def _order(self,o):
        issued = o.status in {"TICKETED", "UNKNOWN_EXTERNAL_STATE"}
        return {"order_id":o.order_id,"account_id":o.account_id,"status":o.status,"total_amount_minor":o.total_amount_minor,"currency":o.currency,"passengers":o.passengers,"passenger_count":len(o.passengers or []),"data_mode":"SIMULATION","external_live":False,"booking_reference":o.booking_reference if issued else None,"ticket_numbers":o.ticket_numbers if issued else [],"journey":o.current_journey,"created_at":_utc_iso(o.created_at),"updated_at":_utc_iso(o.updated_at)} | reservation_expiry.projection('RAIL',o)
    def order(self,account_id,order_id):
        with SessionLocal() as s:
            o=s.get(RailOrderRow,order_id)
            if not o or o.account_id!=account_id: raise ValueError("RAIL_ORDER_NOT_FOUND")
            result=self._order(o)
            changes=s.scalars(select(RailChangeQuoteRow).where(RailChangeQuoteRow.order_id==order_id).order_by(RailChangeQuoteRow.created_at)).all()
            refunds=s.scalars(select(RailRefundRow).where(RailRefundRow.order_id==order_id).order_by(RailRefundRow.created_at)).all()
            result["change_quotes"]=[{"quote_id":x.quote_id,"status":x.status,"new_travel_date":x.new_travel_date,"new_train_no":x.new_train_no,"new_seat_class":x.new_seat_class,"fare_difference_minor":x.fare_difference_minor,"change_fee_minor":x.change_fee_minor,"total_due_minor":x.total_due_minor,"currency":x.currency} for x in changes]
            result["refunds"]=[{"refund_id":x.refund_id,"status":x.status,"refund_fee_minor":x.refund_fee_minor,"refund_amount_minor":x.refund_amount_minor,"currency":x.currency} for x in refunds]
            result["evidence"]=list_vertical_evidence(s,"RAIL",order_id)
            return result
    def trips(self,account_id):
        with SessionLocal() as s:
            rows=s.scalars(select(RailOrderRow).where(RailOrderRow.account_id==account_id).order_by(RailOrderRow.updated_at.desc())).all()
            return [self._order(x) for x in rows]
    def change_quote(self,account_id,order_id,new_travel_date,new_seat_class=None):
        production_truth_required("RAIL", "CHANGE_QUOTE")
        try:
            if date.fromisoformat(new_travel_date).isoformat()!=new_travel_date:raise ValueError()
        except (ValueError,TypeError):raise ValueError('RAIL_DATE_INVALID') from None
        with SessionLocal.begin() as s:
            o=s.get(RailOrderRow,order_id)
            if not o or o.account_id!=account_id or o.status!="TICKETED": raise ValueError("RAIL_ORDER_NOT_CHANGEABLE")
            current=o.current_journey or {}; seat=new_seat_class or current.get("seat_class","SECOND_CLASS")
            count=contracts.party_count(len(o.passengers or []))
            terms=self._terms(s,o)
            if not terms['change_policy']['allowed']:raise ValueError('RAIL_ORDER_NOT_CHANGEABLE')
            if seat not in {'SECOND_CLASS','FIRST_CLASS','BUSINESS_CLASS'}:raise ValueError('RAIL_SEAT_CLASS_INVALID')
            fare_diff=(12000 if seat!=current.get("seat_class") else 3000)*count; fee=terms['change_policy']['fee_minor']*count
            q=RailChangeQuoteRow(quote_id=new_id("rail_chq"),order_id=order_id,new_travel_date=new_travel_date,new_train_no="G7319",new_seat_class=seat,fare_difference_minor=max(0,fare_diff),change_fee_minor=fee,total_due_minor=max(0,fare_diff)+fee,currency=o.currency,status="QUOTED",expires_at=now()+timedelta(minutes=10),created_at=now())
            s.add(q); s.flush(); return {"quote_id":q.quote_id,"order_id":order_id,"new_travel_date":q.new_travel_date,"new_train_no":q.new_train_no,"new_seat_class":q.new_seat_class,"fare_difference_minor":q.fare_difference_minor,"change_fee_minor":q.change_fee_minor,"total_due_minor":q.total_due_minor,"currency":q.currency,"expires_at":q.expires_at.isoformat()}
    def execute_change(self,account_id,order_id,quote_id):
        production_truth_required('RAIL','EXECUTE_CHANGE')
        with transaction(SessionLocal) as s:
            o=s.get(RailOrderRow,order_id,with_for_update=True);q=s.get(RailChangeQuoteRow,quote_id,with_for_update=True)
            if not o or o.account_id!=account_id or not q or q.order_id!=order_id:raise ValueError('RAIL_CHANGE_QUOTE_INVALID')
            if q.status=='PENDING_SUPPLIER' and o.status=='UNKNOWN_EXTERNAL_STATE':return self._order(o)
            if not (q.status=='PREPARING' and o.status=='CHANGE_PENDING'):
                if o.status!='TICKETED' or q.status!='QUOTED' or q.expires_at.replace(tzinfo=q.expires_at.tzinfo or UTC).timestamp()*1000<=db_now_ms(s):raise ValueError('RAIL_CHANGE_QUOTE_INVALID')
                target=capacity.rail_resource(dict(o.current_journey,travel_date=q.new_travel_date,train_no=q.new_train_no,seat_class=q.new_seat_class))
                capacity.prepare_change_in(s,'RAIL',order_id,quote_id,target,capacity.RAIL_LIMITS[q.new_seat_class],len(o.passengers))
                q.status='PREPARING';o.status='CHANGE_PENDING';o.updated_at=now()
                append_vertical_evidence(s,'RAIL',order_id,'CHANGE_PAYMENT_PREPARING',o.status,{'quote_id':quote_id})
                project_vertical_lifecycle(s,'RAIL',o,'change-preparing:'+quote_id,facts={'quote_id':quote_id})
            due=q.total_due_minor
        adjustment=vertical_money_bridge.prepare_adjustment('RAIL',order_id,quote_id,due,f'rail-change://{quote_id}')
        with transaction(SessionLocal) as s:
            o=s.get(RailOrderRow,order_id,with_for_update=True);q=s.get(RailChangeQuoteRow,quote_id,with_for_update=True)
            if not o or o.account_id!=account_id or not q or q.order_id!=order_id:raise ValueError('RAIL_CHANGE_QUOTE_INVALID')
            if q.status=='PENDING_SUPPLIER' and o.status=='UNKNOWN_EXTERNAL_STATE':return self._order(o)
            if o.status!='CHANGE_PENDING' or q.status!='PREPARING':raise ValueError('RAIL_CHANGE_QUOTE_INVALID')
            q.status='PENDING_SUPPLIER';o.status='UNKNOWN_EXTERNAL_STATE';o.updated_at=now()
            facts={'quote_id':quote_id,'authorization_id':(adjustment or {}).get('authorization_id'),'previous_booking_reference':o.booking_reference,'previous_ticket_numbers':o.ticket_numbers}
            append_vertical_evidence(s,'RAIL',order_id,'CHANGE_SUBMITTED_AWAITING_SUPPLIER',o.status,facts)
            project_vertical_lifecycle(s,'RAIL',o,'change-pending:'+quote_id,facts=facts)
            return self._order(o)
    def _refund_quote_in(self,s,o):
        count=contracts.party_count(len(o.passengers or []))
        terms=self._terms(s,o)
        if not terms['refund_policy']['allowed']:raise ValueError('RAIL_ORDER_NOT_REFUNDABLE')
        retained=sum(q.change_fee_minor for q in s.scalars(select(RailChangeQuoteRow).where(RailChangeQuoteRow.order_id==o.order_id,RailChangeQuoteRow.status=='EXECUTED')))
        fee=terms['refund_policy']['fee_minor']*count+retained
        return {'order_id':o.order_id,'refund_fee_minor':fee,'refund_amount_minor':max(0,o.total_amount_minor-fee),'currency':o.currency,'refund_to':'ORIGINAL_PAYMENT_METHOD'}
    def refund_quote(self,account_id,order_id):
        production_truth_required('RAIL','REFUND_QUOTE')
        with transaction(SessionLocal) as s:
            o=s.get(RailOrderRow,order_id,with_for_update=True)
            if not o or o.account_id!=account_id or o.status!='TICKETED':raise ValueError('RAIL_ORDER_NOT_REFUNDABLE')
            from go_hotel.services.refund_consent import bind
            return bind('RAIL',o,self._refund_quote_in(s,o))
    def refund(self,account_id,order_id,accepted_hash=None):
        production_truth_required('RAIL','REFUND')
        return vertical_refund_recovery.refund('RAIL',account_id,order_id,self._refund_quote_in,accepted_hash)
    def admin_external_state(self,order_id,state,evidence_reference,actor,supplier_reference=None,ticket_numbers=None,quote_id=None):
        from go_hotel.services.rail_change_resolution import reconcile
        return reconcile(order_id,state,evidence_reference,actor,supplier_reference,ticket_numbers,quote_id,self._order)

rail_service=RailService()
