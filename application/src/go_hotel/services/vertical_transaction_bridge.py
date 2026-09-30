from __future__ import annotations
from sqlalchemy import select
from go_hotel.core.config import settings
from go_hotel.db.session import SessionLocal, engine
from sqlalchemy.orm import Session
from go_hotel.db.models import OrderSupplierFulfillmentRow, OmnichannelPaymentIntentRow, OmnichannelMoneyMovementRow, OmnichannelPaymentAttemptRow
from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service
from go_hotel.services.omnichannel_payment import omnichannel_payment_service
from go_hotel.services.unified_money_movement import unified_money_movement_service
from go_hotel.autonomy.durable import transaction

OFFICIAL={'FLIGHT':'AIRLINE_OFFICIAL','RAIL':'RAIL_OPERATOR_OFFICIAL','RIDE':'FLEET_OFFICIAL','RENTAL':'RENTAL_COMPANY_OFFICIAL','ATTRACTION':'ATTRACTION_OFFICIAL'}
BTYPE={'FLIGHT':'FLIGHT_ORDER','RAIL':'RAIL_ORDER','RIDE':'RIDE_ORDER','RENTAL':'RENTAL_ORDER','ATTRACTION':'ATTRACTION_ORDER'}

def _prod(): return settings.app_env.strip().lower() in {'prod','production'}

