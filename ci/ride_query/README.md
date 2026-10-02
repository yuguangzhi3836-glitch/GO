# RIDE/money query-cost candidate after PR284 rejection

Change classes: PRODUCT_FIX, TEST_ONLY, DOCUMENTATION. No migration, topology,
merge, deployment, real PSP or C13/C14-state change.

Reference commit: `a6361b9376ab59f05616338b8245ac4e2976dec3`, application tree
`6570b66bc977f89c0311d67bdc6b721cd70d4e09`. This experiment starts from that
original application, without the rejected PR284 connection-reuse candidate.

Two independently revertible runtime changes:

1. RIDE cancellation freeze no longer reads database time for an argument that
   offer_terms unconditionally overwrites. Keep the authoritative database clock
   read AFTER policy resolution, and the separate consent timestamp read.
2. Money history still selects ORM rows with the same FOR UPDATE predicate and
   locks. Load the six fields actually consumed by amount/parent/forfeiture checks;
   defer historical evidence JSON, timestamps and other unused columns. Keep ORM
   identity/pending-state semantics, full idempotency responses and both commits.

This is a small candidate, not a claimed 20% CPU gain. It removes one SQL call per
RIDE create and avoids unused history payload processing. First mapper setup is
reported separately; it is not moved before timing or removed via warm-up.

Fifteen behavior tests cover policy time after resolution/expiry, consent rollback,
actual history SELECT columns and deferred-read counts, caller-owned pending ORM
state, full replay/conflict output, forfeiture parent protection, PostgreSQL
same-key and amount races, disconnects before/after commits, process exit after
AUTH, commit failure and lost CAPTURE commit acknowledgement. PostgreSQL jobs
require zero skips. The frozen 250 regressions and 32 harness tests also run.

The measurement definition is inherited from PR284's verified tools: 4 processes,
pool4/overflow0, baseline/candidate/candidate/baseline, each at20 then100 actual
overlap, plus cold and three continued bursts for each operation. All application
and harness SHA256 bindings are checked. Independent diagnostic rounds are excluded
from the uninstrumented budget. Continued bursts are not a long steady-state soak.

Unchanged adoption gates: application CPU -20%, whole-worker lifetime CPU -20%,
P95 -15%, no P99 regression, RSS sum <=+10%, both candidate100 P95<=5000ms and
P99<=10000ms, then two fixed4x4 revalidations. Original2-vCPU acceptance stays FAIL;
synthetic service actors cannot establish HTTP/real-PSP/production capacity.

`bootstrap.py` runs only in the existing approved four-core Codespace, with the
retained Python environment and disposable localhost PostgreSQL18.4. It is bounded
to90 minutes, publishes all raw evidence on a separate evidence branch and stops
the Codespace. Use a new clean dedicated worktree; verify no other experiment and
port5432 free before launch. Never run this on HK or production.

    /workspaces/.go-capacity-venv/bin/python ci/ride_query/bootstrap.py
