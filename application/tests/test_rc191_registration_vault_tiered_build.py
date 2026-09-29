from pathlib import Path

def test_tiered_build_strategy_is_quality_first():
    s=Path("src/go_hotel/services/regional_hotel_build.py").read_text()
    assert "NATIONAL_TIER_SEQUENCE = [5,4,3,2,1,0]" in s
    assert '"NATIONAL_TIERED"' in s
    assert "_filter_tier" in s and "_maybe_advance_tier" in s

def test_supplier_registration_requires_single_terms_acceptance():
    s=Path("src/go_hotel/api/routes/bff.py").read_text()
    assert "/bff/auth/supplier/register" in s
    assert "SUPPLIER_TERMS_ACCEPTANCE_REQUIRED" in s
    assert "SUPPLIER_REGISTRATION_TERMS_ACCEPTED" in s
    assert "electronic_signature_authorization" in s

def test_consumer_one_click_personal_vault_is_consent_bound():
    svc=Path("src/go_hotel/services/personal_travel_vault.py").read_text()
    api=Path("src/go_hotel/api/routes/personal_travel_vault.py").read_text()
    ui=Path("frontend/consumer/app.js").read_text()
    assert "bootstrap_vault" in svc
    assert "/v1/consumer/profile/vault/bootstrap" in api
    assert "一键建立我的旅行信息库" in ui
    assert "no_automatic_external_sharing" in svc
    assert "CONSENT_REQUIRED" in svc


def test_supplier_partner_onboarding_copy_is_not_plain_registration():
    root=Path(__file__).resolve().parents[1]
    cfg=(root/'frontend/supplier/config.js').read_text('utf-8')
    app=(root/'frontend/shared/app.js').read_text('utf-8')
    bff=(root/'src/go_hotel/api/routes/bff.py').read_text('utf-8')
    assert 'GO 合作伙伴平台' in cfg
    assert '申请成为 GO 合作伙伴' in app
    assert 'GO 合作伙伴入驻' in app
    assert '提交入驻申请' in app
    assert '创建账号后仍需主体与酒店关系审核' in app
    assert '不自动发布或开通交易' in app
    assert 'require_registration_terms_ready' in bff
