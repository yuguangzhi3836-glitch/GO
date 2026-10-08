> **HISTORY** — 历史 / 取证材料，不是当前操作说明。
> **HISTORY** — historical / audit material, not current operating instructions.
>
> 当前入口：人（中文）[`README.md`](../../README.md) · AI（英文）[`AGENTS.md`](../../AGENTS.md)。
> Current entry points: [`README.md`](../../README.md) (Chinese, humans) and [`AGENTS.md`](../../AGENTS.md) (English, AI).
>
> 本文档不定义正常操作路径，不得作为当前操作依据。This document does not define the normal path; do not use it as current operating guidance.

---

# HOTEL — CURRENT STATE

Baseline: `main@8ffcde66d36c1bbf849218529ef015f6e81725af` (refreshed 2026-09-14; previous baseline `286e294d`)

Truth classes: `CURRENT_MAIN_FACT` · `ACTIVE_CANDIDATE` · `UNKNOWN / HOLD / BLOCKERS` · `EVIDENCE / ENTRYPOINTS`

## CURRENT MAIN FACTS

- Hotel application code lives under `application/`.
- Current hotel domain includes offer, prebook, order, payment, supplier-confirmation and after-sales flows.
- Current native hotel booking path uses payment authorization before supplier booking and captures only after supplier booking succeeds.
- The connector registry on this baseline still registers a **mock** hotel connector and `default()` returns `conn_mock_hotel`. Repository code alone does not prove a production hotel inventory authority.
- Hotel offer/prebook models expose inventory/hold-related fields, but model fields and mock behavior must not be treated as proof of real supplier inventory locking.
- HK-STAGING active business runtime is DEPTH48; its live identity must be read from the newest signed VERIFY Evidence for HK-STAGING (`chenzhenxi1-sudo/go-control-evidence`). The repository publishes no runtime pointer: `docs/canonical-baseline/CURRENT_HK_RUNTIME.json` was retired on 2026-10-08.
- The repository-side changes merged between the two context baselines (PR #66–#76) did **not** touch hotel booking/connector source; they were concentrated in flight, judgment, journey, mobility, travel-intelligence, go_ai, API, migration `0134` and CI/evidence. The hotel card therefore carries forward, while the shared migration chain advanced.

## ACTIVE CANDIDATES

- Payment Center discovery PR #61 is examining hotel order/payment/inventory boundaries. Its findings are candidate discovery until separately accepted/merged; it is still open, Draft and unmerged.
- Open `TEST_ONLY` / acceptance PRs (#71, #72, #73, #75, #78, #89, #90, #91) may reference hotel scenarios. None of them is current truth.

## UNKNOWN / HOLD / BLOCKERS

- Production hotel inventory source of truth is not proven by repository code alone.
- Last-room concurrency behavior across GO / hotel / supplier / OTA is not proven.
- Real supplier hard-hold semantics, TTL and release behavior require actual connector/provider evidence.
- Presence of mock/simulator capability must not be described as production capability.
- Full three-end visible acceptance and physical-device acceptance remain unfinished scopes.

## EVIDENCE / ENTRYPOINTS

- `application/src/go_hotel/domain/models.py`
- `application/src/go_hotel/services/booking.py`
- `application/src/go_hotel/services/consistency.py`
- `application/src/go_hotel/connectors/registry.py`
- `application/src/go_hotel/connectors/mock_hotel.py`
- `README.md`

HOTEL_STATE_STATUS=REFRESHED_AT_MAIN_8ffcde66
