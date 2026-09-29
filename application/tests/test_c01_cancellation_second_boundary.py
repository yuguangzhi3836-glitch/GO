"""Synthetic fee rules only: exact confirmed-anchor HTTP boundaries and replay."""
from datetime import datetime,timedelta
import pytest
from sqlalchemy import select
from tests.test_c01_aoluguya_business_day import http,business,post,window
from tests.test_c01_money_authority_matrix import facts
from tests.hosted_review_support import RULES,prepare_publication
from go_hotel.db import models as m
from go_hotel.db.session import SessionLocal
from go_hotel.services import hosted_fare_rules as fare
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service as booking


def long_wait_confirm(http,h,tmp_path):
    rules={**RULES,'fare_family':'SYNTHETIC_BOUNDARY_NOT_HOTEL_POLICY','cooling_off_anchor':'HOTEL_CONFIRMED',
           'cancellation_tiers':[{'min_hours':0,'fee_basis_points':10000}]}
    fare.publish(h['offer'],rules,'isolated://clock-boundary-not-hotel-confirmation',h['maker'].user_id)
    prepare_publication(h['hotel'],h['maker'],h['checker'],tmp_path,add_rules=False)
    booking.publish(h['hotel'],h['maker'])
    h['clock']['at']=window(h['day'].isoformat())[0]+timedelta(hours=12,minutes=50)
    item=next(x for x in post(http,f"/v1/direct/{h['slug']}/availability",{},h['body'])['items'] if x['hosted_offer_id']==h['offer'])
    body={**h['body'],'expected_fare_rule_hash':item['fare_rule']['rule_hash'],'confirmation_timeout_minutes':120}
    r=post(http,f"/v1/direct/{h['slug']}/reservations",h['customer_headers'],body,'second-boundary')
    rid=r['hosted_reservation_id']
    aid=post(http,f'/v1/direct/reservations/{rid}/checkout',h['customer_headers'],{'expected_amount_minor':69800,'currency':'CNY','mode':'CONTRACT_SIMULATOR'})['authorization']['authorization_id']
    h['clock']['at']+=timedelta(hours=1)
    post(http,f'/internal/v1/hosted-direct/reservations/{rid}/decision',h['maker_headers'],{'decision':'CONFIRM'})
    return rid,aid,h['clock']['at'],rules


def shown(http,h,rid):
    r=http.get(f'/v1/direct/reservations/{rid}',headers=h['customer_headers'])
    assert r.status_code==200,r.text
    return r.json()['data']['after_sales']['fare']


@pytest.mark.parametrize('seconds,fee',[(1799,0),(1800,69800),(1801,69800)])
def test_confirmed_anchor_second_boundaries_display_quote_execution(http,business,tmp_path,seconds,fee):
    h=business;rid,aid,confirmed,rules=long_wait_confirm(http,h,tmp_path)
    h['clock']['at']=confirmed+timedelta(seconds=seconds)
    display=shown(http,h,rid)
    assert display['rules']==rules
    q=post(http,f'/v1/direct/reservations/{rid}/fare/cancellation-quote',h['customer_headers'])
    assert q['rule_hash']==display['rule_hash'] and q['rule_version_id']==display['rule_version_id']
    assert q['fee_minor']==fee and q['cooling_off_applied']==(seconds<1800)
    assert q['authorization_release_minor']==69800-fee and q['cash_refund_minor']==0
    if seconds<1800:assert datetime.fromisoformat(q['expires_at'])==confirmed+timedelta(minutes=30)
    body={'quote_id':q['quote_id'],'expected_fee_minor':fee,'currency':'CNY'}
    path=f'/v1/direct/reservations/{rid}/fare/cancel'
    result=post(http,path,h['customer_headers'],body)
    assert result['fee_captured_minor']==fee and result['authorization_released_minor']==69800-fee
    assert result['cash_refund_minor']==0 and result['rule_version_id']==display['rule_version_id']
    after=facts();assert post(http,path,h['customer_headers'],body)==result;assert facts()==after
    with SessionLocal() as s:
        moves=list(s.scalars(select(m.OmnichannelMoneyMovementRow)))
        assert sum(x.amount_minor for x in moves if x.movement_type=='CAPTURE')==fee
        assert sum(x.amount_minor for x in moves if x.movement_type=='RELEASE')==69800-fee
        assert not any(x.movement_type=='REFUND' for x in moves)
        assert s.scalar(select(m.HostedInventoryDayRow.capacity_available).where(m.HostedInventoryDayRow.inventory_pool_id==h['pool'],m.HostedInventoryDayRow.stay_date==h['day'].isoformat()))==50


def test_quote_from_last_free_second_expires_at_exact_confirmed_cutoff(http,business,tmp_path):
    h=business;rid,_,confirmed,_=long_wait_confirm(http,h,tmp_path)
    h['clock']['at']=confirmed+timedelta(minutes=29,seconds=59)
    q=post(http,f'/v1/direct/reservations/{rid}/fare/cancellation-quote',h['customer_headers']);assert q['fee_minor']==0
    h['clock']['at']=confirmed+timedelta(minutes=30)
    before=facts()
    rejected=post(http,f'/v1/direct/reservations/{rid}/fare/cancel',h['customer_headers'],{'quote_id':q['quote_id'],'expected_fee_minor':0,'currency':'CNY'},status=409)
    assert rejected['detail']=='FARE_QUOTE_EXPIRED_REQUOTE_REQUIRED';assert facts()==before
    fresh=post(http,f'/v1/direct/reservations/{rid}/fare/cancellation-quote',h['customer_headers'])
    assert fresh['fee_minor']==69800 and fresh['rule_hash']==q['rule_hash']
