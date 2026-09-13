# C13 independent review — scoped Cell repairs

## Decision

`C13_DOMAIN_SCOPED_CODE_REVIEW=PASS` for the five source-file hashes below.
No new P0/P1 semantic defect was found in the five narrow repairs. C13 did not
implement or edit these business files.

**`WORKER_ENABLED_AGGREGATE_REGRESSION=HOLD`**: three independent candidate runs
failed with SQLite `attempt to write a readonly database` during authentication
setup in inherited hotel tests. These failed runs remain original evidence.
The no-worker diagnostic must not replace them or be called a full regression
PASS. Full fixed-source CI, worker lifecycle, HK capacity, external-provider,
Sealed Node and final release gates are not approved by this review.

HK DEPTH48 was not accessed or changed; Production remains HOLD.

## Reviewed source identities

The source deltas were compared directly against the parent's verified fresh
1325-file canonical baseline at `runtime-transport/source/application`, bound
to `main@286e294d92df4b7d1c0073116a8e628734abec6c`, application tree
`3025b2b6b36ea9211da561a4631f304216de9d90`.

| Cell | Candidate path beneath application/ | SHA256 |
| --- | --- | --- |
| C01 | src/go_hotel/services/hosted_fare_value.py | cf9f2c3ed701419e974f2c9144724238be3ea1d82b18d979fdfbb1b0815ee4e5 |
| C04 | src/go_hotel/mobility/rental/service.py | d8768e8eef0d2e083d6b777ba3eca38124caa801ecda49282c8308708f8c0c99 |
| C08 | src/go_hotel/go_ai/service.py | 9b0ef8d9907155a60c143f55c8ecb32ec18dc2262a44354144d2fad71e1adf45 |
| C10 | src/go_hotel/journey/service.py | cbb4ad735e6a3a6632154dace37a80ef7945e95706bbfc17e1a32f674e0ab67b |
| C11 | src/go_hotel/api/idempotency.py | 260a12d78f7e4b1cb375ee71e200486146feb3b8946ad1805ba5c15534f86c58 |

The main/metrics/pagination inheritance was being assembled concurrently by
the parent. This review is explicitly bound to the listed domain hashes, not
a claimed immutable aggregate commit. The parent must bind final aggregate
CI/review to a fixed candidate tree and source fingerprint.

## Independent focused results

There are **46 distinct new targeted cases** across the five repairs, all
independently executed successfully in isolated groups. Repeated executions
are not additional coverage or additional completed features.

| Cell | New cases | What was independently exercised |
| --- | --- | --- |
| C01 | 4 | Missing current managed nights rejects summary/cancel quote/credit quote without money mutations; legacy no-managed-stay value remains compatible |
| C04 | 8 | Completed refund vs divergent order terminal states; consistent replay; concurrent-completion recheck; owner check |
| C08 | 3 | Provider-timeout and unexpected synthesis failure finalize parent audit as FAILED; successful response retains hash-only audit and advisory boundaries |
| C10 | 15 | Six verticals × owner/member current-status list/detail parity; unauthorized/revoked member; foreign-owned/missing order fallback; no snapshot mutation |
| C11 | 16 | Sync/async result-recording failure retains claim; replay/conflict/key guards; callback-error compatibility; real private SQLite claim and explicit reconciliation |

Clean independent executions:

- `domain-new-db-independent.xml`: C01 + C04, **12 passed**.
- `domain-c08-no-db-independent.xml`: C08 + C10 + C11, **34 passed**.
- `domain-no-db-independent.xml`: earlier C10 + C11, **31 passed** (overlapping,
  not added again).
- `domain-worker-excluded-independent.xml`: same five new suites plus three
  inherited suites, **70 passed**, with both optional expiry workers disabled
  only in the disposable test environment. This is an explicitly reduced-scope
  diagnostic, not worker-enabled aggregate acceptance.

