"""Independent positive currency and daily economic scope, real HTTP/SQL fixtures."""
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import tempfile
from sqlalchemy import select
from tests.test_c01_aoluguya_business_day import http,business,post,close_day,window
from tests.hosted_review_support import hotel_fixture,prepare_publication,register_isolated_rooms,RULES
from go_hotel.db import models as m
from go_hotel.db.session import SessionLocal,engine
from go_hotel.services.hosted_direct_booking import ident,now,out
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service as booking
from go_hotel.services import hosted_fare_rules as fare


def add_usd_offer(http,h,tmp_path):
    offer=post(http,f"/internal/v1/hosted-direct/hotels/{h['hotel']}/offers",h['maker_headers'],
        {'room_name':'Synthetic USD same physical pool','rate_name':'ISOLATED USD',
         'price_minor':12900,'currency':'USD','inventory':50,'cancellation_policy':'ISOLATED ONLY'})['hosted_offer_id']
    with SessionLocal.begin() as s:
        s.add(m.HostedDirectRateVariantRow(rate_variant_id=ident('usd-rate'),inventory_pool_id=h['pool'],
            hosted_offer_id=offer,breakfast_count=0,benefits_json=[],payment_mode='CONTRACT_SIMULATOR',state='ACTIVE'))
        rules=deepcopy(s.scalar(select(m.HostedFareRuleVersionRow).where(
            m.HostedFareRuleVersionRow.hosted_offer_id==h['offer']).order_by(m.HostedFareRuleVersionRow.version.desc())).rules_json)
    fare.publish(offer,rules,'isolated://usd-contract-rule',h['maker'].user_id)
    prepare_publication(h['hotel'],h['maker'],h['checker'],tmp_path,add_rules=False)
    booking.publish(h['hotel'],h['maker'])
    return offer


def calendar(http,h,start,end):
    post(http,f"/internal/v1/hosted-direct/hotels/{h['hotel']}/calendar/bootstrap",h['maker_headers'],
        {'start_date':start.isoformat(),'end_date':end.isoformat()})


def quote(http,h,offer,day):
    body={**h['body'],'hosted_offer_id':offer,'check_in':day.isoformat(),'check_out':(day+timedelta(days=1)).isoformat()}
    result=post(http,f"/v1/direct/{h['slug']}/availability",{},body)
    item=next(x for x in result['items'] if x['hosted_offer_id']==offer)
    assert item['bookable'],item
    return result,item,{**body,'expected_fare_rule_hash':item['fare_rule']['rule_hash']}


