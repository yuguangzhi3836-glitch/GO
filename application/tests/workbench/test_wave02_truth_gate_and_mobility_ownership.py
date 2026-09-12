import json
from pathlib import Path

import pytest

from go_hotel.attractions.service import attraction_service
from go_hotel.core.config import settings
from go_hotel.mobility.rental.service import rental_service
from go_hotel.mobility.ride.service import ride_service
from go_hotel.rail.service import rail_service


def test_engineering_supplier_fixtures_fail_closed_in_production(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    calls = [
        lambda: rail_service.search("SHA", "HZH", "2026-09-01"),
        lambda: ride_service.search("PVG", "Bund", "2026-09-01T10:00:00"),
        lambda: rental_service.search("NRT", "NRT", "2026-09-02T09:00:00", "2026-09-05T09:00:00"),
        lambda: attraction_service.search("东京", "2026-09-03"),
    ]
    for call in calls:
        with pytest.raises(ValueError, match="PROVIDER_TRUTH_REQUIRED"):
            call()


def test_engineering_supplier_fixtures_are_explicitly_non_live_locally(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "local")
    assert all(x["external_live"] is False for x in rail_service.search("SHA", "HZH", "2026-09-01"))
    assert all(x["external_live"] is False for x in ride_service.search("PVG", "Bund", "2026-09-01T10:00:00"))
    assert all(x["external_live"] is False for x in rental_service.search("NRT", "NRT", "2026-09-02T09:00:00", "2026-09-05T09:00:00"))
    assert all(x["external_live"] is False for x in attraction_service.search("东京", "2026-09-03"))


def test_c04_c05_owned_paths_are_isolated_and_shared_facade_has_no_business_truth():
    root = Path(__file__).resolve().parents[2]
    c04 = json.loads((root / "governance/workbench/cell_charters/C04_CELL_CHARTER.json").read_text())
    c05 = json.loads((root / "governance/workbench/cell_charters/C05_CELL_CHARTER.json").read_text())
    assert c04["domain"] == "RENTAL"
    assert c05["domain"] == "RIDE"
    assert "src/go_hotel/mobility/rental/" in c04["owned_paths"]
    assert "src/go_hotel/mobility/ride/" in c05["owned_paths"]
    assert "src/go_hotel/mobility/service.py" in c04["forbidden_paths"]
    assert "src/go_hotel/mobility/service.py" in c05["forbidden_paths"]
    facade = (root / "src/go_hotel/mobility/service.py").read_text()
    for forbidden in ["16800", "26800", "126000", "198000", "supplier_reference=", "RideFlightTrackingBindingRow"]:
        assert forbidden not in facade


def test_public_synthetic_supplier_routes_return_503_in_production(client, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    cases = [
        ("/v1/rail/search", {"origin_station": "SHA", "destination_station": "HZH", "travel_date": "2026-09-01", "currency": "CNY"}),
        ("/v1/mobility/rides/search", {"pickup": "PVG", "dropoff": "Bund", "pickup_at": "2026-09-01T10:00:00", "currency": "CNY"}),
        ("/v1/mobility/rentals/search", {"pickup_location": "NRT", "return_location": "NRT", "pickup_at": "2026-09-02T09:00:00", "return_at": "2026-09-05T09:00:00", "currency": "CNY"}),
        ("/v1/attractions/search", {"destination": "东京", "visit_date": "2026-09-03", "currency": "CNY"}),
    ]
    for path, payload in cases:
        r = client.post(path, json=payload)
        assert r.status_code == 503, (path, r.status_code, r.text)
        assert "PROVIDER_TRUTH_REQUIRED" in r.text
