# C1 real task contract (V1) — 2026-10-02

Status: **Draft / not deployed.** Source: `control-plane/runtime-host-channel-v1/`.
Test: `control-plane/runtime-host-channel-v1/test_c1_real_task_contract.py` (37 cases, offline).

This document covers one change: `AI_WORK_V1` used to be a *fixed smoke* whose payload,
prompt and accepted output were all literals. A second task class, `AI_TASK_V1`, now
carries **one real task** end to end. The smoke is untouched.

---

## 1. The two task classes

| | SMOKE | REAL |
|---|---|---|
| kind | `AI_WORK_V1` | **`AI_TASK_V1`** |
| payload | the fixed `SMOKE_PAYLOAD` literal | a validated real-task payload |
| prompt | the fixed `PROMPT` literal | **derived** from the payload |
| accepted output | must equal `GO_C1_REAL_AI_WORKER_V1_OK` | **any non-empty answer** |
| identity | unchanged, byte for byte | derived from the payload |
| dispatch wire inputs | identity triple | identity triple **+ task_kind + task_payload** |

The two classes cannot collide: their bindings have **different key sets**, so no real
payload can derive a smoke execution identity (or the reverse). That is what stops a
smoke result and a real result from being interchangeable.

**The smoke's identity is pinned.** `rt_fed1d462624d44d39e8ab9561ad429f7` attempt 1 — the
paid smoke of 2026-10-02 — still derives `execution_request_id = 6e5208ddc76d73ddb4728fade382056891ce93941f5c299abe36871609760a75`.
Verified against the pre-change module for 12 task/attempt pairs: identical. If it ever
moved, an already-answered execution would look like new work and a second paid model call
would become possible.

---

## 2. Canonical cell identity

The deployed kernel's responsibility set is `C_IDS = tuple(f"C{i}" for i in range(1, 15))`
(`/opt/go/c1-c14-runtime/runtime.py:20`), so `owner_c` is `C1`…`C14`. The Owner writes
`C01`, which the kernel rejects outright (`ValueError: unknown responsibility domain`).

There is exactly **one** canonical internal spelling — the kernel's — and exactly one place
the external spelling is folded onto it:

```python
canonical_cell_id("C1")  == "C1"
canonical_cell_id("C01") == "C1"      # the boundary
canonical_cell_id("C14") == "C14"
```

It is idempotent, so re-normalising cannot produce a second key, and `assert_canonical_cell_id()`
refuses a non-canonical value used *inside* the system. Unknown domains (`C0`, `C010`, `C15`,
`X1`) are refused rather than coerced.

---

## 3. Real-task payload: what belongs in it

Composed by `build_task_payload(...)`; validated by `validate_task_payload(...)`.

| role | fields | why |
|---|---|---|
| **binding input** | `schema_version`, `cell_id`, `external_task_id` | participate in `execution_request_id`; `external_task_id` is the caller's stable task key and the base of the idempotency key |
| **execution input** | `objective`, `scope` | the only fields the derived prompt is built from |
| **trace only** | `source_anchor`, `issue_number` | recorded in the binding for auditability, **never** placed in the prompt |
| **refused** | `candidate_sha`, `artifact_id`, `pr_number`, `c14_verdict`, `c13_verdict`, `run_id`, `github_run_id`, `execution_request_id`, `output`, `output_sha256`, `result`, `accepted`, `status` | produced *after* the execution, or by the Runtime itself; accepting them at enqueue time would let a caller assert a result before one exists |

A payload whose `cell_id` is not C1 is refused: this contract belongs to C1.

---

## 4. Prompt derivation

`prompt_for_task(kind, payload)` is a **pure function**: same payload → same bytes, so
`prompt_sha256` is a meaningful commitment inside the binding. For a real task only
`objective` and `scope` reach the prompt, wrapped in a header naming the cell and the
external task id, and stating that the model has no authority to change money, state,
deployment, release or configuration.

`task_binding` carries `payload` **and** `payload_sha256`, so two different payloads
necessarily produce two different `execution_request_id`s. The GitHub side re-derives the
identity from the payload it received and refuses a mismatch
(`EXECUTION_REQUEST_ID_DOES_NOT_MATCH_RUNTIME_FACTS`), which is what makes a substituted
payload detectable rather than merely unlikely.

---

## 5. Result contract

The result document shape is **unchanged** (same `RESULT_FIELDS`, same hash, same
`authorizes_any_action: false`). Only the acceptance rule depends on the task class, via
`validate_result(..., task_kind=...)`:

* `AI_WORK_V1` — output must be the fixed smoke literal (unchanged);
* `AI_TASK_V1` — output must be non-empty; a response id is required.

What ties a result to its task is the **identity triple**, not the text. There is no
business-quality score here, by design. A result is refused when it belongs to another
runtime task, another attempt, or another execution identity, and every malformed shape is
refused with a stable reason code.

---

## 6. Where the resume leg gets its identity

`Runtime.claim()` hands out `QUEUED` tasks only, and the kernel exposes no way to read a
task back. So the resume leg cannot re-derive a real task's identity from
`(runtime_task_id, attempt)`.

The outbox therefore **stores the dispatch request** when the identity is first registered
(`c1_dispatch.request_json`, added by `_migrate()`), and `resume()` reads it back. A row
written before this change has no stored request; the smoke fallback then reproduces
exactly the identity such a row was created from — which is why the live host's existing
rows keep their meaning. A stored request that contradicts the one being presented is
refused (`STORED_REQUEST_DOES_NOT_MATCH`).

Consequence: `register`, `drive_once`, `pull_result`, `artifact_name`, `complete_after_pull`
and `loop_state` all accept an optional `request`; **omitting it reproduces the previous
behaviour exactly**, which is what keeps every pre-existing caller and test valid.

---

## 7. Idempotency

No new de-duplication system. `real_idempotency_key(cell_id, external_task_id)` is derived,
not chosen, and is passed to the Runtime's own `enqueue(idempotency_key=...)`, whose
mechanism (UNIQUE column + "return the existing task_id") already provides exactly-once
task creation. On top of that the outbox still enforces `dispatches_sent <= 1` per
execution identity, so a repeated `register()` cannot become a second POST.

---

## 8. What this change deliberately does not do

* no GitHub ingress, no issue watcher, no producer of `AI_TASK_V1` tasks (none exists yet:
  the only `enqueue` caller still hardcodes `RUNTIME_PROBE`);
* no change to the Runtime kernel, to rt01, or to any deployed file;
* no C02–C14 behaviour — the payload must be `cell_id == C1`;
* no new provider, endpoint, model surface or credential path; the model stays a repo-side
  value and the key stays a repository secret;
* no provider/model/endpoint/ref/repo on the wire — still not dispatch inputs.

## 9. Unchanged-by-construction behaviours (regression-pinned)

* the probe path: the worker's kind set is `("AI_WORK_V1", "AI_TASK_V1")` and the loop's
  `_not_our_task()` gate still runs **before** `outbox.register()`, so a refused task never
  reaches the outbox and never gains an identity;
* resume never dispatches twice — dispatch once, restart, resume, still one dispatch;
* the smoke end-to-end, identity and acceptance rule.