def complete(http,h,clock,offer,day,key,room,internal_history_fixture=False):
    if internal_history_fixture:
        # Historical/internal-domain fixture, NOT a customer booking/checkout.
        # Seed dated USD obligation before the first immutable money fact, then
        # use actual isolated money services to create binding/authorization.
        with SessionLocal.begin() as s:
            item=s.get(m.HostedDirectRoomOfferRow,offer)
            variant=s.scalar(select(m.HostedDirectRateVariantRow).where(m.HostedDirectRateVariantRow.hosted_offer_id==offer))
            inv=s.scalar(select(m.HostedInventoryDayRow).where(m.HostedInventoryDayRow.inventory_pool_id==variant.inventory_pool_id,m.HostedInventoryDayRow.stay_date==day.isoformat()))
            assert item.currency in {'CNY','USD'} and inv.capacity_available>0
            inv.capacity_available-=1;inv.updated_at=clock['at']
            row=m.HostedDirectReservationRow(hosted_reservation_id=ident('historical-usd'),hosted_offer_id=offer,
                idempotency_key=key,guest_name='ISOLATED INTERNAL HISTORY',guest_contact='not-a-real-person',
                check_in=day.isoformat(),check_out=(day+timedelta(days=1)).isoformat(),
                amount_minor=item.price_minor,currency=item.currency,reservation_state='PENDING_HOTEL_CONFIRMATION',
                payment_state='ALIPAY_APPLICATION_PENDING_NO_CHARGE',created_at=clock['at'],updated_at=clock['at'])
            s.add(row);s.flush()
            s.add(m.HostedReservationStayRow(hosted_reservation_id=row.hosted_reservation_id,source='INTERNAL_FIXTURE',
                adults=1,children=0,extra_beds=0,operational_state='PENDING_HOTEL_CONFIRMATION',
                confirmation_expires_at=clock['at']+timedelta(minutes=30),created_by=h['customer'].user_id,updated_at=clock['at']))
            s.add(m.HostedReservationNightRow(reservation_night_id=ident('historical-night'),
                hosted_reservation_id=row.hosted_reservation_id,inventory_day_id=inv.inventory_day_id,
                stay_date=day.isoformat(),price_minor=row.amount_minor,state='HELD'))
            fare.snapshot_in_session(s,row);r=out(row)
            s.flush()
            a=m.AlipayAuthorizationRow(authorization_id=ident('history-auth'),hosted_reservation_id=row.hosted_reservation_id,
                amount_minor=row.amount_minor,currency=row.currency,state='CONTRACT_FROZEN_NOT_ALIPAY',
                external_invoked=False,external_authorization_reference=None,settlement_eligible=False,
                idempotency_key='history-auth:'+key,updated_at=clock['at'])
            s.add(a);s.flush()
            from go_hotel.services.hosted_money import ensure_authorization
            ensure_authorization(s,row,s.get(m.HostedReservationStayRow,row.hosted_reservation_id),a)
            checkout={'authorization':out(a)}
    else:
        _,item,body=quote(http,h,offer,day)
        r=post(http,f"/v1/direct/{h['slug']}/reservations",h['customer_headers'],body,key)
        assert (r['amount_minor'],r['currency'])==(item['total_amount_minor'],item['currency'])
        checkout=post(http,f"/v1/direct/reservations/{r['hosted_reservation_id']}/checkout",h['customer_headers'],
            {'expected_amount_minor':r['amount_minor'],'currency':r['currency'],'mode':'CONTRACT_SIMULATOR'})
    rid=r['hosted_reservation_id']
    aid=checkout['authorization']['authorization_id']
    post(http,f'/internal/v1/hosted-direct/reservations/{rid}/decision',h['maker_headers'],{'decision':'CONFIRM'})
    clock['at']=max(clock['at'],window(day.isoformat())[0]+timedelta(hours=14))
    sid=post(http,f'/internal/v1/stays/reservations/{rid}',h['maker_headers'])['stay_lifecycle_id']
    base=f'/internal/v1/stays/{sid}'
    post(http,base+'/arrive',h['maker_headers'])
    post(http,base+'/identity-evidence',h['maker_headers'],{'identity_evidence_hash':'e'*64,'verification_method':'HOTEL_DESK_DOCUMENT_CHECK'})
    post(http,base+'/room-assignment',h['maker_headers'],{'room_reference':room})
    post(http,base+'/check-in',h['maker_headers'],{'registration_evidence_reference':'isolated://currency-day-registration'})
    clock['at']+=timedelta(hours=1)
    proof={'hotel_fulfillment_evidence':'isolated://currency-day-folio','guest_checkout_reference':'isolated://currency-day-checkout','fulfilled_amount_minor':r['amount_minor']}
    post(http,base+'/check-out',h['maker_headers'],proof)
    post(http,f'/internal/v1/alipay/authorizations/{aid}/fulfill',h['maker_headers'],proof)
    first=post(http,f'/internal/v1/alipay/authorizations/{aid}/capture',h['maker_headers'],{'mode':'CONTRACT_DRY_RUN'})
    assert post(http,f'/internal/v1/alipay/authorizations/{aid}/capture',h['maker_headers'],{'mode':'CONTRACT_DRY_RUN'})==first
    with SessionLocal() as s:
        root=s.scalar(select(m.PaymentOrderRootRow).where(m.PaymentOrderRootRow.business_id==aid))
        moves=list(s.scalars(select(m.OmnichannelMoneyMovementRow).where(m.OmnichannelMoneyMovementRow.root_payment_intent_id==root.payment_intent_id)))
        ledger=list(s.scalars(select(m.OmnichannelLedgerEntryRow).where(m.OmnichannelLedgerEntryRow.payment_intent_id==root.payment_intent_id)))
        assert len(ledger)==2 and {x.direction for x in ledger}=={'DEBIT','CREDIT'}
        assert all((x.amount_minor,x.currency)==(r['amount_minor'],r['currency']) for x in ledger)
        assert sorted((x.movement_type,x.amount_minor,x.currency) for x in moves)==[
            ('AUTHORIZATION',r['amount_minor'],r['currency']),('CAPTURE',r['amount_minor'],r['currency'])]
        return {'reservation_id':rid,'amount_minor':r['amount_minor'],'currency':r['currency'],
                'movement_ids':[x.money_movement_id for x in moves],'ledger_ids':[x.ledger_entry_id for x in ledger]}


