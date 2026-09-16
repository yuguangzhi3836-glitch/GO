"""Bounded flight HTTP-claim recovery with real SQLite commits and money graphs."""
from datetime import date, timedelta
from types import SimpleNamespace
import json
import pytest
from sqlalchemy import select
from go_hotel.api.routes import flight as route
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import FlightOrderRow, FlightChangeQuoteRow, IdempotencyRow, OmnichannelMoneyMovementRow as Movement
from go_hotel.flight.service import flight_service as flights
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge as checkout_bridge
from go_hotel.services.vertical_money_bridge import vertical_money_bridge as change_bridge
from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as supplier

OWNER = 'c11-flight-owner'
KEY = 'c11-flight-fixed-key'
PRINCIPAL = SimpleNamespace(user_id=OWNER)


def create_order():
    offer = flights.search('PVG','NRT',(date.today()+timedelta(days=10)).isoformat())[0]
    prebook = flights.prebook(offer['offer_id'])
    return flights.create_order(OWNER,prebook['prebook_id'],[{'full_name':'C11 TEST','type':'ADT'}])


def call_checkout(order_id,key=KEY,owner=OWNER):
    return route.checkout(order_id,route.CheckoutBody(payment_method_id='c11-test-method'),SimpleNamespace(user_id=owner),key)


def create_change():
    order = create_order()
    tx = checkout_bridge.checkout_contract('FLIGHT',order['order_id'],OWNER,'c11-source','isolated://c11')
    supplier.record_supplier_fact(tx['supplier_fulfillment_id'],{'state':'SUPPLIER_CONFIRMED',
        'external_operation_id':'c11-'+order['order_id'],'supplier_confirmation_reference':'C11PNR',
        'ticket_numbers':['C11TICKET'],'evidence_reference':'isolated://c11-ticket'})
    quote = flights.change_quote(OWNER,order['order_id'],(date.today()+timedelta(days=12)).isoformat())
    return order,quote


def call_change(order_id,quote_id,key=KEY,owner=OWNER):
    return route.execute_change(order_id,quote_id,SimpleNamespace(user_id=owner),key,None)


def observe(operation,resource_id,order_id):
    with SessionLocal() as session:
        claim=session.get(IdempotencyRow,{'operation':operation,'idempotency_key':KEY})
        order=session.get(FlightOrderRow,order_id)
        money=list(session.scalars(select(Movement).where(Movement.business_id.in_([order_id,resource_id]))))
        result={'operation':operation,'resource_id':resource_id,'order_id':order_id,'order_status':order.status,
            'claim':None if not claim else {'code':claim.response_code,'resource_id':claim.resource_id,'body':claim.response_body},
            'money':[{'id':m.money_movement_id,'root':m.root_payment_intent_id,'type':m.movement_type,'amount':m.amount_minor,'currency':m.currency,'state':m.state,'key':m.idempotency_key} for m in money]}
    print('C11_SQL '+json.dumps(result,sort_keys=True))
    return result


