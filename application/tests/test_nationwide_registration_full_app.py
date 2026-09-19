"""National self-registration through the real app; isolated SQLite only."""
import secrets
import pytest
from go_hotel.core.config import settings
from go_hotel.db.models import HotelPartnerPropertyRow, IdentityUserRow
from test_hotel_direct_submission_full_app import full_application
from test_hotel_direct_submission_publication import publishing
from test_hotel_direct_submission_review import ready
from test_hotel_direct_submission_verification import setup


def test_consumer_registration_cookie_has_no_supplier_or_admin_access(full_application):
    client, data = full_application
    policy = client.get('/v1/consumer/auth/registration')
    assert policy.status_code == 200
    config = policy.json()['data']
    assert config['enabled'] and config['coverage'] == 'CN_NATIONWIDE'
    body = {'email':'new-traveler@example.com','password':secrets.token_urlsafe(24),
            'display_name':'测试旅客','accepted_terms':True,'term_versions':config['terms']}
    response = client.post('/v1/consumer/auth/register', json=body)
    assert response.status_code in {200,201}, response.text
    assert client.get('/v1/consumer/me').status_code == 200
    assert client.cookies.get(settings.consumer_access_cookie_name)
    assert client.get('/v1/supplier/properties', headers={'X-GO-Actor':'SUPPLIER_USER'}).status_code in {401,403}
    assert client.get('/internal/v1/hotel-autopage/direct-submission-reviews', headers={'X-GO-Actor':'GO_ADMIN'}).status_code in {401,403}
    assert client.post('/v1/consumer/auth/register', json=body|{'actor_type':'GO_ADMIN'}).status_code == 422
    assert client.post('/v1/consumer/auth/register', json=body|{'email':'without-consent@example.com','accepted_terms':False}).status_code == 422


@pytest.mark.parametrize('province,city',[('黑龙江','哈尔滨'),('广东','广州'),('新疆','喀什')])
def test_national_supplier_signup_opens_only_own_draft_library(full_application,province,city):
    client, data = full_application
    foreign_pid=data[2]; factory=data[4]
    terms=client.get('/bff/auth/supplier/registration-terms').json()['data']['versions']
    body={'email':'new-hotel@example.com','password':secrets.token_urlsafe(24),
          'organization_name':'测试酒店主体','hotel_name':city+'测试酒店','contact_name':'测试联系人',
          'province':province,'city':city,'street_address':'测试地址一号',
          'accepted_terms':True,'term_versions':terms}
    response=client.post('/bff/auth/supplier/register',json=body)
    assert response.status_code==201,response.text
    result=response.json()['data']; pid=result['property_id']
    assert result['registration_scope']=='NATIONWIDE'
    assert result['ownership_status']=='DECLARED' and result['publication_state']=='DRAFT'
    headers={'X-GO-Actor':'SUPPLIER_USER'}
    me=client.get('/bff/auth/me',headers=headers).json()['data']
    assert me['actor_type']=='SUPPLIER_USER' and me['roles']==['SUPPLIER_OWNER']
    graph=client.get(f'/v1/supplier/properties/{pid}/product-graph',headers=headers)
    assert graph.status_code==200,graph.text
    assert graph.json()['data']['property']['property_id']==pid
    assert client.get(f'/v1/supplier/properties/{foreign_pid}/product-graph',headers=headers).status_code in {403,404}
    assert client.get('/internal/v1/hotel-autopage/direct-submission-reviews',headers=headers).status_code==403
    write_headers=headers|{settings.csrf_header_name:client.cookies.get(settings.csrf_cookie_name)}
    room={'name_zh':'测试大床房','physical_room_count':10,
          'occupancy':{'max_occupancy':2,'max_adults':2,'max_children':0}}
    created=client.post(f'/v1/supplier/properties/{pid}/room-types',headers=write_headers,json=room)
    assert created.status_code==201,created.text
    room_id=created.json()['data']['room_type_id']
    refreshed=client.get(f'/v1/supplier/properties/{pid}/product-graph',headers=headers)
    assert room_id in str(refreshed.json())
    assert client.post(f'/v1/supplier/properties/{foreign_pid}/room-types',headers=write_headers,json=room).status_code in {403,404}
    assert client.get('/internal/v1/hotel-infrastructure/catalog-scope/status',headers=headers).status_code==403
    with factory() as session:
        prop=session.get(HotelPartnerPropertyRow,pid)
        assert prop.supplier_id==result['supplier_id'] and prop.publication_state=='DRAFT'
        assert prop.address_json['city']==city and prop.address_json['province']==province
        assert prop.operations_json['ownership']['status']=='DECLARED'
        assert prop.operations_json['ownership']['verification_required_before_publication'] is True
