"""C13 independent adversarial assertions rebound to the current checkout; original assertions retained."""
import json,sys,os,tempfile
from pathlib import Path
from datetime import timedelta
import pytest
from sqlalchemy import select
from tests.test_c01_aoluguya_business_day import http,business,purchase,post,close_day,arrive_and_register,window
from tests.hosted_review_support import identity
from go_hotel.db.session import SessionLocal,engine
from go_hotel.db import models as m

SOURCE=Path(__file__).resolve().parents[1]
ART=Path(os.environ.get('GO_C13_ARTIFACT_DIR') or tempfile.mkdtemp(prefix='go-c13-business-day-'))
ART.mkdir(parents=True,exist_ok=True)

@pytest.fixture(autouse=True)
def source_bound():
    def check():
        for name,module in list(sys.modules.items()):
            path=getattr(module,'__file__',None)
            if path and (name.startswith('go_hotel.') or name.startswith('tests.')):
                assert Path(path).resolve().is_relative_to(SOURCE.resolve()),(name,path)
    check();yield;check()

def record(name,value):
    (ART/(name+'.json')).write_text(json.dumps(value,indent=2,ensure_ascii=False,default=str)+'\n')

def graph(rid):
    with SessionLocal() as s:
        r=s.get(m.HostedDirectReservationRow,rid)
        a=s.scalar(select(m.AlipayAuthorizationRow).where(m.AlipayAuthorizationRow.hosted_reservation_id==rid))
        root=s.scalar(select(m.PaymentOrderRootRow).where(m.PaymentOrderRootRow.business_id==a.authorization_id))
        moves=list(s.scalars(select(m.OmnichannelMoneyMovementRow).where(m.OmnichannelMoneyMovementRow.root_payment_intent_id==root.payment_intent_id)))
        ledger=list(s.scalars(select(m.OmnichannelLedgerEntryRow).where(m.OmnichannelLedgerEntryRow.payment_intent_id==root.payment_intent_id)))
        return {'reservation_id':rid,'reservation_state':r.reservation_state,'payment_state':r.payment_state,'amount_minor':r.amount_minor,'currency':r.currency,'dates':[r.check_in,r.check_out], 'root_id':root.payment_order_root_id,'intent_id':root.payment_intent_id,'movements':[{'id':x.money_movement_id,'kind':x.movement_type,'amount_minor':x.amount_minor,'currency':x.currency,'parent':x.parent_movement_id,'state':x.state,'created_at':x.created_at} for x in moves],'ledger':[{'id':x.ledger_entry_id,'transaction':x.transaction_id,'direction':x.direction,'amount_minor':x.amount_minor,'currency':x.currency,'account':x.account_code,'created_at':x.created_at} for x in ledger]}

def captured(http,h,key='capture',overnight=False):
    rid,aid=purchase(http,h,key)
    h['clock']['at']=window(h['day'].isoformat())[0]+timedelta(hours=14)
    sid=arrive_and_register(http,h,rid,'C13-SYNTHETIC-101')
    prior=None
    if overnight:
        h['clock']['at']=window(h['day'].isoformat())[1]
        prior=close_day(http,h,h['day'].isoformat())
        assert prior['daily_close_id']
        h['clock']['at']+=timedelta(hours=11)
    else:h['clock']['at']+=timedelta(hours=4)
    proof={'hotel_fulfillment_evidence':'isolated://c13-folio','guest_checkout_reference':'isolated://c13-checkout','fulfilled_amount_minor':69800}
    post(http,f'/internal/v1/stays/{sid}/check-out',h['maker_headers'],proof)
    post(http,f'/internal/v1/stays/{sid}/settlement-eligibility',h['maker_headers'])
    post(http,f'/internal/v1/alipay/authorizations/{aid}/fulfill',h['maker_headers'],proof)
    first=post(http,f'/internal/v1/alipay/authorizations/{aid}/capture',h['maker_headers'],{'mode':'CONTRACT_DRY_RUN'})
    assert post(http,f'/internal/v1/alipay/authorizations/{aid}/capture',h['maker_headers'],{'mode':'CONTRACT_DRY_RUN'})==first
    return rid,aid,sid,prior

def blocked(result,prefix):
    assert result['daily_close_id'] is None,result
    assert any(x.startswith(prefix) for x in result['exception_summary_json']['blockers']),result

