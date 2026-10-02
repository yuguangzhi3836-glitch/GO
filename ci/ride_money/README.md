# PR284: connection reuse safety and fixed-host ABBA

Change classes: PRODUCT_FIX, TEST_ONLY, DOCUMENTATION.
No migration, runtime topology, real PSP, merge or deployment change.

Candidate follows PR284, not canonical main. Reference commit is
`a6361b9376ab59f05616338b8245ac4e2976dec3`; its application tree remains
`6570b66bc977f89c0311d67bdc6b721cd70d4e09`.

The RIDE graph holds one PostgreSQL connection while separate SessionLocal
instances retain AUTH commit, CAPTURE commit, and a final read. Each session
loads fresh ORM state; failures propagate and context managers release the
connection. The method returns a scalar fulfillment ID. Other verticals keep
their original independently committed money operations.

The two previous source assertions pointed to tests/src and failed before
testing behavior. Eleven behavior cases now cover replay, conflicting amounts
(including a concurrent race), simultaneous same-key callers, changed state
after AUTH, AUTH/CAPTURE rollback, commit failure, real backend termination
after AUTH and CAPTURE, process exit before CAPTURE, and checkout return.
PostgreSQL is mandatory in the isolated qualification: no skips are accepted.

`bootstrap.py` uses the existing approved 4-core/16GB Codespace and retained
Python environment, starts a localhost-only disposable PostgreSQL 18.4,
requires 11 boundary tests plus the original 250 PostgreSQL regressions,
then runs `experiment.py`. It has a 90-minute bound, archives to the separate
`evidence/pr284-ride-money-20261002` branch, and stops the Codespace.

ABBA freezes baseline/candidate/candidate/baseline on one host, four processes,
pool4/overflow0, and exact 20 then 100 overlap. Each round records raw timings,
P95/P99, application and whole-child-lifetime CPU, aggregate worker RSS, SQL
money facts, a cold batch and three continued bursts for each operation.
Separate instrumented rounds expose queue, hold, SQL and commit costs; these
are excluded from the performance budget. Concurrent sums and phase
percentiles are not additive transaction latency or database-server CPU.

Budget: application CPU -20%, whole-child CPU -20%, P95 -15%, no P99 regression,
aggregate RSS no more than +10%, and both candidate 100-actor rounds <=5s P95
and <=10s P99. A qualified candidate then gets two independent fixed 4x4
revalidations. The original two-vCPU acceptance remains FAIL. A pass here is
synthetic service scope only; it is not HTTP capacity or release acceptance.

The formal multi_instance workload and workflow remain byte-identical.
`round.py` binds the existing process_pool harness to each explicit immutable
application tree without relaxing source/digest/concurrency/ledger checks.
The journey worker's previous hard-coded pool5 assertion now checks its actual
declared pool, so the already exposed 4x4 mode can execute.

Launch from a clean dedicated worktree at the fixed candidate:

    /workspaces/.go-capacity-venv/bin/python ci/ride_money/bootstrap.py

Before that launch, verify remote HEAD, clean application files, no other
experiment running, and localhost port5432 free. Do not run on HK or production.
