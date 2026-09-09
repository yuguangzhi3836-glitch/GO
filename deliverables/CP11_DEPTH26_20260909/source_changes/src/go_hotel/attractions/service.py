from go_hotel.services import vertical_reservation_expiry as reservation_expiry
from datetime import UTC, datetime, timedelta, date
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import AttractionOrderRow,AttractionChangeQuoteRow,AttractionRefundRow
from go_hotel.domain.models import new_id
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence, list_vertical_evidence
from go_hotel.services.vertical_lifecycle_projection import project_vertical_lifecycle
from go_hotel.services.vertical_money_bridge import vertical_money_bridge
from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service
from go_hotel.core.production_truth_gate import production_truth_required
from go_hotel.autonomy.durable import transaction,digest
from go_hotel.services import vertical_prebook_contract as contracts
from go_hotel.services import vertical_refund_recovery
from go_hotel.services import vertical_capacity as capacity
from go_hotel.db.models import VerticalPrebookContractRow

def now(): return datetime.now(UTC).replace(tzinfo=None)
CATALOG={
 "tokyo_skytree":{"name":"东京晴空塔天望甲板","type":"ATTRACTION","destination":"东京","ticket_type":"成人票","price":18000,"session":"16:00","sessions":["16:00","17:00"],"eligibility":{"age":"12+ adult","id_required":False},"voucher_type":"QR_CODE","inventory":24,"changeable":True,"refundable":True},
 "teamlab_planets":{"name":"teamLab Planets TOKYO","type":"EXPERIENCE","destination":"东京","ticket_type":"标准入场","price":26000,"session":"18:30","sessions":["18:30"],"eligibility":{"age":"all","id_required":False},"voucher_type":"QR_CODE","inventory":8,"changeable":True,"refundable":False},
 "tokyo_concert":{"name":"Tokyo Live Night","type":"EVENT","destination":"东京","ticket_type":"指定席 A","price":68000,"session":"19:30","sessions":["19:30"],"eligibility":{"age":"6+","id_required":True},"voucher_type":"E_TICKET","inventory":4,"changeable":False,"refundable":True},
}
class AttractionService:
 def _catalog(self,offer_id,visit_date,session_time=None,currency='CNY'):
  x=CATALOG.get(offer_id)
  if not x:raise ValueError('ATTRACTION_OFFER_NOT_FOUND')
  try:
   if date.fromisoformat(visit_date).isoformat()!=visit_date:raise ValueError()
  except (TypeError,ValueError):raise ValueError('ATTRACTION_DATE_INVALID') from None
  if currency!='CNY':raise ValueError('ATTRACTION_ENGINEERING_CURRENCY_INVALID')
  session=session_time or x['session']
  if session not in x['sessions']:raise ValueError('ATTRACTION_SESSION_INVALID')
  return x,session
 def _order_terms(self,s,order_id):
  row=s.scalar(select(VerticalPrebookContractRow).where(VerticalPrebookContractRow.vertical=='ATTRACTION',VerticalPrebookContractRow.order_id==order_id))
  order=s.get(AttractionOrderRow,order_id)
  if (not row or not order or row.terms_hash!=digest(contracts._identity(row)) or
      row.state!='CONSUMED' or row.owner_id!=order.account_id or
      row.issued_account_id not in {None,order.account_id} or not row.consumed_hash or row.consumed_ms is None):
   raise ValueError('ATTRACTION_LEGACY_TERMS_REVIEW_REQUIRED')
  terms=row.terms_json
  # Date/session and total can change after a supplier-confirmed change. The
  # product, currency and booked party remain bound to the consumed contract.
  if (terms.get('offer_id')!=order.product_id or terms.get('currency')!=order.currency or
      terms.get('quantity')!=order.quantity or not isinstance(order.attendees,list) or
      len(order.attendees)!=order.quantity):
   raise ValueError('ATTRACTION_ORDER_TERMS_INTEGRITY_INVALID')
  return row.terms_json
 def search(self,destination,visit_date,product_type=None,currency="CNY"):
  production_truth_required("ATTRACTION", "SEARCH")
  if currency!='CNY':raise ValueError('ATTRACTION_ENGINEERING_CURRENCY_INVALID')
  try:
   if date.fromisoformat(visit_date).isoformat()!=visit_date:raise ValueError()
  except (ValueError,TypeError):raise ValueError('ATTRACTION_DATE_INVALID') from None
  items=[]
  for pid,x in CATALOG.items():
   if destination not in x["destination"]: continue
   if product_type and x["type"]!=product_type: continue
   items.append({"offer_id":pid,"product_id":pid,"product_name":x["name"],"product_type":x["type"],"destination":x["destination"],"visit_date":visit_date,"session_time":x["session"],"available_sessions":x["sessions"],"price_basis":"PER_TICKET","unit_amount_minor":x["price"],"ticket_type":x["ticket_type"],"total_amount_minor":x["price"],"currency":currency,"inventory_units":x["inventory"],"eligibility":x["eligibility"],"voucher_type":x["voucher_type"],"changeable":x["changeable"],"refundable":x["refundable"],"external_live":False})
  with transaction(SessionLocal) as s:
   for item in items:
    available={session:capacity.available_in(s,'ATTRACTION',capacity.attraction_resource(item['offer_id'],visit_date,session),CATALOG[item['offer_id']]['inventory']) for session in item['available_sessions']}
    item['inventory_by_session']=available;item['inventory_units']=available[item['session_time']]
  return items
 def prebook(self,offer_id,visit_date,quantity=1,currency='CNY',session_time=None,account=None):
  production_truth_required('ATTRACTION','PREBOOK')
  quantity=contracts.party_count(quantity,100)
  x,session=self._catalog(offer_id,visit_date,session_time,currency)
  if quantity>x['inventory']:raise ValueError('ATTRACTION_INVENTORY_CHANGED')
  terms={'offer_id':offer_id,'product_name':x['name'],'product_type':x['type'],'destination':x['destination'],
   'visit_date':visit_date,'session_time':session,'available_sessions':x['sessions'],'ticket_type':x['ticket_type'],
   'quantity':quantity,'unit_amount_minor':x['price'],'total_amount_minor':x['price']*quantity,'currency':currency,
   'eligibility':x['eligibility'],'voucher_type':x['voucher_type'],'changeable':x['changeable'],'refundable':x['refundable'],
   'inventory_observed_units':x['inventory'],'inventory_reserved':False}
  with transaction(SessionLocal) as s:
   left=capacity.available_in(s,'ATTRACTION',capacity.attraction_resource(offer_id,visit_date,session),x['inventory'])
   if left<quantity:raise ValueError('ATTRACTION_INVENTORY_CHANGED')
   terms['inventory_observed_units']=left
   row=contracts.issue_in(s,'ATTRACTION',new_id('attr_pre'),terms,account=account)
   return contracts.projection(row)|{'inventory_confirmed':True,'expires_at':datetime.fromtimestamp(row.expires_ms/1000,UTC).isoformat()}
 def create_order(self,account,b):
  production_truth_required('ATTRACTION','CREATE_ORDER')
  if not b.get('prebook_id'):raise ValueError('ATTRACTION_PREBOOK_REQUIRED')
  with transaction(SessionLocal) as s:
   request={k:b.get(k) for k in ('offer_id','visit_date','session_time','quantity','currency','attendees','traveler_ids')}
   contract,replay=contracts.current_in(s,'ATTRACTION',b['prebook_id'],account,request)
   if replay:
    old=s.get(AttractionOrderRow,contract.order_id)
    if not old or old.account_id!=account:raise ValueError('ATTRACTION_PREBOOK_ORDER_INTEGRITY_INVALID')
    return self.out(old)
   terms=contract.terms_json
   for key in ('offer_id','visit_date','quantity','currency'):
    if b.get(key,1 if key=='quantity' else 'CNY' if key=='currency' else None)!=terms[key]:raise ValueError('ATTRACTION_PREBOOK_BODY_MISMATCH')
   if b.get('session_time') not in {None,terms['session_time']}:raise ValueError('ATTRACTION_PREBOOK_SESSION_MISMATCH')
   people=contracts.named_party(b.get('attendees'),terms['quantity'],maximum=100,adults_only=terms['ticket_type']=='成人票')
   contracts.party_refs(b.get('traveler_ids'),terms['quantity'])
   current,_=self._catalog(terms['offer_id'],terms['visit_date'],terms['session_time'],terms['currency'])
   if current['inventory']<terms['quantity']:raise ValueError('ATTRACTION_INVENTORY_CHANGED')
   o=AttractionOrderRow(order_id=new_id('attr_ord'),account_id=account,status='PAYMENT_PENDING',product_id=terms['offer_id'],
    product_name=terms['product_name'],product_type=terms['product_type'],destination=terms['destination'],visit_date=terms['visit_date'],
    session_time=terms['session_time'],ticket_type=terms['ticket_type'],quantity=terms['quantity'],eligibility=terms['eligibility'],
    voucher_type=terms['voucher_type'],voucher_code=None,total_amount_minor=terms['total_amount_minor'],currency=terms['currency'],
    attendees=people,supplier_reference=None,created_at=now(),updated_at=now())
   capacity.reserve_in(s,'ATTRACTION',o.order_id,'ORIGINAL',capacity.attraction_resource(o.product_id,o.visit_date,o.session_time),current['inventory'],o.quantity)
   s.add(o);s.flush();reservation_expiry.issue_in(s,'ATTRACTION',o);contracts.consume_in(s,contract,account,o.order_id,request)
   append_vertical_evidence(s,'ATTRACTION',o.order_id,'ORDER_CREATED',o.status,{'prebook_id':contract.prebook_id,'terms_hash':contract.terms_hash,'external_live':False})
   result=self.out(o)
  vertical_source_runtime_service.decide('ATTRACTION',result['order_id'],[{'source_id':'attraction-engineering-source','source_type':'ATTRACTION_OFFICIAL','authorized':True,'available':True,'evidence_reference':f"attraction-prebook://{b['prebook_id']}"}])
  return result
 def out(self,o): return {"vertical":"ATTRACTION","order_id":o.order_id,"status":o.status,"product_id":o.product_id,"product_name":o.product_name,"product_type":o.product_type,"destination":o.destination,"visit_date":o.visit_date,"session_time":o.session_time,"ticket_type":o.ticket_type,"quantity":o.quantity,"eligibility":o.eligibility,"voucher_type":o.voucher_type,"voucher_code":o.voucher_code if o.status=="CONFIRMED" else None,"total_amount_minor":o.total_amount_minor,"currency":o.currency,"attendees":o.attendees,"supplier_reference":o.supplier_reference if o.status=="CONFIRMED" else None,"external_live":False} | reservation_expiry.projection('ATTRACTION',o)
 def get(self,account,order_id):
  with SessionLocal() as s:
   o=s.get(AttractionOrderRow,order_id,with_for_update=True)
   if not o or o.account_id!=account: raise ValueError("ATTRACTION_ORDER_NOT_FOUND")
   out=self.out(o);out["evidence"]=list_vertical_evidence(s,"ATTRACTION",order_id);return out
 def trips(self,account):
  with SessionLocal() as s:return [self.out(x) for x in s.scalars(select(AttractionOrderRow).where(AttractionOrderRow.account_id==account)).all()]
 def change_quote(self,account,order_id,new_visit_date,new_session_time=None):
  production_truth_required("ATTRACTION", "CHANGE_QUOTE")
  order=self.get(account,order_id)
  with SessionLocal() as read:x=self._order_terms(read,order_id)
  self._catalog(order["product_id"],new_visit_date,new_session_time or order["session_time"],order["currency"])
  if order["status"]!="CONFIRMED": raise ValueError("ATTRACTION_ORDER_NOT_CHANGEABLE")
  if not x["changeable"]: raise ValueError("ATTRACTION_NOT_CHANGEABLE")
  with transaction(SessionLocal) as s:
   q=AttractionChangeQuoteRow(quote_id=new_id("attr_chg"),order_id=order_id,new_visit_date=new_visit_date,new_session_time=new_session_time or order["session_time"],change_fee_minor=0,total_due_minor=0,currency=order["currency"],status="QUOTED",expires_at=now()+timedelta(minutes=10),created_at=now());s.add(q);s.flush();return {"quote_id":q.quote_id,"order_id":order_id,"new_visit_date":q.new_visit_date,"new_session_time":q.new_session_time,"change_fee_minor":0,"total_due_minor":0,"currency":q.currency,"expires_at":q.expires_at.isoformat()}
 def execute_change(self,account,order_id,quote_id):
  production_truth_required("ATTRACTION", "EXECUTE_CHANGE")
  self.get(account,order_id)
  with transaction(SessionLocal) as s:
   o=s.get(AttractionOrderRow,order_id,with_for_update=True);q=s.get(AttractionChangeQuoteRow,quote_id,with_for_update=True)
   if not o or o.account_id!=account or o.status!="CONFIRMED" or not q or q.order_id!=order_id or q.status!="QUOTED" or q.expires_at<now(): raise ValueError("ATTRACTION_CHANGE_QUOTE_NOT_FOUND")
   current,_=self._catalog(o.product_id,q.new_visit_date,q.new_session_time,o.currency)
   capacity.prepare_change_in(s,'ATTRACTION',order_id,quote_id,capacity.attraction_resource(o.product_id,q.new_visit_date,q.new_session_time),current['inventory'],o.quantity)
   q.status='PENDING_SUPPLIER';o.status='UNKNOWN_EXTERNAL_STATE';o.updated_at=now();append_vertical_evidence(s,"ATTRACTION",o.order_id,"CHANGE_SUBMITTED_AWAITING_SUPPLIER",o.status,{"quote_id":quote_id,"previous_voucher_code":o.voucher_code,"previous_supplier_reference":o.supplier_reference});project_vertical_lifecycle(s,"ATTRACTION",o,"change-pending:"+quote_id,facts={"quote_id":quote_id});return self.out(o)
 def _refund_quote_in(self,s,o):
  x=self._order_terms(s,o.order_id)
  fee=0 if x['refundable'] else o.total_amount_minor
  return {'order_id':o.order_id,'refund_fee_minor':fee,'refund_amount_minor':o.total_amount_minor-fee,'currency':o.currency,'refund_to':'ORIGINAL_PAYMENT_METHOD','refundable':x['refundable']}
 def refund_quote(self,account,order_id):
  production_truth_required('ATTRACTION','REFUND_QUOTE')
  with transaction(SessionLocal) as s:
   o=s.get(AttractionOrderRow,order_id,with_for_update=True)
   if not o or o.account_id!=account or o.status!='CONFIRMED':raise ValueError('ATTRACTION_ORDER_NOT_REFUNDABLE')
   return self._refund_quote_in(s,o)
 def refund(self,account,order_id):
  production_truth_required('ATTRACTION','REFUND')
  return vertical_refund_recovery.refund('ATTRACTION',account,order_id,self._refund_quote_in)
 def redeem(self,account,order_id,evidence_reference):
  if not str(evidence_reference or '').strip(): raise ValueError('FULFILLMENT_EVIDENCE_REQUIRED')
  production_truth_required("ATTRACTION", "REDEEM")
  with transaction(SessionLocal) as s:
   o=s.get(AttractionOrderRow,order_id,with_for_update=True)
   if not o or o.account_id!=account: raise ValueError("ATTRACTION_ORDER_NOT_FOUND")
   if o.status!="CONFIRMED": raise ValueError("ATTRACTION_ILLEGAL_STATE_TRANSITION")
   voucher_code=o.voucher_code; supplier_reference=o.supplier_reference
   o.status="FULFILLED";o.updated_at=now();append_vertical_evidence(s,"ATTRACTION",order_id,"VOUCHER_REDEEMED",o.status,{"evidence_reference":evidence_reference,"voucher_code":voucher_code,"supplier_reference":supplier_reference,"external_live":False});project_vertical_lifecycle(s,"ATTRACTION",o,evidence_reference,facts={"voucher_code":voucher_code,"supplier_reference":supplier_reference});return self.out(o)
 def admin_external_state(self,order_id,state,evidence_reference,actor,supplier_reference=None,voucher_code=None):
  if not str(evidence_reference or '').strip() or not str(actor or '').strip(): raise ValueError('EXTERNAL_STATE_ACTOR_AND_EVIDENCE_REQUIRED')
  state=state.upper()
  with transaction(SessionLocal) as s:
   o=s.get(AttractionOrderRow,order_id,with_for_update=True)
   if not o: raise ValueError("ATTRACTION_ORDER_NOT_FOUND")
   pending=s.scalar(select(AttractionChangeQuoteRow).where(AttractionChangeQuoteRow.order_id==order_id,AttractionChangeQuoteRow.status=='PENDING_SUPPLIER').order_by(AttractionChangeQuoteRow.created_at.desc()))
   if state=="UNKNOWN_EXTERNAL_STATE":
    if o.status!="CONFIRMED": raise ValueError("ATTRACTION_ILLEGAL_STATE_TRANSITION")
    o.status=state;kind="EXTERNAL_STATE_UNKNOWN"
   elif state=="CLOSED_BY_SUPPLIER":
    if o.status not in {"CONFIRMED","UNKNOWN_EXTERNAL_STATE"}: raise ValueError("ATTRACTION_ILLEGAL_STATE_TRANSITION")
    if pending:pending.status='FAILED'
    capacity.release_all_in(s,'ATTRACTION',order_id)
    o.status=state;kind="SUPPLIER_CLOSED"
   elif state=="CONFIRMED":
    if o.status!="UNKNOWN_EXTERNAL_STATE": raise ValueError("ATTRACTION_RECONCILIATION_NOT_REQUIRED")
    if pending:
     if not str(supplier_reference or '').strip() or not str(voucher_code or '').strip(): raise ValueError('ATTRACTION_RECONCILIATION_VOUCHER_REQUIRED')
     capacity.complete_change_in(s,'ATTRACTION',order_id,pending.quote_id,True)
     o.visit_date=pending.new_visit_date;o.session_time=pending.new_session_time;pending.status='APPLIED';o.supplier_reference=supplier_reference;o.voucher_code=voucher_code;kind='CHANGE_RECONCILED_TO_CONFIRMED'
    else:kind="RECONCILED_TO_CONFIRMED"
    o.status=state
   else: raise ValueError("ATTRACTION_EXTERNAL_STATE_INVALID")
   o.updated_at=now();append_vertical_evidence(s,"ATTRACTION",order_id,kind,o.status,{"evidence_reference":evidence_reference,"actor":actor,"supplier_reference":o.supplier_reference,"voucher_code":o.voucher_code,"quote_id":pending.quote_id if pending else None,"external_live":False});project_vertical_lifecycle(s,"ATTRACTION",o,evidence_reference,facts={"actor":actor,"supplier_reference":o.supplier_reference,"voucher_code":o.voucher_code,"quote_id":pending.quote_id if pending else None});return self.out(o)

attraction_service=AttractionService()
