# C13 independent PR 66 CI review

Status: ORIGINAL_CANDIDATE_REJECTED_FOR_SOURCE_MERGE; SOURCE_MERGE_GATE=HOLD; FULL_RELEASE_GATE=HOLD; DEPLOY_GATE=HOLD.

Update: independent job 103743756189 original confirms a genuine inherited PR 62 compatibility regression. `test_depth41_transaction_views.py::test_admin_hotel_refund_amount_is_real_column` calls `vertical_snapshot('HOTEL', p=None)` directly, leaving FastAPI `Query` objects as Python defaults; `order_id.strip()` raises AttributeError. Shard 0 reports 477 tests: 475 passed, 1 failed, 1 skipped, 0 errors, selected_files=64. This is distinct from the earlier workspace SQLite failure. No merge approval is given to commit 9f28f822. The other scoped PASS results remain valid and are not rerun. A smallest compatible signature correction with preserved HTTP constraints requires its own independent code/targeted-test acceptance.

This review reads existing CI originals only; no test rerun, source modification, GitHub mutation, merge, or Hong Kong operation was performed by C13.

Fixed candidate: `9f28f822110e187c22baf82391063c8b05c039c1`; application Git tree `b9aee82e8c3932a540349b1f62b714c5ea52e837`; source SHA256 tree `20b8b9b547636b47ab627f2adf8adc562deb01e07bce224e4705e838c92e7eb2`; 1,332 source files. All four workflow API originals bind this same head. Completed log originals independently print the same source fingerprint and the 19 inherited compatibility files unchanged.

| Run | Job evidence | Independent finding |
|---|---|---|
| 34764800518 | scoped-acceptance / 103743756297 | PASS: six new regression files 73+4+8+3+15+16=119; inherited capacity 11 and pagination 28 also PASS. Frozen Python 3.13.5 dependencies, new processes, normal worker settings. |
| 34764800483 | frontend-http-compat / 103743756072 | PASS: 270 frontend tests, zero fail/skip; disposable HTTP 150 checks / 88 requests, zero fail; 34 compatibility unit tests successful. Four Python shards remain pending independent complete-result review. |
| 34764800484 | postgres / 103743756528 | PASS: disposable PostgreSQL 16.4 migration through 0133_flight_change_plan; six tests, zero fail/error/skip. Four persisted race proofs report PASS. No external providers. |
| 34764800484 | browser / 103743756438 | PASS_SCOPED: real isolated browser three actors, six same-order journeys, viewport checks, hotel change/refund recovery; independent six-order ledger and separate hotel-change ledger PASS. Does not establish Hong Kong concurrency, real provider or production readiness. |
| 34764800494 | mobile-source-and-native-linking / 103743755992 | PASS_SCOPED: types/contracts, native links, generated disposable iOS/Android projects. No signed native build or physical-device acceptance. |

The inherited `ci/retention/run_suite.py` enumerates sorted `application/tests/**/test*.py` and assigns `files[shard::4]`. It records the all/selected inventories and counts JUnit failures/errors/skips, exits with pytest's return code, and uses frozen dependencies with explicit pytest-asyncio loading. Independent complete Git tree API enumeration found 253 test files; the expected four disjoint shards contain 64/63/63/63 files. The reconstructed inventory is saved separately and is explicitly not a downloaded artifact. Complete four-shard logs must still confirm selected-file counts and execution results. Artifact ZIP download attempts by the coordinator returned HTTP 403; ZIP digests are API claims, not locally recalculated. This review does not claim direct artifact JUnit/inventory inspection. The historical parent-package job is deliberately skipped by its old PR 47 exact-head condition; this is neither a regression failure nor a new candidate runtime package PASS.

Nine completed decoded job logs are saved in `c13-pr66-ci-originals/` as tool text representations, possibly with a normalized final newline. They are not ZIP originals. Their local file SHA256 values are independently computable.

Final full-shard observations supersede the interim pending statements above:

| Shard | Files | Tests | Passed | Failures | Errors | Skipped |
|---|---:|---:|---:|---:|---:|---:|
| 0 | 64 | 477 | 475 | 1 | 0 | 1 |
| 1 | 63 | 518 | 518 | 0 | 0 | 0 |
| 2 | 63 | 519 | 519 | 0 | 0 | 0 |
| 3 | 63 | 418 | 413 | 0 | 0 | 5 |
| Total | 253 | 1932 | 1925 | 1 | 0 | 6 |

All four fixed-source log summaries match the independent expected file coverage. This is a complete attempted regression with one actual compatibility failure; it is not a full regression PASS. Six PostgreSQL tests separately pass in the dedicated disposable PostgreSQL workflow; exact skip node IDs were not directly inspected in inaccessible artifact JUnit, so this report does not infer a node-by-node skip replacement from matching counts alone.

The old local SQLite failures remain preserved evidence. They are not overwritten by the new CI pass and do not prove workers were responsible. Source integration of the six scoped fixes may be acceptable after the remaining all-shard proof and authority review, independently of full release. Full release still needs the remaining V7 Cell gaps, live/external and device gates, candidate runtime package and authorized deployment evidence. User authorization to merge/deploy does not itself create those technical PASS results. Production remains HOLD.

## C12 compatibility correction: independent C13 addendum

C12 corrected only `operations_console.py`: added `typing.Annotated`, moved the four existing Query constraints into Annotated metadata, and restored ordinary Python defaults 1/1/50/None. The exact repaired file SHA256 is `e945428dec148fcabdb904a3fcbd9232a3bed6a657a61dbb78869d0866113724`. Independent diff against fixed 9f28 source confirms no route body, pagination SQL, role dependency, refund mapping, or limit changes. A representation-only final newline in the downloaded comparison copy is not a source change.

C13 independently ran only affected checks in new processes and /tmp test state with normal worker settings: the original failing hotel refund direct-call test now passes (1/1); invalid HTTP parameters and authentication/roles pass (9/9). Files: `c13-pr66-direct-independent.xml`, `c13-pr66-http-independent.xml`. C12 separately reports its broader affected domain tests: original transaction views 12/12 and pagination 28/28; C13 does not relabel those developer runs as independently rerun. Original tests were retained.

PATCH_REVIEW=PASS_SCOPED and LOCAL_AFFECTED_REGRESSION=PASS. The original 9f28 frozen CI remains failed. The repaired file still requires exact new candidate binding and frozen affected CI before SOURCE_MERGE_GATE can advance. None of the old unrelated PASS tests was rerun by C13; all prior original results remain preserved. FULL_RELEASE_GATE=HOLD and DEPLOY_GATE=HOLD.
