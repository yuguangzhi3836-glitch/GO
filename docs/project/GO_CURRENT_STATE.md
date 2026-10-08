> **HISTORY** — 历史 / 取证材料，不是当前操作说明。
> **HISTORY** — historical / audit material, not current operating instructions.
>
> 当前入口：人（中文）[`README.md`](../../README.md) · AI（英文）[`AGENTS.md`](../../AGENTS.md)。
> Current entry points: [`README.md`](../../README.md) (Chinese, humans) and [`AGENTS.md`](../../AGENTS.md) (English, AI).
>
> 本文档不定义正常操作路径，不得作为当前操作依据。This document does not define the normal path; do not use it as current operating guidance.

---

# GO CURRENT STATE

> Purpose (historical): the project-state layer that was current until 2026-10-08.
> Current entry points are the repository root `README.md` (Chinese) and `AGENTS.md` (English);
> this file is retained as HISTORY and must not be used as the startup path.
>
> Refreshed against canonical `main` **bdaba56bbb6b7a5e47b75f1fe74a93ae3f9e45bc** on 2026-10-04 after the first full automatic Builder -> C14 -> C13 live E2E.
> This file is descriptive context, not Execution Authority. Live GitHub / real environment / current Evidence outrank this snapshot.

## 0. Three separate axes

GO currently has three separate axes that must not be inferred from one another:

1. **Repository source** — GitHub `main`.
2. **Business runtime** — what the eight GO business services are actually running on HK-STAGING.
3. **Persistent Runtime / AI execution transport** — rt01, which durably accepts work, dispatches AI execution and adopts results.

`merged != deployed` · `deployed != accepted` · `accepted != authorized` · `Runtime healthy != product correct`

## 1. Repository source truth

| Item | Current value |
| --- | --- |
| Canonical main | `bdaba56bbb6b7a5e47b75f1fe74a93ae3f9e45bc` |
| Main root tree | `be1c40c09c1f81964867c995e92a811d14a73d94` |
| `main:application` tree | `83e73327d5f8f00841a3febdbe2a94e2078dbeae` |
| Repository migration head | `0135_supplier_onboarding` |
| Migration down revision | `0134_flight_status_width` |

The `application` tree did not change in the Runtime auto-review closeout; the changes are Runtime/control-plane/docs.

## 2. HK-STAGING business runtime — separate axis

**The repository publishes no runtime pointer.** `docs/canonical-baseline/CURRENT_HK_RUNTIME.json`
was retired on 2026-10-08: it declared what was running on HK-STAGING, it demonstrably drifted
from the host, and a file inside a repository cannot truthfully answer that question. This
checkpoint therefore records **no** runtime values. To establish the live identity, read the
newest signed VERIFY Evidence for HK-STAGING on the evidence bus
(`chenzhenxi1-sudo/go-control-evidence`) — it names the image, database revision and tree that
were current at the moment it ran, and it is signed.

The last values this section carried (runtime generation `DEPTH48`, image
`go-hk-test-pr:eeafca1b…`, live DB revision `0145_source_latest_index`) were copied from that
retired pointer and are no longer maintained here. They are history, not a current claim.

Current GitHub source and current HK business runtime are **not the same tree**. Do not infer one from the other.

## 3. Persistent Runtime — END-TO-END AUTO PROGRESSION LIVE / PROVEN / DELIVERED

The Runtime Host role remains intentionally narrow:

`queue/state/lease/attempt fencing -> dispatch -> evidence/result adoption -> recovery`

It is not a local 14-model host, not Command Center, not a merge/release authority and not a product-quality judge.

### 3.1 Normal C01-C12 owner path

The normal owner workflow is now:

`Formal C01-C12 Issue -> Runtime -> Generic Builder -> Draft PR -> automatic C14 -> automatic C13 -> sealed round decision -> STOP`

Important:

- The Owner normally creates **one C01-C12 Formal Task Issue only**.
- If the Builder produces exactly one valid Draft PR, the Builder completion hook freezes that candidate and idempotently enqueues `C14_REVIEW_V1` **before** completing the Builder task.
- A sealed admissible C14 then idempotently enqueues `C13_REVIEW_V1` **before** completing C14.
- The Runtime's own deterministic idempotency keys are the transaction coordinator for both crash windows.
- C13/C14 never merge or deploy. Even `PASS_SCOPED + ACCEPT` stops at review completion.
- If a Builder legitimately produces no PR, the Builder may complete with zero review tasks.

### 3.2 Candidate identity after Builder

The Builder's ordinary `c1_result.json` is sealed before gh-aw `safe_outputs` creates the Draft PR, so PR identity is not taken from the model answer or guessed by title/time.

