# DEPTH48 capacity upgrade candidate

Status: source candidate; HK deployment and live 1000-active-user acceptance remain HOLD.

## Baseline and classification

Base main: `286e294d92df4b7d1c0073116a8e628734abec6c`.
Canonical HK application tree: `3025b2b6b36ea9211da561a4631f304216de9d90`.
The two HK runs at 2026-09-13 11:15 UTC and 12:31 UTC both passed the scoped
500-VU stage and aborted at 1000. The second run had 382/1444 request failures
at 1000, plus two HTTP 502 responses at 250. This is motivation, not proof of
an application root cause. The live runtime binding and HK telemetry remain missing.

Classes: PRODUCT_FIX, TEST_ONLY, BUILD, DOCUMENTATION.
No migration, topology change, dependency declaration change, or service-count change.
The active-runtime pointer is deliberately not updated by this source candidate.

## Changes

1. Run synchronous incident-control, cookie authentication, CSRF validation,
   audit and security-signal database work through the existing bounded
   Starlette/AnyIO worker pool. Each service creates and closes its own database
   session in that worker thread. Calls are awaited: no dropped audit work,
   background fire-and-forget, cached incident decisions or authorization bypass.
2. Preserve fail-closed incident behavior and existing CSRF/refresh rules.
   Incident denials now carry the request ID and contribute to HTTP/5xx metrics;
   lookup exceptions are correlated in request-failure logs. This makes
   application-denied 503 responses visible to the availability calculation.
3. Retain at most 4096 latency observations per label set. Counts and sums remain
   exact for the process lifetime. The existing P95 metric now describes the
   most recent retained observations, explicitly declared by HELP output;
   it is neither an all-time quantile nor a timed SLO window. A retained-sample
   metric exposes the window size. Callers must still bound label cardinality.
   Counter reads no longer copy unrelated histogram history.
4. Upgrade the load harness to retain transport cause codes, distinguish
   shutdown cancellations from coincident failures, exclude shutdown draining
   from sustained-load duration, and prevent a failed final health check from
   being labelled a public-load pass. Workload and abort thresholds are unchanged.

The pool size, Uvicorn process count, DB pool settings, eight service roles,
Dockerfile, Compose, migration head and protected non-targets are preserved.
This avoids introducing duplicated embedded schedulers or multiplying database
connections before the live resource budget is known.

Implementation reference: [Starlette thread pool](https://starlette.dev/threadpool/).

## Validation and evidence interpretation

The new targeted tests first ran against the unchanged baseline: 10 failed,
1 passed. They demonstrate event-loop blocking, unbounded metric history,
whole-registry copying and missing denial correlation. After the repair all
11 passed. Existing authentication/session/CSRF/MFA/observability regression:
33 passed. Full local backend regression with the canonical CI dependency lock:
1807 passed, 6 PostgreSQL-only tests skipped locally, 270 warnings, 804.91 seconds.
The separate PostgreSQL 18.4 capacity CI passed all 50 selected checks, including
those six concurrency checks. Initial source commit `08f6b691680783dd53b856386a54603ca27f5190`
also passed the isolated runtime-image build, startup health and migration-head checks
in [run 34759359218](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34759359218).

Initial existing retention/ordered-repair workflows stopped at their strict source
allowlist because the new capacity test was not registered (runs 34759359171 and
34759359107). This follow-up registers exactly the two modified modules and one
new test, including their blob/SHA256 values, and the resulting application tree.
Validators, original provenance records and gate thresholds are unchanged.
Results of the rerun are recorded on the PR; initial failures remain available.

`ci/capacity/compare.py` loads the two exact baseline Git blobs and candidate
files, then compares the real middleware with an injected 3 ms synchronous I/O
wait. It also measures retained telemetry after 200000 observations. It makes
no external requests, has no real business DB, and is NOT a live HK load gate.
Its source binding is recorded in the output.

The isolated CI uses the existing canonical dependency lock, PostgreSQL 18.4,
50 capacity/security/PostgreSQL tests and the diagnostic harness self-test.
It runs the comparison after those tests finish. A dependent job builds the
unchanged canonical Dockerfile, labels the image with exact source identities,
checks health and the 0133 migration graph against disposable storage, and
preserves the image plus its SHA256. CI never runs the HK load harness with
`--run` and never deploys to HK or Production.

Four unchanged large PNG assets could not be materialized through the local
text connector. Their canonical Git blob references are retained unchanged;
local code/blob checks cover all other 1321 application files. GitHub CI obtains
its own complete application checkout. A missing local asset is not to be
silently replaced or counted as a product regression/pass.

## Deployment and rollback boundary

This candidate is compatible with the current eight-service, single-image
business topology and 0133 schema. A source PR or isolated image build is not
installation evidence and does not close the live 1000-user gate.

Before a switch: read the current HK runbooks; capture the live image, Compose,
environment, DB head, all eight services and protected non-targets; resolve drift;
validate this exact image/source digest in the authorized CANARY path; preserve
the current runtime image and durable prior-state record. Then use the authorized
signed DEPLOY path for the fixed eight services and collect signed evidence.
Do not infer these live values from this document or the old control-plane snapshot.

The current Boss Request guide exposes VERIFY only. This PR creates no guessed
CANARY/DEPLOY request, formal Task or signature and does not bypass that boundary.
Rollback is a separate approved operation derived from the eligible durable V2
deployment record; there is no automatic rollback or schema downgrade.

## Next live acceptance

First obtain existing HK logs for 2026-09-13 12:35:00–12:37:10 UTC and correlate
the prior request IDs, including the two 502 responses. After authorized
installation, bind the actual candidate image/SHA/0133/eight services and then
repeat gradual 1000-active-user load with error causes and exact stop timestamps.
Require the complete 120-second target interval, P95 <= 2 s, P99 <= 5 s,
request errors <= 1%, and zero semantic failures for the scoped public workload.
Three-end authenticated transactions, money reconciliation, Sealed Node and
Final Release remain separate unfinished gates.
