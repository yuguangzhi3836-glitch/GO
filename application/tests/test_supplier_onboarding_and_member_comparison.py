import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from go_hotel.db.models import IdentityUserRow, HotelPartnerPropertyRow
from go_hotel.db.session import SessionLocal
from go_hotel.services.consumer_ota_comparison import consumer_ota_comparison_service as comparison
from go_hotel.services.supplier_onboarding import supplier_onboarding_service as onboarding

SEARCH = {'city_code':'SHA','hotel_id':'hotel-sha-1','check_in':'2026-10-01','check_out':'2026-10-02','rooms':1,'adults':2,'children':0,'currency':'CNY'}


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


def quote(now, **overrides):
    base = SEARCH | {
        'provider':'CTRIP','provider_quote_id':'ctrip-q-1','total_amount_minor':88000,
        'price_basis':'STAY_TOTAL','tax_fee_basis':'INCLUDES_MANDATORY_TAXES_AND_FEES',
        'verified_for_user_id':'consumer-comparison','account_holder_authorized':True,
        'verification_source':'OFFICIAL_PROVIDER_ADAPTER','member_tier':'DIAMOND',
        'observed_at':now.isoformat(),'expires_at':(now+timedelta(minutes=3)).isoformat(),
    }
    return base | overrides


def test_login_only_deep_link_is_not_presented_as_member_price(monkeypatch):
    monkeypatch.setenv('GO_CTRIP_CONSUMER_DEEP_LINK','ctrip://hotel/search?city={city}&checkin={checkin}&checkout={checkout}&rooms={rooms}&adults={adults}&children={children}')
    result=comparison.options('consumer-comparison',SEARCH)
    ctrip=next(x for x in result['providers'] if x['provider']=='CTRIP')
    assert result['comparison_scope']=='CURRENT_CONSUMER'
    assert ctrip['member_price_status']=='VISIBLE_AFTER_PROVIDER_LOGIN'
    assert ctrip['eligible_for_price_comparison'] is False
    assert ctrip['verified_member_price'] is None
    assert ctrip['suppression_reasons']==['NO_VERIFIED_QUOTE']
    assert ctrip['deep_link_status']=='OFFICIAL_PROVIDER_DESTINATION'
    assert ctrip['credentials_received_by_go'] is False


def test_verified_personal_member_price_requires_same_basis_and_freshness():
    now=datetime(2026,9,18,10,0,tzinfo=timezone.utc)
    result=comparison.options('consumer-comparison',SEARCH,[quote(now)],now)
    ctrip=next(x for x in result['providers'] if x['provider']=='CTRIP')
    assert ctrip['member_price_status']=='VERIFIED_PERSONAL_MEMBER_PRICE'
    # Quote authenticity and same-product comparability are distinct.
    assert ctrip['eligible_for_price_comparison'] is False
    assert ctrip['product_comparability']['state'] == 'UNKNOWN'
    assert ctrip['verified_member_price']['total_amount_minor']==88000
    assert ctrip['verified_member_price']['currency']=='CNY'
    assert ctrip['verified_member_price']['comparison_basis_fingerprint']==result['comparison_basis']['fingerprint']
    assert ctrip['provider_identity']['merchant_of_record']=='CTRIP'


@pytest.mark.parametrize('changed,reason',[
    ({'adults':1},'COMPARISON_BASIS_MISMATCH'),
    ({'tax_fee_basis':'EXCLUDES_TAXES'},'COMPARISON_BASIS_MISMATCH'),
    ({'verified_for_user_id':'another-user'},'CURRENT_CONSUMER_VERIFICATION_REQUIRED'),
    ({'verification_source':'USER_SCREENSHOT'},'OFFICIAL_ADAPTER_VERIFICATION_REQUIRED'),
    ({'provider_quote_id':''},'PROVIDER_QUOTE_ID_REQUIRED'),
    ({'hotel_id':''},'HOTEL_ID_REQUIRED_FOR_PRICE_COMPARISON'),
])
def test_unverified_or_different_basis_amount_is_suppressed(changed,reason):
    now=datetime(2026,9,18,10,0,tzinfo=timezone.utc)
    ctrip=next(x for x in comparison.options('consumer-comparison',SEARCH,[quote(now,**changed)],now)['providers'] if x['provider']=='CTRIP')
    assert ctrip['member_price_status']=='QUOTE_SUPPRESSED'
    assert ctrip['eligible_for_price_comparison'] is False
    assert ctrip['verified_member_price'] is None
    assert reason in ctrip['suppression_reasons']
    assert 'total_amount_minor' not in ctrip


