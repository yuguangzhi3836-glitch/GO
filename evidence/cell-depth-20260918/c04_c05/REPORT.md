# C04 / C05 scoped development — 2026-09-18

Source commit: `c23a449d9bd117dc2f6ee2c249e65c343e050589`. Local parent: `42f3e62da844279cc3569c90eaa58d24a291a4d5`. This is a prepared PR217-derived candidate, not canonical main or the live runtime. No remote write, merge, deployment, migration or live supplier operation occurred.

## GAP → TASK → TEST → EVIDENCE

- **C04 / GAP-C04-CHANGE-RECEIPT-20260918:** rental extensions and shortenings trusted executor response labels/IDs. The repair checks the actual quote-bound capture, authorization, owner, beneficiary, currency and amount, and verifies every refund against this change's frozen allocation and idempotency key. Unproven responses retain the old dates/total and pending state; valid retries settle once. Fourteen new fault cases include foreign/original/authorization captures, absent receipts, damaged durable receipts, and equal earlier refunds on the same order.
- **C05 / GAP-C05-FLEET-STALE-SNAPSHOT-20260918:** the adjustment was read before waiting for its ride lock, permitting stale `PENDING` decisions or stale finalization. Both phases now use the same ride → adjustment lock order and refresh the row before acting. Four new injected stale-snapshot cases cover duplicate dispatch and a late confirmed/rejected query overwriting another worker's success. Existing threaded, process-kill and query-only recovery cases also pass.
- **Inherited PR204 / PR205:** only the exact additional identity-isolation test and evidence-row ownership fix/test were copied. Their workflows and historical PASS evidence were not transferred. PR212 UI changes were not modified here.

## Validation

Final affected regression: **77 passed, 0 failed, 0 skipped**, including 18 new cases. Raw output: `final.log`; machine-readable cases: `final.xml`; exact commands, environments and exit codes: `COMMANDS.json`. The first eight new cases failed on the original behavior (`red.*`); another eight capture cases failed before the capture guard (`capture-red.*`). Intermediate passing runs are retained but are not added to the final unique-test count. Changed source files compile and `git diff --check` passes.

The fleet race tests inject a durable SQL transition while retaining a stale ORM instance. This reproduces the stale-state failure in SQLite; it is **not** a PostgreSQL competing-session acceptance test. SQLite's existing `BEGIN IMMEDIATE` serialized tests would otherwise hide that window. No provider credentials or real funds were used.

## Remaining work

- C04 rental recovery still needs fail-closed UNKNOWN evidence validation and a current-episode confirmation contract; the default-to-CONFIRMED path was identified but is outside this settlement repair.
- C05 still needs the exact integrated candidate run under real PostgreSQL READ COMMITTED contention.
- Real rental/fleet acceptance, physical three-end UI, hosted CI and independent C14/C13 review remain open. Local PASS does not mean product completion or release approval.
- The earlier PR217 upload rejection remains unresolved. This worker did not retry it or use another channel.

`RESULT.json` binds every changed file's SHA256 and lists explicit next tasks. Final integration must bind and validate its own application tree; the worker's local baseline contains a runtime media database which the parent has separately removed in the integration workspace.
