# GO CURRENT STATE

> Purpose: canonical human-readable project-state snapshot for new ChatGPT, Codex, WorkBuddy and human handoffs.
>
> This file is **descriptive context, not Execution Authority**. Runtime and deployment authority still comes from current live state, Human Approval, Signed Task, installed artifact, durable previous-state and Signed Evidence where applicable.
>
> New sessions should read this file instead of reconstructing GO by replaying historical pull requests.
>
> **Checkpoint binding:** this snapshot describes canonical main `8ffcde66d36c1bbf849218529ef015f6e81725af` (2026-09-14). The machine-readable binding is [`CONTEXT_CHECKPOINT.json`](CONTEXT_CHECKPOINT.json). The checkpoint binds **canonical main**, not any context-PR branch head.

## 0. Truth classes in one line

`CURRENT_MAIN_FACT` (accepted/current main or canonical runtime evidence) · `ACTIVE_DECISION` (effective human decision) · `ACTIVE_CANDIDATE` (open PR/branch/proposal, not canonical) · `HISTORICAL` (superseded/archive/audit) · `HOLD` (explicitly not effective/authorized) · `UNKNOWN` (insufficient evidence; do not fill the gap).

An open PR/branch must never be silently promoted into `CURRENT_MAIN_FACT`.

## 1. What GO is right now

GO is a multi-domain travel product under active development. The repository contains hotel, flight, rail, ride, rental, attraction, mobile, payment/funds, Command Center, Control Plane, deployment, packaging and operational evidence work.

The project is not considered globally complete or production-ready merely because code exists for a capability. Source integration, runtime cutover and release acceptance are three separate things (section 6).

## 2. Repository source truth — `CURRENT_MAIN_FACT`

