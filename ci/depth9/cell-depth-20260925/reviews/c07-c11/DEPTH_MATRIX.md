# C07–C11 scoped depth review — 2026-09-25

Candidate input: PR #246, `6acf9fdcde4b208b12a8c9d57ef74497e745faae`. This is candidate source, not canonical main or deployed runtime. Scope is before real suppliers / real PSP. No deployment, money, supplier call, signing or GitHub write was performed by this reviewer.

| Cell | Inspected existing capability | Concrete finding / current disposition | Remaining acceptance to close depth |
|---|---|---|---|
| C07 | `travel_intelligence/preferences.py`: owner/SELF constraints, encrypted explicit preferences, live purpose-bound consent locks and auditable reads; `service.py`: intention/context preparation | Existing boundary tests retained; no new defect asserted in this limited sample. | Independently bind consent withdrawal/process-recovery evidence to integrated final candidate; complete C/B/admin/mobile user-visible purpose/withdrawal journey. Existing process tests are not evidence of a live run in this review. |
| C08 | `go_ai/planner.py` retains all required tasks; `go_ai/service.py` request audit, database-time lease, fencing and checkpoint recovery | No duplicate rewrite of existing durable execution/hard-exit recovery work. Existing task-plan test included in cross-domain regression. | Bind long-task takeover and output audit evidence to final application tree; final cross-end interrupted-session re-entry acceptance remains separately required. |
| C09 | `judgment/service.py` persisted review/risk evidence, commercial independence and six-dimension recommendation evidence | Existing evidence-authority test included; no new defect asserted. | Independent candidate-bound judgment-concurrency evidence and operational risk-update→recommendation invalidation end-to-end acceptance. Do not translate source presence into 100%. |
| C10 | `consumer_unified_lifecycle.py`, `consumer_trip_index.py`, `vertical_lifecycle_projection.py` | Confirmed: later facts could change/erase supplier identity; stale and idempotent shortcuts hid mismatch. Fixed supplier immutability including missing identity. Confirmed: UNKNOWN_EXTERNAL_STATE was projected as PAID. Fixed explicit unknown payment state. | C13 independent review; current tests are local SQLite, not PostgreSQL or browser evidence. Historical supplier-less records requiring enrichment must use separately controlled repair; ordinary projection rejects identity changes. |
| C11 | `vertical_transaction_bridge.py`, flight recovery tests and Trips payment projection | Reuse existing root→intent→fulfillment authority; repaired downstream false PAID display through C10 projection, no new payment truth. Existing flight committed-boundary recovery tests included. | Independent full candidate financial state/compensation matrix and PG concurrency/close-race evidence; no real-PSP claim. Broader native-status→payment mapping still relies on established vertical workflow, not newly proven bank evidence. |

## Code changes

1. `application/src/go_hotel/services/consumer_unified_lifecycle.py`: check supplier identity immediately after account identity, before stale/idempotent shortcuts and before mutation/event emission.
2. `application/src/go_hotel/services/vertical_lifecycle_projection.py`: preserve UNKNOWN_EXTERNAL_STATE for payment projection instead of inferring PAID.
3. New tests: `test_c10_lifecycle_supplier_identity.py` (11 cases), `test_c10_unknown_payment_projection.py` (7 cases).

Existing native producers carry supplier identity from order or bound Root/Intent/Fulfillment, hosted producer from its hotel, while external OTA imports retain None. None→known is intentionally rejected as an ordinary projection; this is a compatibility limitation requiring explicit historical repair if encountered.

## Evidence

- `baseline.txt` / `baseline-junit.xml`: original supplier-identity code, 8 failed / 3 passed; failures are missing rejection.
- `unknown-baseline.txt` / `unknown-baseline-junit.xml`: original unknown-payment projection, 7 failed; actual payment_state was PAID.
- `supplier-fixed.txt`: first development rerun had 6 assertion failures solely from SQLite naive/aware datetime serialization; production rejection worked. Test corrected to compare persisted before/after snapshots, preserving full mutation checks.
- `fixed.txt` / `fixed-junit.xml`: 64 passed across both new tests plus existing lifecycle, external OTA import, trip re-entry, hotel change, hosted money and unified six-vertical Trips.
- `cross-domain.txt` / `cross-domain-junit.xml`: 142 passed, 4 subtests passed, 5 existing deprecation warnings; producer compatibility and C07/C08/C09/C11 regression. Combined with fixed suite: 206 passed.

These are implementation-side regression results, not C13 independent PASS and not a declaration of any cell's 100% completion.
