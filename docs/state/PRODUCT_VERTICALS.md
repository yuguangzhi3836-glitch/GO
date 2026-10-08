> **HISTORY** — 历史 / 取证材料，不是当前操作说明。
> **HISTORY** — historical / audit material, not current operating instructions.
>
> 当前入口：人（中文）[`README.md`](../../README.md) · AI（英文）[`AGENTS.md`](../../AGENTS.md)。
> Current entry points: [`README.md`](../../README.md) (Chinese, humans) and [`AGENTS.md`](../../AGENTS.md) (English, AI).
>
> 本文档不定义正常操作路径，不得作为当前操作依据。This document does not define the normal path; do not use it as current operating guidance.

---

# PRODUCT VERTICALS — CURRENT STATE

Baseline: `main@8ffcde66d36c1bbf849218529ef015f6e81725af` (refreshed 2026-09-14; previous baseline `286e294d`)

Truth classes: `CURRENT_MAIN_FACT` · `ACTIVE_CANDIDATE` · `UNKNOWN / HOLD / BLOCKERS` · `EVIDENCE / ENTRYPOINTS`

## CURRENT MAIN FACTS

Current `application/` contains product work across multiple travel verticals, including:

- HOTEL
- FLIGHT
- RAIL
- RIDE
- RENTAL
- ATTRACTION
- plus cross-cutting modules: judgment, journey, travel intelligence, go_ai, mobility, autonomy, compensation, incident, truth, routing, recovery adapters

The existence of code, database tables, tests or simulator paths for a vertical does not by itself establish external-provider readiness, production acceptance or commercial completeness.

Where the most recent merged work sits on canonical main: the changes merged between the two context baselines (PR #66–#76) are concentrated in **FLIGHT** (flight status width, flight checkout/change idempotency and payment recovery, coupon plan), plus judgment, journey, travel-intelligence, go_ai, mobility, attractions and the API layer, together with migration `0134` and CI/evidence. HOTEL booking and connector source did not change in that delta.

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

Currently open and unmerged at this checkpoint: #61, #65, #71, #72, #73, #75, #78, #89, #90, #91 (plus older long-lived Draft branches). None of them is current truth.

## UNKNOWN / HOLD / BLOCKERS

- This card intentionally does not claim detailed real-world supplier readiness for every vertical. A dedicated state card should be created when a vertical becomes an independently active/review-critical workstream.
- Round-2 14-Cell `PASS_SCOPED` results do **not** transfer to the current main tree; the CI manifests on main record `historical_pass_transferred: false`.
- C11 (flight post-commit callback / repeated side-effect boundary) remains `HOLD` in the round-2 ledger; `c11/followup/ACCEPTANCE.md` is an acceptance worksheet, not a PASS record.
- `HK_DEPLOY` / `FINAL_RELEASE` / `PRODUCTION` remain `HOLD`; no vertical is exempt.

## EVIDENCE / ENTRYPOINTS

- `README.md`
- `application/`
- `docs/canonical-baseline/DEPTH48_ORDERED_REPAIRS.md`
- `docs/canonical-baseline/REMAINING_GAPS.md` where current/relevant
- `ci/retention/BASELINE.json`, `ci/next-depth/CANDIDATE.json`, `ci/cell-closure/CANDIDATE.json`
- `evidence/v70-round2-20260914/README.md`

PRODUCT_VERTICALS_STATE_STATUS=REFRESHED_AT_MAIN_8ffcde66
