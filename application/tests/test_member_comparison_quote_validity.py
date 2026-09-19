"""Regression cases for quote validity and strict occupancy equivalence."""

from datetime import datetime, timedelta, timezone

import pytest

from go_hotel.services.consumer_ota_comparison import consumer_ota_comparison_service as comparison


NOW = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)
USER_ID = "comparison-validity-consumer"
SEARCH = {
    "city_code": "SHA", "hotel_id": "hotel-validity-1",
    "check_in": "2026-10-01", "check_out": "2026-10-02",
    "rooms": 1, "adults": 1, "children": 0, "currency": "CNY",
}


def verified_quote():
    return SEARCH | {
        "provider": "CTRIP", "provider_quote_id": "validity-quote-1",
        "total_amount_minor": 88000, "price_basis": "STAY_TOTAL",
        "tax_fee_basis": "INCLUDES_MANDATORY_TAXES_AND_FEES",
        "verified_for_user_id": USER_ID, "account_holder_authorized": True,
        "verification_source": "OFFICIAL_PROVIDER_ADAPTER", "member_tier": "DIAMOND",
        "observed_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(minutes=3)).isoformat(),
    }


def ctrip_result(quote, now=NOW):
    result = comparison.options(USER_ID, SEARCH, [quote], now)
    return next(item for item in result["providers"] if item["provider"] == "CTRIP")


def assert_suppressed(result, reason):
    assert reason in result["suppression_reasons"]
    assert result["eligible_for_price_comparison"] is False
    assert result["member_price_status"] == "QUOTE_SUPPRESSED"
    assert result["verified_member_price"] is None
    assert "total_amount_minor" not in result


@pytest.mark.parametrize("expiry", [None, "", "not-a-date", "2026-99-99T10:00:00Z", 12345])
def test_missing_or_unparseable_expiry_cannot_be_a_rankable_member_price(expiry):
    assert_suppressed(ctrip_result(verified_quote() | {"expires_at": expiry}), "QUOTE_EXPIRES_AT_REQUIRED")


def test_omitted_expiry_is_not_an_unlimited_quote():
    quote = verified_quote()
    quote.pop("expires_at")
    assert_suppressed(ctrip_result(quote), "QUOTE_EXPIRES_AT_REQUIRED")


@pytest.mark.parametrize("field,value", [
    ("rooms", True), ("rooms", 1.0),
    ("adults", True), ("adults", 1.0),
    ("children", False), ("children", 0.0),
])
def test_boolean_or_float_occupancy_cannot_pass_integer_basis_equality(field, value):
    assert_suppressed(ctrip_result(verified_quote() | {field: value}), "COMPARISON_BASIS_MISMATCH")


def test_valid_member_quote_remains_eligible_until_exact_expiration():
    quote = verified_quote()
    before = ctrip_result(quote, NOW + timedelta(minutes=3, microseconds=-1))
    assert before["eligible_for_price_comparison"] is True
    assert before["suppression_reasons"] == []
    assert before["verified_member_price"]["total_amount_minor"] == 88000
    assert before["verified_member_price"]["member_tier"] == "DIAMOND"
    assert_suppressed(ctrip_result(quote, NOW + timedelta(minutes=3)), "QUOTE_EXPIRED")


def test_equivalent_expiry_timezone_uses_the_same_instant():
    quote = verified_quote() | {"expires_at": "2026-09-19T18:03:00+08:00"}
    assert ctrip_result(quote)["eligible_for_price_comparison"] is True
    assert_suppressed(ctrip_result(quote, NOW + timedelta(minutes=3)), "QUOTE_EXPIRED")
