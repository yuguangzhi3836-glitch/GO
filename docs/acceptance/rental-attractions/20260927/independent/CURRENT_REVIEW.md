# Current limited independent review

Result: **19 PASS, 0 failure/error**, isolated local SQLite / TestClient and service calls. Runtime 15.95 seconds. This is a development-tree review, not a frozen candidate acceptance and not 100%.

The original 16 independent probes were rerun unchanged in intent: expired/missing-policy redemption refusal (2), completed movement amount/currency/state corruption refusal (6), completed ledger amount/currency/account/evidence corruption refusal without money changes (8).

Three additional focused checks passed:

1. A customer-nonrefundable attraction has a zero refund quote and the refund command refuses without changing funds. After supplier closure, its involuntary refund quote correctly allows the full 36,000 minor units. An injected interruption immediately before money execution leaves native REFUND_PENDING, unified lifecycle CANCELLED and refund state REFUND_PROCESSING. The pending quote is exactly the originally frozen quote, including hash/reason. Resuming with that original acceptance succeeds; completed replay returns the same receipt without additional money. The final unified state stays CANCELLED / REFUND_COMPLETED.
2. After one date-change quote is supplier-confirmed, an earlier unused quote rejects with ATTRACTION_CHANGE_QUOTE_STALE_REQUOTE_REQUIRED. Full order output, target capacity search and money/ledger snapshots remain unchanged.
3. Rental longer → shorter → longer adjustments, followed by cancellation, refund all captures exactly once across multiple money records: captured 294,000, refunded 294,000 minor units. Final cancellation receipt is 168,000 and replays without changed funds. The new strict ledger checks did not falsely reject these genuine multi-capture/refund records.

The zero-refund case proves refusal without a fabricated payout for the current nonrefundable path. It does not prove a separate zero-payout cancellation workflow or its cross-client display. The interruption uses a controlled exception, not a killed process or real provider outage. No PG concurrency or actual browser/native interaction was executed here.

## Source binding

The five reviewed implementation files were SHA256-hashed before and after the complete test subprocess. All hashes stayed equal (`stable: true`); see CURRENT_BINDING.json. This narrow binding is not a whole application-tree signature.

| Source | SHA256 |
|---|---|
| `src/go_hotel/attractions/service.py` | `2ae041c369901c19119a23e4b7edfdcd86c6bc024fae1947ad9c37f07c90c8fc` |
| `src/go_hotel/attractions/validity.py` | `dfa8d81d972e853d023701c1d4a422c0c3ba1a77d86d53a9f3c23d81b5c859d1` |
| `src/go_hotel/services/vertical_refund_recovery.py` | `ca4a445608a48a6ab40d4cb1a194e0b99a8e0267d526bfdccc3d62116b43a266` |
| `src/go_hotel/mobility/rental/service.py` | `711ec8e7754cd3dab431a80c853fdf10de369641460c8b9863037af64cb5af1a` |
| `src/go_hotel/services/vertical_lifecycle_projection.py` | `54da7c1473afb7243b88cd1c744eadf576233b90a6c1e9a6351c6d488658d1a1` |

## Outstanding full scope

SCOPE_REVIEW_INDEX.json retains all **C04 30 obligations / 108 cases** and **C06 14 obligations / 44 cases**, each complete case NOT_VERIFIED until fixed-candidate evidence is adjudicated. No denominator reduction or historical PASS transfer.

Still required: exact final source/CI binding; PG concurrency and interrupted-operation recovery; complete actual web/native/admin/supplier journeys and read-only/foreign-tenant denial; policy registry imports/revocation/version conflicts and trusted validity provenance; full rental supplier/damage/compensation journey; structured operations assignment, SLA/escalation, independent result verification and follow-up; complete per-case order/capacity/ledger snapshots. Synthetic engineering policy is not a real supplier policy. Static supplier-access denial does not count as implementing the supplier journey.

No application implementation was edited by this reviewer. No real inventory, PSP, merge or deployment was used. Raw evidence: current-review.xml, current-review.log; original failures remain preserved.
