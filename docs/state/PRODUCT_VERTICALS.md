# PRODUCT VERTICALS — CURRENT STATE

Baseline: `main@286e294d92df4b7d1c0073116a8e628734abec6c`

## CURRENT MAIN FACTS

Current `application/` contains product work across multiple travel verticals, including:

- HOTEL
- FLIGHT
- RAIL
- RIDE
- RENTAL
- ATTRACTION

The existence of code, database tables, tests or simulator paths for a vertical does not by itself establish external-provider readiness, production acceptance or commercial completeness.

The current README records substantial integrated source/test progress through DEPTH48 while also recording remaining external/device/provider/release gaps.

## CURRENT PRODUCT-GOVERNANCE RULE

Do not interpret GO's large module/PR/table count as proof that every vertical is equally mature.

For a task involving one vertical:

1. read current project state;
2. identify the vertical's current source path;
3. inspect current accepted main facts;
4. distinguish simulator/mock/internal closure from real provider integration;
5. identify current external gates before describing the capability as complete.

## ACTIVE CANDIDATES

Boss GPT and other agents may continue to create product candidates. Those PRs remain candidates until integrated/reviewed under the current lineage and change-control rules.

## UNKNOWN / HOLD / BLOCKERS

This V1 card intentionally does not claim detailed real-world supplier readiness for every vertical. A dedicated state card should be created when a vertical becomes an independently active/review-critical workstream.

## EVIDENCE / ENTRYPOINTS

- `README.md`
- `application/`
- `docs/canonical-baseline/DEPTH48_ORDERED_REPAIRS.md`
- `docs/canonical-baseline/REMAINING_GAPS.md` where current/relevant

PRODUCT_VERTICALS_STATE_STATUS=V1_CANDIDATE
