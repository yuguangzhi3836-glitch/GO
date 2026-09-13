from pathlib import Path
import pytest
pytestmark=pytest.mark.no_db


def test_autopage_contract_symbols_exist():
    root=Path(__file__).resolve().parents[1]
    service=(root/'src/go_hotel/services/hotel_autopage_factory.py').read_text()
    routes=(root/'src/go_hotel/api/routes/hotel_autopage_factory.py').read_text()
    for symbol in ['HotelAutoPageFactoryService','def ingest','def compose','def public_page','def register_for_go_direct','def decide_registration_direct','def suppress_contact']:
        assert symbol in service
    assert "@router.get('/v1/hotel-pages/{slug}')" in routes
    assert "hotel_registration_required_for_page':False" in service
    assert "automatic_send_allowed':False" in service


def test_source_rights_and_prebuilt_page_principles_are_fail_closed():
    root=Path(__file__).resolve().parents[1]
    service=(root/'src/go_hotel/services/hotel_autopage_factory.py').read_text()
    assert "ALLOWED_RIGHTS={'AUTHORIZED','HOTEL_SUBMITTED','PUBLIC_BUSINESS_FACT','DISTRIBUTION_LICENSE'}" in service
    assert "CONTENT_RIGHTS_NOT_ALLOWED" in service
    assert "GO_PREBUILT_HOTEL_PAGE" in service
    assert "NOT_REGISTERED" in service and "GO_DIRECT_VERIFIED" in service
    assert "JURISDICTION_POLICY_GATE_REQUIRED" in service
