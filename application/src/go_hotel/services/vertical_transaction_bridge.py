from __future__ import annotations
from sqlalchemy import select
from go_hotel.core.config import settings
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OrderSupplierFulfillmentRow, OmnichannelPaymentIntentRow, OmnichannelMoneyMovementRow
from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service
from go_hotel.services.omnichannel_payment import omnichannel_payment_service
from go_hotel.services.unified_money_movement import unified_money_movement_service

OFFICIAL={'FLIGHT':'AIRLINE_OFFICIAL','RAIL':'RAIL_OPERATOR_OFFICIAL','RIDE':'FLEET_OFFICIAL','RENTAL':'RENTAL_COMPANY_OFFICIAL','ATTRACTION':'ATTRACTION_OFFICIAL'}
BTYPE={'FLIGHT':'FLIGHT_ORDER','RAIL':'RAIL_ORDER','RIDE':'RIDE_ORDER','RENTAL':'RENTAL_ORDER','ATTRACTION':'ATTRACTION_ORDER'}

def _prod(): return settings.app_env.strip().lower() in {'prod','production'}

class VerticalTransactionBridge:
    def _money_graph(self, iid, vertical, order_id, evidence_reference):
        def pair(create):
            auth=create(iid,{'movement_type':'AUTHORIZATION','evidence':[evidence_reference],'mode':'CONTRACT_SIMULATOR'},f'{vertical.lower()}-auth:{order_id}','vertical-transaction-bridge')
            cap=create(iid,{'movement_type':'CAPTURE','parent_movement_id':auth['money_movement_id'],'evidence':[evidence_reference],'mode':'CONTRACT_SIMULATOR'},f'{vertical.lower()}-cap:{order_id}','vertical-transaction-bridge')
            return auth,cap
        with SessionLocal() as probe:
            bind=probe.get_bind()
        if bind.dialect.name!='postgresql':
            return pair(unified_money_movement_service.create)
        # Retain one physical checkout, not one transaction. AUTH remains durable
        # if CAPTURE fails; an invalid connection is never retried here.
        with bind.connect() as connection:
            def create(intent_id, body, key, actor):
                # Keep the original identity-map lifetime across the two commits.
                with SessionLocal(bind=connection) as session:
                    result=unified_money_movement_service.create_in_session(session,intent_id,body,key,actor)
                    session.commit()
                    return result
            return pair(create)

    def checkout_contract(self, vertical:str, order_id:str, account_id:str, source_id:str, evidence_reference:str, payment_method_id:str|None=None):
        if _prod(): raise ValueError('EXTERNAL_PAYMENT_EXECUTOR_REQUIRED')
        if vertical in {'RIDE','RENTAL'}:
            from go_hotel.services.vertical_reservation_expiry import guard_checkout_payment
            guard_checkout_payment(vertical, order_id, account_id)
        if not vertical_source_runtime_service.latest(vertical,order_id):
            vertical_source_runtime_service.decide(vertical,order_id,[{'source_id':source_id,'source_type':OFFICIAL[vertical],'authorized':True,'available':True,'evidence_reference':evidence_reference}])
        # Resume the durable payment root. Order status legitimately changes after capture;
        # re-hashing that changed status as a new payment request must not double-charge.
        with SessionLocal() as s:
            existing=s.scalar(select(OmnichannelPaymentIntentRow).where(OmnichannelPaymentIntentRow.business_type==BTYPE[vertical],OmnichannelPaymentIntentRow.business_id==order_id))
            if existing and existing.payer_id!=account_id:raise ValueError('PAYMENT_PAYER_ORDER_MISMATCH')
            i={'payment_intent_id':existing.payment_intent_id,'state':existing.state} if existing else None
        if i is None:
            i=omnichannel_payment_service.create_intent({'business_type':BTYPE[vertical],'business_id':order_id,'channel_priority':['LOCAL_MARKET']},f'{vertical.lower()}-checkout:{order_id}',account_id)
        if vertical in {'RIDE','RENTAL'}:
            from go_hotel.services.vertical_reservation_expiry import payment_started
            payment_started(vertical, order_id, account_id)
        if i['state']=='UNKNOWN_EXTERNAL_STATE':raise ValueError('PAYMENT_RECONCILIATION_REQUIRED')
        if i['state']=='REQUIRES_CHANNEL_SELECTION': i=omnichannel_payment_service.select_channel(i['payment_intent_id'],'LOCAL_MARKET',account_id,True)
        if i['state']=='READY':
            a=omnichannel_payment_service.execute(i['payment_intent_id'],'CONTRACT_SIMULATOR')
            omnichannel_payment_service.simulate_result(a['payment_attempt_id'],'SUCCEEDED')
        iid=i['payment_intent_id']
        auth,cap=self._money_graph(iid,vertical,order_id,evidence_reference)
        with SessionLocal() as s:
            f=s.scalar(select(OrderSupplierFulfillmentRow).where(OrderSupplierFulfillmentRow.payment_intent_id==iid))
            return {'payment_intent_id':iid,'authorization_id':auth['money_movement_id'],'capture_id':cap['money_movement_id'],'supplier_fulfillment_id':f.order_supplier_fulfillment_id if f else None,'state':'PAYMENT_CONFIRMED_AWAITING_SUPPLIER'}

vertical_transaction_bridge=VerticalTransactionBridge()
