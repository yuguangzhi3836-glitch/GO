from __future__ import annotations
from datetime import datetime, timezone
import hashlib,json,uuid
from sqlalchemy import select, text
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
            if s.bind.dialect.name=='sqlite':s.execute(text('BEGIN IMMEDIATE'))
            s.get(Intent,base.payment_intent_id,with_for_update=True)
            root=s.scalar(select(Root).where(Root.business_type==business_type,Root.business_id==adjustment_id).with_for_update())
            if root:
                iid=root.payment_intent_id
                previous=s.get(Intent,iid)
                if (previous.payer_id,previous.payee_id,previous.currency,previous.amount_minor)!=(base.payer_id,base.payee_id,base.currency,amount_minor):
                    raise ValueError('CHANGE_PAYMENT_FACT_MISMATCH')
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
    def plan_refund(self,vertical,order_id,adjustment_ids,amount_minor,key):
        """Freeze allocations against remaining original captures before releasing the order lock."""
        if type(amount_minor) is not int or amount_minor<=0:raise ValueError('REFUND_AMOUNT_INVALID')
        root,base,cap,_=self.original(vertical,order_id)
        components=[(root,cap)]
        with SessionLocal() as s:
            for aid in dict.fromkeys(adjustment_ids):
                extra=s.scalar(select(Root).where(Root.business_type==f'{vertical}_CHANGE',Root.business_id==aid))
                intent=s.get(Intent,extra.payment_intent_id) if extra else None
                captured=s.scalar(select(Movement).where(Movement.root_payment_intent_id==extra.payment_intent_id,
                    Movement.movement_type=='CAPTURE',Movement.state=='CONFIRMED')) if extra else None
                if not intent or not captured:raise ValueError('CHANGE_CONFIRMED_CAPTURE_REQUIRED')
                if (intent.payer_id,intent.payee_id,intent.currency)!=(base.payer_id,base.payee_id,base.currency):
                    raise ValueError('CHANGE_PAYMENT_OWNER_OR_CURRENCY_MISMATCH')
                components.append((extra,captured))
            remaining=amount_minor;plan=[]
            for payment_root,capture in components:
                refunds=s.scalars(select(Movement).where(Movement.parent_movement_id==capture.money_movement_id,
                    Movement.movement_type.in_(['REFUND','COMPENSATION']))).all()
                if any(r.state not in {'CONFIRMED','FAILED','REJECTED','CANCELLED'} for r in refunds):
                    raise ValueError('ORIGINAL_REFUND_HISTORY_RECONCILIATION_REQUIRED')
                available=capture.amount_minor-sum(r.amount_minor for r in refunds if r.state=='CONFIRMED')
                allocated=min(remaining,available);remaining-=allocated
                if allocated>0:plan.append({'payment_intent_id':payment_root.payment_intent_id,
                    'capture_id':capture.money_movement_id,'amount_minor':allocated,
                    'key':key+':'+digest(capture.money_movement_id)[:16]})
            if remaining:raise ValueError('REFUND_EXCEEDS_REMAINING_CAPTURES')
            return plan
    def execute_refund_plan(self,plan,evidence_reference):
        if _prod():raise ValueError('EXTERNAL_REFUND_EXECUTOR_REQUIRED')
        if not plan:raise ValueError('ORIGINAL_REFUND_PLAN_REQUIRED')
        movements=[]
        for item in plan:
            movement=unified_money_movement_service.create(item['payment_intent_id'],{'movement_type':'REFUND',
                'parent_movement_id':item['capture_id'],'amount_minor':item['amount_minor'],
                'evidence':[evidence_reference],'mode':'CONTRACT_SIMULATOR'},item['key'],'vertical-money-bridge')
            movements.append(movement)
            if movement['state']!='CONFIRMED':break
        return {'state':'CONFIRMED' if len(movements)==len(plan) and all(m['state']=='CONFIRMED' for m in movements) else movements[-1]['state'],
            'money_movement_id':movements[0]['money_movement_id'],
            'money_movement_ids':[m['money_movement_id'] for m in movements]}
    def refund_with_adjustments(self,vertical,order_id,adjustment_ids,amount_minor,evidence_reference,key):
        """Return money to each original capture, including paid change differences.

        Component allocations are deterministic and use fixed idempotency keys;
        retrying after a partial failure cannot create another component refund.
        """
        if _prod():raise ValueError('EXTERNAL_REFUND_EXECUTOR_REQUIRED')
        if type(amount_minor) is not int or amount_minor<=0:raise ValueError('REFUND_AMOUNT_INVALID')
        root,base,cap,_=self.original(vertical,order_id)
        if not adjustment_ids:return self.refund(vertical,order_id,amount_minor,evidence_reference,key)
        components=[(root,cap)]
        with SessionLocal() as s:
            for aid in dict.fromkeys(adjustment_ids):
                extra=s.scalar(select(Root).where(Root.business_type==f'{vertical}_CHANGE',Root.business_id==aid))
                intent=s.get(Intent,extra.payment_intent_id) if extra else None
                captured=s.scalar(select(Movement).where(Movement.root_payment_intent_id==extra.payment_intent_id,
                    Movement.movement_type=='CAPTURE',Movement.state=='CONFIRMED')) if extra else None
                if not intent or not captured:raise ValueError('CHANGE_CONFIRMED_CAPTURE_REQUIRED')
                if (intent.payer_id,intent.payee_id,intent.currency)!=(base.payer_id,base.payee_id,base.currency):
                    raise ValueError('CHANGE_PAYMENT_OWNER_OR_CURRENCY_MISMATCH')
                components.append((extra,captured))
            if amount_minor>sum(c.amount_minor for _,c in components):raise ValueError('REFUND_EXCEEDS_CONFIRMED_CAPTURES')
            remaining=amount_minor;plan=[]
            for payment_root,capture in components:
                allocated=min(remaining,capture.amount_minor);remaining-=allocated
                component_key=key+':'+digest(capture.money_movement_id)[:16]
                refunds=s.scalars(select(Movement).where(Movement.parent_movement_id==capture.money_movement_id,
                    Movement.movement_type=='REFUND')).all()
                for previous in refunds:
                    if previous.idempotency_key==component_key:
                        if previous.amount_minor!=allocated:raise ValueError('REFUND_ALLOCATION_CHANGED')
                    elif previous.state not in {'FAILED','REJECTED','CANCELLED'}:
                        raise ValueError('ORIGINAL_REFUND_HISTORY_RECONCILIATION_REQUIRED')
                if allocated:plan.append((payment_root.payment_intent_id,capture.money_movement_id,allocated,component_key))
        movements=[]
        for intent_id,capture_id,allocated,component_key in plan:
            movement=unified_money_movement_service.create(intent_id,{'movement_type':'REFUND',
                'parent_movement_id':capture_id,'amount_minor':allocated,'evidence':[evidence_reference],
                'mode':'CONTRACT_SIMULATOR'},component_key,'vertical-money-bridge')
            movements.append(movement)
            if movement['state']!='CONFIRMED':break
        return {'state':'CONFIRMED' if len(movements)==len(plan) and all(m['state']=='CONFIRMED' for m in movements) else movements[-1]['state'],
            'money_movement_id':movements[0]['money_movement_id'],'money_movement_ids':[m['money_movement_id'] for m in movements],
            'allocated_amount_minor':sum(p[2] for p in plan),'component_count':len(plan)}
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
