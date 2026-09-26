"""Real route → durable coupon plan → existing C11 ledger → selective outcome."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db import models as m
from go_hotel.flight.service import flight_service as flights
from go_hotel.flight import coupon_refunds as refunds
from tests.test_depth48_flight_changes import booked,consent,amounts
from tests.test_flight_journey_depth import day


def confirmation(q):
    return {'quote_hash':q['quote_hash'],'expected_refund_amount_minor':q['refund_amount_minor'],'currency':q['currency'],'confirmed':True}


def test_partial_person_change_uses_actual_coupons_and_preserves_every_other_coupon(client):
    owner,o,h=booked(client);oid=o['order_id'];original=deepcopy(o['coupons']);target=original[0]
    q=client.post(f'/v1/flights/orders/{oid}/change-quote',headers=h,json={'changes':[
        {'leg_index':0,'coupon_ids':[target['coupon_id']],'new_departure_date':day(12)}]})
    assert q.status_code==200,q.text
    q=q.json()['data'];assert q['total_due_minor']==40000 and q['partial_party']
    r=client.post(f"/v1/flights/orders/{oid}/execute-change/{q['quote_id']}",headers={**h,'Idempotency-Key':'partial-change'},json=consent(q))
    assert r.status_code==200,r.text
    pending=flights.order(owner,oid);assert pending['coupons'][0]['state']=='CHANGE_PENDING'
    assert len(pending['ticket_assignments'])==3
    changed=flights.admin_external_state(oid,'TICKETED','isolated://partial-change','ops','PARTIAL',['ONE-NEW'],q['quote_id'])
    fresh=flights.order(owner,oid);assert fresh['coupons'][1:]==original[1:]
    c=fresh['coupons'][0];assert c['ticket_number']=='ONE-NEW' and c['leg']['departure_date']==day(12)
    assert c['paid_amount_minor']==target['paid_amount_minor']+40000
    assert c['supplier_reference']=='PARTIAL' and fresh['pnr']==o['pnr']
    assert fresh['total_amount_minor']==o['total_amount_minor']+40000
    assert flights.admin_external_state(oid,'TICKETED','isolated://partial-change','ops','PARTIAL',['ONE-NEW'],q['quote_id'])==changed
    # Successive selection reads the changed passenger's own date and version.
    second=flights.change_quote(owner,oid,changes=[{'leg_index':0,'coupon_ids':[c['coupon_id']],'new_departure_date':day(13)}])
    assert second['changes'][0]['old_departure_date']==day(12)


def test_partial_refund_http_and_then_remaining_order_refund_conserve_money(client):
    owner,o,h=booked(client);oid=o['order_id'];target=o['coupons'][1]
    q=client.post(f'/v1/flights/orders/{oid}/coupon-refund-quotes',headers=h,json={'coupon_ids':[target['coupon_id']]})
    assert q.status_code==200,q.text
    q=q.json()['data'];assert q['refund_amount_minor']==448000
    path=f"/v1/flights/orders/{oid}/coupon-refunds/{q['refund_id']}"
    r=client.post(path,headers=h,json=confirmation(q));assert r.status_code==200,r.text
    replay=client.post(path,headers={**h,'Idempotency-Key':'another-device'},json=confirmation(q))
    assert replay.status_code==200 and replay.json()['data']['idempotent_replay']
    fresh=flights.order(owner,oid);assert fresh['status']=='TICKETED'
    assert fresh['coupons'][1]['state']=='REFUNDED' and len(fresh['ticket_assignments'])==3
    assert [c for c in fresh['coupons'] if c['coupon_id']!=target['coupon_id']]==[c for c in o['coupons'] if c['coupon_id']!=target['coupon_id']]
    remaining=flights.refund_quote(owner,oid);assert remaining['refund_amount_minor']==448000*3
    flights.refund(owner,oid,remaining['quote_hash'])
    assert flights.order(owner,oid)['status']=='REFUNDED'
    assert amounts()['REFUND']==448000*4 and amounts()['CAPTURE']==o['total_amount_minor']
    assert refunds.execute(owner,oid,q['refund_id'],confirmation(q))['idempotent_replay']


def test_stale_parallel_quote_and_other_owner_coupon_reject_without_money(client):
    owner,o,h=booked(client);oid=o['order_id'];ids=[o['coupons'][0]['coupon_id']]
    with pytest.raises(ValueError,match='SELECTION_INVALID'):refunds.quote(owner,oid,['foreign-coupon'])
    q=refunds.quote(owner,oid,ids);peer=refunds.quote(owner,oid,ids)
    before=amounts()
    with pytest.raises(ValueError,match='NOT_FOUND'):refunds.execute('other',oid,q['refund_id'],confirmation(q))
    with pytest.raises(ValueError,match='CONSENT_INVALID'):refunds.execute(owner,oid,q['refund_id'],confirmation(q)|{'currency':'USD'})
    assert amounts()==before
    refunds.execute(owner,oid,q['refund_id'],confirmation(q));after=amounts()
    with pytest.raises(ValueError,match='CHANGED_REQUOTE'):refunds.execute(owner,oid,peer['refund_id'],confirmation(peer))
    assert amounts()==after


def test_partial_refund_crash_after_money_recovers_same_allocation(client,monkeypatch):
    owner,o,_=booked(client);oid=o['order_id'];q=refunds.quote(owner,oid,[o['coupons'][0]['coupon_id']])
    original=refunds.money.execute_refund_plan
    def crash(*a,**kw):original(*a,**kw);raise RuntimeError('AFTER_MONEY')
    monkeypatch.setattr(refunds.money,'execute_refund_plan',crash)
    with pytest.raises(RuntimeError,match='AFTER_MONEY'):refunds.execute(owner,oid,q['refund_id'],confirmation(q))
    pending=flights.order(owner,oid);assert pending['status']=='REFUND_PENDING'
    assert pending['coupons'][0]['state']=='REFUND_PENDING' and len(pending['ticket_assignments'])==3
    total=amounts()['REFUND'];assert total==q['refund_amount_minor']
    monkeypatch.setattr(refunds.money,'execute_refund_plan',original)
    result=refunds.execute(owner,oid,q['refund_id'],confirmation(q));assert result['status']=='REFUND_COMPLETED'
    assert amounts()['REFUND']==total


def test_refund_expiry_and_tampered_operation_reject_before_money(client):
    owner,o,_=booked(client);q=refunds.quote(owner,o['order_id'],[o['coupons'][0]['coupon_id']]);before=amounts()
    with SessionLocal.begin() as s:
        op=s.get(m.FlightCouponRefundRow,q['refund_id']);data=deepcopy(op.quote_json);data['refund_amount_minor']+=1;op.quote_json=data
    with pytest.raises(ValueError,match='INTEGRITY_INVALID'):refunds.execute(owner,o['order_id'],q['refund_id'],confirmation(q))
    assert amounts()==before


def test_selected_coupons_cannot_borrow_other_leg_or_duplicate_selection(client):
    owner,o,h=booked(client);oid=o['order_id'];before=amounts()
    for ids in [[o['coupons'][2]['coupon_id']],['foreign'],[o['coupons'][0]['coupon_id']]*2]:
        r=client.post(f'/v1/flights/orders/{oid}/change-quote',headers=h,json={'changes':[{'leg_index':0,'coupon_ids':ids,'new_departure_date':day(12)}]})
        assert r.status_code==409,r.text
    assert amounts()==before
