# Transaction-boundary candidate — pending PostgreSQL qualification

Scope: Draft PR #279 only. No merge, deployment, Hong Kong, supplier or real
payment access. Frozen baseline: 059ebec3ab379099ef258effc3ab0a9833d52c35,
application 6570b66bc977f89c0311d67bdc6b721cd70d4e09.

## Independently revertible implementation commits

1. `6bed2daff5f7e1f1db4d7531d8825cda772de711`: local RIDE order, source,
   evidence and successful API receipt commit together after the independent
   durable claim. Pre-commit rollback can release the claim; ambiguous commit
   and abrupt process death retain it. Generic/Flight recovery is unchanged.
2. `05fe1f2f47850a814e0684c4ff1f5c3da88c012e`: consolidate RIDE order checks,
   payment intent/root creation and deadline confirmation in one local transaction.
   RIDE public intent creation uses the same order-first locking sequence.
   Payment execution, authorization and capture remain independently durable.
3. `0e1506fb95413a12998128080da346b95a1e88a9`: one committed database snapshot
   for confirmed RIDE authorization/capture replay; preserve key/amount/type/parent
   conflicts. No financial result cache. Misses, non-confirmed rows, rental deposit
   scope and caller-owned verified-external transactions retain the locked path.
   First-operation lookup overhead must be included in the measured comparison.

The following qualification/binding commit adds real driver disconnect probes
and a PostgreSQL-only full concurrent-checkout test; it is separate from runtime
changes. Final application: `b77840d31f0e31b046d8f3359c35630c75b8a02d`.

## Local evidence (not PostgreSQL capacity proof)

- Existing frozen regression selection: 248 passed, 2 PostgreSQL-specific skips.
- New tests: 22 passed, 2 PostgreSQL-only concurrency tests pending remotely.
- Harness tests: 34 passed.
- Real subprocess exits on both sides of order and payment-root commits.
- Real DBAPI connection closure before/after order commit, plus ambiguous-ack
  injection. Before-commit loss leaves no order and a retained claim; after-commit
  loss leaves one order plus a replayable success receipt.
- SQLite full payment-transition concurrency exposed a fulfillment uniqueness
  race: SQLite does not implement the existing FOR UPDATE semantics. It is not
  accepted as concurrent-payment proof. The new root-preparation concurrency test
  passes locally; the full checkout test is mandatory, with zero skips, on PostgreSQL.
- Cold import inspection: zero configured ORM mappers and zero pool connections.

## Measurement and decision

Run original/candidate/candidate/original on one runner with fresh per-round
schemas/processes, unchanged 2 workers, pool5/overflow0 and 5ms switch interval.
Keep 20 then 100 concurrent full actors, cold plus all continued journey batches.
Run separate instrumented 20/100 diagnostics after each uninstrumented round on
the same machine. Diagnostic phase timings, SQL and pool waits are not acceptance
latencies or additive percentiles. Diagnostic adapter adds labels for the new
session-owned entry points; no frozen formal harness file is edited.

Adoption requires app CPU -20%, lifetime CPU -20%, P95 -15%, no P99 regression,
RSS growth <=10%, all correctness/regression tests, then the original formal
100-actor P95<=5000ms/P99<=10000ms gate. No higher load before that formal gate.
Planned connection-acquisition reduction 21->18 is a design estimate, not a
measured result. Hardware expansion is a separate 4-vCPU comparison, only if the
original configuration fails; it cannot re-label the original gate as passed.

Frozen SHA256:
- run.py: e274bc3cb2b114cd2ed9e024c30a5ebb71d1b3a4e26ba27a5c521b7d56889a5c
- ride_workload.py: b5a97b55cd6815534b1844c99ba9073dafe1c534be57d00d2e10d0520e665d32
- formal workflow: 160720754942621bdff87dbf2a96e90395444567c7c932d3bb799d0622160330

## Review-provider funding update

User-provided email screenshot dated 2026-09-30 11:32 Asia/Shanghai reports a
USD 113 charge to fund GOAI OpenAI API credits. This is funding evidence only;
the configured review environment has not yet been probed successfully. Do not
retain "credit exhausted" as a freshly verified current fact, or infer C14 PASS.
C14 and C13 remain pending the fixed final candidate and their own actual results.
