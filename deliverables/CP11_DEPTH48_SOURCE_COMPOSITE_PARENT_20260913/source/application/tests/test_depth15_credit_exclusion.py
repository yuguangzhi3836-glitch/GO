from copy import deepcopy
from datetime import datetime,timedelta
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select,func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (CatalogCreditSourceRow as Source,CatalogCreditContractRow as Contract,
    CatalogCashFareOperationRow as Operation,OmnichannelMoneyMovementRow as Movement,
    CatalogCreditQuoteRow as Quote,StayCreditRow as Credit)
from go_hotel.services import catalog_stay_credit as svc,catalog_credit_value as value,catalog_credit_after_sales as after
from go_hotel.services import catalog_supplier_remedy as remedy
from go_hotel.services.omnichannel_payment import digest
from go_hotel.services.hosted_money import money
from test_depth14_cash_fare import booked_order,change_quote,execute,run,moves,day
from test_depth12_catalog_credit import redeem
from test_depth11_catalog_supplier_remedy import approved,configure

def changed(client,delta=-43200):
    oid=booked_order(client);result=execute(oid,change_quote(oid,delta))
    assert result['state']=='COMPLETED'
    return oid,result
def convert(client,delta=-43200):
    oid,change=changed(client,delta);q=svc.conversion_quote(oid)
    c=run(svc.convert(oid,q['quote_id'],q['quote_hash'],True,'owner'))
    return oid,c['stay_credit_id'],q,change

def test_low_cash_change_converts_only_retained_value_and_preserves_real_refund_facts(client):
    oid,cid,q,change=convert(client)
    assert q['credit_value_minor']==1400000
    proof=q['cash_change_forfeiture']
    assert (proof['gross_paid_minor'],proof['prior_refund_minor'],proof['excluded_minor'],proof['retained_minor'])==(1443200,0,43200,1400000)
    assert proof['accepted_changes'][0]['operation_id']==change['operation_id']
    with SessionLocal() as s:
        c,p=value.checked(s,cid)
        sources=s.scalars(select(Source).where(Source.credit_id==cid)).all()
        assert sum(x.funded_minor for x in sources)==1400000
        assert sum(x.excluded_minor for x in sources)==43200
        assert sum(x.prior_refund_minor for x in sources)==0
        assert len(sources)==1 and sources[0].excluded_minor==43200
        for source in sources:
            cap=s.get(Movement,source.capture_id)
            assert cap.amount_minor==source.funded_minor+source.prior_refund_minor+source.excluded_minor
    assert not moves(oid,'REFUND')

def test_original_full_source_credit_has_no_fabricated_zero_forfeiture_breakdown(client):
    from test_depth12_catalog_credit import convert as original_convert
    _,cid,_=original_convert(client)
    current=svc.get_credit(cid)
    assert current['cash_change_forfeiture'] is None
    with SessionLocal() as s:
        _,p=value.checked(s,cid)
        assert 'cash_change_forfeiture' not in p.contract_json
        assert all('excluded_minor' not in x for x in p.contract_json['sources'])

def test_high_redemption_then_customer_cancel_restores_only_retained_credit(client):
    oid,cid,q,_=convert(client);expiry=svc.get_credit(cid)['expires_at']
    rq,r=redeem(cid,156800)
    assert rq['applied_minor']==1400000 and rq['amount_due_minor']==200000
    cancel=after.cancellation_quote(r['order_id'])
    done=run(after.cancel(r['order_id'],cancel['quote_id'],cancel['quote_hash'],True,'owner'))
    assert done['restored_credit_minor']==1400000 and done['cash_refund_minor']==200000
    assert svc.get_credit(cid)['available_minor']==1400000 and svc.get_credit(cid)['expires_at']==expiry
    assert not moves(oid,'REFUND')
    with SessionLocal() as s:value.checked(s,cid)