def test_independent_normal_overnight_funds_inventory_replay(http,business):
    h=business;rid,aid,sid,prior=captured(http,h,'normal-overnight',True)
    assert close_day(http,h,h['day'].isoformat())==prior
    h['clock']['at']=window(h['end'].isoformat())[1]
    final=close_day(http,h,h['end'].isoformat())
    c=final['exception_summary_json']['currencies']['CNY']
    assert (c['opening_held_minor'],c['capture_minor'],c['closing_held_minor'],c['net_capture_minor'],c['difference_minor'])==(69800,69800,0,69800,0)
    assert prior['inventory_snapshot_json']['available']==249 and final['inventory_snapshot_json']['available']==250
    record('normal-overnight',{'scope':'REAL_JWT_HTTP_'+engine.dialect.name.upper()+'_SYNTHETIC_ROOM_AND_MONEY','prior_day':prior,'checkout_day':final,'money':graph(rid),'prior_replay_equal':True})

def test_independent_short_stay_refund_and_free_cancel(http,business):
    h=business
    cancel,_=purchase(http,h,'cancel')
    q=post(http,f'/v1/direct/reservations/{cancel}/fare/cancellation-quote',h['customer_headers']);assert q['fee_minor']==0
    post(http,f'/v1/direct/reservations/{cancel}/fare/cancel',h['customer_headers'],{'quote_id':q['quote_id'],'expected_fee_minor':0,'currency':'CNY'})
    rid,aid,sid,_=captured(http,h,'short-stay')
    case=post(http,f'/internal/v1/post-stay/stays/{sid}/cases',h['maker_headers'],{'opened_by_party':'GUEST','dispute_type':'SERVICE','assigned_to':'c13-synthetic','initial_evidence_reference':'isolated://c13-service'})['dispute_case_id']
    d=post(http,f'/internal/v1/post-stay/cases/{case}/decisions',h['maker_headers'],{'outcome':'PARTIAL_REFUND','refund_amount_minor':9800})['post_stay_decision_id']
    post(http,f'/internal/v1/post-stay/decisions/{d}/approve',h['checker_headers'],{'evidence_reference':'isolated://c13-review'})
    e=post(http,f'/internal/v1/post-stay/decisions/{d}/refund-eligibility',h['checker_headers'])['refund_eligibility_id']
    blocked(close_day(http,h,h['day'].isoformat()),'PENDING_REFUND:')
    first=post(http,f'/internal/v1/post-stay/refund-eligibilities/{e}/execute',h['checker_headers'])
    assert post(http,f'/internal/v1/post-stay/refund-eligibilities/{e}/execute',h['checker_headers'])==first
    post(http,f'/internal/v1/post-stay/cases/{case}/reconcile',h['checker_headers'])
    post(http,f'/internal/v1/post-stay/cases/{case}/close',h['checker_headers'],{'closure_evidence_reference':'isolated://c13-close'})
    h['clock']['at']=window(h['day'].isoformat())[1]
    final=close_day(http,h,h['day'].isoformat());c=final['exception_summary_json']['currencies']['CNY']
    assert (c['authorization_minor'],c['capture_minor'],c['release_minor'],c['refund_minor'],c['net_capture_minor'],c['closing_held_minor'])==(139600,69800,69800,9800,60000,0)
    assert final['inventory_snapshot_json']['available']==249
    record('same-day-short-stay',{'scope':'EARLY_CHECKOUT_FULL_BOOKED_CHARGE_WITH_SEPARATE_APPROVED_SERVICE_REFUND','close':final,'fulfilled':graph(rid),'cancelled':graph(cancel),'capture_refund_replay_equal':True})

def test_confirmed_six_prices_share_only_two_of_five_physical_pools(http,business):
    h=business
    items=post(http,f"/v1/direct/{h['slug']}/availability",{},h['body'])['items']
    with SessionLocal() as s:
        pools=list(s.scalars(select(m.HostedDirectInventoryPoolRow).where(m.HostedDirectInventoryPoolRow.hosted_hotel_id==h['hotel'])))
        rates=list(s.scalars(select(m.HostedDirectRateVariantRow)))
        offers={x.hosted_offer_id:x for x in s.scalars(select(m.HostedDirectRoomOfferRow))}
        mapping=[{'pool':x.inventory_pool_id,'price':offers[x.hosted_offer_id].price_minor,'breakfast':x.breakfast_count} for x in rates]
        assert len(pools)==5 and all(x.capacity_total==50 for x in pools)
        assert len(rates)==6 and len({x['pool'] for x in mapping})==2
        for pool in {x['pool'] for x in mapping}:assert sorted(x['price'] for x in mapping if x['pool']==pool)==[69800,79800,89800]
        assert len(items)==6 and all(x['bookable'] for x in items)
        record('confirmed-rates-pools',{'pools':[{'id':x.inventory_pool_id,'key':x.physical_room_key,'capacity':x.capacity_total} for x in pools],'rates':mapping,'closed_unpriced_pool_ids':sorted({x.inventory_pool_id for x in pools}-{x['pool'] for x in mapping}),'available_offers':len(items),'real_hotel_authority':'NOT_ESTABLISHED_BY_SYNTHETIC_FIXTURE'})