def test_availability_truthful_currency_and_unsupported_sale_is_zero_write(http,business,tmp_path):
    import pytest
    h=business;usd=add_usd_offer(http,h,tmp_path)
    calendar(http,h,h['day'],h['end'])
    body={**h['body'],'hosted_offer_id':usd}
    response=post(http,f"/v1/direct/{h['slug']}/availability",{},body)
    item=next(x for x in response['items'] if x['hosted_offer_id']==usd)
    assert {x['currency'] for x in response['items']}=={'CNY','USD'}
    assert response['currency'] is None
    assert response['currencies']==['CNY','USD']
    assert not item['bookable'] and 'HOSTED_CHECKOUT_CURRENCY_UNSUPPORTED' in item['unavailable_reasons']
    body['expected_fare_rule_hash']=item['fare_rule']['rule_hash']
    def counts():
        with SessionLocal() as s:
            return (s.query(m.HostedDirectReservationRow).count(),s.query(m.HostedReservationNightRow).count(),
                s.query(m.HostedReservationNotificationRow).count(),s.query(m.HostedDirectReservationEventRow).count(),
                [(r.inventory_day_id,r.capacity_available) for r in s.scalars(select(m.HostedInventoryDayRow).order_by(m.HostedInventoryDayRow.inventory_day_id))])
    before=counts()
    for suffix in ['reservations','managed-reservations']:
        rejected=http.post(f"/v1/direct/{h['slug']}/{suffix}",headers={**h['customer_headers'],'Idempotency-Key':'unsupported-'+suffix},json=body)
        assert rejected.status_code==409 and rejected.json()['detail']=='HOSTED_CHECKOUT_CURRENCY_UNSUPPORTED',rejected.text
        assert counts()==before
    from tests.hosted_review_support import identity
    from go_hotel.services.hosted_frontdesk_uat import hosted_frontdesk_uat_service as desk
    staff,phone_headers=identity('currency-reservations',['GO_ORDER_OPS'])
    desk.assign_role(h['hotel'],{'staff_id':staff.user_id,'role':'RESERVATIONS','evidence_reference':'isolated://currency-phone'},h['maker'])
    for suffix in ['phone-reservations','governed-phone-reservations']:
        rejected=http.post(f"/internal/v1/hosted-direct/{h['slug']}/{suffix}",headers={**phone_headers,'Idempotency-Key':'unsupported-'+suffix},json=body)
        assert rejected.status_code==409 and rejected.json()['detail']=='HOSTED_CHECKOUT_CURRENCY_UNSUPPORTED',rejected.text
        assert counts()==before
    with pytest.raises(ValueError,match='HOSTED_CHECKOUT_CURRENCY_UNSUPPORTED'):
        booking.reserve(h['slug'],body,'unsupported-legacy')
    assert counts()==before


