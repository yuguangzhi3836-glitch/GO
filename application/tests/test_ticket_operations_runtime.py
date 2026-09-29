from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OrderSupplierFulfillmentRow
from go_hotel.security.service import identity_service
from go_hotel.core.config import settings
from tests.test_depth48_flight_changes import booked,consent,amounts
from tests.test_flight_journey_depth import day
from go_hotel.flight.service import flight_service


def login(role,supplier=None):
    name='ticket-'+uuid4().hex
    identity_service.ensure_user(name,'Synthetic-only-2026!', 'SUPPLIER_USER' if supplier else 'GO_ADMIN',supplier,[role])
    return {'Authorization':'Bearer '+identity_service.login(name,'Synthetic-only-2026!')['access_token']}


def test_real_roles_partial_change_cross_surface_workflow(client,monkeypatch):
    monkeypatch.setattr(settings,'mfa_required_for_admin',False)
    owner,o,consumer=booked(client);oid=o['order_id']
    with SessionLocal() as s:
        sid=s.scalar(select(OrderSupplierFulfillmentRow).where(OrderSupplierFulfillmentRow.business_id==oid)).supplier_id
    supplier=login('SUPPLIER_OWNER',sid);operator=login('GO_ORDER_OPS');verifier=login('GO_ORDER_OPS')
    readonly=login('READ_ONLY',sid);foreign=login('SUPPLIER_OWNER','foreign-isolated')
    sp=f'/v1/supplier/ticket-operations/FLIGHT/{oid}';ap=f'/internal/v1/admin/ticket-operations/FLIGHT/{oid}'
    assert client.get(sp,headers=foreign).status_code==404
    assert client.get(ap,headers=consumer).status_code==403
    q=flight_service.change_quote(owner,oid,changes=[{'leg_index':0,'coupon_ids':[o['coupons'][0]['coupon_id']],'new_departure_date':day(12)}])
    flight_service.execute_change(owner,oid,q['quote_id'],consent(q))
    revision=0
    def command(action,headers,path=ap,receipt=None,expected=200):
        nonlocal revision
        body={'action':action,'command_id':uuid4().hex,'expected_revision':revision,'note':'isolated cross-surface acceptance'}
        if receipt:body['receipt']=receipt
        r=client.post(path,headers=headers,json=body);assert r.status_code==expected,r.text
        if expected==200:
            revision=r.json()['data']['workflow']['revision']
            replay=client.post(path,headers=headers,json=body);assert replay.status_code==200,replay.text
            assert replay.json()['data']['idempotent_replay']
        return body
    command('REGISTER',readonly,sp,expected=403)
    command('REGISTER',supplier,sp);command('CLAIM',supplier,sp)
    receipt={'state':'TICKETED','evidence_reference':'isolated://ops-receipt','supplier_reference':'OPSREF','ticket_numbers':['OPS-ONE'],'quote_id':q['quote_id']}
    command('RECEIPT',supplier,sp,receipt)
    before=amounts();command('APPLY',supplier,sp,expected=409);assert amounts()==before
    command('APPLY',operator)
    command('VERIFY',operator,expected=409)
    command('VERIFY',verifier);command('FOLLOW_UP',operator)
    end=client.get(sp,headers=supplier).json()['data']
    assert end['workflow']['stage']=='CLOSED'
    assert end['order']['coupons'][0]['ticket_number']=='OPS-ONE'
    assert end['order']['coupons'][1:]==[{k:v for k,v in c.items() if k!='account_id'} for c in o['coupons'][1:]]
    assert 'account_id' not in end['order']
    assert flight_service.order(owner,oid)['coupons'][0]['ticket_number']=='OPS-ONE'
