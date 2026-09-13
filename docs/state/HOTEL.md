# HOTEL — CURRENT STATE

Baseline: `main@286e294d92df4b7d1c0073116a8e628734abec6c`

## CURRENT MAIN FACTS

- Hotel application code lives under `application/`.
- Current hotel domain includes offer, prebook, order, payment, supplier-confirmation and after-sales flows.
- Current native hotel booking path uses payment authorization before supplier booking and captures only after supplier booking succeeds.
- Current repository connector registry on this baseline registers a mock hotel connector; repository code alone does not prove a production hotel inventory authority.
- Hotel offer/prebook models expose inventory/hold-related fields, but model fields and mock behavior must not be treated as proof of real supplier inventory locking.
- HK-STAGING active business runtime is DEPTH48; runtime identity must be read from `docs/canonical-baseline/CURRENT_HK_RUNTIME.json`.

## ACTIVE CANDIDATES

- Payment Center discovery PR #61 is examining hotel order/payment/inventory boundaries. Its findings are candidate discovery until separately accepted/merged.

## UNKNOWN / HOLD / BLOCKERS

- Production hotel inventory source of truth is not proven by repository code alone.
- Last-room concurrency behavior across GO / hotel / supplier / OTA is not proven.
- Real supplier hard-hold semantics, TTL and release behavior require actual connector/provider evidence.
- Presence of mock/simulator capability must not be described as production capability.

## EVIDENCE / ENTRYPOINTS

- `application/src/go_hotel/domain/models.py`
- `application/src/go_hotel/services/booking.py`
- `application/src/go_hotel/services/consistency.py`
- `application/src/go_hotel/connectors/registry.py`
- `application/src/go_hotel/connectors/mock_hotel.py`
- `README.md`
- `docs/canonical-baseline/CURRENT_HK_RUNTIME.json`

HOTEL_STATE_STATUS=V1_CANDIDATE
