# C13 final independent review — V7.0 Cell closure candidate

Latest status is the dated addendum at the end: the exact 70-case selection
now passes with existing default workers and a private `/tmp` DB. Earlier
failure/diagnostic records below are preserved as historical observations.
Complete production/final-release acceptance remains HOLD.

## Outcome

**Scoped six-repair review: PASS. Complete release / aggregate acceptance:
HOLD.** No newly introduced P0/P1 semantic defect was found within the six
narrow repair scopes. Independent focused executions cover **119 distinct new
cases: C14 73 + C01/C04/C08/C10/C11 46**. Repeated runs and inherited tests are
not added to that distinct-new-case count.

Three worker-enabled candidate regression runs contain unresolved SQLite
readonly failures. They are preserved below. A 70-pass run with expiry workers
disabled is explicitly a reduced-scope diagnostic, not a replacement PASS.
C12's controlled worker-lifecycle investigation is still separate and pending
at this report's finalization.

HK DEPTH48 was not accessed, installed, changed or deployed by C13. Production
and full release remain HOLD. A Draft PR or source manifest is not execution
authority; this report grants no deployment authority.

## Independently verified final source identity

C13 independently rebuilt Git blob and directory-tree hashes from the current
local bytes and baseline inventory, checked executable modes and old/new blob
links, and computed the sorted path-NUL-SHA256 source fingerprint. No Git write
or business-file edit was used for this verification.

| Identity | Verified value |
| --- | --- |
| Baseline commit | 286e294d92df4b7d1c0073116a8e628734abec6c |
| Baseline application tree | 3025b2b6b36ea9211da561a4631f304216de9d90 |
| Candidate application tree | b9aee82e8c3932a540349b1f62b714c5ea52e837 |
| Candidate tracked source files | 1332 |
| Candidate source SHA256 | 20b8b9b547636b47ab627f2adf8adc562deb01e07bce224e4705e838c92e7eb2 |
| Changed application manifest entries | 17 |
| ci/cell-closure/CANDIDATE.json SHA256 | 685a75a42c2c45acde7db1ce969536d0d289373f9622a3ba55c14cd5554f8e71 |
| Source manifest integrity mismatches | 0 |

The manifest correctly identifies inherited PR62 `d8aa02ff...` and PR64
`8246993f...`, and declares `production=HOLD`, `full_release=HOLD` and no HK
access/deployment. Its shape and source checks are a **source-integrity PASS**,
not evidence-retrieval completeness, a signature check, or a run-generated
full-test PASS. No signed release/execution evidence is claimed.

The final aggregate identity was verified after the focused tests. Earlier
tests were bound to the six reviewed file hashes; the parent was assembling
the other inherited application files concurrently. Therefore this report
does not retroactively claim every earlier runtime executed this exact final
1332-file tree. New aggregate CI must bind its own run to its fixed commit/tree.

## Six exact repair hashes and scoped decisions

| Cell | Source path beneath application/ | SHA256 | Distinct new cases |
| --- | --- | --- | --- |
| C01 | src/go_hotel/services/hosted_fare_value.py | cf9f2c3ed701419e974f2c9144724238be3ea1d82b18d979fdfbb1b0815ee4e5 | 4 |
| C04 | src/go_hotel/mobility/rental/service.py | d8768e8eef0d2e083d6b777ba3eca38124caa801ecda49282c8308708f8c0c99 | 8 |
| C08 | src/go_hotel/go_ai/service.py | 9b0ef8d9907155a60c143f55c8ecb32ec18dc2262a44354144d2fad71e1adf45 | 3 |
| C10 | src/go_hotel/journey/service.py | cbb4ad735e6a3a6632154dace37a80ef7945e95706bbfc17e1a32f674e0ab67b | 15 |
| C11 | src/go_hotel/api/idempotency.py | 260a12d78f7e4b1cb375ee71e200486146feb3b8946ad1805ba5c15534f86c58 | 16 |
| C14 | src/go_hotel/autonomy/release.py | add9483e8e11e115a8bdb57791528a4137577088e396bdbcdb18cb302a1f3802 | 73 |

All six hashes matched the reviewed versions and final candidate manifest.
Details and test-source hashes are in `domain-independent-review.md` and
`c14-review.md`. C13 did not implement any of these business changes.

## Raw independent execution ledger

