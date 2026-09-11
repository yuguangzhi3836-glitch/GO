from datetime import datetime, timezone, timedelta
from go_hotel.connectors.mock_hotel import connector
from go_hotel.payments.mock import payment_provider
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import PaymentOrderRootRow, OmnichannelMoneyMovementRow


def booked_order(client, check_in=None, check_out=None, idem='x'):
    if check_in is None:
        check_in=(datetime.now(timezone.utc)+timedelta(days=20)).date().isoformat()
        check_out=(datetime.now(timezone.utc)+timedelta(days=24)).date().isoformat()
    s=client.post('/v1/search/hotels',json={'destination':{'city_code':'TYO'},'stay':{'check_in':check_in,'check_out':check_out},'occupancy':{'rooms':1,'adults':2,'children':0},'currency':'CNY'})
    off=s.json()['data']['hotels'][0]['best_offer']
    pb=client.post(f"/v1/offers/{off['offer_id']}/prebook",json={'currency':'CNY'}).json()['data']
    o=client.post('/v1/orders',headers={'Idempotency-Key':f'ord-{idem}'},json={'prebook_id':pb['prebook_id'],'account_id':'acct_demo'}).json()['data']
    client.post(f"/v1/orders/{o['order_id']}/payments",headers={'Idempotency-Key':f'pay-{idem}'},json={'payment_method_token':'pm_success','amount_minor':o['total_amount_minor'],'currency':'CNY'})
    c=client.post(f"/internal/v1/orders/{o['order_id']}/confirm")
    assert c.status_code==200 and c.json()['data']['status']=='CONFIRMED'
    return o['order_id']


def test_free_cancel_full_refund(client):
    oid=booked_order(client,idem='cancel-free')
    q=client.post(f'/v1/orders/{oid}/cancellation-quote').json()['data']
    assert q['cancellation_fee_minor']==0
    assert q['refund_amount_minor']==1_443_200
    r=client.post(f'/v1/orders/{oid}/cancel',headers={'Idempotency-Key':'cancel-free'},json={'cancellation_quote_id':q['quote_id'],'reason_code':'CHANGE_OF_PLAN'})
    assert r.status_code==200
    assert r.json()['data']['status']=='CANCELLED'
    assert r.json()['data']['refund']['status']=='COMPLETED'
    assert payment_provider.refund_calls==0
    with SessionLocal() as s:
        root=s.scalar(select(PaymentOrderRootRow).where(PaymentOrderRootRow.business_type=='HOTEL_ORDER',PaymentOrderRootRow.business_id==oid))
        refunds=s.scalars(select(OmnichannelMoneyMovementRow).where(OmnichannelMoneyMovementRow.root_payment_intent_id==root.payment_intent_id,OmnichannelMoneyMovementRow.movement_type=='REFUND',OmnichannelMoneyMovementRow.state=='CONFIRMED')).all()
        assert len(refunds)==1


def test_tiered_cancel_50_percent(client):
    ci=(datetime.now(timezone.utc)+timedelta(hours=48)).date().isoformat()
    co=(datetime.now(timezone.utc)+timedelta(days=4)).date().isoformat()
    oid=booked_order(client,ci,co,'cancel-tier')
    q=client.post(f'/v1/orders/{oid}/cancellation-quote').json()['data']
    # Date-only check-in at 00:00 may be 24-48h away; rule is therefore 50% in this fixture.
    assert q['cancellation_fee_minor']==721_600
    assert q['refund_amount_minor']==721_600


def test_change_higher_price_supplement_and_lower_no_refund(client):
    oid=booked_order(client,idem='change-high')
    new_ci=(datetime.now(timezone.utc)+timedelta(days=50)).date().isoformat(); new_co=(datetime.now(timezone.utc)+timedelta(days=54)).date().isoformat()
    connector.date_price_delta[new_ci]=80_000
    q=client.post(f'/v1/orders/{oid}/change-quote',json={'new_check_in':new_ci,'new_check_out':new_co}).json()['data']
    assert q['fare_difference_minor']==80_000 and q['change_fee_minor']==10_000 and q['amount_due_minor']==90_000
    r=client.post(f'/v1/orders/{oid}/change',headers={'Idempotency-Key':'chg-high'},json={'change_quote_id':q['change_quote_id'],'payment_method_token':'pm_success'})
    assert r.status_code==200 and r.json()['data']['amount_paid_minor']==90_000

    oid2=booked_order(client,idem='change-low')
    low_ci=(datetime.now(timezone.utc)+timedelta(days=60)).date().isoformat(); low_co=(datetime.now(timezone.utc)+timedelta(days=64)).date().isoformat()
    connector.date_price_delta[low_ci]=-43_200
    q2=client.post(f'/v1/orders/{oid2}/change-quote',json={'new_check_in':low_ci,'new_check_out':low_co}).json()['data']
    assert q2['new_value_minor']==1_400_000
    assert q2['fare_difference_minor']==0
    assert q2['amount_due_minor']==10_000
    assert q2['lower_price_no_refund'] is True


def test_stay_credit_property_only_and_redeem_with_difference(client):
    oid=booked_order(client,idem='credit')
    quote=client.post(f'/v1/orders/{oid}/stay-credit-quote').json()['data']
    assert quote['scope']=='PROPERTY_ONLY' and quote['validity_days']==365
    conv=client.post(f'/v1/orders/{oid}/convert-to-stay-credit',headers={'Idempotency-Key':'credit-convert'},json={'quote_id':quote['quote_id'],'quote_hash':quote['quote_hash'],'confirmed':True}).json()['data']
    assert conv['status']=='ACTIVE' and conv['property_id']=='htl_conrad_tokyo'
    credit_id=conv['stay_credit_id']
    new_ci=(datetime.now(timezone.utc)+timedelta(days=100)).date().isoformat(); new_co=(datetime.now(timezone.utc)+timedelta(days=104)).date().isoformat()
    connector.date_price_delta[new_ci]=156_800
    rq=client.post(f'/v1/stay-credits/{credit_id}/redemption-quote',json={'check_in':new_ci,'check_out':new_co}).json()['data']
    assert rq['new_value_minor']==1_600_000 and rq['amount_due_minor']==156_800
    red=client.post(f'/v1/stay-credits/{credit_id}/redeem',headers={'Idempotency-Key':'credit-redeem'},json={'redemption_quote_id':rq['quote_id'],'quote_hash':rq['quote_hash'],'confirmed':True,'payment_method_token':'pm_success'})
    assert red.status_code==200
    data=red.json()['data']
    assert data['status']=='REDEEMED' and data['amount_due_minor']==156_800
    c=client.get(f'/v1/stay-credits/{credit_id}').json()['data']
    assert c['status']=='REDEEMED' and c['redemption_order_id']==data['order_id']
