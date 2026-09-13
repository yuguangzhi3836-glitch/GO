from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_two_frontends_exist():
    assert (ROOT/'frontend/supplier/index.html').exists()
    assert (ROOT/'frontend/admin/index.html').exists()
def test_supplier_never_sends_supplier_id():
    text=(ROOT/'frontend/supplier/index.html').read_text()+(ROOT/'frontend/shared/app.js').read_text()
    assert 'supplier_id=' not in text
    assert 'supplier_id:' not in text
def test_admin_has_operational_planes():
    t=(ROOT/'frontend/admin/index.html').read_text()
    for p in ['/internal/v1/admin/orders','/internal/v1/admin/refunds','/internal/v1/admin/liabilities','/internal/v1/admin/risk-cases','/internal/v1/admin/judgments','/internal/v1/admin/connectors','/internal/v1/admin/settlement']:
        assert p in t
def test_auth_client_refresh_and_logout():
    t=(ROOT/'frontend/shared/api.js').read_text()
    assert '/v1/auth/refresh' in t and '/v1/auth/logout' in t and 'Bearer' in t
def test_no_direct_mutation_routes():
    t=''.join(p.read_text() for p in (ROOT/'frontend').rglob('*.js'))
    forbidden=['/go-score/patch','/recommendation/patch','/ledger/update','/refund/status/patch']
    assert all(x not in t for x in forbidden)
