"""Exact coupon refunds with frozen capture allocations and recoverable execution.

All selectors and prices come from durable server coupons. The native order lock
serializes preparation with changes and other refunds; the operation lease fences
finalization, while C11 movement keys fence money across crashes and retries.
"""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import select
from go_hotel.autonomy.durable import transaction, db_now_ms, digest
from go_hotel.core.production_truth_gate import production_truth_required
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (FlightOrderRow as Order, FlightCouponRefundRow as Operation,
    FlightRefundRow as Refund, FlightChangeQuoteRow as Change,
    JourneyRecoveryEvidenceChainRow as Evidence, OmnichannelMoneyMovementRow as Movement,
    OmnichannelPaymentIntentRow as Intent)
from go_hotel.services.vertical_money_bridge import vertical_money_bridge as money
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence
from go_hotel.services.vertical_lifecycle_projection import project_vertical_lifecycle
from go_hotel.services.flight_refund_consent import records as verify_evidence
from go_hotel.flight.changes import order_facts
from . import coupons

LEASE_MS=30000


def _now():return datetime.now(timezone.utc).replace(tzinfo=None)


def _public(op):
    q=op.quote_json
    return {'refund_id':op.refund_id,'quote_id':op.refund_id,'order_id':op.order_id,
        'scope':'SELECTED_COUPONS','status':op.state,'quote_hash':op.quote_hash,
        'coupon_ids':q['coupon_ids'],'coupons':[c for c in q['coupons'] if c['coupon_id'] in q['coupon_ids']],
        'refund_amount_minor':q['refund_amount_minor'],'refund_fee_minor':q['refund_fee_minor'],
        'currency':q['currency'],'expires_ms':op.expires_ms,'refund_to':'ORIGINAL_PAYMENT_METHOD',
        'data_mode':'SIMULATION','external_live':False}


def _identity(op):
    return {'refund_id':op.refund_id,'order_id':op.order_id,'account_id':op.account_id,
        'created_ms':op.created_ms,'expires_ms':op.expires_ms,'quote':op.quote_json}


def _integrity(op):
    if digest(_identity(op))!=op.quote_hash:raise ValueError('FLIGHT_COUPON_REFUND_INTEGRITY_INVALID')
    if op.state!='QUOTED' and op.execution_hash!=digest({'quote_hash':op.quote_hash,'money_plan':op.money_plan_json}):
        raise ValueError('FLIGHT_COUPON_REFUND_INTEGRITY_INVALID')


def _consent(op,body):
    expected={'quote_hash':op.quote_hash,'expected_refund_amount_minor':op.quote_json['refund_amount_minor'],
        'currency':op.quote_json['currency'],'confirmed':True}
    if (not isinstance(body,dict) or body!=expected or type(body.get('confirmed')) is not bool
            or type(body.get('expected_refund_amount_minor')) is not int):
        raise ValueError('FLIGHT_COUPON_REFUND_CONSENT_INVALID')


def quote(account,order_id,ids=None):
    production_truth_required('FLIGHT','COUPON_REFUND_QUOTE')
    with transaction(SessionLocal) as s:
        order=s.get(Order,order_id,with_for_update=True)
        if not order or order.account_id!=account or order.status!='TICKETED':raise ValueError('FLIGHT_ORDER_NOT_REFUNDABLE')
        items=coupons.ledger(s,order)
        if ids is None:ids=[c.coupon_id for c in items if c.state=='ISSUED']
        selected=coupons.selected(items,ids)
        if any(c.refund_policy.get('allowed') is not True for c in selected):raise ValueError('FLIGHT_ORDER_NOT_REFUNDABLE:FARE_POLICY')
        amounts=[]
        for c in selected:
            fee=c.refund_policy.get('fee_minor')
            if type(fee) is not int or fee<0:raise ValueError('FLIGHT_COUPON_FARE_INVALID')
            amounts.append({'coupon_id':c.coupon_id,'amount_minor':max(0,c.paid_amount_minor-fee),
                'fee_minor':min(c.paid_amount_minor,fee)})
        created=db_now_ms(s)
        data={'order':order_facts(order),'coupons':[coupons.snapshot(c) for c in items],
            'coupon_ids':[c.coupon_id for c in selected],'allocations':amounts,
            'refund_amount_minor':sum(v['amount_minor'] for v in amounts),
            'refund_fee_minor':sum(v['fee_minor'] for v in amounts),'currency':order.currency}
        op=Operation(refund_id='flt_crf_'+uuid4().hex,order_id=order_id,account_id=account,state='QUOTED',
            quote_json=data,quote_hash='',money_plan_json=None,execution_hash=None,result_json=None,
            lease_token=None,lease_until_ms=0,created_ms=created,expires_ms=created+900000)
        op.quote_hash=digest(_identity(op));s.add(op);s.flush();return _public(op)


