from pathlib import Path
import re
import json
ROOT=Path(__file__).resolve().parents[1]
errors=[]
sec=(ROOT/'src/go_hotel/security/service.py').read_text()
bff=(ROOT/'src/go_hotel/api/routes/bff.py').read_text()
app=(ROOT/'frontend/shared/app.js').read_text()
api=(ROOT/'frontend/shared/api.js').read_text()
supplier=(ROOT/'frontend/supplier/config.js').read_text()
admin=(ROOT/'frontend/admin/config.js').read_text()
styles=(ROOT/'frontend/shared/styles.css').read_text()
for token in ["purpose':'MFA_ENROLLMENT'",'begin_admin_mfa_enrollment','confirm_admin_mfa_enrollment','PASSWORD_MFA_ENROLLMENT']:
    if token not in sec: errors.append('MFA_FLOW_MISSING:'+token)
for token in ['/bff/auth/mfa/enroll/start','/bff/auth/mfa/enroll/confirm']:
    if token not in bff: errors.append('MFA_ENDPOINT_MISSING:'+token)
for token in ['startMfaEnrollment','confirmMfaEnrollment']:
    if token not in api: errors.append('FRONTEND_MFA_API_MISSING:'+token)
for token in ['首次 MFA 绑定','确认绑定并登录','MFA_ENROLLMENT_REQUIRED']:
    if token not in app: errors.append('FRONTEND_MFA_UI_MISSING:'+token)
if "settings.mfa_required_for_admin and u.actor_type=='GO_ADMIN'" not in sec: errors.append('ADMIN_MFA_FORCE_MISSING')
if "if must_mfa and not u.mfa_enabled_at: raise ValueError('MFA_ENROLLMENT_REQUIRED')" not in sec: errors.append('MFA_ENROLLMENT_GATE_MISSING')
for token in ['GO 合作伙伴平台','经营中心','订单与履约','促销与权益','经营数据','财务','业务管理','异常中心','全品类能力','酒店资料','房型管理','房态房价','内容与媒体','通知中心']:
    if token not in supplier: errors.append('SUPPLIER_ZH_MISSING:'+token)
for token in ['GO 运营管理系统','全局运行状态','风险事件','GO 判断证据','支付运营','财务对账','审计日志']:
    if token not in admin: errors.append('ADMIN_ZH_MISSING:'+token)

if '<h1>${esc(config.title)}</h1>' not in app: errors.append('ADMIN_LOGIN_TITLE_PREFIX_FIX_MISSING')
if "INVALID_CREDENTIALS:'用户名或密码错误'" not in app: errors.append('ADMIN_LOGIN_ERROR_ZH_MISSING')
admin_tool=(ROOT/'scripts/staging_admin_account.py').read_text()
for token in ['getpass.getpass','APP_ENV must be staging','password_output=NEVER_PRINTED','--reset-mfa']:
    if token not in admin_tool: errors.append('STAGING_ADMIN_TOOL_MISSING:'+token)

# RC10.3: mobile core navigation must never depend on horizontal scrolling.
if 'overflow-x:auto!important' in styles.replace(' ','').lower(): errors.append('MOBILE_NAV_HORIZONTAL_SCROLL_DEPENDENCY')
if '.home-nav,.supplier-mobile-bottom,.admin-mobile-bottom{overflow-x:hidden!important;max-width:100vw}' not in styles: errors.append('MOBILE_BOTTOM_NAV_NO_OVERFLOW_GUARD_MISSING')
if '.supplier-mobile-bottom{display:grid;grid-template-columns:repeat(5,1fr)' not in styles: errors.append('SUPPLIER_MOBILE_BOTTOM_GRID_MISSING')
if '.admin-mobile-bottom{display:grid;grid-template-columns:repeat(5,1fr)' not in styles: errors.append('ADMIN_MOBILE_BOTTOM_GRID_MISSING')
manifest=json.loads((ROOT/'CURRENT_RELEASE_MANIFEST.json').read_text(encoding='utf-8'))
CURRENT_ASSET_TOKEN=manifest.get('release_integrity',{}).get('console_asset_cache_token')
if not CURRENT_ASSET_TOKEN: errors.append('CURRENT_ASSET_TOKEN_MISSING_FROM_MANIFEST')
cache_expectations={
    'frontend/supplier/index.html':('/console-assets/styles.css','/console-assets/app.js'),
    'frontend/admin/index.html':('/console-assets/styles.css','/console-assets/app.js'),
}
for rel,assets in cache_expectations.items():
    text=(ROOT/rel).read_text(encoding='utf-8')
    for asset in assets:
        expected=asset+'?v='+str(CURRENT_ASSET_TOKEN)
        if expected not in text: errors.append('CACHE_BUSTER_MISSING:'+rel+':'+expected)
    for m in re.finditer(r'(?:src|href)="([^"]+\.(?:js|css))(?:\?v=([^"]+))?"', text):
        url,token=m.group(1),m.group(2)
        if url.startswith(('/console-assets/','/supplier-console/','/go-admin/')) and token != CURRENT_ASSET_TOKEN:
            errors.append('CACHE_BUSTER_STALE:'+rel+':'+url+':'+str(token or 'NONE'))

if errors:
    print('R8.2_ADMIN_ACCESS_ZH_GATE: BLOCK')
    print('\n'.join(errors))
    raise SystemExit(1)
print('admin_first_mfa_enrollment=PASS')
print('admin_mfa_no_bypass=PASS')
print('supplier_primary_nav_zh=PASS')
print('admin_primary_nav_zh=PASS')
print('admin_login_title=PASS')
print('admin_login_error_localization=PASS')
print('staging_admin_account_tool=PASS')
print('mobile_nav_overflow_guard=PASS')
print('R8.2_ADMIN_ACCESS_ZH_GATE: PASS')
