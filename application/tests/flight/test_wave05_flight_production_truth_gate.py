from go_hotel.core.config import settings
from go_hotel.flight.service import flight_service


def test_flight_fixture_search_fails_closed_in_production(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    try:
        flight_service.search("PVG", "NRT", "2026-09-01")
        assert False, "production fixture path must fail closed"
    except ValueError as exc:
        assert str(exc) == "FLIGHT_PROVIDER_TRUTH_REQUIRED:SEARCH"


def test_flight_fixture_search_not_blocked_by_truth_gate_in_local(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "local")
    # Do not execute DB-backed search here; parity assertion is that the gate itself only blocks production.
    from go_hotel.core.production_truth_gate import production_truth_required
    production_truth_required("FLIGHT", "SEARCH")
