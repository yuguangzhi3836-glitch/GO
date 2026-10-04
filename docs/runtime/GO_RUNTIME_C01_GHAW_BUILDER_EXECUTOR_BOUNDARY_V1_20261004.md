# GO Runtime C01 — gh-aw Builder executor boundary (U3 + U10)

> Status: **candidate (Draft PR)**. Date: 2026-10-04. Base: `main` @
> `ca1e5f8eeae397e96e6c97972b76c291960c60b3`.
>
> This document records **two decisions** and the code that carries them. It is not
> Evidence, not Authority, and not a current-state pointer. It grants no execution right
> and describes nothing that has been deployed.

## 1. Scope

Round 4 of the Persistent Runtime work proved, end to end, that the Runtime can lose its
process and still recover the same execution exactly once. That proof used **one**
executor and **one** outbox, which is why two questions had one obvious answer then and
no defined answer the moment a second executor exists:

* **U3** — what is the formal relationship between an executor and an outbox?
* **U10** — what does `Runtime.claim()` formally mean?

This round answers exactly those two, in code and in tests. It does **not** register a
gh-aw workflow, does not dispatch anything, and does not start the 14-Cell migration.

## 2. U3 — one kind, one executor; one executor, one outbox

### 2.1 A kind IS the routing

`Runtime.claim(kinds=...)` filters the queue by task kind. That makes a kind not a label
but the routing decision itself: whichever executor asks for a kind is the executor that
gets those tasks. Two executors claiming one kind is therefore not a shared duty — it is a
race whose loser is whichever executor was restarted last, and the loss is a task executed
(or not executed) by the wrong side, potentially paying twice.

So the channel now has three task classes and two executors, with **disjoint** kind sets:

| task class | kind | payload | executor | component |
|---|---|---|---|---|
| SMOKE | `AI_WORK_V1` | fixed literal | Responses-API executor | `c1_worker.py` |
| REAL | `AI_TASK_V1` | validated real-task payload | Responses-API executor | `c1_worker.py` |
| REAL | `GHAW_BUILDER_V1` | the same validated real-task payload | gh-aw Builder executor | `c1_ghaw_builder_worker.py` |

`GHAW_BUILDER_V1` is new. It carries the same payload shape as `AI_TASK_V1` — a task's
objective and scope do not change because a different executor runs it — but it is a
different *execution*: a gh-aw workflow that runs its own agent, not a single OpenAI
Responses call. That difference is inside the binding, in `provider`
(`GITHUB_AGENTIC_WORKFLOWS` vs `OPENAI_RESPONSES_API`), so the two real classes can never
derive the same `execution_request_id` for the same Runtime task and attempt.

The C01 issue ingress now produces `GHAW_BUILDER_V1`. A C01 issue is a work order for the
Builder, and routing it to the Responses executor instead would be a silent, permanent
misdelivery rather than a fallback.

### 2.2 The ownership boundary is four values, and they are stated once per executor

One executor / one execution loop owns **one durable outbox, one worker identity and one
kind set**:

| | Responses-API executor | gh-aw Builder executor |
|---|---|---|
| kinds | `AI_WORK_V1`, `AI_TASK_V1` | `GHAW_BUILDER_V1` |
| outbox | `/var/lib/go-runtime-c1/outbox.db` | `/var/lib/go-runtime-c1/outbox-ghaw-builder.db` |
| worker id | `go-runtime-host-c1-worker` | `go-runtime-host-ghaw-builder-worker` |
| executes | one OpenAI Responses call | a gh-aw Builder run (**U1**) |

Both point at the **same** Runtime database: they are two workers of one Runtime, not two
Runtimes. What is separate is the dispatch outbox, because the outbox is what remembers
work in progress.

The loop itself is **shared, not copied**. `c1_ghaw_builder_worker.py` imports `tick`,
`main`, the credential gate and the status vocabulary from `c1_worker`; it supplies only
its three constants. A second implementation of the exactly-once model is how the
exactly-once model forks, and the outbox, the dispatch counter and the result seal must
exist once and only once.

### 2.3 Isolation is a contract, not a convention about paths

Distinct outbox paths alone are a convention: nothing stops a future change from pointing
one executor at the other's file. `c1_execution_loop.resume()` therefore **re-checks the
kind of the identity it is asked to resume** against the set the caller passes in:

* the row's stored request names kind `K`, and `K` is not owned by this executor →
  `Refused(RESUME_KIND_NOT_OWNED_BY_THIS_EXECUTOR:K)`;
* there is no stored request at all and this executor does not own the smoke kind →
  `Refused(RESUME_IDENTITY_NOT_IN_THIS_OUTBOX)`. The pre-contract smoke fallback
  reproduces a *smoke* identity, so it is only ever correct for the executor that owns
  the smoke kind; for anyone else it would register and dispatch an execution nobody
  asked for.

