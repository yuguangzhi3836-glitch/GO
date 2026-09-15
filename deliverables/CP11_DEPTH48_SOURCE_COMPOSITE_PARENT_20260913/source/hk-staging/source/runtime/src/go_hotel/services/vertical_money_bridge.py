from __future__ import annotations
from datetime import datetime, timezone
import hashlib,json,uuid
from sqlalchemy import select
from go_hotel.core.config import settings
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    PaymentOrderRootRow as Root, OmnichannelPaymentIntentRow as Intent,
    OmnichannelMoneyMovementRow as Movement, PaymentOrderFactBindingRow as FactBinding,
)
from go_hotel.services.unified_money_movement import unified_money_movement_service

def now(): return datetime.now(timezone.utc)
def ident(p): return f'{p}_{uuid.uuid4().hex}'
def digest(v): return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def _prod(): return settings.app_env.strip().lower() in {'prod','production'}
BTYPE={'FLIGHT':'FLIGHT_ORDER','RAIL':'RAIL_ORDER','RIDE':'RIDE_ORDER','RENTAL':'RENTAL_ORDER','ATTRACTION':'ATTRACTION_ORDER'}

class VerticalMoneyBridge:
    def original(self,vertical,order_id):
        bt=BTYPE[vertical]
        with SessionLocal() as s:
            root=s.scalar(select(Root).where(Root.business_type==bt,Root.business_id==order_id))
            if not root: raise ValueError('ORIGINAL_PAYMENT_ROOT_REQUIRED')
            intent=s.get(Intent,root.payment_intent_id)
            cap=s.scalar(select(Movement).where(Movement.root_payment_intent_id==root.payment_intent_id,Movement.movement_type=='CAPTURE',Movement.state=='CONFIRMED').order_by(Movement.created_at.desc()))
            if not intent or not cap: raise ValueError('CONFIRMED_CAPTURE_REQUIRED')
            binding=s.scalar(select(FactBinding).where(FactBinding.payment_intent_id==root.payment_intent_id).order_by(FactBinding.created_at.desc()))
            return root,intent,cap,binding
    def refund(self,vertical,order_id,amount_minor,evidence_reference,key):
        root,intent,cap,_=self.original(vertical,order_id)
        mode='EXTERNAL_CERTIFIED_FACT' if _prod() else 'CONTRACT_SIMULATOR'
        if _prod(): raise ValueError('EXTERNAL_REFUND_EXECUTOR_REQUIRED')
        return unified_money_movement_service.create(root.payment_intent_id,{'movement_type':'REFUND','parent_movement_id':cap.money_movement_id,'amount_minor':amount_minor,'evidence':[evidence_reference],'mode':mode},key,'vertical-money-bridge')
    def prepare_adjustment(self,vertical,order_id,adjustment_id,amount_minor,evidence_reference):
        if amount_minor<=0:return None
        if _prod(): raise ValueError('EXTERNAL_PAYMENT_EXECUTOR_REQUIRED_FOR_ADJUSTMENT')
        _,base,_,base_binding=self.original(vertical,order_id)
        business_type=f'{vertical}_CHANGE';created=now();iid=ident('opi')
        with SessionLocal() as s:
            root=s.scalar(select(Root).where(Root.business_type==business_type,Root.business_id==adjustment_id).with_for_update())
            if root:
                iid=root.payment_intent_id
            else:
                i=Intent(payment_intent_id=iid,business_type=business_type,business_id=adjustment_id,payer_id=base.payer_id,payee_id=base.payee_id,operation='PAY',amount_minor=amount_minor,currency=base.currency,channel_priority_json=['LOCAL_MARKET'],selected_channel='LOCAL_MARKET',state='SUCCEEDED',idempotency_key=f'{vertical.lower()}-change-intent:{adjustment_id}',automatic_fallback_allowed=False,user_channel_consent_at=created,created_at=created,updated_at=created);s.add(i);s.flush()
                legal='GO_CN' if base.currency=='CNY' else 'GO_GLOBAL'
                s.add(Root(payment_order_root_id=ident('por'),business_type=business_type,business_id=adjustment_id,payment_intent_id=iid,legal_entity_id=legal,state='ACTIVE',root_hash=digest({'business_type':business_type,'business_id':adjustment_id,'payment_intent_id':iid,'legal_entity_id':legal}),created_at=created))
                fact={'business_type':business_type,'business_id':adjustment_id,'payer_id':base.payer_id,'payee_id':base.payee_id,'amount_minor':amount_minor,'currency':base.currency,'source_decision_id':base_binding.source_decision_id if base_binding else None}
                s.add(FactBinding(payment_order_fact_binding_id=ident('pofb'),payment_intent_id=iid,business_type=business_type,business_id=adjustment_id,payer_id=base.payer_id,payee_id=base.payee_id,amount_minor=amount_minor,currency=base.currency,legal_entity_id=legal,source_decision_id=(base_binding.source_decision_id if base_binding else None),request_fingerprint=digest(fact),order_fact_hash=digest(fact),evidence_reference=evidence_reference,created_at=created));s.commit()
        with SessionLocal() as s:
            auth=s.scalar(select(Movement).where(Movement.root_payment_intent_id==iid,Movement.movement_type=='AUTHORIZATION',Movement.state=='CONFIRMED'))
            cap=s.scalar(select(Movement).where(Movement.root_payment_intent_id==iid,Movement.movement_type=='CAPTURE',Movement.state=='CONFIRMED'))
            rel=s.scalar(select(Movement).where(Movement.root_payment_intent_id==iid,Movement.movement_type=='RELEASE',Movement.state=='CONFIRMED'))
            if cap:return {'payment_intent_id':iid,'authorization_id':auth.money_movement_id if auth else None,'capture_id':cap.money_movement_id,'released':False}
            if rel:return {'payment_intent_id':iid,'authorization_id':auth.money_movement_id if auth else None,'capture_id':None,'released':True}
        if not auth:
            a=unified_money_movement_service.create(iid,{'movement_type':'AUTHORIZATION','amount_minor':amount_minor,'evidence':[evidence_reference],'mode':'CONTRACT_SIMULATOR'},f'{vertical.lower()}-change-auth:{adjustment_id}','vertical-money-bridge');aid=a['money_movement_id']
        else: aid=auth.money_movement_id
        return {'payment_intent_id':iid,'authorization_id':aid,'capture_id':None,'released':False}
    def capture_adjustment(self,vertical,adjustment_id,amount_minor,evidence_reference):
        prepared=self.prepare_adjustment(vertical,'__LOOKUP_NOT_USED__',adjustment_id,amount_minor,evidence_reference) if False else None
        business_type=f'{vertical}_CHANGE'
        with SessionLocal() as s:
            root=s.scalar(select(Root).where(Root.business_type==business_type,Root.business_id==adjustment_id));
            if not root:return None
            auth=s.scalar(select(Movement).where(Movement.root_payment_intent_id==root.payment_intent_id,Movement.movement_type=='AUTHORIZATION',Movement.state=='CONFIRMED'))
            cap=s.scalar(select(Movement).where(Movement.root_payment_intent_id==root.payment_intent_id,Movement.movement_type=='CAPTURE',Movement.state=='CONFIRMED'))
            if cap:return {'payment_intent_id':root.payment_intent_id,'capture_id':cap.money_movement_id}
            if not auth:raise ValueError('CHANGE_AUTHORIZATION_REQUIRED')
        cap=unified_money_movement_service.create(root.payment_intent_id,{'movement_type':'CAPTURE','parent_movement_id':auth.money_movement_id,'amount_minor':amount_minor,'evidence':[evidence_reference],'mode':'CONTRACT_SIMULATOR'},f'{vertical.lower()}-change-cap:{adjustment_id}','vertical-money-bridge')
        return {'payment_intent_id':root.payment_intent_id,'capture_id':cap['money_movement_id']}
    def release_adjustment(self,vertical,adjustment_id,amount_minor,evidence_reference):
        business_type=f'{vertical}_CHANGE'
        with SessionLocal() as s:
            root=s.scalar(select(Root).where(Root.business_type==business_type,Root.business_id==adjustment_id));
            if not root:return None
            auth=s.scalar(select(Movement).where(Movement.root_payment_intent_id==root.payment_intent_id,Movement.movement_type=='AUTHORIZATION',Movement.state=='CONFIRMED'))
            cap=s.scalar(select(Movement).where(Movement.root_payment_intent_id==root.payment_intent_id,Movement.movement_type=='CAPTURE',Movement.state=='CONFIRMED'))
            rel=s.scalar(select(Movement).where(Movement.root_payment_intent_id==root.payment_intent_id,Movement.movement_type=='RELEASE',Movement.state=='CONFIRMED'))
            if cap:raise ValueError('CHANGE_ALREADY_CAPTURED')
            if rel:return {'payment_intent_id':root.payment_intent_id,'release_id':rel.money_movement_id}
            if not auth:return None
        rel=unified_money_movement_service.create(root.payment_intent_id,{'movement_type':'RELEASE','parent_movement_id':auth.money_movement_id,'amount_minor':amount_minor,'evidence':[evidence_reference],'mode':'CONTRACT_SIMULATOR'},f'{vertical.lower()}-change-release:{adjustment_id}','vertical-money-bridge')
        return {'payment_intent_id':root.payment_intent_id,'release_id':rel['money_movement_id']}
vertical_money_bridge=VerticalMoneyBridge()
