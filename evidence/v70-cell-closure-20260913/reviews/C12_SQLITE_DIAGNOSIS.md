# C12 isolated-acceptance SQLite diagnosis

Scope: diagnosis only, no application, worker, conftest, runtime, migration,
security rule, Hong Kong, or Production changes.

## Outcome

The observed failure is **SQLITE_READONLY_DBMOVED (1032)**, not proof of an OS
permission problem, C11 idempotency regression, or broken business money rule.
A database file open by the acceptance process was removed/replaced while a
test was active. The identity of the actor that moved that file is not proven.

Use a fresh, exclusively owned temporary directory outside the shared workspace
for the mutable SQLite acceptance database; preserve raw evidence afterwards.
Do not disable workers or patch business code to suppress this failure.

## Evidence

| Run | Worker configuration | Database | Result |
|---|---|---|---|
| Original hotel-only diagnostic | Existing defaults: vertical enabled, hosted disabled | workspace | 13 PASS |
| Original inherited 24, with inode/error instrumentation | Same existing defaults | workspace, exclusively named `c12-inode24-diagnostic.db` | 23 PASS / 1 FAIL |
| Same inherited 24, with the same instrumentation | Same existing defaults | `/tmp/go-c12-db-diagnostic-G1CQ0C/acceptance.db` | 24 PASS, 16.64 seconds |
| Controlled lifecycle diagnostic | Existing worker and TestClient behavior, blocked test callback | No business database | 2 PASS |

The 24-test selection is unchanged:

- `tests/test_depth48_hosted_forfeiture.py`
- `tests/test_depth33_mobility_refund_consent.py`
- `tests/test_idempotency.py`

No C11 added fixture runs in that selection. The isolated `/tmp` run records
15 worker starts and 15 worker ends, with no SQL_ERROR or STALE_CHECKOUT.

The failed workspace run reaches the non-HTTP case
`test_mobility_crash_after_money_keeps_pending_and_recovers_once[RIDE]`:

- Connection checkout at monotonic `52385338132242` observes inode `1188809`.
- SQL_ERROR at `52385349457584` reports code `1032`, name
  `SQLITE_READONLY_DBMOVED`, current path inode `1188829`.
- `/proc/self/fd/12` points to the same acceptance database with ` (deleted)`.
- No local RESET_UNLINK event occurs between those observations.
- The last expiry-worker completion was earlier, at `52382668783531`.

This demonstrates a moved live database file, not a mere text interpretation of
"readonly". It does not identify the actor performing the move. Workspace/tool
synchronization is one hypothesis, not a verified conclusion. The parent also
paused filesystem edits during the `/tmp` control; that is a recorded diagnostic
condition, not evidence that a particular parent edit caused the original issue.

## Worker hypothesis: tested, not guessed

Controlled tests using the actual worker prove that cancelling its coroutine can
finish before an in-flight `asyncio.to_thread` callback finishes. Separately,
the actual `TestClient` context exit waits for that default-executor work to
finish. Therefore the proposed chain "cancel coroutine, then conftest resets
while its thread remains" is not established for the normal client fixture.

`tests/conftest.py` and `workers/vertical_expiry_worker.py` remain byte-identical
to the transported inherited source, with SHA256 respectively:

- `52ce17e787753b0f827e8b249aa857176729ce1139779e05031412fa88caa17b`
- `b7cffb357ccaa32484e6d8e2ea2909fdc1c7dc4623da55008fd28e8cda475491`

## Raw evidence and SHA256

| File | SHA256 |
|---|---|
| `c12-inode24-diagnostic.xml` | `4732a5f70315ea0cbc3575a5df6b05591918a439c618ceea440191c6998dbb81` |
| `c12-inode24-diagnostic.jsonl` | `fe244f83bbcef58f5b490bf50c5c44635187543dd3dc8f31a661d7e6c7b7f5c6` |
| `c12-tmp24-diagnostic.xml` | `8eded0204cf14d3bb087a8a260cbcfd3f3d1a626656995fa871cff0f19b4ecd3` |
| `c12-tmp24-diagnostic.jsonl` | `ef6463a0574257f1a1cd1383b3c0e269193a7c83a03eb94699d55d64cfea7b2a` |
| `c12-worker-lifecycle-diagnostic.xml` | `9bcaa496f33091432e03ea6eed95ee161863122cc63b6edec5c2fa17fc8c8fd8` |

All files are under `/workspace/scratch/2d68c25b0133/`. Diagnostic-only source:
`c12_sqlite_diagnostic.py` and `test_c12_worker_lifecycle_diagnostic.py`.
Do not add these as new production behavior or count diagnostic controls as
business-function completion.

## Remaining gate / next action

C13 should re-run the complete candidate selection with default workers enabled
and an independently named database under a fresh `/tmp` directory, binding the
raw result to the fixed candidate. Preserve the earlier failures alongside the
new result; no rewriting or replacing of historical evidence. This diagnosis
does not itself establish complete C13, PostgreSQL, external payment, deployment,
or final-release acceptance. No business or worker patch is proposed.
