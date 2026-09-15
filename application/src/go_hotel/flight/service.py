from __future__ import annotations
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, text
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import FlightOfferRow, FlightPrebookRow, FlightOrderRow, FlightChangeQuoteRow, FlightRefundRow
from go_hotel.domain.models import new_id
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence, list_vertical_evidence
from go_hotel.services.vertical_lifecycle_projection import project_vertical_lifecycle
from go_hotel.services.vertical_money_bridge import vertical_money_bridge
from go_hotel.core.production_truth_gate import production_truth_required
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge
from go_hotel.services import refund_consent, flight_refund_consent

def now(): return datetime.now(timezone.utc).replace(tzinfo=None)

class FlightService:
    def search(self, origin:str, destination:str, departure_date:str, cabin:str="ECONOMY", currency:str="CNY", adults:int=1):
        production_truth_required("FLIGHT", "SEARCH")
        if type(adults) is not int or not 1<=adults<=9:raise ValueError('FLIGHT_PASSENGER_COUNT_INVALID')
        templates=[
            ("GO","718","GO Flex",468000,68000,{"checked_bag_kg":23,"cabin_bag_kg":7},{"fee_minor":10000,"allowed":True},{"fee_minor":20000,"allowed":True},"09:20","13:15"),
            ("GO","726","GO Saver",398000,62000,{"checked_bag_kg":20,"cabin_bag_kg":7},{"fee_minor":18000,"allowed":True},{"fee_minor":35000,"allowed":True},"13:40","17:35"),
            ("GO","732","GO Light",358000,58000,{"checked_bag_kg":0,"cabin_bag_kg":7},{"fee_minor":28000,"allowed":True},{"fee_minor":0,"allowed":False},"18:10","22:05"),
        ]
        out=[]
        with SessionLocal.begin() as s:
            for carrier,num,family,total,tax,baggage,change,refund,dep,arr in templates:
                oid=new_id("flt_off")
                seg=[{"origin":origin,"destination":destination,"departure_date":departure_date,"departure_time":dep,"arrival_time":arr,"carrier_code":carrier,"flight_number":num,"duration_minutes":235,
                    'passenger_count':adults,'unit_total_amount_minor':total,'unit_tax_amount_minor':tax}]
                total*=adults;tax*=adults;change={**change,'fee_minor':change['fee_minor']*adults};refund={**refund,'fee_minor':refund['fee_minor']*adults}
                r=FlightOfferRow(offer_id=oid,origin=origin,destination=destination,departure_date=departure_date,carrier_code=carrier,flight_number=num,cabin=cabin,fare_family=family,total_amount_minor=total,tax_amount_minor=tax,currency=currency,baggage=baggage,change_policy=change,refund_policy=refund,segments=seg,expires_at=now()+timedelta(minutes=20),created_at=now())
                s.add(r); out.append(self._offer(r))
        return out
    def _offer(self,r):
        return {"passenger_count":(r.segments[0].get("passenger_count",1) if r.segments else 1),"trip_type":(r.segments[0].get("trip_type", "ONE_WAY") if r.segments else "ONE_WAY"),"data_mode":"SIMULATION","external_live":False,"offer_id":r.offer_id,"origin":r.origin,"destination":r.destination,"departure_date":r.departure_date,"carrier_code":r.carrier_code,"flight_number":r.flight_number,"cabin":r.cabin,"fare_family":r.fare_family,"total_amount_minor":r.total_amount_minor,"tax_amount_minor":r.tax_amount_minor,"currency":r.currency,"baggage":r.baggage,"change_policy":r.change_policy,"refund_policy":r.refund_policy,"segments":r.segments,"expires_at":r.expires_at.isoformat()}
    def get_offer(self,offer_id):
        production_truth_required("FLIGHT", "GET_OFFER")
        with SessionLocal() as s:
            r=s.get(FlightOfferRow,offer_id)
            if not r: raise ValueError("FLIGHT_OFFER_NOT_FOUND")
            return self._offer(r)
    def prebook(self,offer_id):
        production_truth_required("FLIGHT", "PREBOOK")
        with SessionLocal.begin() as s:
            o=s.get(FlightOfferRow,offer_id)
            if not o or o.expires_at < now(): raise ValueError("FLIGHT_OFFER_EXPIRED")
            p=FlightPrebookRow(prebook_id=new_id("flt_pb"),offer_id=offer_id,total_amount_minor=o.total_amount_minor,currency=o.currency,status="CONFIRMED",price_locked=True,inventory_confirmed=True,expires_at=min(o.expires_at,now()+timedelta(minutes=15)),created_at=now())
            s.add(p); s.flush()
            return {"passenger_count":(o.segments[0].get("passenger_count",1) if o.segments else 1),"prebook_id":p.prebook_id,"offer_id":offer_id,"status":p.status,"total_amount_minor":p.total_amount_minor,"currency":p.currency,"price_locked":True,"inventory_confirmed":True,"expires_at":p.expires_at.isoformat()}
    def create_order(self,account_id,prebook_id,passengers):
        production_truth_required("FLIGHT", "CREATE_ORDER")
        with SessionLocal.begin() as s:
            p=s.get(FlightPrebookRow,prebook_id)
            if not p or p.status!="CONFIRMED" or p.expires_at<now(): raise ValueError("FLIGHT_PREBOOK_INVALID")
            off=s.get(FlightOfferRow,p.offer_id)
            expected=off.segments[0].get('passenger_count',1) if off.segments else 1
            if len(passengers)!=expected:raise ValueError('FLIGHT_PASSENGER_COUNT_INVALID:REQUOTE_REQUIRED')
            if any(not isinstance(p,dict) or p.get('type','ADT')!='ADT' or not isinstance(p.get('full_name'),str) or not p['full_name'].strip() for p in passengers):
                raise ValueError('FLIGHT_PASSENGER_INVALID:ADULT_NAME_REQUIRED')
            o=FlightOrderRow(order_id=new_id("flt_ord"),account_id=account_id,prebook_id=prebook_id,status="PAYMENT_PENDING",total_amount_minor=p.total_amount_minor,currency=p.currency,passengers=passengers,payment_method_id=None,pnr=None,ticket_numbers=[],current_itinerary=off.segments,created_at=now(),updated_at=now())
            s.add(o); s.flush(); append_vertical_evidence(s,"FLIGHT",o.order_id,"ORDER_CREATED",o.status,{"prebook_id":prebook_id}); return self._order(o)
    def recover_checkout(self,account_id,order_id,payment_method_id,boundary):
        if not boundary or not boundary.recovering:
            raise ValueError('FLIGHT_RECOVERY_CONTEXT_REQUIRED')
        from .payment_recovery import checkout
        return checkout(self,account_id,order_id,payment_method_id,boundary)
    def checkout(self,account_id,order_id,payment_method_id,boundary=None):
        if boundary is not None:
            from .payment_recovery import checkout
            return checkout(self,account_id,order_id,payment_method_id,boundary)
        production_truth_required("FLIGHT", "CHECKOUT")
        with SessionLocal.begin() as s:
            o=s.get(FlightOrderRow,order_id)
            if not o or o.account_id!=account_id: raise ValueError("FLIGHT_ORDER_NOT_FOUND")
            if o.status not in {"PAYMENT_PENDING","PAYMENT_AUTHORIZED"}: return self._order(o)
            o.payment_method_id=payment_method_id; o.status="PAYMENT_AUTHORIZED"; o.updated_at=now(); s.flush()
            order_id=o.order_id; account=o.account_id; source_id=(s.get(FlightOfferRow,s.get(FlightPrebookRow,o.prebook_id).offer_id).carrier_code or 'AIRLINE')
        tx=vertical_transaction_bridge.checkout_contract('FLIGHT',order_id,account,source_id,f'flight-offer://{order_id}',payment_method_id)
        with SessionLocal.begin() as s:
            o=s.get(FlightOrderRow,order_id); o.status=tx['state']; o.updated_at=now(); append_vertical_evidence(s,'FLIGHT',order_id,'PAYMENT_CAPTURED',o.status,{'payment_intent_id':tx['payment_intent_id'],'capture_id':tx['capture_id'],'external_live':False}); s.flush(); return self._order(o)
    def _ticket_assignments(self,o):
        if o.status!='TICKETED' or len(o.ticket_numbers)!=len(o.passengers)*len(o.current_itinerary):return []
        return [{'leg_index':leg,'passenger_index':person,'passenger_name':p['full_name'],
            'ticket_number':o.ticket_numbers[leg*len(o.passengers)+person],
            'supplier_reference':o.current_itinerary[leg].get('supplier_reference',o.pnr)}
            for leg in range(len(o.current_itinerary)) for person,p in enumerate(o.passengers)]
    def _order(self,o):
        return {"passenger_count":len(o.passengers),"ticket_assignments":self._ticket_assignments(o),"trip_type":(o.current_itinerary[0].get("trip_type", "ONE_WAY") if o.current_itinerary else "ONE_WAY"),"data_mode":"SIMULATION","external_live":False,"order_id":o.order_id,"account_id":o.account_id,"status":o.status,"total_amount_minor":o.total_amount_minor,"currency":o.currency,"passengers":o.passengers,"pnr":o.pnr if o.status=="TICKETED" else None,"ticket_numbers":o.ticket_numbers if o.status=="TICKETED" else [],"itinerary":o.current_itinerary,"created_at":o.created_at.isoformat(),"updated_at":o.updated_at.isoformat()}
    def order(self,account_id,order_id):
        production_truth_required("FLIGHT", "ORDER_READ")
        with SessionLocal() as s:
            o=s.get(FlightOrderRow,order_id)
            if not o or o.account_id!=account_id: raise ValueError("FLIGHT_ORDER_NOT_FOUND")
            result=self._order(o)
            changes=s.scalars(select(FlightChangeQuoteRow).where(FlightChangeQuoteRow.order_id==order_id).order_by(FlightChangeQuoteRow.created_at)).all()
            refunds=s.scalars(select(FlightRefundRow).where(FlightRefundRow.order_id==order_id).order_by(FlightRefundRow.created_at)).all()
            result["change_quotes"]=[{"quote_id":x.quote_id,"status":x.status,"new_departure_date":x.new_departure_date,"new_flight_number":x.new_flight_number,"fare_difference_minor":x.fare_difference_minor,"change_fee_minor":x.change_fee_minor,"total_due_minor":x.total_due_minor,"currency":x.currency} for x in changes]
            from go_hotel.db.models import FlightChangePlanRow
            from go_hotel.flight.changes import public as change_public
            result['change_quotes']=[change_public(x,p) if (p:=s.get(FlightChangePlanRow,x.quote_id)) else item
                                     for x,item in zip(changes,result['change_quotes'])]
            result["refunds"]=[{"refund_id":x.refund_id,"status":x.status,"refund_fee_minor":x.refund_fee_minor,"refund_amount_minor":x.refund_amount_minor,"currency":x.currency} for x in refunds]
            result["evidence"]=list_vertical_evidence(s,"FLIGHT",order_id)
            return result
    def trips(self,account_id):
        production_truth_required("FLIGHT", "TRIPS_READ")
        with SessionLocal() as s:
            rows=s.scalars(select(FlightOrderRow).where(FlightOrderRow.account_id==account_id).order_by(FlightOrderRow.updated_at.desc())).all()
            return [self._order(x) for x in rows]
    def change_quote(self,account_id,order_id,new_departure_date=None,leg_index=None,changes=None):
        from go_hotel.flight.changes import create_quote
        return create_quote(account_id,order_id,new_departure_date,leg_index,changes)
    def recover_execute_change(self,account_id,order_id,quote_id,confirmation,boundary):
        if not boundary or not boundary.recovering:
            raise ValueError('FLIGHT_RECOVERY_CONTEXT_REQUIRED')
        from .payment_recovery import execute_change
        return execute_change(self,account_id,order_id,quote_id,confirmation,boundary)
    def execute_change(self,account_id,order_id,quote_id,confirmation=None,boundary=None):
        if boundary is not None:
            from .payment_recovery import execute_change
            return execute_change(self,account_id,order_id,quote_id,confirmation,boundary)
        production_truth_required('FLIGHT','EXECUTE_CHANGE')
        with SessionLocal() as s:
            if s.bind.dialect.name=='sqlite':s.execute(text('BEGIN IMMEDIATE'))
            o=s.get(FlightOrderRow,order_id,with_for_update=True);q=s.get(FlightChangeQuoteRow,quote_id)
            if not o or o.account_id!=account_id or not q or q.order_id!=order_id:raise ValueError('FLIGHT_CHANGE_QUOTE_INVALID')
            from go_hotel.flight.changes import checked,consent
            plan=checked(s,o,q,require_current=q.status not in {'EXECUTED','FAILED'})
            consent(o,q,plan,confirmation)
            if q.status=='PENDING_SUPPLIER' and o.status=='UNKNOWN_EXTERNAL_STATE':return self._order(o)|{'idempotent_replay':True}
            if q.status=='EXECUTED':return self._order(o)|{'idempotent_replay':True}
            resuming=q.status=='AUTHORIZATION_PENDING' and o.status=='UNKNOWN_EXTERNAL_STATE'
            if not resuming:
                if o.status!='TICKETED' or q.status!='QUOTED' or q.expires_at<now():raise ValueError('FLIGHT_CHANGE_QUOTE_INVALID')
                q.status='AUTHORIZATION_PENDING';o.status='UNKNOWN_EXTERNAL_STATE';o.updated_at=now()
                for other in s.scalars(select(FlightChangeQuoteRow).where(FlightChangeQuoteRow.order_id==order_id,
                    FlightChangeQuoteRow.quote_id!=quote_id,FlightChangeQuoteRow.status=='QUOTED')).all():other.status='SUPERSEDED'
                append_vertical_evidence(s,'FLIGHT',order_id,'CHANGE_AUTHORIZATION_REQUESTED',o.status,
                    {'quote_id':quote_id,'previous_pnr':o.pnr,'previous_ticket_numbers':o.ticket_numbers})
                project_vertical_lifecycle(s,'FLIGHT',o,'change-auth:'+quote_id,facts={'quote_id':quote_id})
            due=q.total_due_minor;s.commit()
        adjustment=vertical_money_bridge.prepare_adjustment('FLIGHT',order_id,quote_id,due,f'flight-change://{quote_id}')
        if adjustment and adjustment.get('released'):raise ValueError('FLIGHT_CHANGE_AUTHORIZATION_RELEASED_REQUOTE_REQUIRED')
        with SessionLocal() as s:
            if s.bind.dialect.name=='sqlite':s.execute(text('BEGIN IMMEDIATE'))
            o=s.get(FlightOrderRow,order_id,with_for_update=True);q=s.get(FlightChangeQuoteRow,quote_id)
            if q.status=='PENDING_SUPPLIER':return self._order(o)|{'idempotent_replay':True}
            if o.status!='UNKNOWN_EXTERNAL_STATE' or q.status!='AUTHORIZATION_PENDING':raise ValueError('FLIGHT_CHANGE_QUOTE_INVALID')
            checked(s,o,q)
            q.status='PENDING_SUPPLIER';o.updated_at=now()
            append_vertical_evidence(s,'FLIGHT',order_id,'CHANGE_SUBMITTED_AWAITING_SUPPLIER',o.status,
                {'quote_id':quote_id,'authorization_id':(adjustment or {}).get('authorization_id')})
            project_vertical_lifecycle(s,'FLIGHT',o,'change-pending:'+quote_id,
                facts={'quote_id':quote_id,'authorization_id':(adjustment or {}).get('authorization_id')})
            s.commit();return self._order(o)
    def refund_quote(self,account_id,order_id):
        production_truth_required("FLIGHT", "REFUND_QUOTE")
        with SessionLocal() as s:
            o=s.get(FlightOrderRow,order_id)
            if not o or o.account_id!=account_id or o.status!="TICKETED": raise ValueError("FLIGHT_ORDER_NOT_REFUNDABLE")
            offer=s.get(FlightOfferRow,s.get(FlightPrebookRow,o.prebook_id).offer_id)
            if not offer.refund_policy.get("allowed", False):
                raise ValueError("FLIGHT_ORDER_NOT_REFUNDABLE:FARE_POLICY")
            fee=offer.refund_policy.get("fee_minor", 0); amount=max(0,o.total_amount_minor-fee)
            return refund_consent.bind('FLIGHT',o,{"order_id":order_id,"refund_fee_minor":fee,"refund_amount_minor":amount,"currency":o.currency,"refund_to":"ORIGINAL_PAYMENT_METHOD"})
    def refund(self,account_id,order_id,accepted_hash=None):
        production_truth_required("FLIGHT", "REFUND")
        def result(row):
            return {'refund_id':row.refund_id,'order_id':order_id,'status':row.status,
                'refund_fee_minor':row.refund_fee_minor,'refund_amount_minor':row.refund_amount_minor,'currency':row.currency}
        with SessionLocal() as s:
            if s.bind.dialect.name=='sqlite':s.execute(text('BEGIN IMMEDIATE'))
            order=s.get(FlightOrderRow,order_id,with_for_update=True)
            if not order or order.account_id!=account_id:raise ValueError('FLIGHT_ORDER_NOT_FOUND')
            row=s.scalar(select(FlightRefundRow).where(FlightRefundRow.order_id==order_id,
                FlightRefundRow.status.in_(['REFUND_PENDING','REFUND_COMPLETED'])).order_by(FlightRefundRow.created_at.desc()))
            if row:
                flight_refund_consent.existing(s,order,row,accepted_hash)
            if row and row.status=='REFUND_COMPLETED':return result(row)|{'idempotent_replay':True}
            if not row:
                if order.status!='TICKETED':raise ValueError('FLIGHT_ORDER_NOT_REFUNDABLE')
                offer=s.get(FlightOfferRow,s.get(FlightPrebookRow,order.prebook_id).offer_id)
                if not offer.refund_policy.get('allowed',False):raise ValueError('FLIGHT_ORDER_NOT_REFUNDABLE:FARE_POLICY')
                fee=offer.refund_policy.get('fee_minor',0);amount=max(0,order.total_amount_minor-fee)
                row=FlightRefundRow(refund_id=new_id('flt_ref'),order_id=order_id,refund_fee_minor=fee,
                    refund_amount_minor=amount,currency=order.currency,status='REFUND_PENDING',created_at=now(),completed_at=None)
                quote=refund_consent.bind('FLIGHT',order,{'order_id':order_id,'refund_fee_minor':fee,
                    'refund_amount_minor':amount,'currency':order.currency,'refund_to':'ORIGINAL_PAYMENT_METHOD'})
                flight_refund_consent.freeze(s,order,row,quote,accepted_hash)
                s.add(row);order.status='REFUND_PENDING';order.updated_at=now();s.flush()
                append_vertical_evidence(s,'FLIGHT',order_id,'REFUND_REQUESTED',order.status,{'refund_id':row.refund_id,'refund_amount_minor':amount})
                project_vertical_lifecycle(s,'FLIGHT',order,'refund-request:'+row.refund_id,facts={'refund_id':row.refund_id})
            elif order.status!='REFUND_PENDING':raise ValueError('FLIGHT_REFUND_STATE_INVALID')
            amount=row.refund_amount_minor;refund_id=row.refund_id
            changes=s.scalars(select(FlightChangeQuoteRow).where(FlightChangeQuoteRow.order_id==order_id,
                FlightChangeQuoteRow.status=='EXECUTED').order_by(FlightChangeQuoteRow.created_at,FlightChangeQuoteRow.quote_id)).all()
            adjustments=[q.quote_id for q in changes if q.total_due_minor>0];s.commit()
        movement=vertical_money_bridge.refund_with_adjustments('FLIGHT',order_id,adjustments,amount,
            f'flight-refund://{order_id}',f'flight-refund:{order_id}')
        if movement['state']!='CONFIRMED':raise ValueError('FLIGHT_REFUND_MONEY_NOT_CONFIRMED')
        with SessionLocal() as s:
            if s.bind.dialect.name=='sqlite':s.execute(text('BEGIN IMMEDIATE'))
            order=s.get(FlightOrderRow,order_id,with_for_update=True);row=s.get(FlightRefundRow,refund_id)
            flight_refund_consent.existing(s,order,row,accepted_hash)
            if row.status=='REFUND_COMPLETED':return result(row)|{'idempotent_replay':True}
            if order.status!='REFUND_PENDING':raise ValueError('FLIGHT_REFUND_STATE_INVALID')
            row.status='REFUND_COMPLETED';row.completed_at=now();order.status='REFUNDED';order.updated_at=now()
            flight_refund_consent.complete(s,order,row)
            facts={'refund_id':refund_id,'refund_amount_minor':amount,'money_movement_id':movement['money_movement_id'],
                'money_movement_ids':movement.get('money_movement_ids',[movement['money_movement_id']])}
            append_vertical_evidence(s,'FLIGHT',order_id,'REFUND_COMPLETED',order.status,facts)
            project_vertical_lifecycle(s,'FLIGHT',order,'refund:'+refund_id,facts=facts);s.commit();return result(row)
    def admin_external_state(self,order_id,state,evidence_reference,actor,supplier_reference=None,ticket_numbers=None,quote_id=None):
        from go_hotel.db.models import FlightChangePlanRow,FlightChangeResolutionRow
        with SessionLocal() as s:
            managed=quote_id or s.scalar(select(FlightChangePlanRow.quote_id).where(FlightChangePlanRow.order_id==order_id))
        if managed:
            from go_hotel.services.flight_change_resolution import reconcile
            return reconcile(order_id,state,evidence_reference,actor,supplier_reference,ticket_numbers,quote_id,self._order)
        return self._legacy_admin_external_state(order_id,state,evidence_reference,actor,supplier_reference,ticket_numbers)

    def _legacy_admin_external_state(self,order_id,state,evidence_reference,actor,supplier_reference=None,ticket_numbers=None):
        if not str(evidence_reference or '').strip() or not str(actor or '').strip(): raise ValueError('EXTERNAL_STATE_ACTOR_AND_EVIDENCE_REQUIRED')
        state=state.upper();ticket_numbers=list(ticket_numbers or [])
        with SessionLocal() as s:
            o=s.get(FlightOrderRow,order_id)
            if not o: raise ValueError("FLIGHT_ORDER_NOT_FOUND")
            pending=s.scalar(select(FlightChangeQuoteRow).where(FlightChangeQuoteRow.order_id==order_id,FlightChangeQuoteRow.status=='PENDING_SUPPLIER').order_by(FlightChangeQuoteRow.created_at.desc()))
            if state=='TICKETED' and o.status=='UNKNOWN_EXTERNAL_STATE' and pending:
                if not str(supplier_reference or '').strip() or not ticket_numbers: raise ValueError('FLIGHT_RECONCILIATION_SUPPLIER_REFERENCE_REQUIRED')
                due=pending.total_due_minor; qid=pending.quote_id
            elif state=='FAILED' and o.status=='UNKNOWN_EXTERNAL_STATE' and pending:
                due=pending.total_due_minor; qid=pending.quote_id
            else: due=0;qid=None
        if qid and state=='TICKETED': vertical_money_bridge.capture_adjustment('FLIGHT',qid,due,evidence_reference)
        if qid and state=='FAILED': vertical_money_bridge.release_adjustment('FLIGHT',qid,due,evidence_reference)
        with SessionLocal.begin() as sess:
            o=sess.get(FlightOrderRow,order_id)
            if not o: raise ValueError("FLIGHT_ORDER_NOT_FOUND")
            pending=sess.scalar(select(FlightChangeQuoteRow).where(FlightChangeQuoteRow.order_id==order_id,FlightChangeQuoteRow.status=='PENDING_SUPPLIER').order_by(FlightChangeQuoteRow.created_at.desc()))
            if state=="UNKNOWN_EXTERNAL_STATE":
                if o.status!="TICKETED": raise ValueError("FLIGHT_ILLEGAL_STATE_TRANSITION")
                o.status=state;kind="EXTERNAL_STATE_UNKNOWN"
            elif state=="TICKETED":
                if o.status!="UNKNOWN_EXTERNAL_STATE": raise ValueError("FLIGHT_RECONCILIATION_NOT_REQUIRED")
                if pending:
                    if not str(supplier_reference or '').strip() or not ticket_numbers: raise ValueError('FLIGHT_RECONCILIATION_SUPPLIER_REFERENCE_REQUIRED')
                    it=list(o.current_itinerary);it[0]={**it[0],"departure_date":pending.new_departure_date,"flight_number":pending.new_flight_number};o.current_itinerary=it;o.total_amount_minor+=pending.total_due_minor;pending.status='EXECUTED';o.pnr=supplier_reference;o.ticket_numbers=ticket_numbers;kind='CHANGE_RECONCILED_TO_TICKETED'
                else: kind="RECONCILED_TO_TICKETED"
                o.status="TICKETED"
            elif state=="FAILED":
                if o.status!="UNKNOWN_EXTERNAL_STATE": raise ValueError("FLIGHT_RECONCILIATION_NOT_REQUIRED")
                if pending: pending.status='FAILED';o.status='TICKETED';kind='CHANGE_FAILED_RESTORED_TICKETED'
                else:o.status='FAILED';kind='RECONCILED_TO_FAILED'
            else: raise ValueError("FLIGHT_EXTERNAL_STATE_INVALID")
            o.updated_at=now();append_vertical_evidence(sess,"FLIGHT",o.order_id,kind,o.status,{"evidence_reference":evidence_reference,"actor":actor,"pnr":o.pnr,"ticket_numbers":o.ticket_numbers,"quote_id":pending.quote_id if pending else None});project_vertical_lifecycle(sess,"FLIGHT",o,evidence_reference,facts={"actor":actor,"native_status":o.status,"quote_id":pending.quote_id if pending else None});return self._order(o)

flight_service=FlightService()