Independent environment: Python 3.12.14, pytest 9.1.1, FastAPI 0.141.1,
SQLAlchemy 2.0.52, Starlette 1.6.0, AnyIO 4.15.1. This is not frozen-runtime,
PostgreSQL, production or real-provider acceptance.

Each file-backed run had its own explicit DB filename in the uniquely-created
`c13-review/domain-db-kODgeS/` directory. The new no_db fixtures use their own
memory/file-backed SQLite engines. No configured business database was used.

## Preserved failures and diagnostic boundary

| Raw XML | Outcome | Failure scope |
| --- | --- | --- |
| domain-independent.xml | 66 pass / 1 fail | First inherited hotel forfeiture case after all 43 then-existing new tests passed; readonly auth-session INSERT |
| domain-db-independent.xml | 35 pass / 1 fail | Fresh process without C10/C11 new tests; another inherited checkout case, readonly identity-user INSERT |
| candidate-inherited-only-independent.xml | 23 pass / 1 fail | Fresh process running only the 24 inherited tests; cancellation case, readonly identity-user INSERT |
| baseline-inherited-independent.xml | 24 pass | Same 24 inherited tests on untouched transport baseline |

The candidate inherited-only failure rules out direct contamination by the
new C11 in-memory test fixture in that process. The single clean baseline run
does not establish that the problem is absent from all baseline executions.
The varying failing hotel scenarios share HTTP authentication setup, not a
failed fare-value assertion.

Code inspection found a plausible lifecycle interaction: default vertical
expiry is enabled; the lifespan cancels/awaits the async worker; that worker
awaits `asyncio.to_thread(expire_due)`, while the pytest reset fixture disposes
the engine then unlinks/restores the SQLite database. Cancelling the awaiting
coroutine does not itself establish that the worker thread has stopped using
the old file. Disabling only the optional expiry workers produced 70/70, which
supports investigating this boundary but is not by itself causal proof.

C12 has been given the exact command, failed XMLs, and worker-exclusion result
for a controlled slow-tick/cancellation proof. The worker-enabled aggregate
gate remains HOLD pending that investigation and a fixed-source rerun.

## Semantic review notes and remaining gaps

### C01

The extra managed-stay lookup only runs when no current nightly rows are
found. Managed reservations normally create Stay and all dated Night facts
in the same existing session. Missing all current nights now fails closed
instead of restoring gross funding as spendable room value. Existing partial
night-count and negative-value checks remain. Legacy direct reservations
without a managed stay retain the existing face-value behavior.

This guard does not restore corrupt rows or prove integrity when both the
managed-stay marker and night facts disappear. It does not change hotel fees,
365-day rules, forfeiture policy, or authorize refunds/payments.

### C04

Both completed-refund early-return paths now require the order's terminal
state REFUNDED. Existing owned-order locks, frozen consent verification,
money-confirmation requirements and state/evidence writes remain in place.
The guard surfaces inconsistent truth; it does not silently reconcile it or
send money. No new fee/deposit/insurance policy was introduced.

### C08

Synthesis failures now follow the already-existing subtask-failure audit
finalization contract. Existing ValueError codes are preserved; unexpected
exceptions become the stable orchestration-failure code. Successful behavior
and advisory-only response remain unchanged. This does not guarantee audit
storage availability, record every unexpected provider invocation failure,
or handle every other planning/verification failure path. No provider network
request, credential use or model-business-truth authority was introduced.

### C10

List uses the same current-owner-checked status projection as detail and
does not rewrite canonical orders or historical attachment snapshots. Active
journey membership and existing missing/foreign-owned fallback remain.
It adds a native-order read for each listed item (an N+1 query cost); the
current-status correctness pass is not a capacity/performance pass. Missing
orders can still display historical snapshot status under the retained
fallback, so "all visible statuses always current" would overstate scope.

### C11

Moving resource-ID extraction and result completion outside the callback's
claim-release handler prevents a second side effect after a successful
callback followed by completion-storage failure. The persistent 102 claim
then returns 409 IN_PROGRESS on retry. Explicit use of the existing completion
primitive recovers replay in private SQLite tests.

