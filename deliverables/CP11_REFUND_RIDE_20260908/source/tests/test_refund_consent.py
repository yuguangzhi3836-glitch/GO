import pytest
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import VerticalRefundOperationRow as Operation, RailOrderRow, AttractionOrderRow
from tests.test_depth21_refund_recovery import booked, refunded_movements, row_state


def auth(client, vertical):
    email=f'consent-{vertical}@example.test'
    r=client.post('/v1/consumer/auth/register',json={'email':email,'password':'StrongPass123!','display_name':'Consent'})
    assert r.status_code==200,r.text
    owner=r.json()['data']['profile']['user_id']
    token=client.post('/v1/mobile/auth/login',json={'email':email,'password':'StrongPass123!'}).json()['data']['access_token']
    client.cookies.clear()
    return owner,{'Authorization':'Bearer '+token}


def case(client,vertical):
    owner,headers=auth(client,vertical);svc,_,oid=booked(vertical,owner)
    base='/v1/'+('rail' if vertical=='RAIL' else 'attractions')+'/orders/'+oid
    return svc,owner,oid,headers,base


@pytest.mark.parametrize('vertical',['RAIL','ATTRACTION'])
def test_public_refund_requires_quote_confirmation_before_any_money(client,vertical):
    svc,owner,oid,headers,base=case(client,vertical)
    response=client.post(base+'/refund',headers=headers)
    assert response.status_code==422,response.text
    assert not refunded_movements()
    assert row_state(vertical,oid)==('TICKETED' if vertical=='RAIL' else 'CONFIRMED')


@pytest.mark.parametrize('vertical',['RAIL','ATTRACTION'])
def test_completed_change_invalidates_displayed_quote_even_for_same_price(client,vertical):
    svc,owner,oid,h,base=case(client,vertical)
    quote=client.get(base+'/refund-quote',headers=h).json()['data']
    change=svc.change_quote(owner,oid,'2026-09-16');svc.execute_change(owner,oid,change['quote_id'])
    if vertical=='RAIL':
        svc.admin_external_state(oid,'TICKETED','isolated://changed','ops','NEW',['NEW-A','NEW-B'],change['quote_id'])
    else:
        svc.admin_external_state(oid,'CONFIRMED','isolated://changed','ops','NEW','NEW-VOUCHER')
    fresh=client.get(base+'/refund-quote',headers=h).json()['data']
    assert fresh['quote_hash']!=quote['quote_hash']
    if vertical=='ATTRACTION':assert fresh['refund_amount_minor']==quote['refund_amount_minor']
    stale=client.post(base+'/refund',headers=h,json={'expected_quote_hash':quote['quote_hash']})
    assert stale.status_code==409 and stale.json()['detail']=='REFUND_QUOTE_CHANGED'
    assert not refunded_movements()
    with SessionLocal() as s:assert s.get(Operation,(vertical,oid)) is None
    accepted=client.post(base+'/refund',headers=h,json={'expected_quote_hash':fresh['quote_hash']})
    assert accepted.status_code==200,accepted.text
    assert accepted.json()['data']['refund_amount_minor']==fresh['refund_amount_minor']


@pytest.mark.parametrize('vertical',['RAIL','ATTRACTION'])
def test_quote_belongs_to_exact_order_and_replay_keeps_original_confirmation(client,vertical):
    svc,owner,oid,h,base=case(client,vertical)
    quote=client.get(base+'/refund-quote',headers=h).json()['data']
    _,_,second=booked(vertical,owner)
    second_quote=svc.refund_quote(owner,second)
    assert second_quote['refund_amount_minor']==quote['refund_amount_minor']
    bad=client.post(base+'/refund',headers=h,json={'expected_quote_hash':second_quote['quote_hash']})
    assert bad.status_code==409 and not refunded_movements()
    body={'expected_quote_hash':quote['quote_hash']}
    first=client.post(base+'/refund',headers={**h,'Idempotency-Key':'original'},json=body)
    assert first.status_code==200,first.text
    for key in ['original','different-device']:
        retry=client.post(base+'/refund',headers={**h,'Idempotency-Key':key},json=body)
        assert retry.status_code==200 and retry.json()==first.json()
    changed=client.post(base+'/refund',headers={**h,'Idempotency-Key':'original'},json={'expected_quote_hash':second_quote['quote_hash']})
    assert changed.status_code==409
    assert len(refunded_movements())==1


