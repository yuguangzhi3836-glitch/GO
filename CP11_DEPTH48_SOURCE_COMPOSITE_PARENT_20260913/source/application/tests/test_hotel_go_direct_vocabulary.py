from pathlib import Path

def test_go_direct_is_single_product_vocabulary():
    root=Path(__file__).resolve().parents[1]
    service=(root/'src/go_hotel/services/hotel_autopage_factory.py').read_text()
    routes=(root/'src/go_hotel/api/routes/hotel_autopage_factory.py').read_text()
    models=(root/'src/go_hotel/db/models.py').read_text()
    migration=(root/'alembic/versions/0108_hotel_go_direct_semantics.py').read_text()
    for symbol in ['register_for_go_direct','GO_DIRECT_VERIFIED','GO_DIRECT_LIVE','HOTEL_GO_DIRECT_VERIFIED','go_direct_state']:
        assert symbol in service or symbol in models or symbol in migration
    assert 'hotel_registration_go_direct' in models
    assert 'go-direct-registration' in routes
    assert 'go-direct-registrations' in routes
    assert "revision='0108_hotel_go_direct_semantics'" in migration
    # Old terms may exist in historical migrations/routing truth, but not in active AutoPage product API/service.
    assert 'register_for_official_direct' not in service
    assert 'official-direct-registration' not in routes
    assert 'official-direct-registrations' not in routes

def test_go_direct_verified_does_not_fake_live_transaction():
    root=Path(__file__).resolve().parents[1]
    service=(root/'src/go_hotel/services/hotel_autopage_factory.py').read_text()
    assert "p.go_direct_state='GO_DIRECT_VERIFIED'" in service
    assert "'transaction':{'route':'UNRESOLVED_UNTIL_SUPPLY_QUERY','official_direct':False}" in service