@pytest.mark.parametrize('operation',['FLIGHT_CHECKOUT','FLIGHT_EXECUTE_CHANGE'])
def test_after_committed_money_failure_retains_resource_and_recovers_same_root(monkeypatch,operation):
    if operation=='FLIGHT_CHECKOUT':
        order=create_order();resource=order['order_id'];bridge=checkout_bridge;name='checkout_contract'
        call=lambda:call_checkout(order['order_id'])
    else:
        order,quote=create_change();resource=quote['quote_id'];bridge=change_bridge;name='prepare_adjustment'
        call=lambda:call_change(order['order_id'],quote['quote_id'])
    original=getattr(bridge,name)
    def lost(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('C11_AFTER_COMMITTED_MONEY')
    monkeypatch.setattr(bridge,name,lost)
    with pytest.raises(RuntimeError,match='C11_AFTER_COMMITTED_MONEY'):call()
    before=observe(operation,resource,order['order_id'])
    assert before['claim'] is not None
    assert before['claim']['code']==102
    assert before['claim']['resource_id']==resource
    assert before['claim']['body']['status']=='RECOVERY_REQUIRED'
    before_money=before['money']
    monkeypatch.setattr(bridge,name,original)
    result=call()
    after=observe(operation,resource,order['order_id'])
    assert after['claim']['code']==200
    assert after['money']==before_money
    assert call()==result
    assert result['data']['status']==('PAYMENT_CONFIRMED_AWAITING_SUPPLIER' if operation=='FLIGHT_CHECKOUT' else 'UNKNOWN_EXTERNAL_STATE')

from fastapi import HTTPException
from go_hotel.api.idempotency import run_recoverable_idempotent
from go_hotel.repositories.sql import repo
from go_hotel.services.omnichannel_payment import omnichannel_payment_service as payments
from go_hotel.services.unified_money_movement import unified_money_movement_service as money_service
from go_hotel.db.models import (PaymentOrderRootRow as Root, PaymentOrderFactBindingRow as Binding,
    OmnichannelPaymentIntentRow as Intent, OmnichannelPaymentAttemptRow as Attempt)


def payload_for(order_id, quote_id=None):
    result={'user_id':OWNER,'order_id':order_id}
    return result|({'quote_id':quote_id,'confirmation':None} if quote_id else {'payment_method_id':'c11-test-method'})


def claim_for(operation='FLIGHT_CHECKOUT',key=KEY):
    return repo.get_idempotency(operation,key)


@pytest.mark.parametrize('point',['before_bridge','create_intent','execute','simulate_result','AUTHORIZATION','CAPTURE'])
def test_checkout_resumes_each_committed_boundary(monkeypatch,point):
    order=create_order();oid=order['order_id']
    target,name=(checkout_bridge,'checkout_contract') if point=='before_bridge' else ((money_service,'create') if point in {'AUTHORIZATION','CAPTURE'} else (payments,point))
    original=getattr(target,name)
    def fault(*args,**kwargs):
        if point=='before_bridge':raise ValueError('C11_POST_ORDER_COMMIT')
        result=original(*args,**kwargs)
        if point not in {'AUTHORIZATION','CAPTURE'} or args[1]['movement_type']==point:
            raise ValueError('C11_POST_STEP_COMMIT')
        return result
    monkeypatch.setattr(target,name,fault)
    with pytest.raises(HTTPException):call_checkout(oid)
    before=observe('FLIGHT_CHECKOUT',oid,oid)
    assert before['claim']['body']['status']=='RECOVERY_REQUIRED'
    with SessionLocal() as s:
        roots=[r.payment_intent_id for r in s.scalars(select(Root).where(Root.business_id==oid))]
        attempts=[a.payment_attempt_id for a in s.scalars(select(Attempt))]
    monkeypatch.setattr(target,name,original)
    call_checkout(oid)
    with SessionLocal() as s:
        final_roots=[r.payment_intent_id for r in s.scalars(select(Root).where(Root.business_id==oid))]
        final_attempts=[a.payment_attempt_id for a in s.scalars(select(Attempt))]
    assert len(final_roots)==1 and (not roots or roots==final_roots)
    assert len(final_attempts)==1 and (not attempts or attempts==final_attempts)
    after=observe('FLIGHT_CHECKOUT',oid,oid)
    assert len(after['money'])==2
    assert {m['type'] for m in after['money']}=={'AUTHORIZATION','CAPTURE'}
    assert all(m in after['money'] for m in before['money'])


@pytest.mark.parametrize('owner',['missing-owner',OWNER])
def test_explicit_absent_or_foreign_validation_releases_claim(owner):
    order=create_order()
    with pytest.raises(HTTPException):call_checkout(order['order_id'] if owner!=OWNER else 'absent',owner=owner)
    assert claim_for() is None
    with SessionLocal() as s:
        assert not list(s.scalars(select(Root)))
        assert s.get(FlightOrderRow,order['order_id']).status=='PAYMENT_PENDING'


def test_change_expiry_validation_is_safely_retryable():
    order,quote=create_change()
    with SessionLocal.begin() as s:
        q=s.get(FlightChangeQuoteRow,quote['quote_id']);q.expires_at=q.expires_at-timedelta(days=1)
    with pytest.raises(HTTPException):call_change(order['order_id'],quote['quote_id'])
    assert claim_for('FLIGHT_EXECUTE_CHANGE') is None
    with SessionLocal() as s:
        assert s.get(FlightOrderRow,order['order_id']).status=='TICKETED'
        assert not list(s.scalars(select(Root).where(Root.business_type=='FLIGHT_CHANGE')))


@pytest.mark.parametrize('after_commit',[False,True])
def test_binding_failure_never_invokes_business(monkeypatch,after_commit):
    order=create_order();original=repo.bind_idempotency_resource
    def broken(*args,**kwargs):
        if after_commit:original(*args,**kwargs)
        raise RuntimeError('C11_BIND_FAILURE')
    monkeypatch.setattr(repo,'bind_idempotency_resource',broken)
    monkeypatch.setattr(flights,'checkout',lambda *a:pytest.fail('business invoked before binding acknowledgement'))
    with pytest.raises(RuntimeError,match='C11_BIND_FAILURE'):call_checkout(order['order_id'])
    assert claim_for()['response_code']==102
    with SessionLocal() as s:assert not list(s.scalars(select(Root)))


@pytest.mark.parametrize('operation',['FLIGHT_CHECKOUT','FLIGHT_EXECUTE_CHANGE'])
def test_legacy_completed_unbound_claim_replays_without_execution(monkeypatch,operation):
    oid='historical-order';qid='historical-quote' if operation.endswith('CHANGE') else None
    payload=payload_for(oid,qid);response={'data':{'order_id':oid,'status':'TICKETED'}}
    repo.claim_idempotency(operation,KEY,payload)
    repo.complete_idempotency(operation,KEY,payload,response)
    def forbidden(*a):pytest.fail('historical response reran business')
    monkeypatch.setattr(flights,'checkout',forbidden);monkeypatch.setattr(flights,'execute_change',forbidden)
    assert (call_change(oid,qid) if qid else call_checkout(oid))==response
    with pytest.raises(HTTPException) as exc:
        call_change(oid,qid,owner='other') if qid else call_checkout(oid,owner='other')
    assert exc.value.status_code==409


def test_legacy_unprovable_response_is_held():
    payload=payload_for('a')
    repo.claim_idempotency('FLIGHT_CHECKOUT',KEY,payload)
    repo.complete_idempotency('FLIGHT_CHECKOUT',KEY,payload,{'data':{'order_id':'different'}})
    with pytest.raises(HTTPException) as exc:call_checkout('a')
    assert exc.value.status_code==409


@pytest.mark.parametrize('corruption',['intent_unknown','payer','currency','amount','binding','movement_unknown','movement_key','parent','attempt_external'])
def test_recovery_rejects_unknown_or_mismatched_money_without_bridge(monkeypatch,corruption):
    order=create_order();oid=order['order_id'];original=checkout_bridge.checkout_contract
    def fault(*a,**kw):original(*a,**kw);raise RuntimeError('committed')
    monkeypatch.setattr(checkout_bridge,'checkout_contract',fault)
    with pytest.raises(RuntimeError):call_checkout(oid)
    with SessionLocal.begin() as s:
        intent=s.scalar(select(Intent).where(Intent.business_id==oid))
        if corruption=='intent_unknown':intent.state='UNKNOWN_EXTERNAL_STATE'
        elif corruption=='payer':intent.payer_id='other'
        elif corruption=='currency':intent.currency='USD'
        elif corruption=='amount':intent.amount_minor+=1
        elif corruption=='binding':s.scalar(select(Binding)).payer_id='other'
        elif corruption=='attempt_external':s.scalar(select(Attempt)).external_invoked=True
        else:
            movement=s.scalar(select(Movement).where(Movement.business_id==oid,Movement.movement_type=='CAPTURE'))
            if corruption=='movement_unknown':movement.state='UNKNOWN_EXTERNAL_STATE'
            elif corruption=='movement_key':movement.idempotency_key='incorrect'
            else:movement.parent_movement_id='wrong-parent'
    before=observe('FLIGHT_CHECKOUT',oid,oid)
    monkeypatch.setattr(checkout_bridge,'checkout_contract',lambda *a,**kw:pytest.fail('uncertain money re-executed'))
    with pytest.raises(HTTPException):call_checkout(oid)
    after=observe('FLIGHT_CHECKOUT',oid,oid)
    assert after==before


def test_released_change_cannot_revive_under_same_or_new_key(monkeypatch):
    order,quote=create_change();oid=order['order_id'];qid=quote['quote_id'];original=change_bridge.prepare_adjustment
    def fault(*a,**kw):original(*a,**kw);raise RuntimeError('committed')
    monkeypatch.setattr(change_bridge,'prepare_adjustment',fault)
    with pytest.raises(RuntimeError):call_change(oid,qid)
    change_bridge.release_adjustment('FLIGHT',qid,quote['total_due_minor'],'isolated://release')
    before=observe('FLIGHT_EXECUTE_CHANGE',qid,oid)['money']
    monkeypatch.setattr(change_bridge,'prepare_adjustment',lambda *a,**kw:pytest.fail('released auth revived'))
    for key in (KEY,'new-key'):
        with pytest.raises(HTTPException):call_change(oid,qid,key)
    assert observe('FLIGHT_EXECUTE_CHANGE',qid,oid)['money']==before


@pytest.mark.parametrize('action',['COMPLETE','RELEASE','RECOVERY_REQUIRED'])
def test_stale_execution_token_cannot_write_request_or_resource(action):
    op='FLIGHT_CHECKOUT';payload=payload_for('order');rid='order'
    repo.claim_idempotency(op,KEY,payload)
    assert repo.bind_idempotency_resource(op,KEY,payload,rid,'old',new_claim=True)[0]=='START'
    repo.finish_recoverable_idempotency(op,KEY,payload,rid,'old','RECOVERY_REQUIRED')
    assert repo.bind_idempotency_resource(op,KEY,payload,rid,'new',new_claim=False)[0]=='RECOVER'
    with pytest.raises(ValueError,match='IDEMPOTENCY_EXECUTION_LOST'):
        repo.finish_recoverable_idempotency(op,KEY,payload,rid,'old',action,{'data':{}})
    assert claim_for()['response']['execution_token']=='new'
    guard=repo.get_idempotency('RESOURCE:'+op,rid)
    assert guard['response']['execution_token']=='new'


@pytest.mark.parametrize('different_key',[False,True])
def test_active_resource_blocks_concurrent_callback_then_replays(monkeypatch,different_key):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    order=create_order();oid=order['order_id'];entered=Event();release=Event();original=checkout_bridge.checkout_contract
    def paused(*a,**kw):
        entered.set();assert release.wait(20);return original(*a,**kw)
    monkeypatch.setattr(checkout_bridge,'checkout_contract',paused)
    key='other-key' if different_key else KEY
    with ThreadPoolExecutor(max_workers=1) as pool:
        first=pool.submit(call_checkout,oid)
        try:
            assert entered.wait(20)
            with pytest.raises(HTTPException) as exc:call_checkout(oid,key)
            assert exc.value.status_code==409
        finally:release.set()
        result=first.result(timeout=20)
    assert call_checkout(oid,key)==result
    with SessionLocal() as s:
        assert len(list(s.scalars(select(Attempt))))==1
        assert len(list(s.scalars(select(Movement))))==2


@pytest.mark.parametrize('after_commit',[False,True])
def test_completion_failure_replays_without_repeating_money(monkeypatch,after_commit):
    order=create_order();oid=order['order_id'];original=repo.finish_recoverable_idempotency
    def fail(*a,**kw):
        if a[5]=='COMPLETE':
            if after_commit:original(*a,**kw)
            raise RuntimeError('C11_COMPLETE_ACK')
        return original(*a,**kw)
    monkeypatch.setattr(repo,'finish_recoverable_idempotency',fail)
    with pytest.raises(RuntimeError,match='C11_COMPLETE_ACK'):call_checkout(oid)
    before=observe('FLIGHT_CHECKOUT',oid,oid)
    assert before['claim']['code']==(200 if after_commit else 102)
    monkeypatch.setattr(repo,'finish_recoverable_idempotency',original)
    monkeypatch.setattr(checkout_bridge,'checkout_contract',lambda *a,**kw:pytest.fail('completed payment was executed'))
    call_checkout(oid)
    assert observe('FLIGHT_CHECKOUT',oid,oid)['money']==before['money']


def test_failure_recording_unavailable_keeps_running_fence(monkeypatch):
    order=create_order();oid=order['order_id']
    monkeypatch.setattr(checkout_bridge,'checkout_contract',lambda *a,**kw:(_ for _ in ()).throw(ValueError('ORIGINAL')))
    monkeypatch.setattr(repo,'finish_recoverable_idempotency',lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('database unavailable')))
    with pytest.raises(HTTPException) as exc:call_checkout(oid)
    assert 'ORIGINAL' in str(exc.value.detail)
    assert claim_for()['response']['status']=='RUNNING'
    with pytest.raises(HTTPException) as exc:call_checkout(oid)
    assert exc.value.status_code==409

