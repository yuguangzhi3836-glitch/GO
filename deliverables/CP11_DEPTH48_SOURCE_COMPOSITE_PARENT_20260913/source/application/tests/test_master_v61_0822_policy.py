import pytest
from go_hotel.core import master_baseline as m
from go_hotel.core import v61_commercial_policy as p

pytestmark = pytest.mark.no_db


def test_master_0822_controls():
    assert m.MASTER_VERSION == "V6.1"
    assert m.MASTER_DATE == "2026-08-22"
    assert m.AI_BASE_INFRASTRUCTURE_CALL_PRICE_CNY == 0
    assert m.T20_FINAL_COMPLETION_TARGET == 1.0
    assert m.EQUIVALENT_BILLING_MONTHS == 10
    assert "HOTEL_OWNS_PRICE_AND_GO_MUST_NOT_AUTO_CHANGE_IT" in m.LOCKED_INVARIANTS
    assert "GO_DOES_NOT_BUY_AI_DISTRIBUTION" in m.LOCKED_INVARIANTS


def test_subscription_pricing_locked():
    assert p.monthly_subscription_cny("UP_TO_TWO_DIAMOND", year=1) == 399
    assert p.monthly_subscription_cny("THREE_DIAMOND", year=1) == 699
    assert p.monthly_subscription_cny("FOUR_DIAMOND", year=1) == 999
    assert p.monthly_subscription_cny("FIVE_DIAMOND", year=1) == 1999
    assert p.monthly_subscription_cny("FOUR_DIAMOND", 130, year=2) == 999
    assert p.monthly_subscription_cny("FOUR_DIAMOND", 131, year=2) == 1299
    assert p.monthly_subscription_cny("FIVE_DIAMOND", 199, year=2) == 1999
    assert p.monthly_subscription_cny("FIVE_DIAMOND", 250, year=2) == 2999
    assert p.monthly_subscription_cny("FIVE_DIAMOND", 301, year=2) == 3999


def test_finance_base_outputs():
    assert p.y1_weighted_monthly_cny() == pytest.approx(667.965517, rel=1e-6)
    assert p.mature_weighted_monthly_cny() == pytest.approx(740.379310, rel=1e-6)
    assert p.base_subscription_revenue_cny("Y1") == pytest.approx(400_779_310.34, rel=1e-6)
    assert p.base_subscription_revenue_cny("Y2") == pytest.approx(2_221_137_931.03, rel=1e-6)
    assert p.base_subscription_revenue_cny("Y3") == pytest.approx(3_998_048_275.86, rel=1e-6)
    assert p.Y1_TOTAL_OPERATING_BUDGET_CNY == 160_000_000
    assert p.Y1_ADVERTISING_BRAND_BUDGET_CNY == 30_000_000


def test_go_star_equivalent_labels():
    assert p.star_equivalent_label(3) == "GO ★★★"
    assert p.star_equivalent_label(4) == "GO ★★★★"
    assert p.star_equivalent_label(5) == "GO ★★★★★"
    assert p.star_equivalent_label(6) == "GO ★★★★★+"
    assert p.star_equivalent_label(5, official_award=True) == "官方 ★★★★★"
