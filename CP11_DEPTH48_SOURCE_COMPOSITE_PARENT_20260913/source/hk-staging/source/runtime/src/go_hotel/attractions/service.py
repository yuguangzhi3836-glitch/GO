from datetime import UTC, datetime, timedelta
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import AttractionOrderRow,AttractionChangeQuoteRow,AttractionRefundRow
from go_hotel.domain.models import new_id
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence, list_vertical_evidence
from go_hotel.services.vertical_lifecycle_projection import project_vertical_lifecycle
from go_hotel.services.vertical_money_bridge import vertical_money_bridge
from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service
from go_hotel.core.production_truth_gate import production_truth_required

def now(): return datetime.now(UTC).replace(tzinfo=None)
CATALOG={
 "tokyo_skytree":{"name":"东京晴空塔天望甲板","type":"ATTRACTION","destination":"东京","ticket_type":"成人票","price":18000,"session":"16:00","eligibility":{"age":"12+ adult","id_required":False},"voucher_type":"QR_CODE","inventory":24,"changeable":True,"refundable":True},
 "teamlab_planets":{"name":"teamLab Planets TOKYO","type":"EXPERIENCE","destination":"东京","ticket_type":"标准入场","price":26000,"session":"18:30","eligibility":{"age":"all","id_required":False},"voucher_type":"QR_CODE","inventory":8,"changeable":True,"refundable":False},
 "tokyo_concert":{"name":"Tokyo Live Night","type":"EVENT","destination":"东京","ticket_type":"指定席 A","price":68000,"session":"19:30","eligibility":{"age":"6+","id_required":True},"voucher_type":"E_TICKET","inventory":4,"changeable":False,"refundable":True},
}
class AttractionService:
 def search(self,destination,visit_date,product_type=None,currency="CNY"):
  production_truth_required("ATTRACTION", "SEARCH")
  items=[]
  for pid,x in CATALOG.items():
   if destination not in x["destination"]: continue
   if product_type and x["type"]!=product_type: continue
   items.append({"offer_id":pid,"product_id":pid,"product_name":x["name"],"product_type":x["type"],"destination":x["destination"],"visit_date":visit_date,"session_time":x["session"],"ticket_type":x["ticket_type"],"total_amount_minor":x["price"],"currency":currency,"inventory_units":x["inventory"],"eligibility":x["eligibility"],"voucher_type":x["voucher_type"],"changeable":x["changeable"],"refundable":x["refundable"],"external_live":False})
  return items
 def prebook(self,offer_id,visit_date,quantity=1,currency="CNY"):
  production_truth_required("ATTRACTION", "PREBOOK")
  x=CATALOG.get(offer_id)
  if not x: raise ValueError("ATTRACTION_OFFER_NOT_FOUND")
  if quantity<1 or quantity>x["inventory"]: raise ValueError("ATTRACTION_INVENTORY_CHANGED")
  return {"prebook_id":new_id("attr_pre"),"offer_id":offer_id,"product_name":x["name"],"visit_date":visit_date,"session_time":x["session"],"ticket_type":x["ticket_type"],"quantity":quantity,"unit_amount_minor":x["price"],"total_amount_minor":x["price"]*quantity,"currency":currency,"inventory_confirmed":True,"eligibility":x["eligibility"],"changeable":x["changeable"],"refundable":x["refundable"],"expires_at":(now()+timedelta(minutes=10)).isoformat()}
 def create_order(self,account,b):
  production_truth_required("ATTRACTION", "CREATE_ORDER")
  x=CATALOG.get(b["offer_id"])
  if not x: raise ValueError("ATTRACTION_OFFER_NOT_FOUND")
  q=int(b.get("quantity",1))
  if q<1 or q>x["inventory"]: raise ValueError("ATTRACTION_INVENTORY_CHANGED")
  with SessionLocal.begin() as s:
   o=AttractionOrderRow(order_id=new_id("attr_ord"),account_id=account,status="PAYMENT_PENDING",product_id=b["offer_id"],product_name=x["name"],product_type=x["type"],destination=x["destination"],visit_date=b["visit_date"],session_time=b.get("session_time") or x["session"],ticket_type=x["ticket_type"],quantity=q,eligibility=x["eligibility"],voucher_type=x["voucher_type"],voucher_code=None,total_amount_minor=x["price"]*q,currency=b.get("currency","CNY"),attendees=b.get("attendees",[]),supplier_reference=None,created_at=now(),updated_at=now());s.add(o);s.flush()
   append_vertical_evidence(s,"ATTRACTION",o.order_id,"ORDER_CREATED",o.status,{"offer_id":b["offer_id"],"external_live":False})
   result=self.out(o)
  vertical_source_runtime_service.decide("ATTRACTION",result["order_id"],[{"source_id":"attraction-engineering-source","source_type":"ATTRACTION_OFFICIAL","authorized":True,"available":True,"evidence_reference":f"attraction-offer://{b['offer_id']}"}])
  return result
 def out(self,o): return {"vertical":"ATTRACTION","order_id":o.order_id,"status":o.status,"product_id":o.product_id,"product_name":o.product_name,"product_type":o.product_type,"destination":o.destination,"visit_date":o.visit_date,"session_time":o.session_time,"ticket_type":o.ticket_type,"quantity":o.quantity,"eligibility":o.eligibility,"voucher_type":o.voucher_type,"voucher_code":o.voucher_code if o.status=="CONFIRMED" else None,"total_amount_minor":o.total_amount_minor,"currency":o.currency,"attendees":o.attendees,"supplier_reference":o.supplier_reference if o.status=="CONFIRMED" else None,"external_live":False}
 def get(self,account,order_id):
  with SessionLocal() as s:
   o=s.get(AttractionOrderRow,order_id)
   if not o or o.account_id!=account: raise ValueError("ATTRACTION_ORDER_NOT_FOUND")
   out=self.out(o);out["evidence"]=list_vertical_evidence(s,"ATTRACTION",order_id);return out
 def trips(self,account):
  with SessionLocal() as s:return [self.out(x) for x in s.scalars(select(AttractionOrderRow).where(AttractionOrderRow.account_id==account)).all()]
 def change_quote(self,account,order_id,new_visit_date,new_session_time=None):
  production_truth_required("ATTRACTION", "CHANGE_QUOTE")
  order=self.get(account,order_id);x=CATALOG[order["product_id"]]
  if order["status"]!="CONFIRMED": raise ValueError("ATTRACTION_ORDER_NOT_CHANGEABLE")
  if not x["changeable"]: raise ValueError("ATTRACTION_NOT_CHANGEABLE")
  with SessionLocal.begin() as s:
   q=AttractionChangeQuoteRow(quote_id=new_id("attr_chg"),order_id=order_id,new_visit_date=new_visit_date,new_session_time=new_session_time or order["session_time"],change_fee_minor=0,total_due_minor=0,currency=order["currency"],status="QUOTED",expires_at=now()+timedelta(minutes=10),created_at=now());s.add(q);s.flush();return {"quote_id":q.quote_id,"order_id":order_id,"new_visit_date":q.new_visit_date,"new_session_time":q.new_session_time,"change_fee_minor":0,"total_due_minor":0,"currency":q.currency,"expires_at":q.expires_at.isoformat()}
 def execute_change(self,account,order_id,quote_id):
  production_truth_required("ATTRACTION", "EXECUTE_CHANGE")
  self.get(account,order_id)
  with SessionLocal.begin() as s:
   q=s.get(AttractionChangeQuoteRow,quote_id);o=s.get(AttractionOrderRow,order_id)
   if not o or o.account_id!=account or o.status!="CONFIRMED" or not q or q.order_id!=order_id or q.status!="QUOTED" or q.expires_at<now(): raise ValueError("ATTRACTION_CHANGE_QUOTE_NOT_FOUND")
   q.status='PENDING_SUPPLIER';o.status='UNKNOWN_EXTERNAL_STATE';o.updated_at=now();append_vertical_evidence(s,"ATTRACTION",o.order_id,"CHANGE_SUBMITTED_AWAITING_SUPPLIER",o.status,{"quote_id":quote_id,"previous_voucher_code":o.voucher_code,"previous_supplier_reference":o.supplier_reference});project_vertical_lifecycle(s,"ATTRACTION",o,"change-pending:"+quote_id,facts={"quote_id":quote_id});return self.out(o)
 def refund_quote(self,account,order_id):
  production_truth_required("ATTRACTION", "REFUND_QUOTE")
  o=self.get(account,order_id)
  if o["status"]!="CONFIRMED": raise ValueError("ATTRACTION_ORDER_NOT_REFUNDABLE")
  x=CATALOG[o["product_id"]];fee=0 if x["refundable"] else o["total_amount_minor"];return {"order_id":order_id,"refund_fee_minor":fee,"refund_amount_minor":o["total_amount_minor"]-fee,"currency":o["currency"],"refund_to":"ORIGINAL_PAYMENT_METHOD","refundable":x["refundable"]}
 def refund(self,account,order_id):
  production_truth_required("ATTRACTION", "REFUND")
  quote=self.refund_quote(account,order_id)
  if quote["refund_amount_minor"]<=0: raise ValueError("ATTRACTION_NON_REFUNDABLE")
  movement=vertical_money_bridge.refund('ATTRACTION',order_id,quote['refund_amount_minor'],f'attraction-refund://{order_id}',f'attraction-refund:{order_id}')
  if movement['state']!='CONFIRMED': raise ValueError('ATTRACTION_REFUND_MONEY_NOT_CONFIRMED')
  with SessionLocal.begin() as s:
   o=s.get(AttractionOrderRow,order_id);existing=s.scalar(select(AttractionRefundRow).where(AttractionRefundRow.order_id==order_id,AttractionRefundRow.status=='REFUND_COMPLETED').order_by(AttractionRefundRow.created_at.desc()))
   if existing:return {"refund_id":existing.refund_id,"order_id":order_id,"status":existing.status,"refund_amount_minor":existing.refund_amount_minor,"currency":existing.currency}
   if not o or o.account_id!=account or o.status!="CONFIRMED":raise ValueError("ATTRACTION_ORDER_NOT_REFUNDABLE")
   o.status="REFUNDED";o.updated_at=now();r=AttractionRefundRow(refund_id=new_id("attr_ref"),order_id=order_id,refund_fee_minor=quote["refund_fee_minor"],refund_amount_minor=quote["refund_amount_minor"],currency=o.currency,status="REFUND_COMPLETED",created_at=now(),completed_at=now());s.add(r);append_vertical_evidence(s,"ATTRACTION",o.order_id,"REFUND_COMPLETED",o.status,{"refund_id":r.refund_id,"refund_amount_minor":r.refund_amount_minor,"money_movement_id":movement['money_movement_id']});project_vertical_lifecycle(s,"ATTRACTION",o,"refund:"+r.refund_id,facts={"refund_id":r.refund_id,"refund_amount_minor":r.refund_amount_minor,"money_movement_id":movement['money_movement_id']});s.flush();return {"refund_id":r.refund_id,"order_id":order_id,"status":r.status,"refund_amount_minor":r.refund_amount_minor,"currency":r.currency}
 def redeem(self,account,order_id,evidence_reference):
  if not str(evidence_reference or '').strip(): raise ValueError('FULFILLMENT_EVIDENCE_REQUIRED')
  production_truth_required("ATTRACTION", "REDEEM")
  with SessionLocal.begin() as s:
   o=s.get(AttractionOrderRow,order_id)
   if not o or o.account_id!=account: raise ValueError("ATTRACTION_ORDER_NOT_FOUND")
   if o.status!="CONFIRMED": raise ValueError("ATTRACTION_ILLEGAL_STATE_TRANSITION")
   voucher_code=o.voucher_code; supplier_reference=o.supplier_reference
   o.status="FULFILLED";o.updated_at=now();append_vertical_evidence(s,"ATTRACTION",order_id,"VOUCHER_REDEEMED",o.status,{"evidence_reference":evidence_reference,"voucher_code":voucher_code,"supplier_reference":supplier_reference,"external_live":False});project_vertical_lifecycle(s,"ATTRACTION",o,evidence_reference,facts={"voucher_code":voucher_code,"supplier_reference":supplier_reference});return self.out(o)
 def admin_external_state(self,order_id,state,evidence_reference,actor,supplier_reference=None,voucher_code=None):
  if not str(evidence_reference or '').strip() or not str(actor or '').strip(): raise ValueError('EXTERNAL_STATE_ACTOR_AND_EVIDENCE_REQUIRED')
  state=state.upper()
  with SessionLocal.begin() as s:
   o=s.get(AttractionOrderRow,order_id)
   if not o: raise ValueError("ATTRACTION_ORDER_NOT_FOUND")
   pending=s.scalar(select(AttractionChangeQuoteRow).where(AttractionChangeQuoteRow.order_id==order_id,AttractionChangeQuoteRow.status=='PENDING_SUPPLIER').order_by(AttractionChangeQuoteRow.created_at.desc()))
   if state=="UNKNOWN_EXTERNAL_STATE":
    if o.status!="CONFIRMED": raise ValueError("ATTRACTION_ILLEGAL_STATE_TRANSITION")
    o.status=state;kind="EXTERNAL_STATE_UNKNOWN"
   elif state=="CLOSED_BY_SUPPLIER":
    if o.status not in {"CONFIRMED","UNKNOWN_EXTERNAL_STATE"}: raise ValueError("ATTRACTION_ILLEGAL_STATE_TRANSITION")
    if pending:pending.status='FAILED'
    o.status=state;kind="SUPPLIER_CLOSED"
   elif state=="CONFIRMED":
    if o.status!="UNKNOWN_EXTERNAL_STATE": raise ValueError("ATTRACTION_RECONCILIATION_NOT_REQUIRED")
    if pending:
     if not str(supplier_reference or '').strip() or not str(voucher_code or '').strip(): raise ValueError('ATTRACTION_RECONCILIATION_VOUCHER_REQUIRED')
     o.visit_date=pending.new_visit_date;o.session_time=pending.new_session_time;pending.status='APPLIED';o.supplier_reference=supplier_reference;o.voucher_code=voucher_code;kind='CHANGE_RECONCILED_TO_CONFIRMED'
    else:kind="RECONCILED_TO_CONFIRMED"
    o.status=state
   else: raise ValueError("ATTRACTION_EXTERNAL_STATE_INVALID")
   o.updated_at=now();append_vertical_evidence(s,"ATTRACTION",order_id,kind,o.status,{"evidence_reference":evidence_reference,"actor":actor,"supplier_reference":o.supplier_reference,"voucher_code":o.voucher_code,"quote_id":pending.quote_id if pending else None,"external_live":False});project_vertical_lifecycle(s,"ATTRACTION",o,evidence_reference,facts={"actor":actor,"supplier_reference":o.supplier_reference,"voucher_code":o.voucher_code,"quote_id":pending.quote_id if pending else None});return self.out(o)

attraction_service=AttractionService()