| Item | Value |
| --- | --- |
| Canonical main | `8ffcde66d36c1bbf849218529ef015f6e81725af` (2026-09-14T18:34:48+08:00, merge of PR #76) |
| Application source root | `application/` |
| `main:application` git tree | `dd815baf0105cce603e9a28b002cfb9d8b95d186` |
| Application files | 1365 (all mode `100644`) |
| Application source fingerprint | `a64f8185f19f1c78a70fc6662fbafc85f69273745a95503f97c2948ab6d85374` |
| Migration head | `0134_flight_status_width` (`down_revision = 0133_flight_change_plan`) |
| Migrations | 134 revisions, one linear chain, base `0001_sprint1d` |
| Current gate manifests | `ci/retention/BASELINE.json`, `ci/next-depth/CANDIDATE.json`, `ci/cell-closure/CANDIDATE.json` — all three bind tree `dd815baf…` / `a64f8185…` |

The fingerprint is `sha256` over `f"{path}\0{sha256(bytes)}\n"` for every tracked path under `application/`, sorted; it is **not** the git tree hash. Verify against `ci/retention/verify_source.py`.

Merged into canonical main since the previous context checkpoint (`286e294d`, 2026-09-13): **PR #66, #67, #69, #70, #74, #76** (see section 7).

## 3. Live runtime truth — `CURRENT_MAIN_FACT`, unchanged since 2026-09-13

| Item | Value |
| --- | --- |
| Environment | HK-STAGING, host `i-j6ccs8t04f1p4d8pe69z` |
| Active business runtime generation | `DEPTH48`, cut over 2026-09-13 |
| Machine-readable pointer | [`docs/canonical-baseline/CURRENT_HK_RUNTIME.json`](../canonical-baseline/CURRENT_HK_RUNTIME.json) |
| Image | `go-hotel:depth48-runtime-6d0fd905` (`sha256:57beafa250f42eb1319ae561e0b79f432bb80d7171592392303a31446cd8ac6c`) |
| Deployed runtime application tree | `3025b2b6b36ea9211da561a4631f304216de9d90` (1325 files) |
| Live database revision | `0133_flight_change_plan` (PostgreSQL 18.4, 551 tables) |
| Services | `api` + `outbox` / `recovery` / `reconciliation` / `judgment` / `mobile-engagement` / `mobile-push` / `mobile-push-receipt` workers |
| Health | `/health` 200 `{"status":"ok","service":"go-hotel-platform"}` |
| Protected non-targets | `caddy`, `redis`, PostgreSQL/RDS business data, persistent media volumes, HK Agent, Executor, signing keys, Task/Evidence/ledger, Control Plane authority data, SSH key material, Production |

The HK runtime pointer is owned by the runtime/deploy line, not by the context layer. This context layer only references it.

**No HK runtime mutation, migration or deployment was performed by the work that produced this snapshot.**

## 4. How the repository source relates to the live runtime — important

They are **not the same thing right now**, and both statements are simultaneously true:

- The live HK-STAGING runtime is the accepted **DEPTH48** runtime: deployed tree `3025b2b6…` (1325 files).
- Canonical main has advanced **past** that runtime: `dd815baf…` (1365 files).

Measured delta between the deployed runtime application tree and current main:

```text
3025b2b6 (deployed runtime tree) -> dd815baf (current main tree)
62 files changed, +5329 / -195
migration delta   0133_flight_change_plan -> 0134_flight_status_width   NOT APPLIED
```

Consequences a fresh session must respect:

- `current main` is the current **source** truth; it is not automatically what is running.
- `0134_flight_status_width` exists in repository source but has **not** been executed against live HK data. The last confirmed live revision remains `0133_flight_change_plan`.
- Updating the runtime pointer, migrating live data, or cutting over the business runtime requires separate authorization. It is not implied by a merge into main.

## 5. Release / gate status — `CURRENT_MAIN_FACT`

Recorded in canonical main by `ci/retention/BASELINE.json`, `ci/next-depth/CANDIDATE.json` and `ci/cell-closure/CANDIDATE.json`:

| Gate | Status |
| --- | --- |
| `RETENTION` (rebind to final 0134 tree) | `PASS` — run `34825183779` |
| `C07 / C09 / C11` PostgreSQL scopes | `C11` original PostgreSQL cases `10/10 PASS` — run `34807203728`; C07/C09 scopes still listed in the remaining gate order |
| Migration `0134` data preservation + downgrade guard | `PASS` |
| `C14` (independent engineering/authority/boundary review) | not recorded on main for the final tree |
| `C13` (independent acceptance) | not recorded on main for the final tree |
| `HK_DEPLOY` | **`HOLD`** |
| `FINAL_RELEASE` | **`HOLD`** |
| `PRODUCTION` | **`HOLD`** |
| Hong Kong access from these gate runs | `NOT_ACCESSED` |
| `historical_pass_transferred` | `false` |

Declared gate order on main: `RETENTION → C07_POSTGRES → C09_POSTGRES → C11_POSTGRES → REGRESSION → C14 → C13`.

**Scoped acceptance does not transfer across source changes.** The round-2 `C13`/`C14` `PASS_SCOPED` records under `evidence/v70-round2-20260914/` are bound to candidate tree `740d026e…` (1341 files) — that is **not** the current main tree, and the same CI manifests say `historical_pass_transferred=false`. Those records are inherited evidence, not a verdict on `dd815baf…`.

## 6. Three axes that must not be conflated

| Axis | What it covers | Where it lives |
| --- | --- | --- |
| **Business Runtime** | what serves hotel/flight/... traffic | `application/`, `deploy/hk-staging/`, `docs/canonical-baseline/CURRENT_HK_RUNTIME.json` |
| **Control Plane** | signed tasks, HK Agent/Executor, Command Center, ledger, evidence transport | `command-center/`, `control-plane/`, `hk-staging/source/{agent,executor}` |
| **Release Acceptance** | whether a candidate is accepted for release | `ci/`, `evidence/`, `packaging/`, gate records |

`Runtime is ACTIVE` **never** means `release acceptance passed`, and a Control Plane service being maintenance-inactive is not a business-runtime gap.

## 7. Merged Cell work and evidence on canonical main

| PR | Merged content | What it does and does not mean |
| --- | --- | --- |
| #66 | V7 14-Cell convergence: six P1 fixes and scoped evidence | Source/test repairs; not domain completeness |
| #67 | Archive of PR66 canonical CI and independent acceptance evidence | Documentation/evidence only |
| #69 | `packaging/canonical-runtime/` — fixed canonical runtime package + independent offline restore | Packaged image-byte transport bound to tree `995d0d83…` at main `c6ea4dd`; explicitly not "completed Sealed Node", not a deployment |
| #70 | `packaging/canonical-node-seal/` — canonical Node toolchain overlay + independent restore | `PASS_SCOPED` toolchain gate only; explicitly not full release or deployment permission |
| #74 | C11 flight status model alignment; original C11 PostgreSQL cases verified | `10/10 PASS` on the original C11 PostgreSQL cases; does not close every C11 open gap |
| #76 | `0134_flight_status_width` SQLite partial-history compatibility + final gate evidence rebind | Test-only compatibility repair plus CI rebinding; `HK_DEPLOY`/`FINAL_RELEASE`/`PRODUCTION` stay `HOLD` |

Evidence entrypoints:

- `evidence/v70-round2-20260914/` — 14-Cell round-2 ledger, `c13/`, `c14/` scoped acceptance (bound to `740d026e…`)
- `evidence/v70-round2-20260914/c11/` — C11 original failures retained, plus `c11/followup/` design and an **unexecuted** acceptance worksheet
- `evidence/v70-pr73-integrated-gate-20260914/INTEGRATED_CANDIDATE_BINDING.json` — integrated-gate binding with `hk_deploy`/`final_release`/`production` all `HOLD`

`evidence/`, `journey-evidence/` and `deliverables/` are historical evidence bound to their original commit and scope. They are not current authority by default.

## 8. Active candidates — `ACTIVE_CANDIDATE`, not current truth

All items below are **open and unmerged** at this checkpoint. None of them may be described as current main behaviour.

| PR | Draft | Branch / head | Nature |
| --- | --- | --- | --- |
| #61 | yes | `payment-center/reality-discovery-01` `bf1c266a` | Payment Center technical reality discovery (read-only) |
| #65 | yes | `project-context/current-state-v1` | This context/state/governance layer |
| #71 | yes | `test/existing-image-47bb66c4-three-end-20260914` `7df5c491` | `TEST_ONLY` three-end browser acceptance over an existing immutable image |
| #72 | no | `evidence/canonical-release-preparation-20260914` `e239a1ca` | `DOCUMENTATION` — archive Node seal acceptance + current release-preparation gates |
| #73 | yes | `fix/v70-round2-fef9c748-20260914` `72151d2e` | V7 continued depth: C11 flight recovery + scoped 14-Cell evidence |
| #75 | yes | `gate/pr73-integrated-4d236353-20260914` `29489073` | Gate-only descendant of #73 (based on #73, not main) |
| #78 | yes | `ops/14-cell-ledger-main-8ffcde66-20260914` `00e8f315` | Rebind 14-Cell execution ledger to main `8ffcde66`; dispatches `ASSIGNED_NO_ACK` |
| #89 | yes | `chore/post-merge-canonical-rebind-8ffcde66-20260914` `f9a8eb74` | Post-merge governance/evidence pointer rebind |
| #90 | yes | `acceptance/runner-canary-f9a8eb-20260914` `9f5f4b64` | CI runner availability canary for candidate `f9a8eb74` |
| #91 | yes | `ops/r3-real-worker-ack-8ffcde66-20260914` `89504555` | Source-bound R3 worker ACK/start evidence runners |

Notes a fresh session must not miss:

- Claims inside these PRs (`C14 PASS_SCOPED`, `C13 PASS_SCOPED`, `MAIN_MERGE=PASS`, worker `ACK`) are **candidate claims**. As a verifiable check: candidate SHA `37d9a420…`, which PR #78 cites for `C13`/`C14` `PASS_SCOPED`, does **not** appear anywhere in canonical main.
- `ASSIGNED_NO_ACK` means exactly that: no worker is claimed to have started.
- Older long-lived Draft PRs (#2–#64 range, acceptance/package/governance branches) remain open; their number or age grants nothing.

## 9. Payment Center — `HOLD` + `ACTIVE_CANDIDATE`

- Active discovery PR: **#61** `payment-center/reality-discovery-01` — still open, still Draft, still unmerged.
- Current direction is **technical reality discovery before any Payment Center implementation**.
- Canonical main contains both native HOTEL payment records/flows and newer omnichannel payment/funds models. Repository code alone does not prove live WeChat Pay / Alipay / card acquiring execution, and does not prove real hotel inventory authority.
- Payment Center must not introduce a second independent money truth by default. Live-money authority remains locked.
- This context layer does not implement Payment Center, does not modify payment business code, and does not decide new money truth.

## 10. Human / AI responsibility model

- **Boss / 余总**: product owner and final business-direction decision maker.
- **Boss GPT**: product exploration/development agent; branches and PRs are candidates, not automatically canonical and not Execution Authority.
- **Eason / 陈震曦**: integration, review, execution coordination and human technical-operations owner.
- **Eason's ChatGPT**: context, review, task-decomposition and coordination layer; not product owner or deployment authority.
- **Codex / WorkBuddy**: execution agents under Eason's control, on `Eason-8845` and `Eason-13490` respectively.

Full detail: [`OPERATING_CONTEXT.md`](OPERATING_CONTEXT.md) and [`../../AGENTS.md`](../../AGENTS.md).

## 11. What is explicitly NOT safe to infer

Do not infer any of the following from PR count, PR number, DEPTH number, file count, table count or presence of a model/table:

- that a feature is production-ready;
- that a provider integration is real rather than simulated;
- that an AI-generated design is an approved business decision;
- that a newer PR supersedes a reviewed baseline;
- that a mock capability equals supplier/PSP capability;
- that historical evidence describes current runtime;
- that a merged feature automatically has deployment authority;
- that "the runtime is ACTIVE" implies release acceptance;
- that the repository migration head equals the live database revision.

## 12. Context-compaction rule

GO project continuity must not depend on replaying all historical pull requests.

A new session should normally read, in order:

1. [`README.md`](../../README.md)
2. [`docs/project/OPERATING_CONTEXT.md`](OPERATING_CONTEXT.md)
3. [`docs/project/GO_CURRENT_STATE.md`](GO_CURRENT_STATE.md) (this file)
4. [`docs/project/ACTIVE_DECISIONS.md`](ACTIVE_DECISIONS.md)
5. the relevant module state file under [`docs/state/`](../state/README.md)
6. [`docs/project/CONTEXT_CHECKPOINT.json`](CONTEXT_CHECKPOINT.json)
7. only repository changes after the recorded checkpoint, unless older history is specifically needed for audit or dispute resolution.

Historical PRs remain evidence. They are not mandatory context once their effective state has been compressed into the current-state layer.

## 13. Updating this file and the checkpoint

Refresh the current-state layer when a reviewed change materially changes current project truth — for example roughly 10–20 materially relevant PRs, a new module baseline, a runtime generation change, or before a new project phase.

Refresh procedure (also recorded in [`CONTEXT_HANDOFF_PROTOCOL.md`](CONTEXT_HANDOFF_PROTOCOL.md)):

1. resolve the real canonical `main` SHA at execution time (do not assume a previously quoted SHA is still current);
2. recompute `main:application` tree, file count and source fingerprint from the repository;
3. recompute the Alembic head from source, and separately restate the **live** database revision;
4. re-read the gate/release fields from the canonical CI manifests rather than from PR text;
5. reclassify newly opened/merged PRs into `CURRENT_MAIN_FACT` / `ACTIVE_CANDIDATE` / `HOLD` / `HISTORICAL`;
6. update only the state files whose effective truth changed;
7. rebind `CONTEXT_CHECKPOINT.json` to canonical main and the refresh date;
8. keep this file short enough for a fresh session to load without consuming most of its working context.

Do not copy every PR summary into this file. When a decision changes, preserve history in the decision register and update only the currently-effective statement here.

GO_CURRENT_STATE_STATUS=REFRESHED_AT_MAIN_8ffcde66
