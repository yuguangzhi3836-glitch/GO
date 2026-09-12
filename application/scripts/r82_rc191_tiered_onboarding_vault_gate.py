#!/usr/bin/env python3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
errors=[]
regional=(ROOT/'src/go_hotel/services/regional_hotel_build.py').read_text('utf-8')
bff=(ROOT/'src/go_hotel/api/routes/bff.py').read_text('utf-8')
app=(ROOT/'frontend/shared/app.js').read_text('utf-8')
cfg=(ROOT/'frontend/supplier/config.js').read_text('utf-8')
consumer=(ROOT/'frontend/consumer/app.js').read_text('utf-8')
vault=(ROOT/'src/go_hotel/services/personal_travel_vault.py').read_text('utf-8')
for token in ['NATIONAL_TIER_SEQUENCE = [5,4,3,2,1,0]','"NATIONAL_TIERED"','_filter_tier','_maybe_advance_tier']:
    if token not in regional: errors.append('TIERED_BUILD_MISSING:'+token)
for token in ['/bff/auth/supplier/register','SUPPLIER_TERMS_ACCEPTANCE_REQUIRED','SUPPLIER_REGISTRATION_TERMS_ACCEPTED','electronic_signature_authorization','GO 合作伙伴服务协议']:
    if token not in bff: errors.append('PARTNER_ONBOARDING_API_MISSING:'+token)
for token in ['GO 合作伙伴平台']:
    if token not in cfg: errors.append('PARTNER_PLATFORM_COPY_MISSING:'+token)
for token in ['申请成为 GO 合作伙伴','GO 合作伙伴入驻','提交入驻申请','创建账号不代表已审核或已开通交易']:
    if token not in app: errors.append('PARTNER_ONBOARDING_UI_MISSING:'+token)
for token in ['注册 GO ID','一键建立我的旅行信息库']:
    if token not in consumer: errors.append('CONSUMER_VAULT_UI_MISSING:'+token)
for token in ['bootstrap_vault','no_automatic_external_sharing','CONSENT_REQUIRED']:
    if token not in vault: errors.append('CONSUMER_VAULT_CONTROL_MISSING:'+token)
if errors:
    print('R8.2_RC19_1_TIERED_ONBOARDING_VAULT_GATE: BLOCK')
    print('\n'.join(errors)); raise SystemExit(1)
print('national_tiered_build=PASS')
print('partner_onboarding_single_sign=PASS')
print('consumer_registration_and_vault=PASS')
print('R8.2_RC19_1_TIERED_ONBOARDING_VAULT_GATE: PASS')