def test_preview_and_unprovable_historical_first_close(http,business):
    h=business;rid,_=purchase(http,h,'preview')
    first=close_day(http,h,h['day'].isoformat());assert first['daily_close_id'] is None and first['exception_summary_json']['state']=='PREVIEW_OPEN_BUSINESS_DAY'
    h['clock']['at']=window(h['day'].isoformat())[1]+timedelta(hours=1)
    with SessionLocal.begin() as s:s.get(m.HostedDirectReservationRow,rid).updated_at=h['clock']['at']
    result=close_day(http,h,h['day'].isoformat());blocked(result,'HOLD_HISTORICAL_STATE_UNPROVABLE:');record('historical-hold',result)

@pytest.mark.parametrize('fault',['missing_root','missing_authorization','wrong_binding','missing_calendar'])
def test_missing_sources_block(http,business,fault):
    h=business;rid,aid=purchase(http,h,fault)
    with SessionLocal.begin() as s:
        root=s.scalar(select(m.PaymentOrderRootRow).where(m.PaymentOrderRootRow.business_id==aid))
        if fault=='missing_root':s.delete(root);prefix='MISSING_CANONICAL_MONEY_ROOT:'
        elif fault=='missing_authorization':
            for x in s.scalars(select(m.OmnichannelMoneyMovementRow).where(m.OmnichannelMoneyMovementRow.root_payment_intent_id==root.payment_intent_id)):s.delete(x)
            prefix='MISSING_AUTHORIZATION_MOVEMENT:'
        elif fault=='wrong_binding':s.scalar(select(m.PaymentOrderFactBindingRow).where(m.PaymentOrderFactBindingRow.payment_intent_id==root.payment_intent_id)).amount_minor+=1;prefix='MONEY_ORDER_BINDING_DIFFERENCE:'
        else:s.delete(s.scalar(select(m.HostedInventoryDayRow).where(m.HostedInventoryDayRow.inventory_pool_id!=h['pool'],m.HostedInventoryDayRow.stay_date==h['day'].isoformat())));prefix='MISSING_INVENTORY_DAY:'
    result=close_day(http,h,h['day'].isoformat());blocked(result,prefix);record('missing-'+fault,result)

def test_parent_budget_cannot_be_offset_by_other_root(http,business):
    h=business;purchase(http,h,'other-held');rid,_,_,_=captured(http,h)
    g=graph(rid);mid=next(x['id'] for x in g['movements'] if x['kind']=='CAPTURE')
    with SessionLocal.begin() as s:
        s.get(m.OmnichannelMoneyMovementRow,mid).amount_minor+=1
        for x in s.scalars(select(m.OmnichannelLedgerEntryRow).where(m.OmnichannelLedgerEntryRow.transaction_id==mid)):x.amount_minor+=1
    result=close_day(http,h,h['day'].isoformat());blocked(result,'PARENT_MONEY_BUDGET_DIFFERENCE:');record('parent-budget',result)

def test_economic_date_uses_movement_across_midnight(http,business):
    h=business;rid,_,_,_=captured(http,h);g=graph(rid);mid=next(x['id'] for x in g['movements'] if x['kind']=='CAPTURE');end=window(h['day'].isoformat())[1]
    with SessionLocal.begin() as s:
        s.get(m.OmnichannelMoneyMovementRow,mid).created_at=end-timedelta(microseconds=1)
        for x in s.scalars(select(m.OmnichannelLedgerEntryRow).where(m.OmnichannelLedgerEntryRow.transaction_id==mid)):x.created_at=end+timedelta(microseconds=1)
    h['clock']['at']=end
    result=close_day(http,h,h['day'].isoformat());assert result['daily_close_id'] and not result['exception_summary_json']['blockers'];assert result['exception_summary_json']['currencies']['CNY']['capture_minor']==69800
    record('economic-midnight',result)

