# Capacity projection experiment — 2026-09-29

User direction: prioritize the high-concurrency failure. Draft PR #279 remains
the integration candidate. No merge, deployment, live payment or supplier access.

Baseline commit: `059ebec3ab379099ef258effc3ab0a9833d52c35`.
Baseline application tree: `6570b66bc977f89c0311d67bdc6b721cd70d4e09`.
Experimental application tree: `b4a998aa5980a5207e658cc708c7e88829543918`.

## Hypothesis and scope

Reduce recurring ORM query construction and unused-column loading in the
payment, evidence verification, supplier-money projection and lifecycle paths.
The rejected payment-only query-reuse experiment is included as one component;
its earlier 6.88% CPU improvement does not qualify it for adoption. This combined
candidate requires its own measured decision. Nothing is accepted in advance.

Statement objects retain bind parameters, database reads, FOR UPDATE clauses,
ordering, predicates and existing transaction/commit boundaries. No business
facts, payer identities, clocks, locks or validation decisions are cached.
`load_only` keeps ORM session identity semantics and all fields used by the full
evidence-chain and money-graph checks. All graph nodes and chain links remain
checked; no history truncation or removal of safety/recovery work.

## Local qualification — not PostgreSQL capacity

The 68 existing relevant regressions and four new projection tests passed on
SQLite, plus 31 harness qualification tests. New tests cover unflushed session
tampering, chain validation without deferred-field queries, and money parent
integrity with large unused payloads. Local sequential 100-transaction ABBA CPU:
2.669386359 / 2.545566863 / 2.512696317 / 2.951782511 seconds. The median reduction
is approximately 10.02%, below the 20% goal; this is a discovery result only.
Packages differ from the CI runner (local SQLAlchemy 2.0.54 versus previous CI
2.1.1), so these absolute timings cannot be mixed with the PostgreSQL evidence.

An initial cProfile CPU-clock probe produced invalid thread accounting and is
excluded. The replacement Yappi discovery used native thread CPU accounting;
neither profile is an uninstrumented throughput measurement.

## Required next evidence

Existing same-runner ABBA, identical packages/harness and PostgreSQL 18.4; fresh
schema/processes, two workers, pool5/overflow0, default 5ms switch interval.
Each round retains all 13 money/idempotency/recovery prerequisites followed by
20 then 100 complete actors, plus cold and three continued-operation batches
for full transaction, create, payment and query. Check raw overlap, CPU/PIDs,
P95/P99, SQL facts and artifact digests. CPU and whole-lifetime CPU <=80%, P95
<=85%, P99 <=100%, RSS <=110% remain the screening budget. Failed screening
means restore the exact baseline application tree, retaining this experiment.

Formal capacity still requires 100 complete actors P95 <=5000ms, P99 <=10000ms,
zero unexpected errors and all money/recovery checks. Higher tiers remain
blocked until the original staircase permits them. Three continued bursts are
not a soak test; service-level synthetic actors do not establish HTTP/auth,
network, live supplier/PSP or production capacity.

C14 R9 remains historical evidence for the old candidate. API credit exhaustion
does not prevent this isolated development/measurement work. A changed final
application must receive a fresh whole-candidate C14 and then C13 when usable API
credit is restored. No paid retry is queued by this experiment.
