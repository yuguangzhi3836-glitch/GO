# DEPTH48 1000-user acceptance — stopped on a visible-order gap

2026-09-13 18:18–18:47 Beijing time. Result: **HOLD — 1000-user target not reached**.

Business source remains current main `286e294d92df4b7d1c0073116a8e628734abec6c`,
application tree `3025b2b6b36ea9211da561a4631f304216de9d90`, 1325 files,
SHA256 `d90a9e26c3a64b98009aaf170056f4b3acfa6acebd41baaed276b7baf17c6925`.
The full source fingerprint was checked before and after execution and is unchanged.

| Module | Attempted users | Full journey PASS | Admin-page FAIL |
|---|---:|---:|---:|
| Hotel | 52 | 50 | 2 |
| Flight | 52 | 50 | 2 |
| Rail | 51 | 50 | 1 |
| Ride | 51 | 50 | 1 |
| Rental | 51 | 50 | 1 |
| Attraction | 51 | 50 | 1 |
| Total | 308 | 300 | 8 |

The first stages (6 users / concurrency 1, 54 / 2, 240 / 4) passed. The first
8 users of the final stage failed on admin order visibility; further scheduling
stopped. The remaining 692 users were not attempted. The failed 8 orders did
complete consumer booking, simulator payment, refund/replay and supplier detail.
All 308 orders passed the independent read-only SQL money audit: one capture,
one refund, correct parent linkage, source/payee/amount/currency bindings and
balanced ledger pairs. No HTTP 5xx was found in 125299 raw server request records.
Initial unauthenticated identity probes returned 401 as expected; these are not
authenticated business failures.

Browser API latency sample: 20733 requests, p50 123.948 ms, p95 365.997 ms,
p99 559.381 ms. These are isolated-run observations, not an HK capacity result.
The separate preflight passed 53 browser checks, 72 viewport checks, the six-order
money audit and hotel-change ledger audit; its accounts are excluded from 1000.

## Located gap

Users 301–308 all timed out after 12000 ms waiting for their order ID on
`/go-admin/#/vertical-<module>`, despite HTTP 200 from the admin operations API.
The matching canonical source has a 50-row default sample in
[`operations_console.py`](https://github.com/yuguangzhi3836-glitch/GO/blob/286e294d92df4b7d1c0073116a8e628734abec6c/application/src/go_hotel/api/routes/operations_console.py),
without stable ordering or pagination parameters. The
[`adminVertical` renderer](https://github.com/yuguangzhi3836-glitch/GO/blob/286e294d92df4b7d1c0073116a8e628734abec6c/application/frontend/shared/app.js)
renders only that sample without a page/query control. The first 50 orders in
each module were visible; the next orders were not found by the browser test.
Do not interpret this as a 300-user capacity ceiling or blame concurrency alone.

Evidence limitation: combined three-role failures captured the consumer page,
not the failing admin page. The failing admin response bodies were not archived.
Exact admin locator errors, HTTP 200 observations and source hashes are retained;
the inspected last passing admin screenshot displays 50 orders and 50 refunds.

## Original evidence and scope

- [Run 34751390306 / raw job](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34751390306/job/103708426771)
- [Full original artifact: 882 files and 245 screenshots](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34751390306/artifacts/10316761647)
- Artifact SHA256: `f9704eaa6efd4832e60ab4501b2c77209b02672d60f5eea74313b089a7b3fcee`.
  All 880 listed file hashes were read back with zero mismatches; the two hash
  manifests themselves complete the 882-file artifact. Artifact expires 2026-12-12.
- [Reviewed receipt](RECEIPT.json), [failed-user records](FAILED_USERS.json),
  [raw cumulative browser log](browser.log), [independent ledger](independent-ledger-audit.json).

Actual checked-out test head is `f26d27ccafc428d18159677ccd6e7701aaf8480a`.
The original binding's `harness_commit` is the GitHub event merge SHA
`c9c69603000b9239b8598de7a1a15987907ebd7e`; this naming limitation is recorded
without rewriting original evidence.

Environment: GitHub-hosted Ubuntu, Python 3.13.5, Node 22.22.0, Chromium
140.0.7339.186, private disposable SQLite, synthetic inventory and simulator
payments. The HK image is a reference identity only; it was not load-tested.
Hong Kong, Production, current business source and existing artifacts were not
modified. Native devices, official hotel content completeness, PostgreSQL browser
E2E, sealed Node and final release were not certified by this run.

Next action: repair stable pagination and exact-order retrieval on the admin
vertical page in a separately identified candidate, then rerun the 1000-user
acceptance while retaining this DEPTH48 evidence. Future failure capture must
also retain the actual failing role's page and the sanitized operations response.