@pytest.mark.parametrize('field',['user_id','payment_method_id','order_id'])
def test_resource_guard_refuses_changed_payload_on_different_key(field):
    op='FLIGHT_CHECKOUT';payload=payload_for('order');rid='order'
    repo.claim_idempotency(op,KEY,payload)
    repo.bind_idempotency_resource(op,KEY,payload,rid,'first',new_claim=True)
    repo.finish_recoverable_idempotency(op,KEY,payload,rid,'first','RECOVERY_REQUIRED')
    changed=payload|{field:'other'};repo.claim_idempotency(op,'other',changed)
    with pytest.raises(ValueError,match='IDEMPOTENCY_RESOURCE_CONFLICT'):
        repo.bind_idempotency_resource(op,'other',changed,rid,'second',new_claim=True)
    assert repo.get_idempotency('RESOURCE:'+op,rid)['response']['status']=='RECOVERY_REQUIRED'


def test_different_key_can_only_acquire_quiescent_recovery_and_fences_old_request():
    op='FLIGHT_CHECKOUT';payload=payload_for('order');rid='order'
    repo.claim_idempotency(op,KEY,payload)
    repo.bind_idempotency_resource(op,KEY,payload,rid,'first',new_claim=True)
    repo.finish_recoverable_idempotency(op,KEY,payload,rid,'first','RECOVERY_REQUIRED')
    repo.claim_idempotency(op,'other',payload)
    assert repo.bind_idempotency_resource(op,'other',payload,rid,'second',new_claim=True)[0]=='RECOVER'
    for action in ('COMPLETE','RELEASE','RECOVERY_REQUIRED'):
        with pytest.raises(ValueError,match='IDEMPOTENCY_EXECUTION_LOST'):
            repo.finish_recoverable_idempotency(op,KEY,payload,rid,'first',action,{'data':{}})
    response={'data':{'order_id':rid,'status':'PAYMENT_CONFIRMED_AWAITING_SUPPLIER'}}
    repo.finish_recoverable_idempotency(op,'other',payload,rid,'second','COMPLETE',response)
    assert repo.bind_idempotency_resource(op,KEY,payload,rid,'third',new_claim=False)==('REPLAY',response)

