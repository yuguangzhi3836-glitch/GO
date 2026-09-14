# C13 final independent canonical review — PR 66

SOURCE_INTEGRATION_EVIDENCE=PASS_SCOPED. PR 66 is already merged by the parallel authorized session. Inherit its completed result; do not submit the local parallel patch or rerun successful CI. FULL_RELEASE_GATE=HOLD; DEPLOYMENT_NOT_PROVEN_BY_THIS_REVIEW; Production=HOLD.

## Exact binding

Read-only GitHub PR original confirms merged at 2026-09-13T20:55:34Z. Tested head: `ddd2b9d82d560ba2657a7904f061fb20196d5924`. Merge commit: `779ca25e1e14f141fc6626040fcf026d034f706e`. Both resolve to application Git tree `995d0d83faf883bec980c896fe8a17b0f12360fa`. All four workflow API originals and nine completed job logs bind the tested head; source/alignment results identify 1,332 application files and SHA256 tree `1c4d78c3c1bb5f448d0ebdb99d16a2d76419bbc663cc9ed8fae831e1d18c10c4`.

C13 independently compared complete recursive Git trees: the only application change from failed 9f28f822 to ddd2b9d8 is `src/go_hotel/api/routes/operations_console.py`. All other 1,331 Git blobs remain identical. C13 independently recomputed the actual source SHA256 using those verified bytes and the exact new route; it matches 1c4d78c3. The actual route SHA256 is `dd8ce37a8fa8def78d855012086f22c841aacdda8bbe7437f8322297e53a9a38`. Its AST equals the locally reviewed e945428d route; the difference is the blank line after the typing import. The uncommitted local f1404067 tree is superseded and must not replace canonical.

## Completed CI originals

| Run | Scope | Independent result |
|---|---|---|
| 34781824271 | Canonical parent retention | Four Python shards success; frontend 270/270, compatibility 34/34, HTTP 150 checks / 88 requests / zero failures. |
| 34781824291 | V7 Cell scoped closure | New six-domain regressions 119/119, capacity 11/11, pagination/direct-call suite 34/34. |
| 34781824295 | DEPTH48 ordered acceptance | Disposable PostgreSQL 16.4 migrated through 0133_flight_change_plan, 6/6 tests with no skips, four race proofs; isolated real browser six same-order journeys, six-order independent ledger and hotel-change ledger PASS. |
| 34781824424 | Mobile retention | Types/contracts, native linking and disposable iOS/Android project generation PASS. This is not signed native build or device acceptance. |

| Shard | Job | Files | Tests | Passed | Failed/errors | Skipped |
|---|---|---:|---:|---:|---:|---:|
| 0 | 103790113824 | 64 | 477 | 476 | 0 | 1 |
| 1 | 103790113842 | 63 | 518 | 518 | 0 | 0 |
| 2 | 103790113859 | 63 | 519 | 519 | 0 | 0 |
| 3 | 103790113829 | 63 | 418 | 413 | 0 | 5 |
| Total | | 253 | 1932 | 1926 | 0 | 6 |

The complete fixed application tree contains 253 test*.py files. Fixed run_suite.py assigns its sorted list by files[shard::4]; expected 64/63/63/63 files are disjoint and equal all four completed log selected_files counts. The original failed 9f28 case is in the unchanged 477-case shard 0; new shard 0 has zero failures and one additional PASS. Old raw failure evidence remains historical evidence, not a current canonical failure.

## PostgreSQL skip mapping

This is an explicit inference from fixed source, subprocess environment and completed originals, rather than a claim of direct inaccessible JUnit inspection:

1. Fixed ci/retention/run_suite.py copies only PATH/LANG/LC_ALL/TZ/GO_NATIVE_NODE into pytest's environment and sets a small explicit test environment. POSTGRES_TEST_DATABASE_URL is absent.
2. Fixed `tests/test_p0_0100_postgres_concurrency.py` reads that variable at import and has exactly one test with mandatory skipif(not URL). Its sorted file index belongs to shard 0.
3. Fixed `tests/test_p0_0101_postgres_race_matrix.py` does the same for exactly five tests; its file belongs to shard 3. The completed shard logs show exactly 1 and 5 skips respectively, with none in other shards, matching these mandatory skip sets.
4. Fixed ci/depth47/postgres.py sets POSTGRES_TEST_DATABASE_URL to its disposable loopback PostgreSQL service and runs exactly these same two test files. It asserts tests=6, failures=0, errors=0, skipped=0. Job 103790113738 prints that exact successful result plus real PostgreSQL version, migration head and four persisted race proofs.

Consequently, the six database-specific cases skipped in SQLite shards have same-source successful execution in the dedicated PostgreSQL job. Report as 1926 shard PASS plus 6 dedicated PostgreSQL PASS, preserving the original six shard SKIP statuses; do not rewrite the shard results.

## Query repair and evidence limits

The actual merged route uses Annotated Query metadata and ordinary defaults 1/1/50/None, preserving HTTP bounds and order_id max length, admin dependency, pagination SQL and refund mapping. The fixed `ci/admin-pagination/test_pagination.py` adds six direct-call-versus-HTTP comparisons, one per vertical, while retaining all 28 previous pagination/security tests. The new scoped log reports 34 PASS. This directly closes the inherited direct-call regression and retains HTTP behavior.

Completed nine decoded GitHub job log texts are saved under `c13-canonical-ci-originals/`; save representation may normalize a final newline. They are not artifact ZIP files. Earlier artifact ZIP links were unavailable with HTTP 403; this review does not claim locally downloaded ZIPs, independently recalculated ZIP digests or direct artifact JUnit inspection. The inherited parent-package/archive jobs are intentionally skipped by historical exact PR 47 conditions; no current runtime image/package PASS may be inferred from them.

This C13 task performed only reads and scratch review/original-text saving. No tests were rerun for the already merged candidate, no GO directory edits, GitHub writes, CI dispatch, merge or Hong Kong operations were performed. Source integration evidence is complete for the actual scoped fixes and inherited regression boundary. All-Cell completeness, external providers, native devices, 1000 active-user Hong Kong capacity, sealed runtime/package, formal deployment task and runtime receipt remain separate gates; this report gives no 100% or deployment claim.
