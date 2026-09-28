"""Actual RIDE transaction and complete SQL checks copied from the C12 harness.
Transport/auth are outside this service-level test. Synthetic money only.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import threading,time
from sqlalchemy import select
from go_hotel.db.session import engine, SessionLocal
from go_hotel.db.models import (Base, MobilityRideOrderRow as Order,
    PaymentOrderRootRow as Root, OmnichannelPaymentIntentRow as Intent,
    OmnichannelPaymentAttemptRow as Attempt, OmnichannelMoneyMovementRow as Movement,
    OmnichannelLedgerEntryRow as Ledger, OrderSupplierFulfillmentRow as Fulfillment,
    ConsumerUnifiedLifecycleRow as Lifecycle)
from go_hotel.api.routes.mobility import rb, RideBook
from go_hotel.mobility.ride.service import ride_service
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge
from go_hotel.services.unified_money_movement import unified_money_movement_service as money
from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as supplier


prefix='mi-load'
def transaction(index):
    started=time.perf_counter()
    owner=prefix+'-'+str(index)
    principal=SimpleNamespace(user_id=owner)
    key=owner+'-create'
    record={'index':index,'owner':owner,'outcome':'FAIL','phase':'create_order'}
    try:
        pickup_at=(datetime.now(timezone.utc)+timedelta(days=10)).isoformat()
        offer=ride_service.search('ISOLATED_A','ISOLATED_B',pickup_at,'CNY')[0]
        body=RideBook(offer_id='ride_standard',pickup='ISOLATED_A',dropoff='ISOLATED_B',
            pickup_at=pickup_at,currency='CNY',
            cancellation_policy_hash=offer.get('cancellation',{}).get('policy_hash'),
            passengers=[{'full_name':'ISOLATED CAPACITY TEST'}])
        response=rb(body,principal,key)
        oid=response['data']['order_id'];record['order_id']=oid
        assert rb(body,principal,key)==response, 'CREATE_REPLAY_CHANGED'
        record['phase']='payment_capture'
        tx=vertical_transaction_bridge.checkout_contract('RIDE',oid,owner,
            'ride-engineering-source','isolated://c12/'+oid,'isolated-method')
        assert tx['state']=='PAYMENT_CONFIRMED_AWAITING_SUPPLIER'
        assert tx['supplier_fulfillment_id'], 'FULFILLMENT_MISSING'
        iid=tx['payment_intent_id']
        record['phase']='concurrent_money_replay'
        cap_body={'movement_type':'CAPTURE','parent_movement_id':tx['authorization_id'],
                  'mode':'CONTRACT_SIMULATOR','evidence':['isolated://c12/replay']}
        def replay(_):
            replay_barrier.wait(timeout=10)
            return money.create(iid,cap_body,'ride-cap:'+oid,'c12-capacity')['money_movement_id']
        replay_barrier=threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            captures=list(pool.map(replay,range(2)))
        assert captures==[tx['capture_id']]*2, 'DUPLICATE_CAPTURE_EFFECT'
        try:
            money.create(iid,cap_body|{'amount_minor':16801},'ride-cap:'+oid,'c12-capacity')
        except ValueError as exc:
            assert str(exc)=='MONEY_MOVEMENT_IDEMPOTENCY_CONFLICT'
        else:
            raise AssertionError('CHANGED_AMOUNT_REPLAY_ACCEPTED')
        record['phase']='simulated_supplier_and_fulfillment'
        supplier.record_supplier_fact(tx['supplier_fulfillment_id'],{
            'state':'SUPPLIER_CONFIRMED','external_operation_id':owner+'-supplier',
            'supplier_confirmation_reference':owner,
            'evidence_reference':'isolated://c12/synthetic-supplier/'+oid})
        ride_service.fulfill(owner,oid,'START','isolated://c12/start/'+oid)
        ride_service.fulfill(owner,oid,'COMPLETE','isolated://c12/complete/'+oid)
        record.update(outcome='SUCCESS',phase='completed',payment_intent_id=iid)
    except Exception as exc:
        # Do not render SQLAlchemy exception strings: they may contain URLs.
        record.update(error_type=type(exc).__name__,error_code=str(exc)[:180]
                      if isinstance(exc,(AssertionError,ValueError)) else 'SEE_PHASE')
        if type(exc).__name__=='HTTPException':
            record['http_status']=exc.status_code
            record['error_code']=str(exc.detail)[:180]
    record['duration_ms']=(time.perf_counter()-started)*1000
    return record


def verify(raw):
    observations=[]
    with SessionLocal() as session:
        orders=list(session.scalars(select(Order).where(Order.account_id.like(prefix+'%'))))
        # Include partial/failed orders so a failed request cannot hide effects.
        assert len(orders)==len(raw), 'CREATED_ORDER_COUNT_MISMATCH'
        assert len({r['order_id'] for r in raw if 'order_id' in r})==len(raw), 'ORDER_ID_COLLISION'
        for order in orders:
            roots=list(session.scalars(select(Root).where(Root.business_type=='RIDE_ORDER',Root.business_id==order.order_id)))
            assert len(roots)==1, 'PAYMENT_ROOT_COUNT'
            iid=roots[0].payment_intent_id
            intent=session.get(Intent,iid)
            attempts=list(session.scalars(select(Attempt).where(Attempt.payment_intent_id==iid)))
            moves=list(session.scalars(select(Movement).where(Movement.root_payment_intent_id==iid)))
            entries=list(session.scalars(select(Ledger).where(Ledger.payment_intent_id==iid)))
            fills=list(session.scalars(select(Fulfillment).where(Fulfillment.payment_intent_id==iid)))
            life=list(session.scalars(select(Lifecycle).where(Lifecycle.order_id==order.order_id,Lifecycle.vertical=='RIDE')))
            assert order.status=='COMPLETED' and order.total_amount_minor==16800 and order.currency=='CNY'
            assert intent.state=='SUCCEEDED' and intent.payer_id==order.account_id
            assert intent.amount_minor==16800 and intent.currency=='CNY'
            assert len(attempts)==1 and attempts[0].state=='SUCCEEDED', 'PAYMENT_ATTEMPT_COUNT_OR_STATE'
            assert len(moves)==2 and {m.movement_type for m in moves}=={'AUTHORIZATION','CAPTURE'}
            assert all(m.amount_minor==16800 and m.currency=='CNY' and m.state=='CONFIRMED'
                       and m.business_id==order.order_id and m.business_type=='RIDE_ORDER' for m in moves)
            auth=next(m for m in moves if m.movement_type=='AUTHORIZATION')
            cap=next(m for m in moves if m.movement_type=='CAPTURE')
            assert cap.parent_movement_id==auth.money_movement_id and auth.parent_movement_id is None
            assert len(entries)==2 and {e.direction for e in entries}=={'DEBIT','CREDIT'}
            assert all(e.transaction_id==cap.money_movement_id and e.entry_type=='CAPTURE'
                       and e.amount_minor==16800 and e.currency=='CNY' for e in entries)
            assert len(fills)==1 and fills[0].state=='SUPPLIER_CONFIRMED'
            assert len(life)==1 and life[0].account_id==order.account_id and life[0].payment_state=='PAID'
            assert life[0].lifecycle_state=='COMPLETED', 'TRIPS_NOT_COMPLETED'
            observations.append({'order_id':order.order_id,'order_status':order.status,
                'payment_root_id':iid,'attempts':len(attempts),'money_movement_ids':[m.money_movement_id for m in moves],
                'capture_amount_minor':cap.amount_minor,'currency':'CNY','ledger_entries':len(entries),
                'ledger_debit_minor':16800,'ledger_credit_minor':16800,'trips_state':life[0].lifecycle_state})

    return observations

