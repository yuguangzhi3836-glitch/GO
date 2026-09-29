# Payment query reuse experiment — 2026-09-29

Classification: PRODUCT_FIX, TEST_ONLY, DOCUMENTATION. Draft PR #279 only.
Baseline commit: ae2c3f99c8a455f7f60dab5c967a7af71b75536f.
Baseline application: 6570b66bc977f89c0311d67bdc6b721cd70d4e09.
Candidate application: 4b99a7596ce8e509f306e42b7900138e6ce52336.

The candidate reuses immutable parameterized SQL shapes in payment creation,
selection, execution and deadline reads. Payment orchestration reads only the
columns used and at most two pending attempts, sufficient to reject ambiguity.
No payment results, account facts or ORM objects are cached. Execution ordering,
row locks, commits, checkpoints and existing payment state guards remain.

Four rounds run baseline/candidate/candidate/baseline on one isolated PostgreSQL
runner, same installed dependencies and identical copied harness. Every full
transaction round retains all 13 correctness/recovery cases then runs 20 and 100
complete cold RIDE actors with the original replay/conflict and SQL checks.
No formal harness, original workload or original workflow byte is changed.

Each round additionally measures 20/100 normal create, internal payment confirm,
completed-order query and the original complete transaction in a fresh pair of
processes per operation. First batch is process-cold; three subsequent batches
reuse the exact workers, pools and threads. Every request and its timestamps,
worker CPU, startup and ledger facts are preserved. Full transactions include
replay, supplier simulation and fulfillment; ordinary operation measurements keep
the previously declared fixture boundaries. No HTTP/auth/network, real PSP or
supplier is included. DB/OS caches are not cold. Four bursts are not a sustained
capacity test. Phase percentiles cannot be summed into a journey percentile.

Adoption screening requires CPU <=80%, P95 <=85%, P99 no worse and maximum-worker
RSS <=110%, based on the original full-transaction 100 tier. Whole worker lifetime
CPU (including imports/query construction) must also be <=80%; moving work before
timing cannot qualify. All four rounds must have valid source-bound evidence,
zero unexpected errors and pass ledger/correctness checks. Two rounds per variant
are screening evidence; ranges and both paired ratios remain visible.

Formal acceptance is separate: P95 <=5000ms, P99 <=10000ms. Failure at 100 continues
to prevent 250/500/1000. A screening budget pass is not capacity acceptance.
On budget failure, revert these application changes and retain the experiment and
its evidence. No C14/C13 PASS, merge or deployment is claimed by this experiment.

Local qualification and payment regressions passed 51 tests before the final
full-actor adapter qualification was added; final qualification is recorded in CI.