def test_daily_close_separates_currency_foreign_hotel_and_old_order(http,business,monkeypatch,tmp_path):
    h=business;usd=add_usd_offer(http,h,tmp_path)
    current=h['day']+timedelta(days=2)
    calendar(http,h,h['day'],current+timedelta(days=1))
    # This old order is genuinely booked, authorized, checked in/out and captured
    # two business days earlier. Its opening balance remains economically real.
    old=complete(http,h,h['clock'],h['offer'],h['day'],'old-economic-order','ISOLATED-ROUND-DREAM-101')
    h['clock']['at']=window(current.isoformat())[0]+timedelta(hours=8)
    cny=complete(http,h,h['clock'],h['offer'],current,'current-cny','ISOLATED-ROUND-DREAM-101')
    usd_order=complete(http,h,h['clock'],usd,current,'current-usd','ISOLATED-OVERNIGHT-102',internal_history_fixture=True)
    # A separately scoped hotel receives an explicit internal historical source
    # fixture and actual contract capture; its consumer checkout is NOT enabled.
    foreign=hotel_fixture(monkeypatch,tmp_path/'foreign',ready=False)
    register_isolated_rooms(foreign['hotel'],foreign['offer'],['FOREIGN-101'])
    prepare_publication(foreign['hotel'],foreign['maker'],foreign['checker'],tmp_path/'foreign')
    booking.publish(foreign['hotel'],foreign['maker'])
    calendar(http,foreign,current,current+timedelta(days=1))
    foreign_order=complete(http,foreign,h['clock'],foreign['offer'],current,'foreign-money','FOREIGN-101',internal_history_fixture=True)
    h['clock']['at']=window(current.isoformat())[1]
    result=close_day(http,h,current.isoformat())
    assert result['daily_close_id'],result
    report=result['exception_summary_json']
    assert report['blockers']==[]
    assert report['payment_transactions']==2 and report['refund_transactions']==0
    assert {x['reservation_id'] for x in report['reservations']}=={cny['reservation_id'],usd_order['reservation_id']}
    assert sum(result['reservation_summary_json'].values())==2
    assert set(report['movement_ids'])==set(cny['movement_ids']+usd_order['movement_ids'])
    assert set(report['ledger_ids'])==set(cny['ledger_ids']+usd_order['ledger_ids'])
    assert not set(old['movement_ids']+foreign_order['movement_ids']).intersection(report['movement_ids'])
    assert set(report['currencies'])=={'CNY','USD'}
    for currency,order,opening in [('CNY',cny,old['amount_minor']),('USD',usd_order,0)]:
        totals=report['currencies'][currency]
        assert (totals['authorization_minor'],totals['capture_minor'],totals['debit_minor'],totals['credit_minor'])==(order['amount_minor'],)*4
        assert totals['refund_minor']==totals['release_minor']==totals['difference_minor']==0
        assert totals['opening_net_capture_minor']==opening
        assert totals['closing_net_capture_minor']==opening+order['amount_minor']
        assert totals['opening_held_minor']==totals['closing_held_minor']==0
    assert close_day(http,h,current.isoformat())==result
    directory=Path(os.getenv('GO_C13_ARTIFACT_DIR') or tempfile.mkdtemp(prefix='go-c13-currency-day-'))
    directory.mkdir(parents=True,exist_ok=True)
    (directory/'independent-multicurrency-hotel-day.json').write_text(json.dumps({
        'database':engine.dialect.name,'scope':'PILOT_CNY_HTTP_PLUS_INTERNAL_USD_AND_FOREIGN_HISTORY_FIXTURE_NO_PSP',
        'old_order':old,'current_cny':cny,'current_usd':usd_order,'other_hotel':foreign_order,
        'close':result},ensure_ascii=False,indent=2,default=str)+'\n')


def test_today_booking_for_future_stay_moves_only_future_inventory(http,business):
    h=business;future=h['day']+timedelta(days=1)
    calendar(http,h,h['day'],future+timedelta(days=1))
    _,item,body=quote(http,h,h['offer'],future)
    r=post(http,f"/v1/direct/{h['slug']}/reservations",h['customer_headers'],body,'future-stay-booked-today')
    rid=r['hosted_reservation_id']
    post(http,f'/v1/direct/reservations/{rid}/checkout',h['customer_headers'],
        {'expected_amount_minor':r['amount_minor'],'currency':'CNY','mode':'CONTRACT_SIMULATOR'})
    post(http,f'/internal/v1/hosted-direct/reservations/{rid}/decision',h['maker_headers'],{'decision':'CONFIRM'})
    h['clock']['at']=window(h['day'].isoformat())[1]
    result=close_day(http,h,h['day'].isoformat())
    assert result['daily_close_id'],result
    report=result['exception_summary_json'];totals=report['currencies']['CNY']
    assert report['blockers']==[]
    assert {x['reservation_id'] for x in report['reservations']}=={rid}
    assert sum(result['reservation_summary_json'].values())==1
    assert report['payment_transactions']==report['refund_transactions']==0
    assert totals['authorization_minor']==totals['closing_held_minor']==r['amount_minor']
    assert totals['opening_held_minor']==totals['capture_minor']==totals['net_capture_minor']==0
    assert totals['debit_minor']==totals['credit_minor']==0
    assert result['inventory_snapshot_json']['total']==result['inventory_snapshot_json']['available']==250
    with SessionLocal() as s:
        current=s.scalar(select(m.HostedInventoryDayRow).where(m.HostedInventoryDayRow.inventory_pool_id==h['pool'],m.HostedInventoryDayRow.stay_date==h['day'].isoformat()))
        upcoming=s.scalar(select(m.HostedInventoryDayRow).where(m.HostedInventoryDayRow.inventory_pool_id==h['pool'],m.HostedInventoryDayRow.stay_date==future.isoformat()))
        assert current.capacity_available==50 and upcoming.capacity_available==49
        nights=list(s.scalars(select(m.HostedReservationNightRow).where(m.HostedReservationNightRow.hosted_reservation_id==rid)))
        assert len(nights)==1 and nights[0].inventory_day_id==upcoming.inventory_day_id and nights[0].state=='HELD'