def test_cash_and_redemption_forfeitures_are_separate_and_neither_is_restored(client):
    oid,cid,q,_=convert(client)
    rq,r=redeem(cid,-143200)
    assert rq['new_value_minor']==1300000 and rq['forfeited_difference_minor']==100000
    cancel=after.cancellation_quote(r['order_id'])
    done=run(after.cancel(r['order_id'],cancel['quote_id'],cancel['quote_hash'],True,'owner'))
    assert done['restored_credit_minor']==1300000 and svc.get_credit(cid)['available_minor']==1300000
    with SessionLocal() as s:
        value.checked(s,cid)
        assert sum(x.excluded_minor for x in s.scalars(select(Source).where(Source.credit_id==cid)))==43200

def test_supplier_fault_refunds_and_compensates_applied_value_without_original_exclusion(client):
    oid,cid,_,_=convert(client);_,r=redeem(cid,156800)
    case=approved(r['order_id']);configure('sup_mock',1600000)
    assert case['actual_paid_minor']==case['refund_due_minor']==case['compensation_due_minor']==1600000
    done=run(remedy.execute(case['case_id'],case['decision_hash']))
    assert done['state']=='COMPLETED'
    assert sum(x.amount_minor for x in moves(oid,'REFUND'))==1400000
    with SessionLocal() as s:
        value.checked(s,cid)
        for source in s.scalars(select(Source).where(Source.credit_id==cid)):
            refunds=s.scalars(select(Movement).where(Movement.parent_movement_id==source.capture_id,Movement.movement_type=='REFUND')).all()
            assert sum(x.amount_minor for x in refunds)<=source.funded_minor

def test_zero_funded_capture_stays_reserved_from_generic_refund(client):
    oid=booked_order(client)
    execute(oid,change_quote(oid,80000,50))
    execute(oid,change_quote(oid,-43200,60))
    q=svc.conversion_quote(oid)
    cid=run(svc.convert(oid,q['quote_id'],q['quote_hash'],True,'owner'))['stay_credit_id']
    with SessionLocal() as s:
        source=s.scalar(select(Source).where(Source.credit_id==cid,Source.funded_minor==0))
        assert source and source.excluded_minor>0
    with pytest.raises(ValueError,match='CREDIT_SOURCE_FUNDS_RESERVED'):
        money.create(source.payment_intent_id,{'movement_type':'REFUND','parent_movement_id':source.capture_id,'amount_minor':1,
            'mode':'CONTRACT_SIMULATOR','evidence':['simulation://excluded-bypass']},'excluded-bypass','owner')

@pytest.mark.parametrize('field',['funded_minor','prior_refund_minor','excluded_minor'])
def test_source_amount_tampering_is_detected_without_restoring_any_value(client,field):
    _,cid,_,_=convert(client)
    with SessionLocal.begin() as s:
        source=s.scalar(select(Source).where(Source.credit_id==cid));setattr(source,field,getattr(source,field)+1)
    with SessionLocal() as s:
        with pytest.raises(ValueError,match='MISMATCH'):value.checked(s,cid)

def test_removed_origin_operation_is_not_replaced_by_inferred_forfeiture(client):
    oid,change=changed(client)
    with SessionLocal.begin() as s:s.delete(s.get(Operation,change['operation_id']))
    with pytest.raises(ValueError,match='HISTORICAL_FORFEITURE'):svc.conversion_quote(oid)

def test_changed_origin_plan_is_detected_on_later_credit_read(client):
    _,cid,_,change=convert(client)
    with SessionLocal.begin() as s:
        op=s.get(Operation,change['operation_id']);b=deepcopy(op.plan_json);b['quote']['lower_price_difference_minor']=0;op.plan_json=b
    with SessionLocal() as s:
        with pytest.raises(ValueError,match='INTEGRITY'):value.checked(s,cid)

def test_prior_actual_refund_is_not_confused_with_excluded_change_value(client):
    oid,_=changed(client)
    cap=moves(oid,'CAPTURE')[0]
    money.create(cap.root_payment_intent_id,{'movement_type':'REFUND','parent_movement_id':cap.money_movement_id,'amount_minor':10000,
        'mode':'CONTRACT_SIMULATOR','evidence':['simulation://actual-prior-refund']},'actual-prior-refund','owner')
    q=svc.conversion_quote(oid)
    assert q['credit_value_minor']==1390000
    assert sum(x['prior_refund_minor'] for x in q['sources'])==10000
    assert sum(x['excluded_minor'] for x in q['sources'])==43200
    c=run(svc.convert(oid,q['quote_id'],q['quote_hash'],True,'owner'))
    with SessionLocal() as s:value.checked(s,c['stay_credit_id'])

