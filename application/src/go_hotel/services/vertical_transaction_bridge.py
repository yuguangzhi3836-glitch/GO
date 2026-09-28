from __future__ import annotations
from sqlalchemy import select
from go_hotel.core.config import settings
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OrderSupplierFulfillmentRow, OmnichannelPaymentIntentRow, OmnichannelMoneyMovementRow, OmnichannelPaymentAttemptRow
from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service
from go_hotel.services.omnichannel_payment import omnichannel_payment_service
from go_hotel.services.unified_money_movement import unified_money_movement_service

OFFICIAL={'FLIGHT':'AIRLINE_OFFICIAL','RAIL':'RAIL_OPERATOR_OFFICIAL','RIDE':'FLEET_OFFICIAL','RENTAL':'RENTAL_COMPANY_OFFICIAL','ATTRACTION':'ATTRACTION_OFFICIAL'}
BTYPE={'FLIGHT':'FLIGHT_ORDER','RAIL':'RAIL_ORDER','RIDE':'RIDE_ORDER','RENTAL':'RENTAL_ORDER','ATTRACTION':'ATTRACTION_ORDER'}

def _prod(): return settings.app_env.strip().lower() in {'prod','production'}

class VerticalTransactionBridge:
    def _existing_intent(self, vertical, order_id, account_id):
        with SessionLocal() as s:
            existing=s.scalar(select(OmnichannelPaymentIntentRow).where(OmnichannelPaymentIntentRow.business_type==BTYPE[vertical],OmnichannelPaymentIntentRow.business_id==order_id))
            if existing and existing.payer_id!=account_id:raise ValueError('PAYMENT_PAYER_ORDER_MISMATCH')
            return {'payment_intent_id':existing.payment_intent_id,'state':existing.state} if existing else None

    def _confirm_contract_payment(self, iid, account_id):
        # Resume committed simulator steps, never infer success from a stale
        # pre-execution state. Every transition retains its database row lock.
        # This bounded reconciliation does not send an external payment.
        for _ in range(8):
            with SessionLocal() as s:
                i=s.get(OmnichannelPaymentIntentRow,iid)
                if not i or i.payer_id!=account_id:raise ValueError('PAYMENT_PAYER_ORDER_MISMATCH')
                state=i.state
                if state=='SUCCEEDED':return
                if state=='UNKNOWN_EXTERNAL_STATE':raise ValueError('PAYMENT_RECONCILIATION_REQUIRED')
                pending=list(s.scalars(select(OmnichannelPaymentAttemptRow).where(
                    OmnichannelPaymentAttemptRow.payment_intent_id==iid,
                    OmnichannelPaymentAttemptRow.state=='CONTRACT_READY_NOT_EXTERNAL'))) if state=='CONTRACT_READY_NOT_EXTERNAL' else []
                if len(pending)>1 or any(a.external_invoked for a in pending):raise ValueError('PAYMENT_RECONCILIATION_REQUIRED')
                aid=pending[0].payment_attempt_id if pending else None
            try:
                if state=='REQUIRES_CHANNEL_SELECTION':
                    omnichannel_payment_service.select_channel(iid,'LOCAL_MARKET',account_id,True)
                elif state=='READY':
                    a=omnichannel_payment_service.execute(iid,'CONTRACT_SIMULATOR')
                    omnichannel_payment_service.simulate_result(a['payment_attempt_id'],'SUCCEEDED')
                elif state=='CONTRACT_READY_NOT_EXTERNAL':
                    if aid:omnichannel_payment_service.simulate_result(aid,'SUCCEEDED')
                else:raise ValueError('PAYMENT_RECONCILIATION_REQUIRED')
            except ValueError as exc:
                if str(exc) not in {'CHANNEL_SWITCH_BLOCKED_BY_PAYMENT_STATE','PAYMENT_INTENT_NOT_READY','ACTIVE_OR_UNKNOWN_ATTEMPT_BLOCKS_RESEND'}:raise
                # Another worker may have committed the next state. Reload it;
                # no blanket SQL/network retry and no replacement attempt.
        raise ValueError('PAYMENT_RECONCILIATION_REQUIRED')

    def checkout_contract(self, vertical:str, order_id:str, account_id:str, source_id:str, evidence_reference:str, payment_method_id:str|None=None):
        if _prod(): raise ValueError('EXTERNAL_PAYMENT_EXECUTOR_REQUIRED')
        if vertical=='RIDE':
            from go_hotel.db.models import MobilityRideOrderRow
            from go_hotel.mobility.ride.cancellation_policy import accepted_in
            with SessionLocal() as s:
                order=s.get(MobilityRideOrderRow,order_id)
                if not order or order.account_id!=account_id:raise ValueError('PAYMENT_PAYER_ORDER_MISMATCH')
                accepted_in(s,order)
        if vertical in {'RIDE','RENTAL'}:
            from go_hotel.services.vertical_reservation_expiry import guard_checkout_payment
            guard_checkout_payment(vertical, order_id, account_id)
        if not vertical_source_runtime_service.latest(vertical,order_id):
            vertical_source_runtime_service.decide(vertical,order_id,[{'source_id':source_id,'source_type':OFFICIAL[vertical],'authorized':True,'available':True,'evidence_reference':evidence_reference}])
        # Resume the durable payment root. Order status legitimately changes after capture;
        # re-hashing that changed status as a new payment request must not double-charge.
        i=self._existing_intent(vertical,order_id,account_id)
        if i is None:
            try:
                i=omnichannel_payment_service.create_intent({'business_type':BTYPE[vertical],'business_id':order_id,'channel_priority':['LOCAL_MARKET']},f'{vertical.lower()}-checkout:{order_id}',account_id)
            except ValueError as exc:
                if str(exc) not in {'ORDER_PAYMENT_ROOT_ALREADY_EXISTS','IDEMPOTENCY_KEY_REQUEST_FINGERPRINT_MISMATCH'}:raise
                # The same order's root can commit after our first lookup. The
                # bridge resumes that obligation; it does not change its amount.
                i=self._existing_intent(vertical,order_id,account_id)
                if i is None:raise
        if vertical in {'RIDE','RENTAL'}:
            from go_hotel.services.vertical_reservation_expiry import payment_started
            payment_started(vertical, order_id, account_id)
        iid=i['payment_intent_id']
        self._confirm_contract_payment(iid,account_id)
        auth=unified_money_movement_service.create(iid,{'movement_type':'AUTHORIZATION','evidence':[evidence_reference],'mode':'CONTRACT_SIMULATOR'},f'{vertical.lower()}-auth:{order_id}','vertical-transaction-bridge')
        cap=unified_money_movement_service.create(iid,{'movement_type':'CAPTURE','parent_movement_id':auth['money_movement_id'],'evidence':[evidence_reference],'mode':'CONTRACT_SIMULATOR'},f'{vertical.lower()}-cap:{order_id}','vertical-transaction-bridge')
        with SessionLocal() as s:
            f=s.scalar(select(OrderSupplierFulfillmentRow).where(OrderSupplierFulfillmentRow.payment_intent_id==iid))
            return {'payment_intent_id':iid,'authorization_id':auth['money_movement_id'],'capture_id':cap['money_movement_id'],'supplier_fulfillment_id':f.order_supplier_fulfillment_id if f else None,'state':'PAYMENT_CONFIRMED_AWAITING_SUPPLIER'}

vertical_transaction_bridge=VerticalTransactionBridge()