All paths below are within `c13-review/` unless qualified otherwise.

| Raw XML | Result | Scope / interpretation |
| --- | --- | --- |
| c14-independent.xml | 142 pass | 73 new C14 + 69 unchanged governance/authority tests |
| domain-new-db-independent.xml | 12 pass | New C01 and C04 |
| domain-c08-no-db-independent.xml | 34 pass | New C08, C10 and C11 |
| domain-no-db-independent.xml | 31 pass | Earlier overlapping C10/C11 run, not additive |
| domain-independent.xml | 66 pass / 1 fail | Mixed candidate; inherited hotel auth-session INSERT readonly |
| domain-db-independent.xml | 35 pass / 1 fail | Separate DB/process without C10/C11 new tests; inherited hotel identity-user INSERT readonly |
| candidate-inherited-only-independent.xml | 23 pass / 1 fail | Only inherited suites in a fresh process; inherited hotel identity-user INSERT readonly |
| baseline-inherited-independent.xml | 24 pass | Untouched transport baseline, same inherited suites |
| domain-worker-excluded-independent.xml | 70 pass | New 46 + inherited 24, both optional expiry workers disabled locally; reduced-scope diagnostic only |

Original developer C14 red/green evidence was also independently parsed but
not relabeled as C13 execution: `c14-evidence/baseline.xml` 59 fail/23 pass;
`c14-evidence/fixed.xml` 82 pass; `c14-evidence/inherited-controls.xml` 60 pass.
The independent 160-combination typed-risk/boolean compatibility probe passed;
it is a supplemental probe, not 160 additional unique new pytest cases.

The detailed reports preserve raw XML hashes, commands, interpreter/dependency
versions, private DB isolation, and scope limits. There are no skipped tests
counted as PASS and no full-suite result claimed here.

## Unfinished boundaries

- C14 retains legacy empty `evidence_refs=()` classification compatibility;
  `AUTONOMOUS_QUALIFIED` from that helper is not a complete evidence chain.
  Actor IDs/reference strings are not authentication, signature, freshness or
  source-to-artifact binding. Full C14 Gate → C13 → Evidence remains HOLD.
- C01 detects loss of all current nights while the managed-stay marker exists;
  it does not repair corruption or prove every hotel money path.
- C04 detects contradictory refund/order terminal states; it does not
  reconcile them automatically or authorize external money.
- C08 finalizes synthesis failure; other failure paths and unavailable audit
  storage remain separate. Providers were deterministic and non-network.
- C10 aligns list/detail status but retains historical fallback for missing
  orders and adds a native-order lookup per item. Capacity is unproven.
- C11 keeps claims after successful callback/result-recording failure; it does
  not implement automatic recovery or prove exactly-once external effects
  when a callback mutates then raises.
- Worker-enabled aggregate regression remains HOLD. Evidence supports
  investigating cancellation of `asyncio.to_thread` work against SQLite file
  reset, but the final causal proof/fix is not asserted in this report.
- Prior PR62 original evidence remains partial: 28-unit/preflight PASS and
  920 completed user records, not 1000-user/pagination-final/whole-ledger PASS.
  PR64 original CI results remain attached to their original source and scope,
  not automatically transferred as final aggregate CI PASS.

## Unique next acceptance action

Resolve the worker-enabled regression attribution with C12's controlled
thread/lifecycle evidence, then execute the relevant fixed-source isolated
regression and missing pagination/browser evidence against the preserved
candidate. Keep all existing scoped PASS code/evidence; do not redevelop it.
No automatic HK or Production deployment follows any individual Cell PASS.

## Addendum — 2026-09-13, default-worker private-DB independent rerun

**`C13_DEFAULT_WORKER_TARGETED_REGRESSION=PASS`: 70 passed, zero failures,
errors or skips, in 22.60 seconds (2 deprecation warnings).** This supersedes
the earlier unresolved-worker-enabled HOLD only for this exact test selection
and isolated execution. It is not a full application, PostgreSQL, external
provider, HK-capacity, deployment or production acceptance PASS.

### Diagnosis received and independently checked

C13 read `C12_SQLITE_DIAGNOSIS.md` (SHA256
`de604923ead5c37a33f1a5d2079056fc706da373d70959e94852bf866ce49378`)
and verified the referenced diagnostic XML/JSONL hashes. The raw workspace
failure records SQLite code 1032 `SQLITE_READONLY_DBMOVED`, a changed DB inode,
and an open descriptor to the deleted DB file during a non-HTTP RIDE test.
It does not identify which actor moved the file.

