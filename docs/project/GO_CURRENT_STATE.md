# GO CURRENT STATE

> Purpose: current human-readable project state for fresh ChatGPT / Codex / WorkBuddy sessions.
>
> Refreshed against canonical `main` **1faf0faedf70fab010c3d49001e8787a2f58c024** on 2026-10-04.
> This file is descriptive context, not Execution Authority. For any mutation, live GitHub / real environment / current Evidence outrank this snapshot.

## 0. Read this first

GO currently has three separate axes that must not be inferred from one another:

1. **Repository source** — what is in GitHub `main`.
2. **Business runtime** — what the eight GO business services are actually running on HK-STAGING.
3. **Persistent Runtime / AI execution transport** — the third ECS that durably accepts work, dispatches AI execution and adopts results.

A merge does not imply a business deployment. A business deployment does not imply the same source is on `main`. A C13/C14 review verdict does not authorize merge or deployment.

## 1. Repository source truth — CURRENT_MAIN_FACT

| Item | Current value |
| --- | --- |
| Canonical main | `1faf0faedf70fab010c3d49001e8787a2f58c024` |
| Main root tree | `61d85985c3dcccc3a8bf986a7fd66747b2f180da` |
| `main:application` tree | `83e73327d5f8f00841a3febdbe2a94e2078dbeae` |
| `application/` files | 1369 blobs |
| Repository migration head | `0135_supplier_onboarding` |
| Migration down revision | `0134_flight_status_width` |
| Migration revisions | 135 files under `application/alembic/versions/` |

The source fingerprint from the older 2026-09-14 checkpoint was **not** carried forward: it was bound to another tree and was not recomputed in this refresh.

## 2. HK-STAGING business runtime — separate axis

The canonical repository pointer is `docs/canonical-baseline/CURRENT_HK_RUNTIME.json`. That pointer was re-read during this refresh.

| Item | Current pointer value |
| --- | --- |
| Environment | HK-STAGING |
| Runtime generation label | `DEPTH48` |
| Last pointer/deploy date | 2026-10-02 |
| Deployed candidate | PR `#320`, head `eeafca1b15a4754ba36a0f138a27347cbbd12c73` |
| PR #320 state | open / Draft / **not merged** |
| Deployed application tree | `6f97ac5d572dae1de0b3e38b6201da2a6de14216` |
| Image tag | `go-hk-test-pr:eeafca1b15a4754ba36a0f138a27347cbbd12c73` |
| Image id | `sha256:26c95472d494100dc5365b031335670b57570b86ac50fb1b4ebd161d7933530b` |
| Live DB revision | `0145_source_latest_index` |
| Live tables | 564 |
| OpenAPI paths | 1059 |

Therefore the current GitHub source and the current HK business runtime are **not the same tree**. This is expected and must remain explicit. The business-runtime pointer says the 2026-10-02 PR #320 candidate was deployed by GO Forge and formally verified; that does not make PR #320 merged source.

Do not infer current HK state from `main:application`, and do not infer current main from the deployed image.

## 3. Persistent Runtime — LIVE / PROVEN / DELIVERED

The Persistent Runtime runs on the separate Runtime Host (rt01 / third ECS). Its job is intentionally narrow:

`queue/state/lease/attempt fencing -> dispatch -> evidence/result adoption -> recovery`

It is **not** a local 14-model host, not Command Center, not a release authority and not a product-quality judge.

### 3.1 C01-C12 Builder path

Current live path:

`Formal GitHub Issue -> one resident issue consumer -> Persistent Runtime -> one generic C01-C12 Builder worker -> GitHub Agentic Workflow -> Draft PR -> Runtime result adoption`

Properties proven live:

- C01-C12 share one generic Builder worker and one Builder outbox.
- Formal Builder Issues bind their `source_anchor` to the current `main`; stale historical issues are refused before paid execution.
- The workflow re-checks its execution SHA before the paid agent runs.
- Deterministic run names plus durable outbox state prevent ambiguous `workflow_dispatch` from becoming a second paid POST.
- Historical issues `#79`-`#88` remain open as historical evidence but are stale-refused and do not execute.
- The superseded legacy C1 Responses worker is disabled.

### 3.2 C13/C14 review path

Current live path:

`Formal Review Issue -> same resident issue consumer -> Runtime C14_REVIEW_V1 -> one special review worker -> existing C14 workflow -> sealed admissible C14 -> idempotent Runtime C13_REVIEW_V1 -> same worker -> existing C13 workflow -> sealed round -> Runtime result adoption`

Important semantics:

- C14 and C13 are **special read-only review executions**, not ordinary Builders.
- There is one review worker and one review outbox, not one daemon per cell.
- C13 can only be created by a sealed, admissible C14 result. A GitHub Issue cannot directly create C13.
- Review delivery success is separate from review verdict. A valid `FAIL` / `BLOCKED` review can still be a Runtime `SUCCEEDED` execution.
- `authorizes_any_action=false`; neither C13 nor C14 can merge or deploy.
- Before any paid review dispatch, the review worker confirms it still owns a valid Runtime lease. This was added after the first real live round exposed the paid-dispatch-after-lease-loss failure.

### 3.3 Formal Review Issue ingress

PR `#398` is merged on current main and removed the last manual transport step (`deliver_review_round.py`) from the normal review path.

Owner-facing shape:

```text
C14 · REVIEW · <description>
Candidate PR: #<number>
Candidate SHA: <40-hex frozen PR head>
```

The ingress derives the application tree, round/task/request identities and machine-test inventory. It refuses a moved PR head instead of silently following it.

### 3.4 Live canary