The Runtime reads the same GitHub run's `safe-outputs-items` record, extracts the exact `create_pull_request` result, then read-only verifies:

- exactly one candidate PR;
- `base == main`;
- `draft == true`;
- exact PR head SHA;
- exact candidate `application/` tree;
- changed candidate test inventory, bounded to safe test paths;
- binding to the same Builder Runtime task / attempt / execution / GitHub run;
- `authorizes_any_action == false`.

Missing or ambiguous candidate identity fails closed and creates no review task.

### 3.3 Manual Review Issue is now optional

`C14 · REVIEW · ...` Issue ingress remains supported, but it is **not part of the normal Builder path**.

Use it only to review an independently selected existing PR, historical PR, or other candidate that was not just produced by the Runtime Builder.

An Issue can create C14 only. C13 still exists only because a sealed admissible C14 created it.

### 3.4 Full automatic live E2E

Validation Issue `#403` (`C12 · V72-R1-C12-01 · workbench cell-role table regression`) was created against current main `bdaba56bbb6b7a5e47b75f1fe74a93ae3f9e45bc`.

It proved the complete no-hand-off path:

| Leg | Runtime task | GitHub run | dispatches | Runtime | verdict |
| --- | --- | ---: | ---: | --- | --- |
| Builder C12 | `rt_c82ea8e5a6a64da5a51df521452312a6` | `37194602268` | 1 | SUCCEEDED | — |
| automatic C14 | `rt_7f92f4c6fe07455d991dcff452416ba2` | `37194968153` | 1 | SUCCEEDED | PASS_SCOPED |
| automatic C13 | `rt_36633ba4140f4b448f04f8bcbb023c25` | `37195017030` | 1 | SUCCEEDED | PASS_SCOPED |

Builder produced Draft PR `#404`, head `fe788be4b30f3ba87c47c2447cda9a28c649092d`, one file `+15/-0`. The automatic C14 reviewed exactly that head. PR #404 remains Draft and unmerged.

Round facts:

- `round_decision=ACCEPT`;
- C13's prerequisite root equals the C14 root actually adopted by the Runtime;
- independence is true;
- both review envelopes have `authorizes_any_action=false` and `deployment_eligible=false`;
- the focused C13 machine inventory really ran successfully;
- C14 was enqueued before Builder completion;
- C13 was enqueued before C14 completion;
- repeated enabled polls returned the same Runtime task identities;
- **manual C14 Review Issue count for this chain = 0**;
- **`deliver_review_round.py` calls for this chain = 0**;
- paid executions = exactly 3: Builder 1 + C14 1 + C13 1.

### 3.5 Resident service snapshot after auto-review installation

Last verified 2026-10-04:

| Service | State |
| --- | --- |
| `go-runtime-host-c01-issue-consumer` | active / enabled |
| `go-runtime-host-ghaw-builder-worker` | active / enabled |
| `go-runtime-host-c13c14-review-worker` | active / enabled |
| `go-c1-c14-runtime` | active / enabled |
| `go-runtime-host-agent` | active / enabled |
| `go-runtime-host-runtime-bridge` | active / enabled |
| `go-runtime-host-c1-worker` | inactive / disabled |

`systemctl --failed` was empty. No new unit, daemon, scheduler, queue, DB, registry, workflow or review rule was added by the Builder-auto-review bridge.

> **Superseded on 2026-10-07 — read this before trusting the row above.**
>
> The `go-runtime-host-c1-worker` row is a dated 2026-10-04 observation and is kept as
> history. The **Legacy C1 Responses executor has since been REMOVED from source**: its
> systemd unit `control-plane/runtime-host-channel-v1/systemd/go-runtime-host-c1-worker.service`
> no longer exists in the repository, so **no unit of that name can be installed from
> `main`**. The live resident set is exactly the six `active / enabled` services above.
>
> `c1_worker.py` is **not** part of that removal and must not be deleted: it is the single
> shared execution loop that the gh-aw Builder executor and the C13/C14 review executor
> both import. See section 4.

### 3.6 One known non-blocking observability quirk

The review worker's `--check` status line still reports the shared worker's singular `dispatch_target` default (`c1-ai-execution-backend-v1.yml`) even though the review client is correctly bound to `c14-rule-compliance.yml` and `c13-quality-acceptance.yml` through `workflow_files`.

This is **display-only** and not an execution/dispatch defect. Do not reopen Runtime architecture for it. Fix only if the status UX becomes operationally confusing.

## 4. Persistent Runtime delivery status