C12's actual-TestClient control shows its exit waits for default-executor
work. Therefore the earlier theory that an abandoned expiry thread caused
the normal fixture failure is **not established and is withdrawn as a causal
explanation**. Workspace synchronization is also only an unproven hypothesis.
The verified operational distinction is a moved live workspace DB versus an
exclusively owned temporary DB outside that shared workspace.

No application, conftest, business test, worker setting, migration or runtime
patch was made for this C13 rerun. All earlier failed XMLs and the reduced-scope
worker-disabled diagnostic remain untouched.

### Exact rerun scope and binding

- Database: `/tmp/go-c13-defaultworkers-iTzHhd/acceptance.db`, in an independently
  created `mktemp -d` directory outside the shared workspace.
- Existing defaults: `vertical_reservation_expiry_worker_enabled=true`;
  `hosted_reservation_expiry_worker_enabled=false`. Neither setting was
  overridden. This is not a claim that all eight HK business services were run.
- Same eight test files as the previous 70-case worker-excluded diagnostic:
  five new C01/C04/C08/C10/C11 suites (46 cases) plus the inherited hosted
  forfeiture, mobility refund-consent and idempotency suites (24 cases).
- Before and after execution, C13 independently recomputed all 1332 tracked
  file blobs/modes, the application Git tree and source SHA256. Both checks
  returned exactly tree `b9aee82e8c3932a540349b1f62b714c5ea52e837` and SHA256
  `20b8b9b547636b47ab627f2adf8adc562deb01e07bce224e4705e838c92e7eb2`.
- Test process exit code: 0. Raw XML confirms 70 tests, zero failures/errors/
  skips. The run is additional evidence for the same 46 new cases, not 70
  additional new cases. Overall distinct-new-case count remains 119 with C14.

Original command, from the GO source directory:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 GO_TEST_DB_PATH=/tmp/go-c13-defaultworkers-iTzHhd/acceptance.db PYTHONPATH=application/src:application /workspace/scratch/2d68c25b0133/go-venv/bin/python -m pytest -p no:cacheprovider -o addopts='' application/tests/test_c01_hosted_fare_value_integrity.py application/tests/test_c04_refund_terminal_integrity.py application/tests/go_ai/test_c08_synthesis_audit_finalization.py application/tests/journey/test_c10_current_status_projection.py application/tests/test_c11_idempotency_completion_guard.py application/tests/test_depth48_hosted_forfeiture.py application/tests/test_depth33_mobility_refund_consent.py application/tests/test_idempotency.py -q --tb=short --junitxml=/workspace/scratch/2d68c25b0133/c13-review/domain-default-workers-tmp-independent.xml
```

Source/default checks were run in separate read-only invocations of
`verify_source_identity.py before` and `verify_source_identity.py after` with
the same interpreter and application import path. The tests kept the default
worker configuration throughout; no database relocation was performed while
the process was running.

### New raw evidence

| File within c13-review/ | SHA256 |
| --- | --- |
| domain-default-workers-tmp-independent.xml | d4991e0208ef7011a7632d993a3772eaa9d8c056aa9b40ea13ad3074d890b566 |
| domain-default-workers-tmp-independent.log | 79de6e20f0cc50dbf7e475902048cf5fe29c0f6c00c31c5834bcaf28ed05343f |
| default-workers-source-before.json | 11a6729f2ed0c02c707f22fc083edd018cd9cf2524ef5c8ae8671a29957a138f |
| default-workers-source-after.json | 31aa7cb200c8134bfde1ef68a994f69dbfa9c80b56dafb9ca83fc4cef974ee20 |
| verify_source_identity.py | 8c678fa2fc7056fe114d565f3f273e541adcefd5ce467c1ee1eca0a202354a3b |

### Remaining next acceptance action

Preserve this fixed-source scoped result with its earlier failures, then close
the still-missing aggregate isolated CI and pagination/browser/ledger evidence
on the same candidate. C14's complete-evidence-chain boundary, native/physical
device, PostgreSQL, real provider/payment, Sealed Node and final-release gates
are not closed by these 70 tests. Hong Kong remains untouched; Production HOLD.
