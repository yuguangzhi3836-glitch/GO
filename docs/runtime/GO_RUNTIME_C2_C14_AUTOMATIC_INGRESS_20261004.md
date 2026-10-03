# C2–C14 automatic task ingress and result return

Owner request: 2026-10-04; parent task #382. Source base:
`ca1e5f8eeae397e96e6c97972b76c291960c60b3`.

## Status and scope

Implemented and offline-tested; **not installed, not live accepted**.
No Runtime host is connected to this session. No model calls, main-branch writes,
runtime mutation or deployment occurred during the offline verification.

This change extends the existing C1 channel, without creating another queue or
another provider. C2–C14 can consume structured task issues, claim only their own
AI_TASK_V1 work, dispatch through the existing workflow, resume after restart, and
complete/fail in the original responsibility domain. Each cell gets its own durable
outbox so a stalled C2 does not block C3. Existing C1 services, idempotency keys,
prompt bytes, smoke identity and artifact naming remain compatible.

**This backend returns advisory model text.** It cannot read the source anchor as a
repository checkout, edit code, run product tests or create a PR. Source/issue fields
remain trace-only. Supply the actual bounded facts in the Task/Scope text. An
AI_TASK_V1 SUCCEEDED means result transport succeeded, not PRODUCT_DONE, independent
C13/C14 PASS, or release authority. The existing formal review workflows remain
the source of formal review evidence. A source-aware coding executor is a distinct
remaining capability; merely broadening the ingress cannot supply it.

## Task input and routing

Use the **existing task issue contract**, for example:

    C02 · V70-R4-C02-01 · bounded supplied-facts self-check

    Task: Review the following supplied facts and return missing evidence ...

    source_anchor: <actual 40-character source commit>

Each cell instance only reads its own titles and an operator-configured author
allowlist. Missing/ambiguous source, invalid task identity, closed issues, PRs and
unsupported cells are refused. C1 retains its existing consumer; the new entrypoint
rejects C1 explicitly. C2–C14 never claim C1 smoke or Runtime probe tasks.

**#351–#364 are reserved containers; their comments are not queue items.** #382 and
the prior dispatch comments therefore do not become executable work automatically.
After live acceptance, publish correctly shaped task issues and link them back to
their cell container. Do not create duplicate copies of an active legacy task.
Reuse of a task ID is for unchanged retries only; revised scope needs a new ID.

New cell consumers poll every 180 seconds; workers tick every 30 seconds with a
180-second lease, to avoid multiplying the C1 five-second cadence by thirteen.
At most 1,000 open issues are scanned per poll, with all eligible tasks inside the
window considered (not only the same newest ten). A full window reports
PARTIAL_LISTING_LIMIT, not full coverage. Author filtering does not override GitHub
repository write permissions, review requirements or execution authority.

## Installation and activation (execution handoff, not a claim of completion)

Use the Runtime host's existing authorized installation channel. Forge's
FORGE_DEPLOY business-image action is **not** an installer for these services.
This user request authorizes progressing the team entry; the missing item is a
reachable authorized execution channel, not another request for business approval.

1. Record installed kernel, worker and consumer identities and current active work.
   Drain/pause the C1 services before replacing their shared modules. Confirm no
   legacy consumer owns the same C2–C14 task. Keep prior source/configuration for
   rollback; never delete the queue, outboxes or Evidence to obtain a clean test.
2. Install the reviewed `c1_*.py` shared modules and new `cell_*.py` files together
   in `/opt/go/runtime-host-c1-worker/`. Do not add files to the Management Agent's
   hashed bundle. Keep the existing installed Runtime kernel and database.
3. Install the two template units from `systemd/`; create root-managed cell config
   files `/etc/go-runtime-cells/C2.env` … `/etc/go-runtime-cells/C14.env`. Example:

       CELL_TASK_AUTHORS=yuguangzhi3836-glitch
       C02_RUNTIME_INGRESS_ENABLED=false

   Use C03…C09/C10…C14 switches for the other cells. Author identities must be those
   actually authorized to publish tasks. Reuse the existing GitHub credential path;
   do not copy model credentials onto the Runtime host.
4. Read back installed bytes against the reviewed commit. The repository's shared
   backend at its configured `main` must contain the same contract **before** new
   cells dispatch; do not point a worker at a candidate branch to bypass this.
5. Run both entrypoints `--cell C2 --check`, then consumer `--once` with its switch
   false; repeat C3…C14. Confirm no Runtime task created. C1 old smoke identity is
   pinned by regression and must remain unchanged on the installed bytes.
6. For each cell, set its ingress switch true, then start its own consumer/worker
   instances (e.g. `go-runtime-host-cell-issue-consumer@C2.service` and
   `go-runtime-host-cell-worker@C2.service`). Each worker uses
   `/var/lib/go-runtime-cells/c2/outbox.db` (etc.), owned by go-runtime, mode 0700
   directories. The new templates do not enable themselves.
7. Publish one bounded acceptance issue per cell. Read back issue → queue ID →
   claim/attempt/lease owner → workflow run → artifact → Runtime completion.
   Restart a worker after dispatch and prove one dispatch with a returned result.
   Run C1 regression and confirm a stalled cell does not block another cell.
8. Record whether the repo-side `C1_AI_LIVE_ENABLED` switch was on. Stub output is
   offline transport evidence only. For live acceptance require a real model
   response, inspect its content and retain its bound result without credentials.

Rollback: stop new consumers first; settle in-flight work before stopping workers.
Restore matching reviewed worker/backend bytes together. Preserve all queue/outbox
state. Do not roll a C1-only backend underneath outstanding C2–C14 requests.

## Acceptance evidence

Local command:

    python -m unittest discover -s control-plane/runtime-host-channel-v1 -p 'test_*.py'

317 tests passed. The new integration suite exercises all 13 cells using the real
ingress, SQLite dispatch outbox, backend stub subprocess and result puller. Runtime
fencing and GitHub transport are doubles, explicitly not the live installed kernel.
It checks idempotent enqueue, correct owner on success and failure, restart without
redispatch, cross-owner refusal, probe/smoke isolation, disabled/unauthorized ingress,
and separate outbox/enable-switch configuration. Original C1 regressions pass; one
obsolete C2-rejection test now checks unknown C15, with cross-cell ownership refusal
covered at the worker boundary.

Required live receipt per cell: cell, source/installed identity, issue, runtime task,
worker, attempt, start time, workflow run, output identity, completion state,
real/stub mode and outstanding blocker. Until these exist: ASSIGNED_NO_ACK or
BLOCKED_EXECUTION_CHANNEL, never all-team RUNNING.
