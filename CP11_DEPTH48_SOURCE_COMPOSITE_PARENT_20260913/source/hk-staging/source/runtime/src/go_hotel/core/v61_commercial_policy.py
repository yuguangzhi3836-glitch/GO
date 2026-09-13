"""GO V6.1 2026-08-22 hotel commercial, Virtual Direct and star-equivalent policy.

Controlling assumptions for planning and system guardrails. Supplier prices/inventory remain
supplier-owned facts and must never be mutated by these helpers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CommercialTier = Literal["UP_TO_TWO_DIAMOND", "THREE_DIAMOND", "FOUR_DIAMOND", "FIVE_DIAMOND"]

Y1_LAUNCH_MONTHLY_CNY = {
    "UP_TO_TWO_DIAMOND": 399,
    "THREE_DIAMOND": 699,
    "FOUR_DIAMOND": 999,
    "FIVE_DIAMOND": 1999,
}

EQUIVALENT_BILLING_MONTHS = 10
T20_FINAL_COMPLETION_TARGET = 1.0
LIVE_HOTEL_TARGETS = {"Y1": 60_000, "Y2": 300_000, "Y3": 540_000}
Y1_TOTAL_OPERATING_BUDGET_CNY = 160_000_000
Y1_ADVERTISING_BRAND_BUDGET_CNY = 30_000_000
AI_BASE_INFRASTRUCTURE_CALL_PRICE_CNY = 0

# Internal planning mix only; not an authoritative market statistic.
NATIONAL_TIER_WORKING_ASSUMPTION = {
    "UP_TO_TWO_DIAMOND": 270_000,
    "THREE_DIAMOND": 200_000,
    "FOUR_DIAMOND": 80_000,
    "FIVE_DIAMOND": 30_000,
}

# Y2+ room-band working assumptions used only for financial planning.
FOUR_DIAMOND_ROOM_MIX = {"LE_130": 0.75, "GT_130": 0.25}
FIVE_DIAMOND_ROOM_MIX = {"LT_200": 0.20, "R200_300": 0.40, "GT_300": 0.40}

STAR_EQUIVALENT_LABELS = {
    3: "GO ★★★",
    4: "GO ★★★★",
    5: "GO ★★★★★",
    6: "GO ★★★★★+",
}
STAR_EQUIVALENT_REFERENCE = "GB/T 14308-2023"

VIRTUAL_DIRECT_PRINCIPLES = (
    "HOTEL_OWNS_PRICE",
    "HOTEL_CONTROLS_INVENTORY",
    "GO_PROVIDES_INDEPENDENT_LOW_COST_OFFICIAL_DIRECT_CHANNEL",
    "VIRTUAL_DIRECT_FIRST_NOT_DEEP_PMS_REQUIRED",
    "GO_MUST_NOT_AUTO_CHANGE_SUPPLIER_PRICE",
    "PRICE_AND_BENEFIT_ADVANTAGE_MUST_BE_SUPPLIER_AUTHORIZED",
)

AI_DISTRIBUTION_PRINCIPLES = (
    "GO_DOES_NOT_BUY_DISTRIBUTION",
    "GO_EARNS_DISTRIBUTION_THROUGH_VALUE",
    "NO_PAID_AI_RECOMMENDATION_RANKING",
    "AUTHORIZED_AI_BASE_CALLS_ARE_FREE",
)


def monthly_subscription_cny(tier: CommercialTier, room_count: int | None = None, *, year: int = 1) -> int:
    """Return the controlled subscription price for planning/contract selection.

    This does not mutate a supplier's price/inventory and is independent of GO Judgment or GO Star Equivalent.
    """
    if year <= 1:
        return Y1_LAUNCH_MONTHLY_CNY[tier]
    if tier == "UP_TO_TWO_DIAMOND":
        return 399
    if tier == "THREE_DIAMOND":
        return 699
    if room_count is None or room_count < 0:
        raise ValueError("room_count is required for FOUR_DIAMOND/FIVE_DIAMOND from Y2 onward")
    if tier == "FOUR_DIAMOND":
        return 999 if room_count <= 130 else 1299
    if tier == "FIVE_DIAMOND":
        if room_count < 200:
            return 1999
        if room_count <= 300:
            return 2999
        return 3999
    raise ValueError(f"unknown tier: {tier}")


def star_equivalent_label(level: int, *, official_award: bool = False) -> str:
    if level not in STAR_EQUIVALENT_LABELS:
        raise ValueError("GO Star Equivalent supports 3, 4, 5 and 5+ only")
    label = STAR_EQUIVALENT_LABELS[level]
    if official_award and level != 6:
        return f"官方 {label.replace('GO ', '')}"
    return label


def y1_weighted_monthly_cny() -> float:
    total = sum(NATIONAL_TIER_WORKING_ASSUMPTION.values())
    return sum(NATIONAL_TIER_WORKING_ASSUMPTION[t] * Y1_LAUNCH_MONTHLY_CNY[t] for t in NATIONAL_TIER_WORKING_ASSUMPTION) / total


def mature_weighted_monthly_cny() -> float:
    n = NATIONAL_TIER_WORKING_ASSUMPTION
    four_avg = FOUR_DIAMOND_ROOM_MIX["LE_130"] * 999 + FOUR_DIAMOND_ROOM_MIX["GT_130"] * 1299
    five_avg = FIVE_DIAMOND_ROOM_MIX["LT_200"] * 1999 + FIVE_DIAMOND_ROOM_MIX["R200_300"] * 2999 + FIVE_DIAMOND_ROOM_MIX["GT_300"] * 3999
    total = sum(n.values())
    return (n["UP_TO_TWO_DIAMOND"]*399 + n["THREE_DIAMOND"]*699 + n["FOUR_DIAMOND"]*four_avg + n["FIVE_DIAMOND"]*five_avg) / total


def base_subscription_revenue_cny(year_key: Literal["Y1", "Y2", "Y3"]) -> float:
    avg = y1_weighted_monthly_cny() if year_key == "Y1" else mature_weighted_monthly_cny()
    return LIVE_HOTEL_TARGETS[year_key] * avg * EQUIVALENT_BILLING_MONTHS