@pytest.mark.parametrize('vertical',['RAIL','ATTRACTION'])
def test_recovery_endpoint_cannot_initiate_refund_and_is_owner_scoped(client,vertical):
    svc,owner,oid,h,base=case(client,vertical)
    for suffix,method in [('/refund-progress',client.get),('/refund-progress/reconcile',client.post)]:
        assert method(base+suffix,headers=h).status_code==404
        assert method(base+suffix).status_code==401
    assert not refunded_movements()
    with SessionLocal() as s:assert s.get(Operation,(vertical,oid)) is None
    svc.refund(owner,oid,svc.refund_quote(owner,oid)['quote_hash'])
    _,other=auth(client,vertical+'-other')
    assert client.get(base+'/refund-progress',headers=other).status_code==404
    assert client.post(base+'/refund-progress/reconcile',headers=other).status_code==404


@pytest.mark.parametrize('vertical',['RAIL','ATTRACTION'])
def test_readonly_progress_and_explicit_recovery_preserve_confirmed_money(client,vertical,monkeypatch):
    from go_hotel.services import vertical_refund_recovery as recovery
    svc,owner,oid,h,base=case(client,vertical);q=svc.refund_quote(owner,oid)
    original=recovery.vertical_money_bridge.refund_with_adjustments
    def lost(*a,**kw):original(*a,**kw);raise RuntimeError('RECEIPT_LOST')
    monkeypatch.setattr(recovery.vertical_money_bridge,'refund_with_adjustments',lost)
    with pytest.raises(RuntimeError,match='RECEIPT_LOST'):svc.refund(owner,oid,q['quote_hash'])
    with SessionLocal() as s:
        op=s.get(Operation,(vertical,oid));before=(op.attempt,op.lease_until_ms,op.state,dict(op.quote_json))
    for _ in range(3):
        progress=client.get(base+'/refund-progress',headers=h)
        assert progress.status_code==200 and progress.json()['data']['status']=='PENDING'
        assert progress.json()['data']['refund_amount_minor']==q['refund_amount_minor']
        assert progress.json()['data']['external_live'] is False
    with SessionLocal() as s:
        op=s.get(Operation,(vertical,oid));assert before==(op.attempt,op.lease_until_ms,op.state,dict(op.quote_json))
    monkeypatch.setattr(recovery.vertical_money_bridge,'refund_with_adjustments',original)
    response=client.post(base+'/refund-progress/reconcile',headers=h)
    assert response.status_code==200,response.text
    assert response.json()['data']['status']=='REFUND_COMPLETED' and len(refunded_movements())==1
    assert client.get(base+'/refund-progress',headers=h).json()['data']['status']=='COMPLETED'


@pytest.mark.parametrize('vertical',['RAIL','ATTRACTION'])
def test_order_identity_drift_after_acceptance_requires_review_before_money(client,vertical,monkeypatch):
    from go_hotel.services import vertical_refund_recovery as recovery
    svc,owner,oid,h,base=case(client,vertical);q=svc.refund_quote(owner,oid)
    original=recovery.vertical_money_bridge.refund_with_adjustments
    def offline(*a,**kw):raise RuntimeError('OFFLINE')
    monkeypatch.setattr(recovery.vertical_money_bridge,'refund_with_adjustments',offline)
    with pytest.raises(RuntimeError):svc.refund(owner,oid,q['quote_hash'])
    # Simulate an invalid out-of-band correction. Recovery must not release the
    # new ticket or its capacity using the prior customer's authorization.
    with SessionLocal.begin() as s:
        order=s.get(RailOrderRow if vertical=='RAIL' else AttractionOrderRow,oid)
        if vertical=='RAIL':order.ticket_numbers=['CHANGED-A','CHANGED-B']
        else:order.voucher_code='CHANGED-VOUCHER'
    monkeypatch.setattr(recovery.vertical_money_bridge,'refund_with_adjustments',original)
    response=client.post(base+'/refund-progress/reconcile',headers=h)
    assert response.status_code==409 and 'CONTEXT_CHANGED' in response.json()['detail']
    assert row_state(vertical,oid)=='REFUND_PENDING' and not refunded_movements()


@pytest.mark.parametrize('vertical',['RAIL','ATTRACTION'])
@pytest.mark.parametrize('value',['0'*63,'G'*64,7])
def test_malformed_confirmation_is_rejected(client,vertical,value):
    svc,owner,oid,h,base=case(client,vertical)
    assert client.post(base+'/refund',headers=h,json={'expected_quote_hash':value}).status_code==422
    assert not refunded_movements()
