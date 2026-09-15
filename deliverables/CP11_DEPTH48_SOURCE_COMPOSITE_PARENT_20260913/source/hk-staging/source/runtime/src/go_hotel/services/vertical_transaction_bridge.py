from __future__ import annotations
from sqlalchemy import select
from go_hotel.core.config import settings
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OrderSupplierFulfillmentRow
from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service
from go_hotel.services.omnichannel_payment import omnichannel_payment_service
from go_hotel.services.unified_money_movement import unified_money_movement_service

OFFICIAL={'FLIGHT':'AIRLINE_OFFICIAL','RAIL':'RAIL_OPERATOR_OFFICIAL','RIDE':'FLEET_OFFICIAL','RENTAL':'RENTAL_COMPANY_OFFICIAL','ATTRACTION':'ATTRACTION_OFFICIAL'}
BTYPE={'FLIGHT':'FLIGHT_ORDER','RAIL':'RAIL_ORDER','RIDE':'RIDE_ORDER','RENTAL':'RENTAL_ORDER','ATTRACTION':'ATTRACTION_ORDER'}

def _prod(): return settings.app_env.strip().lower() in {'prod','production'}

class VerticalTransactionBridge:
    def checkout_contract(self, vertical:str, order_id:str, account_id:str, source_id:str, evidence_reference:str, payment_method_id:str|None=None):
        if _prod(): raise ValueError('EXTERNAL_PAYMENT_EXECUTOR_REQUIRED')
        if not vertical_source_runtime_service.latest(vertical,order_id):
            vertical_source_runtime_service.decide(vertical,order_id,[{'source_id':source_id,'source_type':OFFICIAL[vertical],'authorized':True,'available':True,'evidence_reference':evidence_reference}])
        i=omnichannel_payment_service.create_intent({'business_type':BTYPE[vertical],'business_id':order_id,'channel_priority':['LOCAL_MARKET']},f'{vertical.lower()}-checkout:{order_id}',account_id)
        if i['state']=='REQUIRES_CHANNEL_SELECTION': i=omnichannel_payment_service.select_channel(i['payment_intent_id'],'LOCAL_MARKET',account_id,True)
        if i['state']=='READY':
            a=omnichannel_payment_service.execute(i['payment_intent_id'],'CONTRACT_SIMULATOR')
            omnichannel_payment_service.simulate_result(a['payment_attempt_id'],'SUCCEEDED')
        iid=i['payment_intent_id']
        auth=unified_money_movement_service.create(iid,{'movement_type':'AUTHORIZATION','evidence':[evidence_reference],'mode':'CONTRACT_SIMULATOR'},f'{vertical.lower()}-auth:{order_id}','vertical-transaction-bridge')
        cap=unified_money_movement_service.create(iid,{'movement_type':'CAPTURE','parent_movement_id':auth['money_movement_id'],'evidence':[evidence_reference],'mode':'CONTRACT_SIMULATOR'},f'{vertical.lower()}-cap:{order_id}','vertical-transaction-bridge')
        with SessionLocal() as s:
            f=s.scalar(select(OrderSupplierFulfillmentRow).where(OrderSupplierFulfillmentRow.payment_intent_id==iid))
            return {'payment_intent_id':iid,'authorization_id':auth['money_movement_id'],'capture_id':cap['money_movement_id'],'supplier_fulfillment_id':f.order_supplier_fulfillment_id if f else None,'state':'PAYMENT_CONFIRMED_AWAITING_SUPPLIER'}

vertical_transaction_bridge=VerticalTransactionBridge()
