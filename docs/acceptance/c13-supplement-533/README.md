# #533 C13 evidence supplement — staged source repair

Date: 2026-10-07 Asia/Shanghai.
Base: `00dcf6007fee0513b9ef6184209782d67cad7c0c`.
Change classes: CONTROL_PLANE, PRODUCT_FIX, TEST_ONLY, DOCUMENTATION.

## Problem and verified execution

Candidate #531 remains frozen at `0b7d0403f9f171844fdcf9bf3330ff9386e82943`.
C13 run `37484199333`, attempt 1, machine job `112339914820`, reviewer job
`112342053115`, artifact `11423210723` sealed `BLOCKED / C13-EVIDENCE-001`.
The PostgreSQL 18.4 evidence covers 20 passing cases in three changed files.
The required unchanged funding file and checkout node were omitted by the
changed-file inventory derivation. The existing C14 is `PASS_SCOPED` and must
not be repeated for this payment candidate.

Consumer comments are not an execution API. The same Issue/SHA maps to the
same task; posting further directives cannot admit a supplement. No absence of
a new Actions run proves whether a host task is queued or claimed.

## Implemented in this draft

Formal review Issue bodies may declare one plain, single-line `Machine inventory:`
field. It takes precedence over changed tests; without the field, legacy behavior
and task identities remain unchanged. The explicit list is bounded by the existing
400-character / 20-file limits. Unsafe tokens, duplicates, repeated fields and
over-limit lists fail closed, never truncate or fall back. Test files must be
regular files under `application/tests/` in the exact frozen application Git tree.
Symlinks and submodules are refused. Named pytest nodes are supported; node
existence and collection remain the machine runner's responsibility.

Example for a NEW review's explicit scope (not an instruction to mutate #533):

```text
Machine inventory: application/tests/test_depth25_migration_history.py application/tests/test_unknown_episode_retention.py application/tests/test_v70_r4_c01_unknown_episode.py application/tests/test_v70_next_c01_unknown_funding.py application/tests/test_depth06_direct_checkout.py::test_unknown_funds_keep_inventory_and_block_cancel_and_timeout
```

This patch does not change an existing queued payload, read comments, create a
new round, enqueue C13 directly, or raise `max_attempts`. Editing an already
admitted Issue's scope is NOT a supported supplement mechanism. Do not use this
draft to restart #533 or create another C14 review of #531.

## Local verification

Python 3.12.14, no network/model/database execution during tests.

```text
python -m unittest discover -s GO/control-plane/runtime-host-channel-v1 -p 'test_c1_review*.py'
Ran 63 tests
OK (exit 0)
```

12 new tests plus 51 existing ingress tests. Replaying the five-path regression
against the unchanged base implementation produces the expected assertion
failure: actual inventory contains three paths instead of five. The modified
implementation passes. The initial local runs lacked two materialized dependency
files; after fetching those unchanged base files, the suite above passed. No
dependency installation or source workaround was used.

## Remaining work before #533 can close

1. Define a bounded supplement admission bound to the original C13 run/attempt,
   frozen candidate/application tree, original C14 run/root, and the exact missing
   inventory. A comment identifier alone must not create another paid execution.
2. Read original sealed artifacts through the existing trusted transport. Verify
   their roots, byte digests, candidate, run/attempt and actual machine database
   evidence before reuse. Preserve the original blocked opinion and round.
3. Execute ONLY the missing funding file and checkout node on isolated PostgreSQL
   18.4, then verify a complete union with the original evidence. Keep per-run
   manifests, JUnit, stdout, commands and exit codes; do not represent the original
   20 tests as newly executed. Fail on mismatch, skipped/missing/failed cases.
4. Reseal C13 through the existing independent review and original C14 prerequisite.
   Dedup must survive a crash before/after enqueue and ambiguous dispatch; one
   admitted supplement at most, no automatic repeated paid review.
5. Test admission → claim → machine output → aggregate verification → fresh C13
   → readback, including negative cases and restart windows, before any completion
   claim. The source repair candidate needs its own review, separate from #531.

No new Builder Issue was created: #511 already lacks a verifiable terminal
receipt. No Runtime DB/service was accessed or changed. The host ledger and
installed consumer version remain UNPROVEN while no device is connected.

## Delivery status

| Dimension | State |
| --- | --- |
| Explicit inventory source repair | Implemented in this draft |
| Local ingress regression | 63 PASS |
| C13 supplement admission/aggregation | NOT IMPLEMENTED |
| Independent review of this draft | NOT RUN |
| #533 missing tests | NOT EXECUTED by this change |
| Merge / installation / deployment | NOT DONE |

This is a staged WIP candidate, not a complete supplement entry and not payment
acceptance. Keep the draft open for the remaining work; do not create a second
synonymous fix task/PR. No rt01, real payment, SMTP, ABBA or budget changes.

Evidence:
- https://github.com/yuguangzhi3836-glitch/GO/issues/533#issuecomment-6020867987
- https://github.com/yuguangzhi3836-glitch/GO/actions/runs/37484199333/job/112339914820
- https://github.com/yuguangzhi3836-glitch/GO/actions/runs/37484199333/artifacts/11423210723
