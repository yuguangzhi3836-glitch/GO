from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_consumer_has_no_demo_transaction_facts():
    text='\n'.join(p.read_text() for p in (ROOT/'mobile/go-app/src').rglob('*.tsx'))
    forbidden=['visual-','const demo','const fallback','东京银座','4111111111111111','GO-TYO-','387200','无后端时使用展示模式']
    for token in forbidden:
        assert token not in text, token

def test_identity_operating_surfaces_are_wired():
    shared=(ROOT/'frontend/shared/app.js').read_text()
    supplier=(ROOT/'frontend/supplier/config.js').read_text()
    admin=(ROOT/'frontend/admin/config.js').read_text()
    routes=(ROOT/'src/go_hotel/api/routes/go_identity_entitlements.py').read_text()
    for token in ['supplierIdentityPrograms','adminIdentityQueue','revalidation/tick','risk-signals','friends-family-invitations/{invitation_id}/consume']:
        assert token in shared+supplier+admin+routes
    assert 'demoUser' not in supplier