There is no newly implemented automatic claim-reconciliation worker, no
PSP/real-database acceptance and no all-operation exactly-once proof. Callback
exceptions still release the claim under the retained contract; a callback
that commits an external side effect and then raises remains a separate
unresolved boundary. This repair covers successful callback return followed
by recording failure, not every ambiguous external outcome.

## Evidence hashes

| Raw XML | SHA256 |
| --- | --- |
| domain-independent.xml | 6fd0a55c53446d68efab4a24a781015f39b59bf5484f56e7068b555b3a5cdb7a |
| domain-db-independent.xml | 84d7a1fb61e8891aaa707c1ef2ffd83f00d4f922f35bc8e39b26d034b84fa969 |
| candidate-inherited-only-independent.xml | ca76be4ea190f1588c0c3e987a0de90f905c35fae2ae276f347f747901a5a6b0 |
| baseline-inherited-independent.xml | 790c209db24b7bff1dc7c1be5b3756d16ecd4f0258e99fbc0c6fc63cf1559f2d |
| domain-new-db-independent.xml | 8af901529f6ca3ed468cdf89f6a7aa31288321f124689f4d800a4347bd00e9ae |
| domain-c08-no-db-independent.xml | 6690c896c22376e6441b2e0a0e58747091ff59b9257f2cf95278d2d8d4b7dca9 |
| domain-worker-excluded-independent.xml | d539c9154e0cf5b12e0fa2266eee94cbb11ba8fe56b9acf726c20285611c97d5 |

New test-source hashes:

| Path beneath application/ | SHA256 |
| --- | --- |
| tests/test_c01_hosted_fare_value_integrity.py | d5c89d4a4d3d0f880659abce0a8be596da997327e92fd3859368a96b2ad72991 |
| tests/test_c04_refund_terminal_integrity.py | b66b39fe48d6c56bd009ee73a2931845a1e553ad5b65a90fd16f8c669114820a |
| tests/go_ai/test_c08_synthesis_audit_finalization.py | 1c431307f6c97dd2389950391bcaf0af93e99f9f3004088a8c0f31196d022327 |
| tests/journey/test_c10_current_status_projection.py | a87fb62bc980726a5ee5cb83ff57f1f452e9944b7a836c23b7f5ccd0a0059f16 |
| tests/test_c11_idempotency_completion_guard.py | 9b40a65a8c1c36edeb3c036ae932a90f571ae17127dcc8f3b7c23e14813f04f5 |

## Reproduction command for the unresolved inherited failure

From the GO source directory, the following original invocation produced
23 passes and the readonly failure. A later execution must use a newly-created
private DB path and a new output filename, not overwrite the existing evidence.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 GO_TEST_DB_PATH=/workspace/scratch/2d68c25b0133/c13-review/domain-db-kODgeS/candidate-inherited-only.db PYTHONPATH=application/src:application /workspace/scratch/2d68c25b0133/go-venv/bin/python -m pytest -p no:cacheprovider -o addopts='' application/tests/test_depth48_hosted_forfeiture.py application/tests/test_depth33_mobility_refund_consent.py application/tests/test_idempotency.py -q --tb=no --junitxml=/workspace/scratch/2d68c25b0133/c13-review/candidate-inherited-only-independent.xml
```

The 70-case worker-excluded diagnostic used the same interpreter, import path,
pytest flags and all eight new/inherited test files enumerated above; it set
`VERTICAL_RESERVATION_EXPIRY_WORKER_ENABLED=false` and
`HOSTED_RESERVATION_EXPIRY_WORKER_ENABLED=false`, used
`domain-db-kODgeS/worker-excluded.db`, and wrote
`domain-worker-excluded-independent.xml`. No source, configured runtime or
server setting was changed to obtain that reduced-scope result.

All raw runs are retained separately. No skipped/failed/worker-excluded result
is promoted to a broader PASS. See the separate `c14-review.md` for C14 guard
acceptance and its explicit complete-evidence-chain HOLD.