Neither refusal settles the row: the owning executor's in-flight state is left exactly as
it was.

## 3. U10 — `claim()` is a queue read, and the claim is the only identity

**The Runtime kernel is not changed.** In particular **no `claim(task_id=...)` was added**.
The Runtime is formally a queue/scheduler:

```
enqueue(A)
claim(kinds=..., owner_c=..., worker_id=...)
  -> the oldest QUEUED task matching the filter
  -> NOT necessarily A
```

Consequences, now stated in code rather than in prose:

* an executor must build every execution fact from what `claim()` returned —
  `claimed.task_id`, `claimed.attempts`, `claimed.kind`, `claimed.payload`;
* `claimed_identity()` in `c1_execution_loop` is the **only** place those four are read,
  and it returns them as one unit. That makes the Round-3 defect — `A.task_id` combined
  with `B.attempt` — *unrepresentable* rather than merely forbidden: there is no second
  claim in scope to borrow an attempt from. The function fails closed on a claim missing
  any of the four, or carrying a task id / attempt the contract would refuse;
* `priority` keeps only its queue-scheduling meaning and is never read by the loop or by
  either executor. Correctness does not depend on whether the just-enqueued task is the
  one handed out;
* an `enqueue()` return value is never an identity: it carries no attempt, no kind and no
  payload.

`c1_worker.tick` and `c1_ghaw_builder_worker.tick` both pass their own kind set down to
both the claim leg (`advance`) and the resume leg (`resume`), so neither executor can
reach the other's work at either entry point.

## 4. Files

| file | change |
|---|---|
| `control-plane/runtime-host-channel-v1/c1_execution_contract.py` | `GHAW_BUILDER_KIND`, `PROVIDER_GHAW_BUILDER`, `GHAW_BUILDER_WORKFLOW_FILE`; provider / workflow-file / prompt / spec / result acceptance resolved per task kind; `task_idempotency_key(kind, cell, task)` |
| `control-plane/runtime-host-channel-v1/c1_execution_loop.py` | `claimed_identity()`; `claimable_kinds` parameter on `advance()` and `resume()`; resume-leg kind and ownership checks |
| `control-plane/runtime-host-channel-v1/c1_worker.py` | named as the Responses-API executor; boundary stated as its four constants; `main()` parameterised by worker id / kinds / outbox so a second executor can reuse the loop |
| `control-plane/runtime-host-channel-v1/c1_ghaw_builder_worker.py` | **new** — the gh-aw Builder executor: its kinds, its outbox, its worker id, and nothing else |
| `control-plane/runtime-host-channel-v1/c1_issue_ingress.py` | produces `GHAW_BUILDER_V1`; kind-derived idempotency key |
| `control-plane/runtime-host-channel-v1/c1_issue_consumer.py` | docstring corrected |
| `control-plane/runtime-host-channel-v1/test_c1_executor_boundary.py` | **new** — A: claim-is-a-queue-read; B: kind isolation; C: outbox isolation; D: restart semantics |
| `control-plane/runtime-host-channel-v1/test_c1_issue_ingress.py`, `test_c1_issue_consumer.py` | expectations follow the ingress's new kind |

## 5. What this round deliberately does NOT do

* **No workflow is added or registered.** `GHAW_BUILDER_WORKFLOW_FILE` is *declared* so a
  task's own recorded dispatch target is not a false statement about where it goes; the
  file does not exist on `main` and no dispatch is sent. **Registration is U1.**
* **No installation.** No systemd unit is shipped for the gh-aw executor; a unit belongs
  with the registration it serves.
* **No merge, no deploy, no host mutation.** Nothing was installed, restarted or changed on
  `go-runtime-test-01`, HK-STAGING, the Command Center or Production.
* **No real AI call, no `workflow_dispatch`.** Every test is offline; the gh-aw transport
  in the boundary tests synthesises the result document rather than running an executor.
* U2, U4, U5, U6, U7, U8, U9 are untouched and stay open.

## 6. Verification

Local, WSL `Ubuntu-24.04` as root (the principal the channel's own CI runs the suite as),
on an ext4 extraction of the candidate tree:

```
python -m unittest discover -s control-plane/runtime-host-channel-v1 -p 'test_*.py'
Ran 328 tests   OK
```

308 at the base commit → 328 here; the 20 new cases are `test_c1_executor_boundary`.

**Identity freeze.** Smoke and `AI_TASK_V1` bindings, dispatch requests and idempotency
keys were computed from the candidate and from `origin/main` and compared byte for byte:
identical. The already-proven identities resolve to the same values.

**Mutation check.** Each guard was disabled in turn, and the test that is supposed to
catch it was required to go red. 7 mutations, 7 caught, 0 missed, 0 invalid.

**The first gate left green is not the evidence; the mutation is.** A suite that cannot
fail proves nothing about the guard it is nominally testing.
