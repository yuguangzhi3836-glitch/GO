from pathlib import Path
import re
import json

ROOT=Path(__file__).resolve().parents[1]
errors=[]
app=(ROOT/'frontend/shared/app.js').read_text(encoding='utf-8')
for fn in ('enterpriseRiskForecast','riskForecastCalibration'):
    m=re.search(rf'async function {fn}\(\).*?(?=\nasync function |\nconst |\nexport |\Z)', app, re.S)
    if not m:
        errors.append(f'MISSING_FUNCTION:{fn}')
    elif '};}' in m.group(0):
        errors.append(f'EXTRA_CLOSURE:{fn}')

CURRENT_ASSET_TOKEN=json.loads((ROOT/'CURRENT_RELEASE_MANIFEST.json').read_text(encoding='utf-8')).get('release_integrity',{}).get('console_asset_cache_token')
if not CURRENT_ASSET_TOKEN: errors.append('CURRENT_ASSET_TOKEN_MISSING_FROM_MANIFEST')
cache_expectations={
    'frontend/supplier/index.html':('/console-assets/styles.css','/console-assets/app.js'),
    'frontend/admin/index.html':('/console-assets/styles.css','/console-assets/app.js'),
}
for rel,assets in cache_expectations.items():
    text=(ROOT/rel).read_text(encoding='utf-8')
    for asset in assets:
        expected=asset+'?v='+CURRENT_ASSET_TOKEN
        if expected not in text:
            errors.append(f'CACHE_BUSTER_MISSING:{rel}:{expected}')
    for m in re.finditer(r'(?:src|href)="([^"]+\.(?:js|css))(?:\?v=([^"]+))?"', text):
        url,token=m.group(1),m.group(2)
        if url.startswith(('/console-assets/','/supplier-console/','/go-admin/')) and token != CURRENT_ASSET_TOKEN:
            errors.append(f'CACHE_BUSTER_STALE:{rel}:{url}:{token or "NONE"}')

sec=(ROOT/'src/go_hotel/security/service.py').read_text(encoding='utf-8')
required="if not ses or ses.status!='ACTIVE' or aware(ses.expires_at)<now() or not u or u.status!='ACTIVE': raise ValueError('SESSION_REVOKED')"
if required not in sec:
    errors.append('REFRESH_SESSION_EXPIRY_GUARD_MISSING')
if "if must_mfa and not u.mfa_enabled_at: raise ValueError('MFA_ENROLLMENT_REQUIRED')" not in sec:
    errors.append('MFA_ENROLLMENT_GATE_MISSING')
if "settings.mfa_required_for_admin and u.actor_type=='GO_ADMIN'" not in sec:
    errors.append('ADMIN_MFA_REQUIREMENT_LOGIC_MISSING')

env=(ROOT/'deploy/.env.hk-staging.example').read_text(encoding='utf-8')
if not re.search(r'^MFA_REQUIRED_FOR_ADMIN=true\s*$',env,re.M):
    errors.append('STAGING_ADMIN_MFA_NOT_FORCED')

docker=(ROOT/'Dockerfile').read_text(encoding='utf-8')
if not re.search(r'^COPY\s+frontend\s+\./frontend\s*$',docker,re.M):
    errors.append('DOCKER_FRONTEND_COPY_MISSING')

if errors:
    print('R8.2_CONSOLE_SESSION_GATE: BLOCK')
    for e in errors: print(e)
    raise SystemExit(1)
print('target_functions_extra_closure=0')
print('cache_buster_supplier=PASS')
print('cache_buster_admin=PASS')
print('refresh_session_expiry_guard=PASS')
print('admin_mfa_force_and_enrollment_gate=PASS')
print('docker_frontend_copy=PASS')
print('R8.2_CONSOLE_SESSION_GATE: PASS')