class VerticalTransactionBridge:
    def _existing_intent_in(self, s, vertical, order_id, account_id):
        existing=s.scalar(select(OmnichannelPaymentIntentRow).where(OmnichannelPaymentIntentRow.business_type==BTYPE[vertical],OmnichannelPaymentIntentRow.business_id==order_id))
        if existing and existing.payer_id!=account_id:raise ValueError('PAYMENT_PAYER_ORDER_MISMATCH')
        return {'payment_intent_id':existing.payment_intent_id,'state':existing.state} if existing else None

    def _existing_intent(self, vertical, order_id, account_id):
        with SessionLocal() as s:
            return self._existing_intent_in(s,vertical,order_id,account_id)

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
                    selected=omnichannel_payment_service.select_channel(iid,'LOCAL_MARKET',account_id,True)
                    if selected['payment_intent_id']!=iid or selected['payer_id']!=account_id:raise ValueError('PAYMENT_PAYER_ORDER_MISMATCH')
                    state=selected['state']
                if state=='READY':
                    a=omnichannel_payment_service.execute(iid,'CONTRACT_SIMULATOR')
                    confirmed=omnichannel_payment_service.simulate_result(a['payment_attempt_id'],'SUCCEEDED')['intent']
                elif state=='CONTRACT_READY_NOT_EXTERNAL':
                    if not aid:continue
                    confirmed=omnichannel_payment_service.simulate_result(aid,'SUCCEEDED')['intent']
                else:raise ValueError('PAYMENT_RECONCILIATION_REQUIRED')
                # These are the committed result facts of the locked transition,
                # not the stale snapshot read before execution. Concurrent-state
                # conflicts still go through the existing reload loop.
                if confirmed['payment_intent_id']!=iid or confirmed['payer_id']!=account_id:raise ValueError('PAYMENT_PAYER_ORDER_MISMATCH')
                if confirmed['state']=='SUCCEEDED':return
                raise ValueError('PAYMENT_RECONCILIATION_REQUIRED')
            except ValueError as exc:
                if str(exc) not in {'CHANNEL_SWITCH_BLOCKED_BY_PAYMENT_STATE','PAYMENT_INTENT_NOT_READY','ACTIVE_OR_UNKNOWN_ATTEMPT_BLOCKS_RESEND'}:raise
                # Another worker may have committed the next state. Reload it;
                # no blanket SQL/network retry and no replacement attempt.
        raise ValueError('PAYMENT_RECONCILIATION_REQUIRED')

    def _ride_money_graph(self, iid, order_id, evidence_reference):
        """Reuse one PostgreSQL checkout while preserving the AUTH and CAPTURE commit boundary."""
        if engine.dialect.name=='sqlite':
            auth=unified_money_movement_service.create(iid,{'movement_type':'AUTHORIZATION','evidence':[evidence_reference],'mode':'CONTRACT_SIMULATOR'},f'ride-auth:{order_id}','vertical-transaction-bridge')
            cap=unified_money_movement_service.create(iid,{'movement_type':'CAPTURE','parent_movement_id':auth['money_movement_id'],'evidence':[evidence_reference],'mode':'CONTRACT_SIMULATOR'},f'ride-cap:{order_id}','vertical-transaction-bridge')
            with SessionLocal() as s:
                f=s.scalar(select(OrderSupplierFulfillmentRow).where(OrderSupplierFulfillmentRow.payment_intent_id==iid))
                return auth,cap,f
        # Bind the ORM session to one explicitly-held connection. Session.commit()
        # still commits AUTH before CAPTURE, so a process exit between the two
        # leaves the original durable recovery point intact. The connection stays
        # checked out across those short transactions, avoiding release/reacquire
        # queueing between money.create calls and the fulfillment read.
        with engine.connect() as conn:
            with Session(bind=conn,expire_on_commit=False,autoflush=False) as s:
                auth=unified_money_movement_service.create_in_session(s,iid,{'movement_type':'AUTHORIZATION','evidence':[evidence_reference],'mode':'CONTRACT_SIMULATOR'},f'ride-auth:{order_id}','vertical-transaction-bridge')
                s.commit()
                cap=unified_money_movement_service.create_in_session(s,iid,{'movement_type':'CAPTURE','parent_movement_id':auth['money_movement_id'],'evidence':[evidence_reference],'mode':'CONTRACT_SIMULATOR'},f'ride-cap:{order_id}','vertical-transaction-bridge')
                s.commit()
                f=s.scalar(select(OrderSupplierFulfillmentRow).where(OrderSupplierFulfillmentRow.payment_intent_id==iid))
                return auth,cap,f

    def checkout_contract(self, vertical:str, order_id:str, account_id:str, source_id:str, evidence_reference:str, payment_method_id:str|None=None):
        if _prod(): raise ValueError('EXTERNAL_PAYMENT_EXECUTOR_REQUIRED')
        if vertical=='RIDE':
            from go_hotel.db.models import MobilityRideOrderRow
            from go_hotel.mobility.ride.cancellation_policy import accepted_in
            from go_hotel.services.vertical_reservation_expiry import guard_checkout_payment_in
            with transaction(SessionLocal) as s:
                order=s.get(MobilityRideOrderRow,order_id,with_for_update=True)
                if not order or order.account_id!=account_id:raise ValueError('PAYMENT_PAYER_ORDER_MISMATCH')
                accepted_in(s,order)
                guard_checkout_payment_in(s,vertical,order,account_id)
                i=self._existing_intent_in(s,vertical,order_id,account_id)
                # This read needs no separate connection after the order guard.
                # Only the snapshot crosses this boundary; no Session is shared
                # with the independently committed payment transitions below.
                source=vertical_source_runtime_service.latest_in(s,vertical,order_id)
        if vertical=='RENTAL':
            from go_hotel.services.vertical_reservation_expiry import guard_checkout_payment
            guard_checkout_payment(vertical, order_id, account_id)
        if vertical!='RIDE':source=vertical_source_runtime_service.latest(vertical,order_id)
        if not source:
            vertical_source_runtime_service.decide(vertical,order_id,[{'source_id':source_id,'source_type':OFFICIAL[vertical],'authorized':True,'available':True,'evidence_reference':evidence_reference}])
        # Resume the durable payment root. Order status legitimately changes after capture;
        # re-hashing that changed status as a new payment request must not double-charge.
        if vertical!='RIDE':i=self._existing_intent(vertical,order_id,account_id)
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
        if vertical=='RIDE':
            auth,cap,f=self._ride_money_graph(iid,order_id,evidence_reference)
        else:
            auth=unified_money_movement_service.create(iid,{'movement_type':'AUTHORIZATION','evidence':[evidence_reference],'mode':'CONTRACT_SIMULATOR'},f'{vertical.lower()}-auth:{order_id}','vertical-transaction-bridge')
            cap=unified_money_movement_service.create(iid,{'movement_type':'CAPTURE','parent_movement_id':auth['money_movement_id'],'evidence':[evidence_reference],'mode':'CONTRACT_SIMULATOR'},f'{vertical.lower()}-cap:{order_id}','vertical-transaction-bridge')
            with SessionLocal() as s:
                f=s.scalar(select(OrderSupplierFulfillmentRow).where(OrderSupplierFulfillmentRow.payment_intent_id==iid))
        return {'payment_intent_id':iid,'authorization_id':auth['money_movement_id'],'capture_id':cap['money_movement_id'],'supplier_fulfillment_id':f.order_supplier_fulfillment_id if f else None,'state':'PAYMENT_CONFIRMED_AWAITING_SUPPLIER'}

vertical_transaction_bridge=VerticalTransactionBridge()
