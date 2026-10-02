# GO Runtime Host — C01 GitHub Issue Ingress V1 (candidate, shadow by default)

Date: 2026-10-02
Base: `main` at `e952f4ee468e2a00598db8eb6c76e648ddee9822`
Code: `control-plane/runtime-host-channel-v1/c1_issue_ingress.py`
Tests: `control-plane/runtime-host-channel-v1/test_c1_issue_ingress.py`
Fixture: `control-plane/runtime-host-channel-v1/issue_fixtures/real_c01_issues.json`

## What this closes

The C1 real-task path is already proven end to end (issue #321, then #322): a task
can be enqueued, claimed, dispatched to GitHub Actions, answered by the model, pulled
back and completed, with exactly one paid dispatch. What has been missing is the leg
before it:

```
Owner phone ChatGPT -> ChatGPT Codex Connector -> C01 issue
   -> [ THIS MODULE ] -> Runtime.enqueue(owner_c="C1", kind="AI_TASK_V1", ...)
   -> Persistent C1 worker
```

This candidate adds only that leg. It does not touch the Owner's entry point, and it
adds nothing after the enqueue: result write-back, issue comments, PR creation,
candidate generation, C14 and C13 are later stages and are not in this file.

## Disabled by default, and structurally so

`C01_RUNTIME_INGRESS_ENABLED` is the switch. Only the exact value `true`
(case-insensitive, surrounding whitespace ignored) enables it; unset, empty, `1`,
`yes`, `on` and any typo leave it disabled. The disabled state is the one that cannot
spend money, so it is the default and the failure direction is closed.

The safety property is a shape, not a discipline:

* `plan_ingress()` parses, validates and computes the Runtime call, and takes **no**
  Runtime parameter at all - so nothing can reach `enqueue` through it in any
  configuration. A test asserts that with `inspect.signature`.
* `ingest()` is the only path to `enqueue`, and it refuses with
  `RUNTIME_REQUIRED_WHEN_INGRESS_ENABLED` if it is enabled without a Runtime, so
  "enabled but nothing to enqueue into" is a loud error rather than a silent no-op.
* The CLI has no flag that can enable or enqueue: `--plan <issues.json> <number>`
  reads an issue, prints the exact task it *would* create, and stops. The enable
  switch is environment-side only.

While disabled the module still reads, parses and reports. That is what makes the
shadow round possible before any cutover decision.

## The parser is minimal and refuses rather than guesses

Input is one issue object as the issues API returns it. Fields come from exactly two
places, both deterministic:

| Field | Source |
|---|---|
| `issue_number` | the issue's own number |
| `cell_id` | segment 1 of the title, e.g. `C01`, folded through `canonical_cell_id()` to `C1` |
| `external_task_id` | segment 2 of the title, e.g. `V70-R3-C01-01` |
| `scope` | segment 3 of the title, e.g. `mixed hotel funds read-only diagnosis` |
| `objective` | the paragraph introduced by `Task:` or `Successor task:` |
| `source_anchor` | the single 40-hex commit on a `Canonical source:` / `Canonical lineage:` / `CANONICAL_BASE:` / `SOURCE_ANCHOR:` / `base=` line |

Refusals, all with a stable reason code: the object is not an issue
(`ISSUE_IS_A_PULL_REQUEST`), it is not open (`ISSUE_NOT_OPEN`), the title is not the
expected three segments (`ISSUE_TITLE_NOT_THREE_SEGMENTS`), the cell or task id is
missing or malformed (`ISSUE_TITLE_CELL_NOT_FOUND`, `ISSUE_TITLE_TASK_ID_NOT_FOUND`),
the task id does not name the same cell (`ISSUE_TITLE_TASK_ID_CELL_MISMATCH`), the
cell is not C01 (`INGRESS_ISSUE_IS_NOT_C01`), the objective paragraph is absent or
empty (`INGRESS_OBJECTIVE_NOT_FOUND`, `INGRESS_OBJECTIVE_EMPTY`), the anchor is absent
or ambiguous (`INGRESS_SOURCE_ANCHOR_NOT_FOUND`, `INGRESS_SOURCE_ANCHOR_AMBIGUOUS`),
or the body repeats the title's cell/task id differently
(`INGRESS_CELL_TITLE_BODY_MISMATCH`, `INGRESS_TASK_ID_TITLE_BODY_MISMATCH`).

No task id, objective or anchor is ever inferred from prose. A 64-hex digest does not
count as a 40-hex anchor.

### Compatibility requirement this puts on the Owner's connector

Both `Canonical source:` (issue #79) and `Canonical lineage:` (issue #116) are already
accepted, so the connector's current output works. Two things are worth stating
plainly:

* issue #170's body carries its commit only as a *predecessor candidate* in prose
  (`Predecessor fixed candidate: ...`), with no anchor line. Read as a task's own
  source that would be inference, so such an issue is **refused** today. If the
  connector produces that shape again, adding one `Canonical source:` line makes it
  ingestible.
* only **open** issues are ingested. A closed C01 issue is already superseded by the
  next one in the same slot, which is exactly what the Owner's history shows
  (#116 closed 2026-09-17T00:56:42Z, #170 created 2026-09-17T00:58:26Z).

The parser reads the title and body only, never comments. That is deliberate: the
same C01 issue slot carries successor rounds in its comments
(`V70-R3-C01-01` -> `V70-R4-C01-01` on #79), and a task id that rolls forward inside a
comment is not a stable identity for de-duplication. A successor round should arrive
as its own issue.

## Payload and idempotency reuse the merged contract

The payload is built and validated by the interfaces that already exist in
`c1_execution_contract` - `build_task_payload()` and `validate_task_payload()` - and
the Runtime key comes from `real_idempotency_key()`:

```
payload          = build_task_payload(cell_id="C01", external_task_id=..., objective=...,
                                      scope=..., source_anchor=..., issue_number=...)
idempotency_key  = real_idempotency_key(payload["cell_id"], payload["external_task_id"])
                   # -> "c1-ai-task-v1:C1:V70-R3-C01-01"
max_attempts     = 1
```

So there is no second task schema, no second de-duplication store, and the key is
derived rather than composed. `cell_id` is folded once, at this boundary, and travels
canonical from there.

`max_attempts` is 1 on purpose: a second attempt of the same execution is a second
paid model call, and who may authorise that is a later, explicit decision.

One honest limit: the kernel exposes no way to read a task back by idempotency key, so
this module does not pre-check for an existing task. Uniqueness rests entirely on the
derived key plus the Runtime's `idempotency_key UNIQUE` constraint. That is also why
the key must never become caller-chosen.

## Boundaries held by this round

* never calls the old C01 session executors, their runner or any old C01 workflow;
  their identities are `codex-real-executor:/root/depth_c01_c02`,
  `codex-work:/root/work_c01_c02` and the `.github/workflows/c01-*` /
  `v70-r3-ai-cell-pipeline.yml` pipelines. Their absence from the module text and its
  imports is asserted by the test suite rather than left to review.
* imports nothing from the repository except `c1_execution_contract` - asserted by
  parsing the module with `ast` and comparing the import set.
* touches no other file: no change to the C1 backend, the worker, the outbox, the
  result pull, the loop, the Runtime kernel, or any workflow.
* no live enable, no enqueue, no systemd change, no model call, no GitHub issue write.
  Tests use a fake Runtime over a temporary sqlite database.

## Offline evidence

* 25 new cases, covering the acceptance set: real #79 fixture, duplicate scans,
  malformed inputs, non-C01 inputs, the disabled default, enabled-offline enqueue, and
  the structural bounds above.
* channel suite: **275 tests OK (skipped=3)**, up from 250; per-file `def test` counts
  are unchanged for every pre-existing file, so no assertion was weakened.
* the fixture is the real captured issue text, and the three body SHA256s are pinned
  in the test, so an edited fixture cannot pass as real input.
* `--plan` on the real #79 fixture prints
  `payload_sha256 = 89bbfc3324a57f9505a82ea2d5b00ce047a86d83de2a084468f57209244291f5`,
  10 consecutive scans collapse to the single key
  `c1-ai-task-v1:C1:V70-R3-C01-01`, and issue #116 is refused with `ISSUE_NOT_OPEN`.

## What the next round would do

1. install the ingress on the Runtime host with the switch **off** (shadow);
2. let it read the Owner's next real C01 issue and print the Runtime task it would
   create, without enqueuing;
3. compare that against what the owner intended;
4. only then does the Owner decide the actual cutover - which also needs an answer to
   the question this candidate does not answer: what stops the Owner's ChatGPT session
   from executing the same issue itself.