def _current(s,order,op,prepared):
    if order_facts(order)!=op.quote_json['order']:raise ValueError('FLIGHT_COUPON_REFUND_CHANGED_REQUOTE_REQUIRED')
    current=[coupons.snapshot(c) for c in coupons.ledger(s,order)]
    if prepared:
        for c in current:
            if c['coupon_id'] in op.quote_json['coupon_ids']:
                if c['state']!='REFUND_PENDING':raise ValueError('FLIGHT_COUPON_REFUND_STATE_INVALID')
                c['state']='ISSUED'
    if current!=op.quote_json['coupons']:raise ValueError('FLIGHT_COUPON_REFUND_CHANGED_REQUOTE_REQUIRED')


def _audit(s,order,op):
    verify_evidence(s,order)
    entries=list(s.scalars(select(Evidence).where(Evidence.execution_id=='rc20:FLIGHT:'+order.order_id,
        Evidence.evidence_kind=='COUPON_REFUND_PREPARED')))
    matches=[e.evidence_json['payload'] for e in entries if e.evidence_json['payload'].get('refund_id')==op.refund_id]
    if len(matches)!=1 or matches[0].get('execution_hash')!=op.execution_hash:
        raise ValueError('FLIGHT_COUPON_REFUND_INTEGRITY_INVALID')
    if op.state=='COMPLETED':
        completed=list(s.scalars(select(Evidence).where(Evidence.execution_id=='rc20:FLIGHT:'+order.order_id,
            Evidence.evidence_kind=='COUPON_REFUND_COMPLETED')))
        receipts=[e.evidence_json['payload'] for e in completed if e.evidence_json['payload'].get('refund_id')==op.refund_id]
        expected=dict(op.result_json or {})|{'actor_id':op.account_id,'execution_hash':op.execution_hash}
        if len(receipts)!=1 or receipts[0]!=expected:
            raise ValueError('FLIGHT_COUPON_REFUND_INTEGRITY_INVALID')
        _money(s,op,op.result_json)


def _money(s,op,result):
    ids=result.get('money_movement_ids',[])
    plan=op.money_plan_json
    if len(ids)!=len(plan) or len(set(ids))!=len(ids):raise ValueError('FLIGHT_COUPON_REFUND_MONEY_INVALID')
    for p,mid in zip(plan,ids):
        m=s.get(Movement,mid);cap=s.get(Movement,p['capture_id']);intent=s.get(Intent,p['payment_intent_id'])
        if (not m or m.state!='CONFIRMED' or m.movement_type!='REFUND' or m.parent_movement_id!=p['capture_id']
                or m.root_payment_intent_id!=p['payment_intent_id'] or m.idempotency_key!=p['key']
                or m.amount_minor!=p['amount_minor'] or m.currency!=op.quote_json['currency']
                or not cap or cap.state!='CONFIRMED' or cap.movement_type!='CAPTURE'
                or cap.root_payment_intent_id!=p['payment_intent_id'] or not intent
                or intent.payer_id!=op.account_id or intent.currency!=op.quote_json['currency']):
            raise ValueError('FLIGHT_COUPON_REFUND_MONEY_INVALID')
    if sum(p['amount_minor'] for p in plan)!=op.quote_json['refund_amount_minor']:
        raise ValueError('FLIGHT_COUPON_REFUND_MONEY_INVALID')


