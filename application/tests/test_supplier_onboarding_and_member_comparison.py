import pytest
from sqlalchemy import select

from go_hotel.db.models import IdentityUserRow, HotelPartnerPropertyRow
from go_hotel.db.session import SessionLocal
from go_hotel.services.consumer_ota_comparison import consumer_ota_comparison_service as comparison
from go_hotel.services.supplier_onboarding import supplier_onboarding_service as onboarding


def test_supplier_self_registration_opens_owned_draft_property():
    body={'username':'owner@example.com','password':'strong-password','hotel':{'name_zh':'账号持有人酒店','property_type':'HOTEL'}}
    result=onboarding.register(body)
    with SessionLocal() as session:
        user=session.scalar(select(IdentityUserRow).where(IdentityUserRow.username=='owner@example.com'))
        prop=session.get(HotelPartnerPropertyRow,result['property_id'])
        assert user.supplier_id==result['supplier_id'] and user.roles==['SUPPLIER_OWNER']
        assert prop.supplier_id==result['supplier_id'] and prop.publication_state=='DRAFT'
    with pytest.raises(ValueError,match='USERNAME_ALREADY_REGISTERED'):
        onboarding.register(body)


def test_member_comparison_is_user_scoped_and_does_not_claim_unverified_price(monkeypatch):
    monkeypatch.setenv('GO_CTRIP_CONSUMER_DEEP_LINK','ctrip://hotel/search?city={city}&checkin={checkin}&checkout={checkout}')
    result=comparison.options('consumer-comparison',{'city_code':'SHA','check_in':'2026-10-01','check_out':'2026-10-02'})
    ctrip=next(x for x in result['providers'] if x['provider']=='CTRIP')
    assert result['comparison_scope']=='CURRENT_CONSUMER'
    assert ctrip['account_holder_authorized'] is False
    assert ctrip['member_price_status']=='VISIBLE_AFTER_PROVIDER_LOGIN'
    assert ctrip['deep_link'].startswith('ctrip://')
    assert ctrip['credentials_received_by_go'] is False
