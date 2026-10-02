"""Nationwide draft onboarding remains scoped and audit-atomic."""
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from go_hotel.api.routes.bff import SupplierRegisterBody, supplier_registration_terms
from go_hotel.services.supplier_onboarding import supplier_onboarding_service
from go_hotel.db.models import IdentityUserRow, HotelPartnerPropertyRow
from go_hotel.db.session import SessionLocal


def test_registration_scope_and_free_text_locations():
    policy = supplier_registration_terms()['data']
    assert policy['registration_scope'] == 'NATIONWIDE'
    assert policy['publication_requires_verification'] is True
    for city in ['哈尔滨', '拉萨', '喀什', '三亚', '县级自定义地区']:
        body = SupplierRegisterBody(email='owner@example.test', password='strong-pass-123',
            organization_name='酒店主体', contact_name='联系人', hotel_name='测试酒店', city=city)
        assert body.city == city
    with pytest.raises(ValidationError):
        SupplierRegisterBody(email='owner@example.test', password='strong-pass-123',
            organization_name='   ', contact_name='联系人')


def test_registration_audit_failure_rolls_back_account_and_hotel():
    def failed_audit(*args):
        raise RuntimeError('AUDIT_NOT_WRITABLE')
    body={'username':'atomic-registration@example.test','password':'strong-pass-123',
          'hotel':{'name_zh':'测试酒店','property_type':'HOTEL'}}
    with pytest.raises(RuntimeError, match='AUDIT_NOT_WRITABLE'):
        supplier_onboarding_service.register(body, audit_factory=failed_audit)
    with SessionLocal() as session:
        assert session.scalar(select(IdentityUserRow).where(IdentityUserRow.username==body['username'])) is None
        assert session.scalar(select(HotelPartnerPropertyRow).where(HotelPartnerPropertyRow.name_zh=='测试酒店')) is None
    result=supplier_onboarding_service.register(body)
    with SessionLocal() as session:
        hotel=session.get(HotelPartnerPropertyRow,result['property_id'])
        assert hotel.publication_state=='DRAFT'
        assert hotel.operations_json['ownership']['status']=='DECLARED'
        assert hotel.operations_json['ownership']['verification_required_before_publication'] is True


@pytest.mark.parametrize('email',['@','a@','@b.test','a b@c.test','a@b'])
def test_invalid_email_never_creates_supplier(email):
    with pytest.raises(ValueError,match='VALID_EMAIL_REQUIRED'):
        supplier_onboarding_service.register({'username':email,'password':'strong-pass-123','hotel':{'name_zh':'测试','property_type':'HOTEL'}})


def test_client_cannot_request_admin_roles():
    with pytest.raises(ValidationError):
        SupplierRegisterBody(email='owner@example.test',password='strong-pass-123',organization_name='主体',contact_name='联系人',roles=['GO_ADMIN'])