def test_stale_or_expired_quote_amount_is_suppressed():
    now=datetime(2026,9,18,10,0,tzinfo=timezone.utc)
    stale=quote(now,observed_at=(now-timedelta(minutes=6)).isoformat(),expires_at=(now-timedelta(seconds=1)).isoformat())
    ctrip=next(x for x in comparison.options('consumer-comparison',SEARCH,[stale],now)['providers'] if x['provider']=='CTRIP')
    assert {'QUOTE_STALE','QUOTE_EXPIRED'} <= set(ctrip['suppression_reasons'])
    assert ctrip['verified_member_price'] is None


def test_unofficial_or_incomplete_deep_link_is_suppressed(monkeypatch):
    monkeypatch.setenv('GO_CTRIP_CONSUMER_DEEP_LINK','https://evil.example/search?checkin={checkin}&checkout={checkout}&rooms={rooms}&adults={adults}&children={children}')
    ctrip=next(x for x in comparison.options('consumer-comparison',SEARCH)['providers'] if x['provider']=='CTRIP')
    assert ctrip['deep_link'] is None
    assert ctrip['deep_link_status']=='SUPPRESSED_UNVERIFIED_PROVIDER_DESTINATION'
    monkeypatch.setenv('GO_CTRIP_CONSUMER_DEEP_LINK','ctrip://hotel/search?checkin={checkin}&checkout={checkout}')
    ctrip=next(x for x in comparison.options('consumer-comparison',SEARCH)['providers'] if x['provider']=='CTRIP')
    assert ctrip['deep_link'] is None
    assert ctrip['deep_link_status']=='SUPPRESSED_INCOMPLETE_SEARCH_BASIS'


def test_member_context_api_returns_explicit_comparison_contract(monkeypatch):
    from go_hotel.api.routes.hotel import member_context_search
    from go_hotel.api.schemas import SearchRequest
    from go_hotel.security.service import Principal

    async def fake_search(*args):
        return [SimpleNamespace(offer_id='go-1',hotel_id='hotel-1',total_amount_minor=90000,currency='JPY',official_direct=True)]
    monkeypatch.setattr('go_hotel.api.routes.hotel.booking_service.search',fake_search)
    body=SearchRequest(destination={'city_code':'TYO'},stay={'check_in':'2026-10-01','check_out':'2026-10-02'},
                       occupancy={'rooms':2,'adults':3,'children':1},currency='JPY')
    principal=Principal('api-consumer','compare@example.com','CONSUMER',None,['CONSUMER'],'session',set())
    data=asyncio.run(member_context_search(body,principal))['data']
    assert data['comparison_basis']['rooms']==2 and data['comparison_basis']['adults']==3
    assert data['comparison_basis']['children']==1 and data['comparison_basis']['currency']=='JPY'
    assert data['misleading_price_prevention']['login_only_deep_links_are_not_prices'] is True
    assert all(x['verified_member_price'] is None for x in data['ota_options'])
    assert data['go_offers'][0]['eligible_for_cross_provider_price_comparison'] is False


def test_invalid_comparison_basis_fails_closed():
    with pytest.raises(ValueError,match='INVALID_OTA_COMPARISON_BASIS'):
        comparison.options('consumer-comparison',SEARCH|{'check_out':'2026-09-30'})

