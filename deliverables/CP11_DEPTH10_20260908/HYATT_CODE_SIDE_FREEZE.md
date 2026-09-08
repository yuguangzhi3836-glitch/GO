# Hyatt code-side candidate freeze

Status: CODE-SIDE CONTRACT FROZEN / RUNTIME GATE HOLD

The Hyatt acceptance code contract is frozen at the commit containing this file. Runtime PASS is explicitly not asserted.

## Frozen contract

1. Cohort is exactly ten properties from one frozen official Hyatt directory snapshot.
2. Generation 1 performs real build execution. Exactly one hotel is the forced-kill probe; the child must signal exact LEASED before SIGKILL.
3. Recovery reclaims the same business task after lease expiry and only the production build worker may ACK it. Generation-1 terminal ACK count must equal one from the durable ledger.
4. Generations 2 and 3 use explicit rerun generations and execute the real production build path. Every generation requires exactly one terminal ACK.
5. Canonical hotel_id may not drift between generations.
6. PostgreSQL authoritative snapshot is captured after every generation. G1->G2 and G1->G3 diffs are both required and are exposed as `authoritative_db_diffs`.
7. Hotel/room entity proliferation, durable-media identity/state drift, page-version proliferation or active-page-version proliferation makes idempotency HOLD. Append-only audit growth is reported separately and is allowed.
8. LKG PASS is derived only from PostgreSQL publication/page event history. Producer-supplied LKG booleans are non-authoritative.
9. Media integrity PASS requires the real MediaBlobRecoveryService reconciliation. Missing runtime media root, missing blobs, corrupt blobs or publication without publishable rights makes the matrix HOLD.
10. Every hotel must pass identity, official-room catalog parity, room-media isolation, hotel-scene coverage/gap truth, durable media, LKG and two authoritative DB diffs. The cohort additionally requires exactly one successful forced-kill recovery probe.

## Freeze rule

Any future change to runner/evaluator/task lease/forced-kill/DB snapshot/LKG/media truth field names or semantics invalidates this freeze until the contract tests and this document are updated together.

## Runtime truth

`HYATT_10_REAL_E2E_GATE=HOLD` until the frozen candidate is executed against PostgreSQL, real official Hyatt capture, durable media storage and the complete 10/10 evidence matrix is green. Code presence, authored tests or this freeze document do not constitute runtime PASS.