def test_prior_day_capture_refunded_today_keeps_prior_close_and_opening_balance(http,business):
    h=business
    captured=complete(http,h,h['clock'],h['offer'],h['day'],'prior-day-refund-source','ISOLATED-ROUND-DREAM-101')
    rid=captured['reservation_id']
    h['clock']['at']=window(h['day'].isoformat())[1]
    previous=close_day(http,h,h['day'].isoformat())
    assert previous['daily_close_id']
    assert previous['exception_summary_json']['currencies']['CNY']['closing_net_capture_minor']==captured['amount_minor']
    with SessionLocal() as s:
        sid=s.scalar(select(m.GuestStayLifecycleRow.stay_lifecycle_id).where(m.GuestStayLifecycleRow.hosted_reservation_id==rid))
    h['clock']['at']+=timedelta(hours=9)
    case=post(http,f'/internal/v1/post-stay/stays/{sid}/cases',h['maker_headers'],
        {'opened_by_party':'GUEST','dispute_type':'SERVICE','assigned_to':'isolated-next-day-owner',
         'initial_evidence_reference':'isolated://next-day-service-case'})['dispute_case_id']
    decision=post(http,f'/internal/v1/post-stay/cases/{case}/decisions',h['maker_headers'],
        {'outcome':'PARTIAL_REFUND','refund_amount_minor':9800})['post_stay_decision_id']
    post(http,f'/internal/v1/post-stay/decisions/{decision}/approve',h['checker_headers'],
        {'evidence_reference':'isolated://next-day-independent-decision'})
    eligibility=post(http,f'/internal/v1/post-stay/decisions/{decision}/refund-eligibility',h['checker_headers'])['refund_eligibility_id']
    path=f'/internal/v1/post-stay/refund-eligibilities/{eligibility}/execute'
    refund=post(http,path,h['checker_headers'])
    assert post(http,path,h['checker_headers'])==refund
    post(http,f'/internal/v1/post-stay/cases/{case}/reconcile',h['checker_headers'])
    post(http,f'/internal/v1/post-stay/cases/{case}/close',h['checker_headers'],{'closure_evidence_reference':'isolated://next-day-case-closed'})
    assert close_day(http,h,h['day'].isoformat())==previous
    current=h['day']+timedelta(days=1);h['clock']['at']=window(current.isoformat())[1]
    result=close_day(http,h,current.isoformat())
    assert result['daily_close_id'],result
    report=result['exception_summary_json'];cny=report['currencies']['CNY']
    assert report['blockers']==[]
    assert report['payment_transactions']==0 and report['refund_transactions']==1
    assert cny['opening_net_capture_minor']==captured['amount_minor']
    assert cny['closing_net_capture_minor']==captured['amount_minor']-9800
    assert cny['authorization_minor']==cny['capture_minor']==cny['release_minor']==0
    assert cny['refund_minor']==cny['debit_minor']==cny['credit_minor']==9800
    assert cny['difference_minor']==0 and cny['net_capture_minor']==-9800
    assert cny['opening_held_minor']==cny['closing_held_minor']==0
    with SessionLocal() as s:
        moves=list(s.scalars(select(m.OmnichannelMoneyMovementRow).where(m.OmnichannelMoneyMovementRow.money_movement_id.in_(report['movement_ids']))))
        assert len(moves)==1 and moves[0].movement_type=='REFUND'
        parent=s.get(m.OmnichannelMoneyMovementRow,moves[0].parent_movement_id)
        assert parent.money_movement_id in captured['movement_ids'] and parent.movement_type=='CAPTURE'
        entries=list(s.scalars(select(m.OmnichannelLedgerEntryRow).where(m.OmnichannelLedgerEntryRow.transaction_id==moves[0].money_movement_id)))
        assert len(entries)==2 and {e.direction for e in entries}=={'DEBIT','CREDIT'}
        assert all((e.amount_minor,e.currency)==(9800,'CNY') for e in entries)
    assert close_day(http,h,h['day'].isoformat())==previous
    directory=Path(os.getenv('GO_C13_ARTIFACT_DIR') or tempfile.mkdtemp(prefix='go-c13-next-day-refund-'))
    directory.mkdir(parents=True,exist_ok=True)
    (directory/'independent-prior-capture-next-day-refund.json').write_text(json.dumps({
        'database':engine.dialect.name,'scope':'ISOLATED_CNY_HTTP_NO_PSP',
        'capture':captured,'previous_close':previous,'current_close':result,
        'prior_replay_unchanged':True,'refund_replay_unchanged':True},ensure_ascii=False,indent=2,default=str)+'\n')