Validation Issue `#399` (`C14 · REVIEW · formal ingress canary for PR #394`) proved the complete formal review path:

| Item | C14 | C13 |
| --- | --- | --- |
| Runtime task | `rt_2054610cd3064d53adf5adf55b48d77a` | `rt_c5ec212556e7477483266dbaede35145` |
| Kind / owner | `C14_REVIEW_V1` / C14 | `C13_REVIEW_V1` / C13 |
| GitHub run | `37189939040` | `37189996082` |
| Dispatch count | 1 | 1 |
| Runtime status | SUCCEEDED / attempts 1 | SUCCEEDED / attempts 1 |
| Review verdict | PASS_SCOPED | PASS_SCOPED |
| `authorizes_any_action` | false | false |
| `deployment_eligible` | false | false |

`round_decision=ACCEPT`, the C13 prerequisite root matched the C14 root actually adopted by the Runtime, independence was true, and repeated enabled polls returned the same Runtime task rather than creating a second task or paid execution.

Issue `#399` was closed after the canary. Validation product PR `#394` remains open Draft and unmerged.

## 4. Runtime Host service snapshot — last verified 2026-10-04

| Service | State |
| --- | --- |
| `go-runtime-host-c01-issue-consumer` | active / enabled |
| `go-runtime-host-ghaw-builder-worker` | active / enabled |
| `go-runtime-host-c13c14-review-worker` | active / enabled |
| `go-c1-c14-runtime` | active / enabled |
| `go-runtime-host-agent` | active / enabled |
| `go-runtime-host-runtime-bridge` | active / enabled |
| `go-runtime-host-c1-worker` | inactive / disabled (retired legacy Responses path) |

`systemctl --failed` was empty during the #399 closeout. Execution decisions must still re-read the host rather than treating this table as permanent authority.

## 5. Persistent Runtime delivery status

| Workstream | Status |
| --- | --- |
| U7A — C01-C12 generic Builder transport | **DONE / LIVE PROVEN** |
| C01-C12 Formal Issue ingress | **DONE / LIVE** |
| Source binding / stale issue protection | **DONE / LIVE PROVEN** |
| U7B — C14->C13 Runtime review transport | **DONE / LIVE PROVEN** |
| Formal Review Issue ingress | **DONE / LIVE PROVEN** |
| C14->C13 automatic chaining | **DONE / LIVE PROVEN** |
| Duplicate paid-dispatch protection | **DONE / LIVE PROVEN** |
| Legacy C1 Responses execution path | **RETIRED / DISABLED** |
| U6 Solution-Leak Gate | **BYPASS / DEFERRED**; not a Runtime blocker |

**Persistent Runtime is delivered.** Do not continue adding architecture merely to make the Runtime look more formal.

The only normal human action left is **admission intent**:

- create a valid C01-C12 Formal Issue when the Owner wants Builder work, or
- create a valid `C14 · REVIEW` Issue when the Owner wants a candidate reviewed.

Once admitted, technical task transport no longer requires Eason to manually move work between GitHub and the Runtime. Choosing *what work should happen* remains a product/engineering decision, not a missing Runtime feature.

## 6. Key 2026-10-04 Runtime lineage

| PR | Result |
| --- | --- |
| `#392` | Formal Builder ingress source binding; old-source tasks fail closed |
| `#395` | C14->C13 Lite dual review attached to Persistent Runtime |
| `#396` | First real C14 dispatch fix: do not send undeclared workflow inputs |
| `#397` | Confirm Runtime lease immediately before paid review dispatch |
| `#398` | Formal Review Issue ingress; removes normal manual review-delivery step |

These entries describe transport evolution only. They do not authorize product deployment.

## 7. Current candidate facts that must not be promoted

- PR `#320` — open Draft, unmerged; nevertheless its candidate is the current HK business runtime according to `CURRENT_HK_RUNTIME.json`.
- PR `#383` — Boss-owned Draft proposing an older per-cell automatic-entry design. It is not canonical and must not be taken over or rewritten.
- PR `#394` — Builder-created Draft used for the real C14/C13 canary. It remains unmerged and is not automatically entitled to merge because the review path worked.

For all other PRs, re-read GitHub live state. Do not maintain a permanently enumerated list of every open candidate here.

## 8. What not to infer

Do not infer:

- `main` == HK runtime;
- merged source == deployed source;
- CI PASS == product acceptance;
- review delivery `SUCCEEDED` == review verdict PASS;
- C13/C14 PASS == merge/deploy authority;
- Runtime healthy == business runtime healthy;
- PR number or age == lineage superiority;
- old Evidence or old `CURRENT_*` filename == current authority.

## 9. Startup / truth priority

For substantive GO work, use:

1. live GitHub `main`;
2. current task PR / branch / commit / diff;
3. `docs/project/OPERATING_CONTEXT.md`;
4. this file;
5. `docs/project/CONTEXT_CHECKPOINT.json`;
6. current runtime / deploy / Evidence / Runbook when the real environment matters.

Truth priority remains:

`live GitHub / real environment / current Evidence > current-state documents > historical PR/docs > AI memory`

Changing implementation facts must be re-derived. Unknown facts stay `UNKNOWN`.

## 10. Historical note

The previous in-file snapshot bound to `8ffcde66d36c1bbf849218529ef015f6e81725af` (2026-09-14) is superseded as current context and remains available in Git history. It must not be used as today's repository/runtime state.

`ACTIVE_DECISIONS.md` is an append-preserving historical decision register and still contains time-bound examples from older checkpoints. Stable decision principles remain useful; changing implementation values in that file must be verified against live state and this snapshot.
