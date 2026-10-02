from pathlib import Path


def test_new_consumer_routes_are_exposed_by_the_application():
    main = Path("src/go_hotel/main.py").read_text()
    assert "from go_hotel.api.routes.consumer_unified_lifecycle import router as consumer_unified_lifecycle_router" in main
    assert "from go_hotel.api.routes.personal_travel_vault import router as personal_travel_vault_router" in main
    assert "app.include_router(consumer_unified_lifecycle_router)" in main
    assert "app.include_router(personal_travel_vault_router)" in main

    hotel = Path("src/go_hotel/api/routes/hotel.py").read_text()
    profile = Path("src/go_hotel/api/routes/personal_travel_vault.py").read_text()
    trips = Path("src/go_hotel/api/routes/consumer_unified_lifecycle.py").read_text()
    assert "'/search/hotels/member-context'" in hotel
    assert "'/v1/consumer/profile/provider-connections'" in profile
    assert "'/v1/consumer/unified-trips/external-orders'" in trips


def test_member_context_route_forwards_the_complete_comparison_scope():
    source = Path("src/go_hotel/api/routes/hotel.py").read_text()
    for expression in (
        "'city_code':body.destination.city_code",
        "'check_in':body.stay.check_in",
        "'check_out':body.stay.check_out",
        "'adults':body.occupancy.adults",
        "'children':body.occupancy.children",
        "'rooms':body.occupancy.rooms",
        "'currency':body.currency",
    ):
        assert expression in source


def test_consumer_surfaces_are_wired_to_account_linking_and_unified_trips():
    mobile = Path("mobile/go-app/src/screens/TravelProfileImportScreen.tsx").read_text()
    trips = Path("mobile/go-app/src/screens/TripsScreen.tsx").read_text()
    app = Path("mobile/go-app/App.tsx").read_text()
    assert "/v1/consumer/profile/provider-connections" in mobile
    assert 'name="TravelProfileImport"' in app
    assert "/v1/consumer/unified-trips" in trips


def test_external_activation_remains_explicit_instead_of_claiming_live_prices():
    source = Path("src/go_hotel/services/consumer_ota_comparison.py").read_text()
    assert "VISIBLE_AFTER_PROVIDER_LOGIN" in source
    assert "FINAL_PRICE_REVALIDATED_BY_PROVIDER_AT_CHECKOUT" in source
    assert '"credentials_received_by_go": False' in source
    assert '"login_only_deep_links_are_not_prices": True' in source
