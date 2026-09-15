# Round 2 development dispatch validator

Change class: `TEST_ONLY` (development dispatch acceptance tooling), plus
`DOCUMENTATION`. This program has no network calls and never reads or writes
the Hong Kong Agent, control-plane ledger, signing path, database or runtime.
Its fixed source **lineage anchor** is main
`fef9c748adb77d37ba5d4dc4fa4662eb668303a1`. Candidate file digests and executed
commands are separately recorded in the C12 evidence directory.

Run from the repository root:

```sh
python ci/round2/test_validate_ledger.py -v
python ci/round2/validate_ledger.py path/to/ledger.json --evidence-root . --report path/to/new-report.json --reconcile-out path/to/new-reconciled-ledger.json
```

`example-ledger.json` is a **synthetic schema example**, not an actual dispatch
record or proof that any worker started. In that example C07 is IDLE with an
executable task, so the observed gate is SCHEDULER_FAIL. Reconciliation creates
a local ASSIGNED followup and preserves the original task and event history.
All output files must be new paths; the source ledger is never overwritten.

Exit codes: `0` is ledger `PASS_SCOPED`; `1` is an observed SCHEDULER_FAIL or
validation HOLD; `2` is a read/parse/output failure. Successful reconciliation
does **not** erase the original SCHEDULER_FAIL or turn that run's exit code into
success. The report separately carries `reconciled_gate`. Rerun validation on
the new ledger to check the resulting assignments.

## Input contract

- Top level: `schema_version: 1`, `source_anchor`, concrete `round_id`, exactly
  one cell each C01–C14 in `cells`, and append-preserved `events: []`.
- Cell: `cell_id`, `task`, boolean `executable_gap`, explicit `next_task`
  (template or null), and `blocked_reason` whenever BLOCKED. Optional
  `domain_completion` is carried unchanged and **never inferred or accepted
  as domain completion evidence by this validator**.
- Task: concrete `id`, `description`, `scope`, `test_plan`, `status`,
  `completion: {percent, definition}`, `evidence: []`,
  `execution_evidence_refs: []`, and `gates`.
- Task status is ASSIGNED, RUNNING, BLOCKED, IDLE, or DONE_SCOPED (DONE-SCOPED
  and DONE are accepted aliases with the same strict scoped completion gate).
- Evidence entry: repository-relative `path`, lowercase SHA256 `sha256`,
  `source_anchor` and current `task_id`. Referenced bytes must actually exist
  within `--evidence-root` and match their hash and task/anchor binding.
- RUNNING requires nonempty `execution_evidence_refs` referencing verified
  evidence entries. A real agent dispatch record plus its current run output
  can be cited. The validator checks the records' bytes and bindings; the
  reviewer must verify their actual execution meaning and freshness.
- Gates have keys `tests`, `evidence`, `c14`, `c13`. Each is an object with
  `status` (HOLD, FAIL, PASS or PASS_SCOPED) and `evidence_refs: []`. PASS requires
  nonempty verified references and `completed_at` with a timezone. C14 and C13
  PASS also require distinct `reviewer` identities. Gate predecessors must
  already pass, with nondecreasing timestamps in tests→Evidence→C14→C13 order.
  This validates a review record; it does not authenticate a signature.
- Scoped 100% requires DONE_SCOPED, verified Evidence and all four passing
  gates. A completed scoped task does not imply its domain is 100% complete.
- Next task template: `id`, `description`, `scope`, `completion_definition`,
  `test_plan`. A completed task's followup must have a new ID. Passed work is
  preserved in `task_history` rather than reassigned under its completed ID.

## Reconciliation behavior

Any IDLE, DONE_SCOPED or BLOCKED task with `executable_gap: true` triggers
SCHEDULER_FAIL and appears in `reassign_cells`. A concrete next task is needed
for completed/blocked work. IDLE may resume its existing unfinished task.
An external blocker is not a reason to leave an executable local alternative
unassigned. Invalid records remain HOLD and are not patched with invented work.

Reconciliation writes a new ledger with the old task in `task_history`, a new
task in ASSIGNED with 0% and HOLD gates, an appended `followups` record and
SCHEDULER_FAIL/LOCAL_TASK_ASSIGNED events. Assignment records explicitly use
`transport: LOCAL_DEVELOPMENT_RECORD`, `acknowledged_at: null`,
`started_at: null`. No server submission or worker ACK is claimed. Refeeding
the reconciled ledger produces no duplicate followups while it remains
ASSIGNED. Existing completed evidence and events are preserved unchanged.

The result is a scoped scheduling-record gate, not the product's C14 gate,
C13 independent acceptance, release readiness, domain completeness, a remote
liveness check or deployment authorization. Actual review/acceptance records
must still be supplied by their respective reviewers.
