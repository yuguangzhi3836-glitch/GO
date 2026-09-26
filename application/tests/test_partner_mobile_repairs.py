import pytest
from go_hotel.services.go_identity_entitlements import go_identity_entitlement_service as svc
from go_hotel.services.hotel_partner_core import hotel_partner_core_service as core
from go_hotel.services import transaction_order_view as view
from go_hotel.security.service import identity_service
from test_depth41_transaction_views import booked


def rooms(supplier='partner-a'):
    h=core.create_property(supplier,'owner',{'name_zh':'验收酒店','property_type':'HOTEL'})
    return [core.create_room_type(supplier,'owner',h['property_id'],{
        'name_zh':name,'physical_room_count':3,
        'occupancy':{'max_occupancy':2,'max_adults':2,'max_children':0}})['room_type_id']
        for name in ['大床房','双床房']]


def selection(ids,typ='STAFF_RATE',enabled=True):
    return {'program_type':typ,'enabled':enabled,'eligible_room_ids':ids}


def test_multiple_programs_rooms_roundtrip_preserves_dates_and_benefits():
    ids=rooms()
    svc.program('partner-a',{'program_type':'OWNER_BENEFITS','enabled':True,
        'eligible_room_ids':ids,'open_date_ranges':[{'start':'2026-10-01','end':'2026-12-31'}],
        'benefits':['BREAKFAST'],'inventory_limit':2,'authorization_reference':'prior'},'owner')
    before=svc.configuration('partner-a')
    after=svc.configure_programs('partner-a',[selection(ids),selection(ids,'OWNER_BENEFITS')],before['revision'],'logged-in-owner')
    assert len(after['programs'])==2
    assert all(p['eligible_room_ids_json']==ids for p in after['programs'])
    owner=next(p for p in after['programs'] if p['program_type']=='OWNER_BENEFITS')
    assert owner['open_date_ranges_json']==[{'start':'2026-10-01','end':'2026-12-31'}]
    assert owner['benefits_json']==['BREAKFAST'] and owner['inventory_limit']==2
    assert owner['authorization_reference']=='SUPPLIER_CONSOLE:logged-in-owner'
    assert svc.configuration('partner-a')['revision']==after['revision']


def test_foreign_room_rejects_entire_batch_without_partial_save():
    ids=rooms();foreign=rooms('partner-b');before=svc.configuration('partner-a')
    assert set(r['room_type_id'] for r in before['rooms'])==set(ids)
    with pytest.raises(ValueError,match='PROGRAM_ROOM_NOT_AVAILABLE'):
        svc.configure_programs('partner-a',[selection(ids),selection(foreign,'OWNER_RATE')],before['revision'],'owner')
    assert svc.configuration('partner-a')==before


def test_owner_benefits_require_explicit_choices_and_reject_unknown_choices():
    ids=rooms();before=svc.configuration('partner-a')
    owner=selection(ids,'OWNER_BENEFITS')
    with pytest.raises(ValueError,match='PROGRAM_BENEFITS_REQUIRED'):
        svc.configure_programs('partner-a',[selection(ids),owner],before['revision'],'owner')
    assert svc.configuration('partner-a')==before
    owner['benefits']=['BREAKFAST','LATE_CHECKOUT']
    saved=svc.configure_programs('partner-a',[owner],before['revision'],'owner')
    assert saved['programs'][0]['benefits_json']==owner['benefits']
    owner['benefits']=['UNSUPPORTED']
    with pytest.raises(ValueError,match='INVALID_PROGRAM_BENEFIT'):
        svc.configure_programs('partner-a',[owner],saved['revision'],'owner')
    assert svc.configuration('partner-a')==saved


def test_empty_enabled_rooms_rejected_and_unchecked_program_can_disable():
    ids=rooms();before=svc.configuration('partner-a')
    with pytest.raises(ValueError,match='PROGRAM_ROOMS_REQUIRED'):
        svc.configure_programs('partner-a',[selection([])],before['revision'],'owner')
    result=svc.configure_programs('partner-a',[selection(ids)],before['revision'],'owner')
    result=svc.configure_programs('partner-a',[selection([],enabled=False)],result['revision'],'owner')
    assert result['programs'][0]['enabled'] is False


def test_stale_configuration_cannot_overwrite_newer_selection():
    ids=rooms();before=svc.configuration('partner-a')
    svc.configure_programs('partner-a',[selection(ids)],before['revision'],'owner')
    with pytest.raises(ValueError,match='PROGRAM_CONFIGURATION_CHANGED'):
        svc.configure_programs('partner-a',[selection([ids[0]])],before['revision'],'other')
    assert svc.configuration('partner-a')['programs'][0]['eligible_room_ids_json']==ids


def test_configuration_http_permission_and_no_client_authority(client):
    ids=rooms();password='Isolated-ui-fix-password'
    identity_service.ensure_user('reader@ui.test',password,'SUPPLIER_USER','partner-a',['READ_ONLY'])
    login=client.post('/bff/auth/login',json={'username':'reader@ui.test','password':password,'expected_actor_type':'SUPPLIER_USER'})
    assert login.status_code==200
    data=client.get('/v1/supplier/go-identity/configuration').json()['data']
    headers={'X-CSRF-Token':client.cookies.get('go_csrf')}
    response=client.put('/v1/supplier/go-identity/configuration',headers=headers,json={'programs':[selection(ids)],'revision':data['revision']})
    assert response.status_code==403
    assert svc.programs('partner-a')==[]


@pytest.mark.parametrize('vertical',list(view.ORDERS))
def test_category_filter_and_refunds_use_bound_tenant_before_pagination(client,vertical):
    oid,owner,supplier,q,refund=booked(vertical,client)
    data=view.supplier_orders(supplier,1,0,vertical)
    assert data['total']==1 and data['items'][0]['order_id']==oid and data['has_more'] is False
    assert view.supplier_orders(supplier,1,1,vertical)['items']==[]
    other='RAIL' if vertical!='RAIL' else 'HOTEL'
    assert view.supplier_orders(supplier,1,0,other)['items']==[]
    refund()
    assert view.supplier_refunds(supplier,vertical=vertical)['items'][0]['order_id']==oid
    assert view.supplier_refunds(supplier,vertical=other)['items']==[]
    assert view.supplier_refunds('unrelated',vertical=vertical)['items']==[]


def test_invalid_category_rejected_at_api(client):
    identity_service.ensure_user('owner@ui.test','Isolated-ui-fix-password','SUPPLIER_USER','partner-a',['SUPPLIER_OWNER'])
    client.post('/bff/auth/login',json={'username':'owner@ui.test','password':'Isolated-ui-fix-password'})
    assert client.get('/v1/supplier/transaction-orders?vertical=BAD').status_code==422
    assert client.get('/v1/supplier/refunds?vertical=BAD').status_code==422
