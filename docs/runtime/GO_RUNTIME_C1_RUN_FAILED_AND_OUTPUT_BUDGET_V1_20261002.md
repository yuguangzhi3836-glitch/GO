# GO Runtime Host — C1 failed-run settlement and real-task output budget

Date: 2026-10-02

Base: `main` at `fd7b472cd37af757a63bc287e6bd6f17e102bb73` (the merge of PR #321). This
document records the two defects found while running the first live `AI_TASK_V1` task on
`go-runtime-test-01`, what changed, and what the change does and does not prove.

Nothing here is deployed. No live Runtime or Host, no credential, no systemd unit, no
GitHub Secret and no C02–C14 was touched.

## D1 — a failed run held the worker forever

`c1_result_pull.pull_result` reports `RUN_DID_NOT_SUCCEED` whenever the GitHub run finished
with a conclusion other than `success`; no artifact from such a run can be trusted. The
loop's `_drive` treated that as "not finished yet" and fell through to `_pending`, which
renews the lease and returns. Every tick therefore renewed, `unfinished()` stayed non-empty,
and `c1_worker.tick` never reached its claim phase again — the worker was stuck permanently,
for any task, however many attempts that task had left. Nothing else could break the loop,
because the renewal itself kept succeeding.

That is exactly what happened in the live run of 2026-10-02: the identity sat in the outbox
until it was settled by hand.

### What changed

A terminal outbox state `RUN_FAILED`, and an entry point `c1_result_pull.fail_after_pull`
that does two things **in this order**:

1. the Runtime is told the execution failed — `complete(..., success=False, error=...)`,
   which is the kernel's own way to record a failed execution. This is what stops the task
   from being requeued as a new attempt;
2. the outbox identity is settled as `RUN_FAILED`, so it leaves `unfinished()` and the
   worker can claim again.

The order is not cosmetic. Settling locally first would leave a window in which a crash
leaves a live Runtime task that `recover_stale()` would requeue — and a requeued task is
handed out as the **next attempt**, a new execution identity, which nothing would stop from
dispatching a second paid model call. If the Runtime refuses the completion (its lease
already expired, say), the identity is settled anyway, because the run really did fail, and
the returned `runtime_told` records that the Runtime was not told.

`RUN_FAILED` is deliberately distinct from `ABANDONED`. ABANDONED means "the Runtime refused
this identity"; RUN_FAILED means "the execution ran and failed". Both are terminal, neither
is a route back to a POST, and neither stores a result — so a later attempt can never adopt
a failure as if it were an answer.

The dispatch leg gained the mirror of the existing "adopt, never pay twice" guard: before
dispatching a newly claimed attempt, the loop asks whether this Runtime task already has a
run settled as failed. If it does, the new identity is settled the same way instead of being
dispatched. Without that, the requeue-and-retry path above would pay for the task a second
time.

### Proven offline

- a failed run is reported to the Runtime, the task becomes `FAILED`, the identity becomes
  `RUN_FAILED`, `unfinished()` is empty and the next worker tick **claims**;
- every route back to a POST is closed: `next_action`, `record_dispatch_sent`, `drive_once`,
  `pull_result` and `resume` all stop at the settled state;
- a refused Runtime completion still settles the identity, and reports `runtime_told=false`;
- a requeued task (attempt 2, after attempt 1 failed with an expired lease) is settled
  **without a dispatch** — `dispatch_calls` stays 1;
- a completed execution can never be rewritten as failed;
- the fixed smoke settles a failed run identically.

## D2 — the real task inherited the smoke's output budget

`c1_ai_execution_backend.MAX_OUTPUT_TOKENS` was 32 for everything. The smoke expects a fixed
ten-token literal, so 32 was enough for it and for nothing else: a real task asks an open
question, and the model spends tokens on its reasoning before it answers.

### What changed

The budget is now a property of the task class:

| task class | budget | who may change it |
|---|---|---|
| `AI_WORK_V1` (smoke) | `SMOKE_MAX_OUTPUT_TOKENS = 32`, unchanged | nobody — it belongs to the smoke contract |
| `AI_TASK_V1` (real) | `REAL_TASK_MAX_OUTPUT_TOKENS = 1024` | a bounded runner-side override |

`--max-output-tokens` is that override, and it is honoured **only** for a real task; the
smoke's budget cannot be moved from outside. The budget is resolved on every path, including
the offline stub, so a bad value fails the run instead of being ignored until a live call.
The workflow passes it from `env.C1_AI_MAX_OUTPUT_TOKENS` — repository-side configuration,
exactly like `C1_AI_MODEL`, and under the same guard as `task_kind`, so the smoke never
receives the argument at all.

The budget is **not** part of the execution identity: `max_output_tokens` appears nowhere in
the dispatch request or in its binding. If it did, re-running an already-answered task with a
different budget would look like new work and pay a second time.

### Proven offline

- the smoke's budget is still 32, and a runner override cannot move it;
- a real task's budget is 1024, and a bounded override is honoured;
- an out-of-range override is refused (`MAX_OUTPUT_TOKENS_OUT_OF_RANGE`), also end to end
  through the CLI;
- the budget reaches the model request body, and the smoke's body is unchanged;
- the smoke's sealed result is **byte-identical** with and without the flag;
- the workflow declares the budget, and passes it only behind the `task_kind` guard.

## Not proven here

- **No live E2E was re-run.** Whether the live failure was `MODEL_RESPONSE_NOT_COMPLETED`
  (the structural hypothesis: a 32-token budget) remains a hypothesis, not an observation —
  the job log is still not readable by any credential we hold.
- `recover_stale()` belongs to the kernel, not to this channel. What is proven is that this
  side stops creating the situation it recovers from.
- The window in which the Runtime cannot be told at all (lease already expired, task already
  requeued) is covered for **this channel's own outbox** by the failed-attempt guard. It is
  not a claim that the Runtime can never hand that task out again.
- The D2 override is a workflow `env` value, so it is repo-controlled configuration rather
  than a dispatch input — but it is also not covered by the dispatch identity, which is
  deliberate and asserted.
