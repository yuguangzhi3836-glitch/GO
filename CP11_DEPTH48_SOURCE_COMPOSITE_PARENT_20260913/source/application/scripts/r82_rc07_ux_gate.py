from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
checks=[]
def need(path,needle):
    text=(ROOT/path).read_text(encoding='utf-8')
    if needle not in text: raise SystemExit(f'R8.2_RC07_UX_GATE: BLOCK\nMISSING:{path}:{needle}')
asset_token=json.loads((ROOT/'CURRENT_RELEASE_MANIFEST.json').read_text(encoding='utf-8')).get('release_integrity',{}).get('console_asset_cache_token')
assert asset_token and ('hosted-direct.js?v='+asset_token) in (ROOT/'frontend/consumer/direct.html').read_text(encoding='utf-8'), 'frontend/consumer/direct.html:current cache buster missing'
need('frontend/consumer/hosted-direct.js','公开渠道历史参考')
need('frontend/consumer/hosted-direct.js','GO 当前测试报价')
need('frontend/consumer/hosted-direct.js','未接真实支付')
assert asset_token and ('admin-ux.js?v='+asset_token) in (ROOT/'frontend/admin/index.html').read_text(), 'frontend/admin/index.html:admin-ux current cache buster missing'
need('frontend/admin/admin-ux.js','运营总览')
need('frontend/shared/app.js','交易状态与证据')
need('frontend/shared/app.js','供应商与其银行/PSP之间的最终财务对账由供应商自行完成')
need('frontend/shared/app.js','loadAdminMfaPolicy')
assert any(x in (ROOT/'frontend/shared/app.js').read_text() for x in ['技术诊断','技术信息 / 高级信息','技术信息']), 'frontend/shared/app.js:technical diagnostics label missing'
need('src/go_hotel/api/routes/bff.py',"@router.get('/bff/auth/policy')")
need('frontend/shared/styles.css','.admin-mobile-bottom')
print('R8.2_RC07_UX_GATE: PASS')
