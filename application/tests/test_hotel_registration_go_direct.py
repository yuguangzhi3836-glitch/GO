from pathlib import Path

def test_go_direct_vocabulary_and_migration():
    root=Path(__file__).resolve().parents[1]
    service=(root/'src/go_hotel/services/hotel_autopage_factory.py').read_text()
    models=(root/'src/go_hotel/db/models.py').read_text()
    routes=(root/'src/go_hotel/api/routes/hotel_autopage_factory.py').read_text()
    migration=(root/'alembic/versions/0108_hotel_go_direct_semantics.py').read_text()
    for symbol in ['def register_for_go_direct','def decide_registration_direct','HOTEL_GO_DIRECT_VERIFIED','GO_DIRECT_VERIFIED','REGISTRATION_PENDING','NOT_REGISTERED']:
        assert symbol in service
    assert 'hotel_registration_go_direct' in models
    assert 'go_direct_state' in models
    assert 'go-direct-registration' in routes
    assert 'go-direct-registrations' in routes
    assert "revision='0108_hotel_go_direct_semantics'" in migration
    assert "down_revision='0107_166151c9cc6e'" in migration
    predecessor=(root/'alembic/versions/0107_hotel_official_direct_semantics.py').read_text()
    assert "revision='0107_166151c9cc6e'" in predecessor

def test_registration_verification_does_not_claim_live_transaction():
    root=Path(__file__).resolve().parents[1]
    service=(root/'src/go_hotel/services/hotel_autopage_factory.py').read_text()
    assert "p.go_direct_state='GO_DIRECT_VERIFIED'" in service
    assert "'transaction':{'route':'UNRESOLVED_UNTIL_SUPPLY_QUERY','official_direct':False}" in service
    assert "p.go_direct_state='GO_DIRECT_LIVE'" not in service

def test_legacy_claim_product_terms_absent_from_active_autopage_code():
    root=Path(__file__).resolve().parents[1]
    active='\n'.join((root/x).read_text() for x in [
        'src/go_hotel/services/hotel_autopage_factory.py',
        'src/go_hotel/api/routes/hotel_autopage_factory.py',
        'src/go_hotel/db/models.py',
    ])
    for legacy in ['HotelPageClaimRow','request_claim','approve_claim','HOTEL_CLAIMED','UNCLAIMED','CLAIM_PENDING','hotel_page_claim','official_association_state','OFFICIAL_ASSOCIATED']:
        assert legacy not in active