def test_authorization_amount_must_match_immutable_intent(http,business):
    h=business;rid,_=purchase(http,h,'authorization-amount')
    with SessionLocal.begin() as s:s.scalar(select(m.OmnichannelMoneyMovementRow).where(m.OmnichannelMoneyMovementRow.movement_type=='AUTHORIZATION')).amount_minor+=1
    h['clock']['at']=window(h['day'].isoformat())[1]
    result=close_day(http,h,h['day'].isoformat());record('authorization-amount-mismatch',{'actual':result,'money':graph(rid),'expected':'BLOCKED_NO_FINAL_CLOSE'})
    assert result['daily_close_id'] is None and result['exception_summary_json']['blockers'],result

@pytest.mark.parametrize('field',['amount_minor','currency','check_out'])
def test_archived_order_source_tamper_rejected(http,business,field):
    h=business;rid,_=purchase(http,h,'archived-'+field);h['clock']['at']=window(h['day'].isoformat())[1]
    first=close_day(http,h,h['day'].isoformat());assert first['daily_close_id']
    with SessionLocal.begin() as s:
        r=s.get(m.HostedDirectReservationRow,rid)
        setattr(r,field,r.amount_minor+1 if field=='amount_minor' else 'USD' if field=='currency' else (h['end']+timedelta(days=1)).isoformat())
    response=http.post(f"/internal/v1/hosted-direct/hotels/{h['hotel']}/daily-closes",headers=h['manager_headers'],json={'business_date':h['day'].isoformat()})
    record('archived-order-'+field,{'status':response.status_code,'response':response.json(),'expected_status':409,'money':graph(rid)})
    assert response.status_code==409,response.text

def test_captured_arrival_voucher_truthful(http,business):
    h=business;rid,_,_,_=captured(http,h)
    response=http.get(f'/internal/v1/hosted-direct/reservations/{rid}/arrival-voucher',headers=h['manager_headers']);assert response.status_code==200,response.text
    data=response.json()['data'];record('captured-arrival-voucher',{'voucher':data,'money':graph(rid)})
    assert data['payment_captured'] is True,data

def test_close_denies_readonly_and_cross_hotel_principals(http,business):
    h=business
    for roles in [['GO_READ_ONLY'],['GO_ORDER_OPS']]:
        _,headers=identity('c13-denied-'+roles[0],roles)
        r=http.post(f"/internal/v1/hosted-direct/hotels/{h['hotel']}/daily-closes",headers=headers,json={'business_date':h['day'].isoformat()})
        assert r.status_code==403,r.text
    with SessionLocal() as s:assert s.query(m.HostedDailyCloseRow).count()==0

@pytest.mark.parametrize('fault',['currency','account','orphan'])
def test_ledger_shape_corruption_never_closes(http,business,fault):
    h=business;rid,_,_,_=captured(http,h)
    with SessionLocal.begin() as s:
        entry=s.scalar(select(m.OmnichannelLedgerEntryRow))
        if fault=='currency':entry.currency='USD';prefix='MOVEMENT_LEDGER_DIFFERENCE:'
        elif fault=='account':entry.account_code='UNRELATED_ACCOUNT';prefix='LEDGER_ACCOUNT_DIFFERENCE:'
        else:entry.transaction_id='c13-missing-movement';prefix='ORPHAN_LEDGER:'
    result=close_day(http,h,h['day'].isoformat());blocked(result,prefix);record('ledger-'+fault,result)

def test_archive_payload_hash_is_rechecked(http,business):
    h=business;purchase(http,h,'archive-payload');h['clock']['at']=window(h['day'].isoformat())[1]
    first=close_day(http,h,h['day'].isoformat());assert first['daily_close_id']
    with SessionLocal.begin() as s:
        row=s.get(m.HostedDailyCloseRow,first['daily_close_id']);row.inventory_snapshot_json={**row.inventory_snapshot_json,'available':250}
    r=http.post(f"/internal/v1/hosted-direct/hotels/{h['hotel']}/daily-closes",headers=h['manager_headers'],json={'business_date':h['day'].isoformat()})
    assert r.status_code==409,r.text;record('archive-payload-tamper',{'status':r.status_code,'response':r.json()})
