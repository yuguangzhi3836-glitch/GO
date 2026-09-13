from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, uuid
from sqlalchemy import select
from go_hotel.core.config import settings
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    OrderRow, PaymentRow, VerticalSourceDecisionRow as SourceDecision,
    OmnichannelPaymentIntentRow as Intent, PaymentOrderRootRow as OrderRoot,
    PaymentOrderFactBindingRow as FactBinding, OmnichannelMoneyMovementRow as Movement,
)
from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service
from go_hotel.services.unified_money_movement import unified_money_movement_service


def now(): return datetime.now(timezone.utc)
def ident(p): return f"{p}_{uuid.uuid4().hex}"
def digest(v): return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def _prod(): return settings.app_env.strip().lower() in {'prod','production'}

class HotelMoneyBridge:
    def _source(self, order: OrderRow):
        with SessionLocal() as s:
            d=s.scalar(select(SourceDecision).where(SourceDecision.vertical=='HOTEL',SourceDecision.business_id==order.order_id).order_by(SourceDecision.created_at.desc()))
            if d: return d
        if _prod():raise ValueError('EXTERNAL_CERTIFIED_HOTEL_SOURCE_REQUIRED')
        source_id=order.supplier_id or 'HOTEL_LEGACY_SUPPLIER'
        vertical_source_runtime_service.decide('HOTEL',order.order_id,[{
            'source_id':source_id,'source_type':'HOTEL_OFFICIAL_DIRECT','authorized':True,'available':True,
            'evidence_reference':f'legacy-hotel-order://{order.order_id}/supplier/{source_id}'
        }])
        with SessionLocal() as s:
            return s.scalar(select(SourceDecision).where(SourceDecision.vertical=='HOTEL',SourceDecision.business_id==order.order_id).order_by(SourceDecision.created_at.desc()))

    def ensure_original_root(self, order_id: str) -> str:
        """Import an actual original payment atomically, never the current quote.

        A historical complete root may be read in production; new or incomplete
        imports need the isolated executor until a certified importer exists.
        """
        from go_hotel.services.alipay_safeguarded_settlement import transaction
        from go_hotel.services.hosted_money import require_isolated
        with SessionLocal() as s:
            order=s.get(OrderRow,order_id)
            if not order:raise ValueError('HOTEL_ORDER_NOT_FOUND')
            payments=s.scalars(select(PaymentRow).where(PaymentRow.order_id==order_id,PaymentRow.payment_type=='ORIGINAL_BOOKING',PaymentRow.status=='CAPTURED')).all()
            if len(payments)!=1:raise ValueError('UNIQUE_CAPTURED_ORIGINAL_PAYMENT_REQUIRED')
            payment=payments[0]
            if payment.amount_minor<=0 or payment.currency!=order.currency:raise ValueError('ORIGINAL_PAYMENT_FACT_MISMATCH')
        source=self._source(order)
        with transaction() as s:
            order=s.get(OrderRow,order_id,with_for_update=True,populate_existing=True)
            pay=s.get(PaymentRow,payment.payment_id,with_for_update=True,populate_existing=True)
            if (pay.order_id,pay.status,pay.payment_type,pay.currency)!=(order_id,'CAPTURED','ORIGINAL_BOOKING',order.currency) or pay.amount_minor<=0:raise ValueError('ORIGINAL_PAYMENT_FACT_CHANGED')
            root=s.scalar(select(OrderRoot).where(OrderRoot.business_type=='HOTEL_ORDER',OrderRoot.business_id==order_id))
            i=s.get(Intent,root.payment_intent_id,with_for_update=True,populate_existing=True) if root else None
            payee=order.supplier_id or source.selected_source_id
            if root:
                if not i or (i.business_type,i.business_id,i.payer_id,i.payee_id,i.amount_minor,i.currency,i.state)!=('HOTEL_ORDER',order_id,order.account_id,payee,pay.amount_minor,pay.currency,'SUCCEEDED'):raise ValueError('ORIGINAL_PAYMENT_ROOT_RECONCILIATION_REQUIRED')
                moves=s.scalars(select(Movement).where(Movement.root_payment_intent_id==i.payment_intent_id)).all()
                if any(m.state!='CONFIRMED' for m in moves):raise ValueError('PAYMENT_RECONCILIATION_REQUIRED')
                captured=sum(m.amount_minor for m in moves if m.movement_type=='CAPTURE')
                if captured==pay.amount_minor:return i.payment_intent_id
                if captured:raise ValueError('ORIGINAL_CAPTURE_RECONCILIATION_REQUIRED')
            require_isolated()
            entity='GO_CN' if pay.currency=='CNY' else 'GO_GLOBAL';created=now()
            evidence=f'isolated-legacy-payment://{pay.payment_id}'
            if not i:
                iid=ident('opi')
                fact={'business_type':'HOTEL_ORDER','business_id':order_id,'payer_id':order.account_id,'payee_id':payee,'amount_minor':pay.amount_minor,'currency':pay.currency,'source_decision_id':source.vertical_source_decision_id,'payment_id':pay.payment_id,'data_mode':'SIMULATION'}
                i=Intent(payment_intent_id=iid,business_type='HOTEL_ORDER',business_id=order_id,payer_id=order.account_id,payee_id=payee,operation='PAY',amount_minor=pay.amount_minor,currency=pay.currency,channel_priority_json=['LOCAL_MARKET'],selected_channel='LOCAL_MARKET',state='SUCCEEDED',idempotency_key=f'legacy-hotel-root:{order_id}',automatic_fallback_allowed=False,user_channel_consent_at=created,created_at=created,updated_at=created)
                s.add(i);s.flush()
                s.add(OrderRoot(payment_order_root_id=ident('por'),business_type='HOTEL_ORDER',business_id=order_id,payment_intent_id=iid,legal_entity_id=entity,state='ACTIVE',root_hash=digest({'business_type':'HOTEL_ORDER','business_id':order_id,'payment_intent_id':iid,'legal_entity_id':entity}),created_at=created))
                s.add(FactBinding(payment_order_fact_binding_id=ident('pofb'),payment_intent_id=iid,business_type='HOTEL_ORDER',business_id=order_id,payer_id=order.account_id,payee_id=payee,amount_minor=pay.amount_minor,currency=pay.currency,legal_entity_id=entity,source_decision_id=source.vertical_source_decision_id,request_fingerprint=digest(fact),order_fact_hash=digest(fact),evidence_reference=evidence,created_at=created));s.flush()
            iid=i.payment_intent_id
            auth=unified_money_movement_service.create_in_session(s,iid,{'movement_type':'AUTHORIZATION','amount_minor':pay.amount_minor,'evidence':[evidence],'mode':'CONTRACT_SIMULATOR'},f'legacy-hotel-auth:{order_id}','hotel-money-bridge')
            unified_money_movement_service.create_in_session(s,iid,{'movement_type':'CAPTURE','parent_movement_id':auth['money_movement_id'],'amount_minor':pay.amount_minor,'evidence':[evidence],'mode':'CONTRACT_SIMULATOR'},f'legacy-hotel-cap:{order_id}','hotel-money-bridge')
            return iid

    def refund(self, order_id: str, amount_minor: int, evidence_reference: str, key: str) -> dict:
        from go_hotel.services.hosted_money import require_isolated
        require_isolated()
        iid=self.ensure_original_root(order_id)
        with SessionLocal() as s:
            cap=s.scalar(select(Movement).where(Movement.root_payment_intent_id==iid,Movement.movement_type=='CAPTURE',Movement.state=='CONFIRMED').order_by(Movement.created_at.desc()))
            if not cap: raise ValueError('CONFIRMED_CAPTURE_REQUIRED')
        return unified_money_movement_service.create(iid,{'movement_type':'REFUND','parent_movement_id':cap.money_movement_id,'amount_minor':amount_minor,'evidence':[evidence_reference],'mode':'CONTRACT_SIMULATOR'},key,'hotel-money-bridge')

    def prepare_adjustment(self, order_id: str, business_type: str, business_id: str, amount_minor: int, evidence_reference: str, key_prefix: str) -> dict | None:
        if amount_minor<=0: return None
        if _prod(): raise ValueError('EXTERNAL_PAYMENT_EXECUTOR_REQUIRED_FOR_ADJUSTMENT')
        with SessionLocal() as s:
            order=s.get(OrderRow,order_id)
            if not order: raise ValueError('HOTEL_ORDER_NOT_FOUND')
        d=self._source(order); entity='GO_CN' if order.currency=='CNY' else 'GO_GLOBAL'; iid=ident('opi'); created=now()
        with SessionLocal() as s:
            s.get(OrderRow,order_id,with_for_update=True)
            from go_hotel.db.models import SupplierFaultCaseRow
            if s.scalar(select(SupplierFaultCaseRow).where(SupplierFaultCaseRow.order_id==order_id,SupplierFaultCaseRow.status!='COMPLETED')):raise ValueError('SUPPLIER_REMEDY_ORDER_FROZEN')
            root=s.scalar(select(OrderRoot).where(OrderRoot.business_type==business_type,OrderRoot.business_id==business_id).with_for_update())
            if root: iid=root.payment_intent_id
            else:
                i=Intent(payment_intent_id=iid,business_type=business_type,business_id=business_id,payer_id=order.account_id,payee_id=order.supplier_id or d.selected_source_id,operation='PAY',amount_minor=amount_minor,currency=order.currency,channel_priority_json=['LOCAL_MARKET'],selected_channel='LOCAL_MARKET',state='SUCCEEDED',idempotency_key=f'{key_prefix}:intent',automatic_fallback_allowed=False,user_channel_consent_at=created,created_at=created,updated_at=created);s.add(i);s.flush()
                s.add(OrderRoot(payment_order_root_id=ident('por'),business_type=business_type,business_id=business_id,payment_intent_id=iid,legal_entity_id=entity,state='ACTIVE',root_hash=digest({'business_type':business_type,'business_id':business_id,'payment_intent_id':iid,'legal_entity_id':entity}),created_at=created))
                fact={'business_type':business_type,'business_id':business_id,'payer_id':order.account_id,'payee_id':order.supplier_id or d.selected_source_id,'amount_minor':amount_minor,'currency':order.currency,'source_decision_id':d.vertical_source_decision_id}
                s.add(FactBinding(payment_order_fact_binding_id=ident('pofb'),payment_intent_id=iid,business_type=business_type,business_id=business_id,payer_id=order.account_id,payee_id=fact['payee_id'],amount_minor=amount_minor,currency=order.currency,legal_entity_id=entity,source_decision_id=d.vertical_source_decision_id,request_fingerprint=digest(fact),order_fact_hash=digest(fact),evidence_reference=evidence_reference,created_at=created));s.commit()
        with SessionLocal() as s:
            auth=s.scalar(select(Movement).where(Movement.root_payment_intent_id==iid,Movement.movement_type=='AUTHORIZATION',Movement.state=='CONFIRMED'))
            cap=s.scalar(select(Movement).where(Movement.root_payment_intent_id==iid,Movement.movement_type=='CAPTURE',Movement.state=='CONFIRMED'))
            if cap: return {'payment_intent_id':iid,'authorization_id':auth.money_movement_id if auth else None,'capture_id':cap.money_movement_id}
        if not auth:
            auth=unified_money_movement_service.create(iid,{'movement_type':'AUTHORIZATION','amount_minor':amount_minor,'evidence':[evidence_reference],'mode':'CONTRACT_SIMULATOR'},f'{key_prefix}:auth','hotel-money-bridge')
            aid=auth['money_movement_id']
        else: aid=auth.money_movement_id
        return {'payment_intent_id':iid,'authorization_id':aid,'capture_id':None}

    def capture_adjustment(self, prepared: dict | None, amount_minor: int, evidence_reference: str, key_prefix: str) -> dict | None:
        if not prepared or amount_minor<=0:return None
        if prepared.get('capture_id'):return prepared
        cap=unified_money_movement_service.create(prepared['payment_intent_id'],{'movement_type':'CAPTURE','parent_movement_id':prepared['authorization_id'],'amount_minor':amount_minor,'evidence':[evidence_reference],'mode':'CONTRACT_SIMULATOR'},f'{key_prefix}:cap','hotel-money-bridge')
        return prepared|{'capture_id':cap['money_movement_id'],'capture':cap}

    def release_adjustment(self, prepared: dict | None, amount_minor: int, evidence_reference: str, key_prefix: str) -> dict | None:
        if not prepared or amount_minor<=0 or prepared.get('capture_id'):return None
        return unified_money_movement_service.create(prepared['payment_intent_id'],{'movement_type':'RELEASE','parent_movement_id':prepared['authorization_id'],'amount_minor':amount_minor,'evidence':[evidence_reference],'mode':'CONTRACT_SIMULATOR'},f'{key_prefix}:release','hotel-money-bridge')

hotel_money_bridge=HotelMoneyBridge()