| Workstream | Status |
| --- | --- |
| C01-C12 Formal Issue ingress | **DONE / LIVE** |
| Generic C01-C12 Builder | **DONE / LIVE PROVEN** |
| Builder -> Draft PR -> automatic C14 bridge | **DONE / LIVE PROVEN** |
| C14 -> automatic C13 chaining | **DONE / LIVE PROVEN** |
| Formal manual Review Issue ingress | **DONE / LIVE PROVEN / OPTIONAL PATH** |
| Duplicate paid-dispatch protection | **DONE / LIVE PROVEN** |
| Source/candidate freshness binding | **DONE / LIVE PROVEN** |
| Legacy C1 Responses path | **RETIRED / DISABLED / REMOVED FROM SOURCE (2026-10-07)** |
| U6 Solution-Leak Gate | **BYPASS / DEFERRED; not a Runtime blocker** |

**Legacy C1 Responses path — what "REMOVED" does and does not mean (2026-10-07).**

- REMOVED: the separate systemd unit that ran `c1_worker.py` as its own executor for
  `AI_WORK_V1` / `AI_TASK_V1`. It was `disabled` + `inactive (dead)` on rt01 since
  2026-10-04 13:31, nothing depends on it, and its unit file is deleted from this
  repository. Reinstall it from `main` and you get nothing, because the file is gone.
- NOT REMOVED, on purpose: `control-plane/runtime-host-channel-v1/c1_worker.py`. It is
  the **shared execution loop** — `c1_ghaw_builder_worker.py` and
  `c1_c13c14_review_worker.py` both do `from c1_worker import (...)` and
  `test_c1_executor_boundary` asserts that import. It is a library that the two live
  executors run on, not a retired worker. Deleting it would break the normal chain.
- NOT REMOVED, on purpose: the `AI_WORK_V1` / `AI_TASK_V1` protocol vocabulary in
  `c1_execution_contract.py`, the `c1-ai-execution-backend-v1.yml` workflow, and the
  `go-runtime-host-c1-worker.tmpfiles.conf` file. The tmpfiles file is live infrastructure:
  it declares `/etc/go-runtime-c1` (the shared credential directory) and
  `/var/lib/go-runtime-c1` (the shared outbox directory) that the consumer, Builder and
  review units all still use.
- Still shared with the live chain: the install directory `/opt/go/runtime-host-c1-worker/`.
  The **live** `go-runtime-host-c01-issue-consumer` unit runs from it
  (`ExecStart=/opt/go/runtime-host-c1-worker/c1_issue_consumer.py`), so that directory must
  not be deleted either.


**Persistent Runtime end-to-end automatic progression is delivered.**

The only normal human action before the review stops is product intent: decide what C01-C12 task to request and create its Formal Issue. Technical task hand-off between Builder, C14 and C13 is automatic.

Merge and deployment remain separate authorized actions after review.

## 5. Key 2026-10-04 Runtime lineage

| PR | Result |
| --- | --- |
| `#392` | Formal Builder ingress source binding |
| `#395` | C14->C13 review transport attached to Persistent Runtime |
| `#396` | First real C14 dispatch wire-input fix |
| `#397` | Confirm Runtime lease before paid review dispatch |
| `#398` | Formal manual Review Issue ingress |
| `#402` | Builder Draft PR automatically advances to C14, then existing C14 automatically advances to C13 |

These PRs describe delivery transport, not product merge/release authority.

## 6. Current candidate facts

- PR `#320` — open Draft, unmerged. Its candidate was recorded as the current HK business runtime in the now-retired `docs/canonical-baseline/CURRENT_HK_RUNTIME.json`; that file no longer exists, and the live runtime identity must come from the newest signed VERIFY Evidence instead.
- PR `#383` — Boss-owned Draft with an older per-cell entry design; read/review only, do not take over.
- PR `#394` — historical review-ingress canary Draft; unmerged.
- PR `#404` — automatic Builder->C14->C13 live E2E candidate; open Draft, unmerged.

For other PRs, re-read GitHub live state.

## 7. What not to infer

Do not infer:

- `main` == HK runtime;
- merged == deployed;
- Builder succeeded == review passed;
- Runtime review `SUCCEEDED` == verdict PASS;
- C13/C14 PASS == merge/deploy authority;
- a Draft PR being auto-reviewed == it may auto-merge;
- old Evidence / old checkpoint / a file named `CURRENT` == live authority.

## 8. Startup / truth priority

For substantive GO work:

1. live GitHub `main`;
2. current task PR / branch / commit / diff;
3. `docs/project/OPERATING_CONTEXT.md`;
4. this file;
5. `docs/project/CONTEXT_CHECKPOINT.json`;
6. current runtime / deploy / Evidence / Runbook if the real environment matters.

Truth priority:

`live GitHub / real environment / current Evidence > repository current-state documents > historical PR/docs > AI memory`

Changing implementation facts must be re-derived. Unknown facts stay `UNKNOWN`.
