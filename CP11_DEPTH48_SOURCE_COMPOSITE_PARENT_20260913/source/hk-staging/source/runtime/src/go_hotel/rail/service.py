from __future__ import annotations
from datetime import UTC, datetime, timedelta
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import RailOfferRow, RailPrebookRow, RailOrderRow, RailChangeQuoteRow, RailRefundRow
from go_hotel.domain.models import new_id
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence, list_vertical_evidence
from go_hotel.services.vertical_lifecycle_projection import project_vertical_lifecycle
from go_hotel.services.vertical_money_bridge import vertical_money_bridge
from go_hotel.core.production_truth_gate import production_truth_required
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge

def now(): return datetime.now(UTC).replace(tzinfo=None)

class RailService:
    def search(self, origin_station:str, destination_station:str, travel_date:str, currency:str="CNY"):
        production_truth_required("RAIL", "SEARCH")
        templates=[
            ("G7315","SECOND_CLASS",7350,"08:05","08:50",45,18,{"allowed":True,"fee_minor":500},{"allowed":True,"fee_minor":800}),
            ("G7501","FIRST_CLASS",11800,"09:30","10:18",48,8,{"allowed":True,"fee_minor":500},{"allowed":True,"fee_minor":800}),
            ("G165","BUSINESS_CLASS",21900,"11:10","11:56",46,3,{"allowed":True,"fee_minor":0},{"allowed":True,"fee_minor":800}),
        ]
        out=[]
        with SessionLocal.begin() as s:
            for train,seat,total,dep,arr,dur,left,change,refund in templates:
                oid=new_id("rail_off")
                stations=[{"station_code":origin_station,"sequence":1,"departure_time":dep},{"station_code":destination_station,"sequence":2,"arrival_time":arr}]
                r=RailOfferRow(offer_id=oid,origin_station=origin_station,destination_station=destination_station,travel_date=travel_date,train_no=train,seat_class=seat,total_amount_minor=total,currency=currency,departure_time=dep,arrival_time=arr,duration_minutes=dur,stations=stations,change_policy=change,refund_policy=refund,inventory_left=left,expires_at=now()+timedelta(minutes=15),created_at=now())
                s.add(r); out.append(self._offer(r) | {"external_live": False})
        return out
    def _offer(self,r):
        return {"offer_id":r.offer_id,"origin_station":r.origin_station,"destination_station":r.destination_station,"travel_date":r.travel_date,"train_no":r.train_no,"seat_class":r.seat_class,"total_amount_minor":r.total_amount_minor,"currency":r.currency,"departure_time":r.departure_time,"arrival_time":r.arrival_time,"duration_minutes":r.duration_minutes,"stations":r.stations,"change_policy":r.change_policy,"refund_policy":r.refund_policy,"inventory_left":r.inventory_left,"expires_at":r.expires_at.isoformat()}
    def get_offer(self,offer_id):
        with SessionLocal() as s:
            r=s.get(RailOfferRow,offer_id)
            if not r: raise ValueError("RAIL_OFFER_NOT_FOUND")
            return self._offer(r)
    def prebook(self,offer_id):
        production_truth_required("RAIL", "PREBOOK")
        with SessionLocal.begin() as s:
            o=s.get(RailOfferRow,offer_id)
            if not o or o.expires_at<now() or o.inventory_left<=0: raise ValueError("RAIL_OFFER_EXPIRED_OR_SOLD_OUT")
            p=RailPrebookRow(prebook_id=new_id("rail_pb"),offer_id=offer_id,total_amount_minor=o.total_amount_minor,currency=o.currency,status="CONFIRMED",price_locked=True,inventory_confirmed=True,expires_at=now()+timedelta(minutes=10),created_at=now())
            s.add(p); s.flush()
            return {"prebook_id":p.prebook_id,"offer_id":offer_id,"status":p.status,"total_amount_minor":p.total_amount_minor,"currency":p.currency,"price_locked":True,"inventory_confirmed":True,"expires_at":p.expires_at.isoformat()}
    def create_order(self,account_id,prebook_id,passengers):
        with SessionLocal.begin() as s:
            p=s.get(RailPrebookRow,prebook_id)
            if not p or p.status!="CONFIRMED" or p.expires_at<now(): raise ValueError("RAIL_PREBOOK_INVALID")
            off=s.get(RailOfferRow,p.offer_id)
            journey={"origin_station":off.origin_station,"destination_station":off.destination_station,"travel_date":off.travel_date,"train_no":off.train_no,"seat_class":off.seat_class,"departure_time":off.departure_time,"arrival_time":off.arrival_time,"duration_minutes":off.duration_minutes,"stations":off.stations}
            o=RailOrderRow(order_id=new_id("rail_ord"),account_id=account_id,prebook_id=prebook_id,status="PAYMENT_PENDING",total_amount_minor=p.total_amount_minor,currency=p.currency,passengers=passengers,payment_method_id=None,booking_reference=None,ticket_numbers=[],current_journey=journey,created_at=now(),updated_at=now())
            s.add(o); s.flush(); append_vertical_evidence(s,"RAIL",o.order_id,"ORDER_CREATED",o.status,{"prebook_id":prebook_id}); return self._order(o)
    def checkout(self,account_id,order_id,payment_method_id):
        production_truth_required("RAIL", "CHECKOUT")
        with SessionLocal.begin() as s:
            o=s.get(RailOrderRow,order_id)
            if not o or o.account_id!=account_id: raise ValueError("RAIL_ORDER_NOT_FOUND")
            if o.status not in {"PAYMENT_PENDING","PAYMENT_AUTHORIZED"}: return self._order(o)
            o.payment_method_id=payment_method_id; o.status="PAYMENT_AUTHORIZED"; o.updated_at=now(); s.flush()
            order_id=o.order_id; account=o.account_id
        tx=vertical_transaction_bridge.checkout_contract('RAIL',order_id,account,'RAIL_OPERATOR',f'rail-order://{order_id}',payment_method_id)
        with SessionLocal.begin() as s:
            o=s.get(RailOrderRow,order_id); o.status=tx['state']; o.updated_at=now(); append_vertical_evidence(s,'RAIL',order_id,'PAYMENT_CAPTURED',o.status,{'payment_intent_id':tx['payment_intent_id'],'capture_id':tx['capture_id'],'external_live':False}); s.flush(); return self._order(o)
    def _order(self,o):
        return {"order_id":o.order_id,"account_id":o.account_id,"status":o.status,"total_amount_minor":o.total_amount_minor,"currency":o.currency,"passengers":o.passengers,"booking_reference":o.booking_reference if o.status=="TICKETED" else None,"ticket_numbers":o.ticket_numbers if o.status=="TICKETED" else [],"journey":o.current_journey,"created_at":o.created_at.isoformat(),"updated_at":o.updated_at.isoformat()}
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
        with SessionLocal.begin() as s:
            o=s.get(RailOrderRow,order_id)
            if not o or o.account_id!=account_id or o.status!="TICKETED": raise ValueError("RAIL_ORDER_NOT_CHANGEABLE")
            current=o.current_journey or {}; seat=new_seat_class or current.get("seat_class","SECOND_CLASS")
            fare_diff=12000 if seat!=current.get("seat_class") else 3000; fee=500
            q=RailChangeQuoteRow(quote_id=new_id("rail_chq"),order_id=order_id,new_travel_date=new_travel_date,new_train_no="G7319",new_seat_class=seat,fare_difference_minor=max(0,fare_diff),change_fee_minor=fee,total_due_minor=max(0,fare_diff)+fee,currency=o.currency,status="QUOTED",expires_at=now()+timedelta(minutes=10),created_at=now())
            s.add(q); s.flush(); return {"quote_id":q.quote_id,"order_id":order_id,"new_travel_date":q.new_travel_date,"new_train_no":q.new_train_no,"new_seat_class":q.new_seat_class,"fare_difference_minor":q.fare_difference_minor,"change_fee_minor":q.change_fee_minor,"total_due_minor":q.total_due_minor,"currency":q.currency,"expires_at":q.expires_at.isoformat()}
    def execute_change(self,account_id,order_id,quote_id):
        production_truth_required("RAIL", "EXECUTE_CHANGE")
        with SessionLocal() as s:
            o=s.get(RailOrderRow,order_id);q=s.get(RailChangeQuoteRow,quote_id)
            if not o or o.account_id!=account_id or o.status!="TICKETED" or not q or q.order_id!=order_id or q.status!="QUOTED" or q.expires_at<now(): raise ValueError("RAIL_CHANGE_QUOTE_INVALID")
            due=q.total_due_minor
        adjustment=vertical_money_bridge.prepare_adjustment('RAIL',order_id,quote_id,due,f'rail-change://{quote_id}')
        with SessionLocal.begin() as s:
            o=s.get(RailOrderRow,order_id);q=s.get(RailChangeQuoteRow,quote_id)
            if not o or o.account_id!=account_id or o.status!="TICKETED" or not q or q.status!="QUOTED": raise ValueError("RAIL_CHANGE_QUOTE_INVALID")
            q.status="PENDING_SUPPLIER";o.status="UNKNOWN_EXTERNAL_STATE";o.updated_at=now();append_vertical_evidence(s,"RAIL",o.order_id,"CHANGE_SUBMITTED_AWAITING_SUPPLIER",o.status,{"quote_id":quote_id,"authorization_id":(adjustment or {}).get('authorization_id'),"previous_booking_reference":o.booking_reference,"previous_ticket_numbers":o.ticket_numbers});project_vertical_lifecycle(s,"RAIL",o,"change-pending:"+quote_id,facts={"quote_id":quote_id,"authorization_id":(adjustment or {}).get('authorization_id')});return self._order(o)
    def refund_quote(self,account_id,order_id):
        production_truth_required("RAIL", "REFUND_QUOTE")
        with SessionLocal() as s:
            o=s.get(RailOrderRow,order_id)
            if not o or o.account_id!=account_id or o.status!="TICKETED": raise ValueError("RAIL_ORDER_NOT_REFUNDABLE")
            fee=800; amount=max(0,o.total_amount_minor-fee)
            return {"order_id":order_id,"refund_fee_minor":fee,"refund_amount_minor":amount,"currency":o.currency,"refund_to":"ORIGINAL_PAYMENT_METHOD"}
    def refund(self,account_id,order_id):
        production_truth_required("RAIL", "REFUND")
        quote=self.refund_quote(account_id,order_id)
        movement=vertical_money_bridge.refund('RAIL',order_id,quote['refund_amount_minor'],f'rail-refund://{order_id}',f'rail-refund:{order_id}')
        if movement['state']!='CONFIRMED': raise ValueError('RAIL_REFUND_MONEY_NOT_CONFIRMED')
        with SessionLocal.begin() as s:
            o=s.get(RailOrderRow,order_id)
            existing=s.scalar(select(RailRefundRow).where(RailRefundRow.order_id==order_id,RailRefundRow.status=='REFUND_COMPLETED').order_by(RailRefundRow.created_at.desc()))
            if existing:return {"refund_id":existing.refund_id,"order_id":order_id,"status":existing.status,"refund_fee_minor":existing.refund_fee_minor,"refund_amount_minor":existing.refund_amount_minor,"currency":existing.currency}
            if not o or o.account_id!=account_id or o.status!="TICKETED": raise ValueError("RAIL_ORDER_NOT_REFUNDABLE")
            r=RailRefundRow(refund_id=new_id("rail_ref"),order_id=order_id,refund_fee_minor=quote['refund_fee_minor'],refund_amount_minor=quote['refund_amount_minor'],currency=o.currency,status="REFUND_COMPLETED",created_at=now(),completed_at=now())
            o.status="REFUNDED"; o.updated_at=now(); s.add(r); append_vertical_evidence(s,"RAIL",o.order_id,"REFUND_COMPLETED",o.status,{"refund_id":r.refund_id,"refund_amount_minor":r.refund_amount_minor,"money_movement_id":movement['money_movement_id']}); project_vertical_lifecycle(s,"RAIL",o,"refund:"+r.refund_id,facts={"refund_id":r.refund_id,"refund_amount_minor":r.refund_amount_minor,"money_movement_id":movement['money_movement_id']}); s.flush()
            return {"refund_id":r.refund_id,"order_id":order_id,"status":r.status,"refund_fee_minor":r.refund_fee_minor,"refund_amount_minor":r.refund_amount_minor,"currency":o.currency}
    def admin_external_state(self,order_id,state,evidence_reference,actor,supplier_reference=None,ticket_numbers=None):
        if not str(evidence_reference or '').strip() or not str(actor or '').strip(): raise ValueError('EXTERNAL_STATE_ACTOR_AND_EVIDENCE_REQUIRED')
        state=state.upper();ticket_numbers=list(ticket_numbers or [])
        with SessionLocal() as s:
            o=s.get(RailOrderRow,order_id)
            if not o: raise ValueError("RAIL_ORDER_NOT_FOUND")
            pending=s.scalar(select(RailChangeQuoteRow).where(RailChangeQuoteRow.order_id==order_id,RailChangeQuoteRow.status=='PENDING_SUPPLIER').order_by(RailChangeQuoteRow.created_at.desc()))
            if state=='TICKETED' and o.status=='UNKNOWN_EXTERNAL_STATE' and pending:
                if not str(supplier_reference or '').strip() or not ticket_numbers: raise ValueError('RAIL_RECONCILIATION_SUPPLIER_REFERENCE_REQUIRED')
                due=pending.total_due_minor;qid=pending.quote_id
            elif state=='FAILED' and o.status=='UNKNOWN_EXTERNAL_STATE' and pending:due=pending.total_due_minor;qid=pending.quote_id
            else:due=0;qid=None
        if qid and state=='TICKETED':vertical_money_bridge.capture_adjustment('RAIL',qid,due,evidence_reference)
        if qid and state=='FAILED':vertical_money_bridge.release_adjustment('RAIL',qid,due,evidence_reference)
        with SessionLocal.begin() as sess:
            o=sess.get(RailOrderRow,order_id);pending=sess.scalar(select(RailChangeQuoteRow).where(RailChangeQuoteRow.order_id==order_id,RailChangeQuoteRow.status=='PENDING_SUPPLIER').order_by(RailChangeQuoteRow.created_at.desc()))
            if not o: raise ValueError("RAIL_ORDER_NOT_FOUND")
            if state=="UNKNOWN_EXTERNAL_STATE":
                if o.status!="TICKETED":raise ValueError("RAIL_ILLEGAL_STATE_TRANSITION")
                o.status=state;kind="EXTERNAL_STATE_UNKNOWN"
            elif state=="TICKETED":
                if o.status!="UNKNOWN_EXTERNAL_STATE":raise ValueError("RAIL_RECONCILIATION_NOT_REQUIRED")
                if pending:
                    if not str(supplier_reference or '').strip() or not ticket_numbers:raise ValueError('RAIL_RECONCILIATION_SUPPLIER_REFERENCE_REQUIRED')
                    j=dict(o.current_journey);j.update({"travel_date":pending.new_travel_date,"train_no":pending.new_train_no,"seat_class":pending.new_seat_class,"departure_time":"08:30","arrival_time":"09:18"});o.current_journey=j;o.total_amount_minor+=pending.total_due_minor;pending.status='EXECUTED';o.booking_reference=supplier_reference;o.ticket_numbers=ticket_numbers;kind='CHANGE_RECONCILED_TO_TICKETED'
                else:kind="RECONCILED_TO_TICKETED"
                o.status="TICKETED"
            elif state=="FAILED":
                if o.status!="UNKNOWN_EXTERNAL_STATE":raise ValueError("RAIL_RECONCILIATION_NOT_REQUIRED")
                if pending:pending.status='FAILED';o.status='TICKETED';kind='CHANGE_FAILED_RESTORED_TICKETED'
                else:o.status='FAILED';kind='RECONCILED_TO_FAILED'
            else:raise ValueError("RAIL_EXTERNAL_STATE_INVALID")
            o.updated_at=now();append_vertical_evidence(sess,"RAIL",o.order_id,kind,o.status,{"evidence_reference":evidence_reference,"actor":actor,"booking_reference":o.booking_reference,"ticket_numbers":o.ticket_numbers,"quote_id":pending.quote_id if pending else None});project_vertical_lifecycle(sess,"RAIL",o,evidence_reference,facts={"actor":actor,"native_status":o.status,"quote_id":pending.quote_id if pending else None});return self._order(o)

rail_service=RailService()