def test_four_conversion_requests_share_one_split_contract_and_one_supplier_cancel(client):
    oid,_=changed(client);q=svc.conversion_quote(oid)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:run(svc.convert(oid,q['quote_id'],q['quote_hash'],True,'owner')),range(4)))
    assert len({r['stay_credit_id'] for r in results})==1
    from go_hotel.connectors.mock_hotel import connector
    assert connector.cancel_calls==1
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(Contract))==1
        value.checked(s,results[0]['stay_credit_id'])

def test_split_source_reservation_failure_rolls_back_before_supplier_cancel(client,monkeypatch):
    oid,_=changed(client);q=svc.conversion_quote(oid)
    original=value.journal
    def fail(s,c,p,kind,*args):
        if kind=='SOURCE_FUNDS_RESERVED':raise RuntimeError('split source reservation interrupted')
        return original(s,c,p,kind,*args)
    with monkeypatch.context() as m:
        m.setattr(value,'journal',fail)
        with pytest.raises(RuntimeError,match='reservation interrupted'):run(svc.convert(oid,q['quote_id'],q['quote_hash'],True,'owner'))
    with SessionLocal() as s:
        assert not s.scalars(select(Source)).all() and not s.scalars(select(Credit)).all()
    from go_hotel.connectors.mock_hotel import connector
    assert connector.cancel_calls==0
    assert run(svc.convert(oid,q['quote_id'],q['quote_hash'],True,'owner'))['available_minor']==1400000

def test_unknown_conversion_recovery_keeps_original_exclusion_and_does_not_recancel(client,monkeypatch):
    from go_hotel.connectors.mock_hotel import connector
    oid,_=changed(client);q=svc.conversion_quote(oid);original=connector.cancel
    async def lost(confirmation):await original(confirmation);raise TimeoutError('conversion reply lost')
    monkeypatch.setattr(connector,'cancel',lost)
    pending=run(svc.convert(oid,q['quote_id'],q['quote_hash'],True,'owner'))
    assert pending['status']=='UNKNOWN_CANCEL'
    recovered=run(svc.reconcile_conversion(pending['stay_credit_id'],'owner'))
    assert recovered['available_minor']==1400000 and connector.cancel_calls==1
    assert recovered['cash_change_forfeiture']['excluded_minor']==43200

def test_late_customer_cancellation_recovery_cannot_extend_split_credit_or_restore_exclusion(client,monkeypatch):
    from go_hotel.services import catalog_fare_snapshot as fare
    from go_hotel.connectors.mock_hotel import connector
    original_rules=fare.demo_rules
    monkeypatch.setattr(fare,'demo_rules',lambda:{**original_rules(),'stay_credit_days':1})
    _,cid,_,_=convert(client)
    expires=svc.get_credit(cid)['expires_at'];_,r=redeem(cid,days=1)
    q=after.cancellation_quote(r['order_id']);original=connector.cancel
    async def lost(confirmation):await original(confirmation);raise TimeoutError('late cancellation')
    monkeypatch.setattr(connector,'cancel',lost)
    assert run(after.cancel(r['order_id'],q['quote_id'],q['quote_hash'],True,'owner'))['state']=='UNKNOWN_CANCEL'
    clock=datetime.fromisoformat(expires)+timedelta(seconds=1)
    monkeypatch.setattr(value,'now',lambda:clock);monkeypatch.setattr(after,'now',lambda:clock)
    done=run(after.reconcile(r['order_id'],'owner'))
    assert done['available_credit_minor']==0 and svc.get_credit(cid)['expires_at']==expires
    with SessionLocal() as s:
        value.checked(s,cid)
        assert sum(x.excluded_minor for x in s.scalars(select(Source).where(Source.credit_id==cid)))==43200