@pytest.mark.parametrize('target',['request','resource'])
def test_unknown_durable_response_code_is_never_replayed(monkeypatch,target):
    order=create_order();oid=order['order_id'];payload=payload_for(oid);op='FLIGHT_CHECKOUT'
    repo.claim_idempotency(op,KEY,payload)
    repo.bind_idempotency_resource(op,KEY,payload,oid,'token',new_claim=True)
    repo.finish_recoverable_idempotency(op,KEY,payload,oid,'token','RECOVERY_REQUIRED')
    with SessionLocal.begin() as s:
        row=s.get(IdempotencyRow,{'operation':op if target=='request' else 'RESOURCE:'+op,'idempotency_key':KEY if target=='request' else oid})
        row.response_code=299;row.response_body={'data':{'order_id':oid,'status':'TICKETED'}}
    monkeypatch.setattr(checkout_bridge,'checkout_contract',lambda *a,**kw:pytest.fail('unknown code executed business'))
    with pytest.raises(HTTPException) as exc:call_checkout(oid)
    assert exc.value.status_code==409
    assert exc.value.detail['code']=='IDEMPOTENCY_RECONCILIATION_REQUIRED'


@pytest.mark.parametrize('state',['TICKETED','FAILED'])
def test_supplier_resolution_money_commit_interruption_reuses_same_movement(monkeypatch,state):
    """A retry after capture/release committed must not duplicate the money side effect."""
    order,quote=create_change();oid=order['order_id'];qid=quote['quote_id']
    call_change(oid,qid)
    action='capture_adjustment' if state=='TICKETED' else 'release_adjustment'
    original=getattr(change_bridge,action)
    committed=[]
    def lost(*args,**kwargs):
        result=original(*args,**kwargs)
        committed.append(result)
        raise RuntimeError('C11_RESOLUTION_AFTER_MONEY_COMMIT')
    monkeypatch.setattr(change_bridge,action,lost)
    kwargs={'supplier_reference':'C11NEWPNR','ticket_numbers':['C11NEWTICKET']} if state=='TICKETED' else {}
    invoke=lambda:flights.admin_external_state(
        oid,state,'isolated://c11-resolution','c11-admin',
        kwargs.get('supplier_reference'),kwargs.get('ticket_numbers'),qid)
    with pytest.raises(RuntimeError,match='C11_RESOLUTION_AFTER_MONEY_COMMIT'):
        invoke()
    assert len(committed)==1
    movement_key='capture_id' if state=='TICKETED' else 'release_id'
    first_movement=committed[0][movement_key]
    with SessionLocal() as s:
        before=list(s.scalars(select(Movement).where(
            Movement.business_id==qid,Movement.movement_type==('CAPTURE' if state=='TICKETED' else 'RELEASE'))))
        assert [m.money_movement_id for m in before]==[first_movement]
    monkeypatch.setattr(change_bridge,action,original)
    result=invoke()
    assert invoke()==result
    with SessionLocal() as s:
        after=list(s.scalars(select(Movement).where(
            Movement.business_id==qid,Movement.movement_type==('CAPTURE' if state=='TICKETED' else 'RELEASE'))))
        assert [m.money_movement_id for m in after]==[first_movement]
        assert s.get(FlightChangeQuoteRow,qid).status==('EXECUTED' if state=='TICKETED' else 'FAILED')
        assert s.get(FlightOrderRow,oid).status=='TICKETED'


@pytest.mark.parametrize('supplier,tickets',[
    ('PNR\\nINJECT',['VALID-TICKET']),
    ('VALIDPNR',['TICKET\\x00INJECT']),
])
def test_supplier_resolution_rejects_non_printable_tokens_before_money(monkeypatch,supplier,tickets):
    order,quote=create_change();oid=order['order_id'];qid=quote['quote_id']
    call_change(oid,qid)
    called=[]
    monkeypatch.setattr(change_bridge,'capture_adjustment',lambda *a,**k: called.append((a,k)))
    with pytest.raises(ValueError):
        flights.admin_external_state(oid,'TICKETED','isolated://c11-parse','c11-admin',supplier,tickets,qid)
    assert called == []
    with SessionLocal() as s:
        assert s.get(FlightChangeQuoteRow,qid).status == 'PENDING_SUPPLIER'
        assert s.get(FlightOrderRow,oid).status == 'UNKNOWN_EXTERNAL_STATE'