def execute(account,order_id,refund_id,confirmation):
    production_truth_required('FLIGHT','COUPON_REFUND')
    with transaction(SessionLocal) as s:
        order=s.get(Order,order_id,with_for_update=True);op=s.get(Operation,refund_id,with_for_update=True)
        if not order or order.account_id!=account or not op or op.order_id!=order_id or op.account_id!=account:
            raise ValueError('FLIGHT_COUPON_REFUND_NOT_FOUND')
        _integrity(op);_consent(op,confirmation)
        if op.state=='COMPLETED':
            _audit(s,order,op)
            return deepcopy(op.result_json)|{'idempotent_replay':True}
        if op.state=='QUOTED':
            if op.expires_ms<=db_now_ms(s):raise ValueError('FLIGHT_COUPON_REFUND_EXPIRED')
            if order.status!='TICKETED':raise ValueError('FLIGHT_COUPON_REFUND_STATE_INVALID')
            _current(s,order,op,False)
            adjustments=list(s.scalars(select(Change.quote_id).where(Change.order_id==order_id,Change.status=='EXECUTED',
                Change.total_due_minor>0).order_by(Change.created_at,Change.quote_id)))
            amount=op.quote_json['refund_amount_minor']
            op.money_plan_json=money.plan_refund('FLIGHT',order_id,adjustments,amount,'flight-coupon-refund:'+refund_id) if amount else []
            op.execution_hash=digest({'quote_hash':op.quote_hash,'money_plan':op.money_plan_json})
            op.state='PREPARED';order.status='REFUND_PENDING';order.updated_at=_now()
            for c in coupons.rows(s,order):
                if c.coupon_id in op.quote_json['coupon_ids']:c.state='REFUND_PENDING'
            s.add(Refund(refund_id=refund_id,order_id=order_id,status='REFUND_PENDING',
                refund_amount_minor=amount,refund_fee_minor=op.quote_json['refund_fee_minor'],currency=order.currency,
                created_at=_now(),completed_at=None))
            append_vertical_evidence(s,'FLIGHT',order_id,'COUPON_REFUND_PREPARED',order.status,
                {'refund_id':refund_id,'actor_id':account,'coupon_ids':op.quote_json['coupon_ids'],
                 'execution_hash':op.execution_hash,'quote_hash':op.quote_hash})
            project_vertical_lifecycle(s,'FLIGHT',order,'coupon-refund:'+refund_id,facts={'refund_id':refund_id})
            s.flush()
        if order.status!='REFUND_PENDING':raise ValueError('FLIGHT_COUPON_REFUND_STATE_INVALID')
        _current(s,order,op,True);_audit(s,order,op)
        if op.lease_token and op.lease_until_ms>db_now_ms(s):raise ValueError('FLIGHT_COUPON_REFUND_ALREADY_PROCESSING')
        token=uuid4().hex;op.lease_token=token;op.lease_until_ms=db_now_ms(s)+LEASE_MS
        plan=deepcopy(op.money_plan_json)
    try:
        result=money.execute_refund_plan(plan,'flight-coupon-refund://'+refund_id) if plan else {'state':'CONFIRMED','money_movement_ids':[]}
        if result['state']!='CONFIRMED':raise ValueError('FLIGHT_COUPON_REFUND_MONEY_NOT_CONFIRMED')
        with transaction(SessionLocal) as s:
            order=s.get(Order,order_id,with_for_update=True);op=s.get(Operation,refund_id,with_for_update=True)
            _integrity(op);_consent(op,confirmation);_audit(s,order,op)
            if op.state=='COMPLETED':return deepcopy(op.result_json)|{'idempotent_replay':True}
            if op.lease_token!=token or op.lease_until_ms<=db_now_ms(s):raise ValueError('FLIGHT_COUPON_REFUND_LEASE_LOST')
            if order.status!='REFUND_PENDING':raise ValueError('FLIGHT_COUPON_REFUND_STATE_INVALID')
            _current(s,order,op,True);_money(s,op,result)
            allocations={a['coupon_id']:a['amount_minor'] for a in op.quote_json['allocations']}
            items=coupons.rows(s,order)
            for c in items:
                if c.coupon_id in allocations:
                    c.state='REFUNDED';c.refunded_amount_minor=allocations[c.coupon_id];c.version+=1
            row=s.get(Refund,refund_id);row.status='REFUND_COMPLETED';row.completed_at=_now()
            order.status='REFUNDED' if all(c.state=='REFUNDED' for c in items) else 'TICKETED';order.updated_at=_now()
            op.state='COMPLETED';op.lease_token=None;op.lease_until_ms=0
            op.result_json={'refund_id':refund_id,'order_id':order_id,'scope':'SELECTED_COUPONS','status':'REFUND_COMPLETED',
                'coupon_ids':op.quote_json['coupon_ids'],'refund_amount_minor':op.quote_json['refund_amount_minor'],
                'refund_fee_minor':op.quote_json['refund_fee_minor'],'currency':op.quote_json['currency'],
                'money_state':'CONFIRMED' if plan else 'NO_REFUND_DUE', 'money_movement_ids':result['money_movement_ids']}
            append_vertical_evidence(s,'FLIGHT',order_id,'COUPON_REFUND_COMPLETED',order.status,
                dict(op.result_json)|{'actor_id':account,'execution_hash':op.execution_hash})
            project_vertical_lifecycle(s,'FLIGHT',order,'coupon-refund-completed:'+refund_id,facts=dict(op.result_json))
            return deepcopy(op.result_json)
    except Exception:
        with transaction(SessionLocal) as s:
            s.get(Order,order_id,with_for_update=True);op=s.get(Operation,refund_id,with_for_update=True)
            if op and op.state=='PREPARED' and op.lease_token==token:
                op.lease_token=None;op.lease_until_ms=0
        raise


def has_operations(s,order):
    return bool(s.scalar(select(Operation.refund_id).where(Operation.order_id==order.order_id,Operation.state!='QUOTED')))


def legacy_execute(account,order_id,accepted_hash):
    with SessionLocal() as s:
        order=s.get(Order,order_id)
        if not order or order.account_id!=account:raise ValueError('FLIGHT_ORDER_NOT_FOUND')
        query=select(Operation).where(Operation.order_id==order_id,Operation.account_id==account)
        if accepted_hash is not None:query=query.where(Operation.quote_hash==accepted_hash)
        else:query=query.where(Operation.state=='PREPARED' if order.status=='REFUND_PENDING' else Operation.state=='COMPLETED' if order.status=='REFUNDED' else Operation.state=='__NONE__')
        op=s.scalar(query.order_by(Operation.created_ms.desc()))
        q=_public(op) if op else None
    if not q:
        if accepted_hash is not None:raise ValueError('REFUND_QUOTE_CHANGED_RECONFIRM_REQUIRED')
        q=quote(account,order_id)
    return execute(account,order_id,q['refund_id'],{'quote_hash':q['quote_hash'],
        'expected_refund_amount_minor':q['refund_amount_minor'],'currency':q['currency'],'confirmed':True})
