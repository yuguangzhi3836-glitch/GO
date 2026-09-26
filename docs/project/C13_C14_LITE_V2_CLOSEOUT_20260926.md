# C13 / C14 Lite V2 — Closeout (2026-09-25 → 2026-09-26)

> **Nature of this document — read this first.**
>
> This is a **historical closeout report / current-state navigation document**.
> It is **not** a new Authority. It does not override code, Policy, GitHub facts, runtime facts
> or Human Authorization.
>
> **If this document conflicts with current main code, formal Policy, the actual GitHub state or
> runtime facts, those more direct sources win.** This file is a map, not a supreme text.
> It is not `CURRENT_AUTHORITY`, not canonical authority, not a constitution and not final truth.

| Field | Value |
| --- | --- |
| Subject | C13 / C14 Lite V2 — why it was rebuilt, what was retired, what is actually in main, what remains |
| Window covered | 2026-09-25 → 2026-09-26 |
| Canonical main when written | `065d03712f54067c58d14da4941882d82089135d` (merge of PR #262) |
| Facts established by | GitHub REST read-only queries for PR/issue state + the repository at the main commit above |
| Status | `IMPLEMENTATION_MERGED / POST_FIX_PRODUCTION_E2E_PENDING` |

Companion navigation: [`GO_CURRENT_STATE.md`](GO_CURRENT_STATE.md) — this closeout is reachable
from that file's section 5. `GO_CURRENT_STATE.md` is itself a checkpoint-bound historical state
snapshot, and this closeout is also only a navigation document. Neither overrides more direct
current facts. If they disagree with current main/code, formal Policy, the actual GitHub state,
runtime evidence or explicit Human Authorization, those more direct sources win.

## 0. 中文摘要（给中文读者）

- 这两天的目标：把 C13/C14 从"试图当**独立裁判**"改成"**同一个团队里分工明确的两道 AI 审核**"。
- 老方案（CC/HK 双见证、真签名、最终聚合、多层 witness、`FINAL_ROOT`）**全部废弃**，
  只留在**已关闭、未合并**的 PR #247–#251 里。
- 真正进了 `main` 的是六个修复（#252–#257）+ 一个监控（#261）+ 一个收口（#262）。
- 现在**只剩一个真实 gate**：拿一份**真实新候选**，跑一次 post-#262 的正式 C14 → C13。
- 这份文档**不是 Authority**；与 main 代码 / 正式 Policy / GitHub 事实 / 运行时事实冲突时，以那些为准。
- ⛔ 以后**不要因为考古旧 PR 就自动复活** witness / `FINAL_ROOT` / C15 / 第二套 authority。

## 1. Why C13 / C14 was rebuilt

C13/C14 were progressively designed, over several rounds, towards something like an
**independent adjudicator / independent review authority**: two cells that would separately
certify a candidate, with extra machinery whose purpose was to demonstrate that the reviewers
were *independent*.

The core logic problem that ended that direction:

- GO is in reality **two humans plus AI** — a small team, not an institution.
- C13 and C14 are **AI members of that same system**, running on the same repository, the same
  GitHub account model and the same operating process.
- They genuinely *can*:
  - run **separately**;
  - perform a **fresh execution** (a new API execution with its own prompt, not a reused context);
  - **not share** one execution's context with the other cell;
  - keep **role separation** (different remits, different inputs, different outputs).
- They **cannot** claim, on the basis of the above:
  - to be an external third party;
  - to be an independent regulator;
  - to be an independent judicial, notarial or certification authority.

Stated as one line, and this line is the whole point:

```text
independent execution != independent external authority
```

## 2. The final definition of "independence"

### 2.1 C14 — rule, permission and governance review

C14 is responsible for:

- governance semantics
- permission / IAM
- authority boundary
- contract
- legal / regulatory
- AI behaviour rules
- topology / governance meaning

C14 judges against the rule text supplied in its own facts (resolved read-only from the
default branch's governance data). It is not a second quality tester: it runs no Docker, no
PostgreSQL, no regression / recovery / journey suite. It is also **not a second GitHub process
checker** — ordinary mechanical repository-process facts are not semantic blockers.

### 2.2 C13 — independent quality acceptance

C13 is responsible for:

- implementation quality
- machine evidence
- regression
- recovery
- security
- journey
- acceptance criteria
- material quality that is directly related to the task

C13 judges the supplied machine evidence and the source against the brief the candidate was
answering, and never accepts the author's own self-test as proof.

### 2.3 Their relationship

- **C14 runs before C13** (C13's seal is gated on the sealed C14 record for the same candidate).
- **Two fresh AI executions** — each cell gets its own execution identity, and the ledger's two
  `reviewer` values are required to differ; this is machine-checked, not a written claim.
- **Each cell judges only within its own remit**, and neither substitutes for the other.
- **Neither grants deployment, merge or release authorization.** Every record carries
  `authorizes_any_action = false`; a human still issues the deployment instruction.

But, and this is the boundary that matters:

> **C13/C14 are GO-internal AI reviewers. They no longer claim to be an external independent
> adjudicator.**

## 3. History, split into RETIRED and CURRENT

### 3.A RETIRED — historical experiments, not a backlog

Verified state (GitHub read-only, 2026-09-26): **all closed, none merged.**

| PR | Title | State | Verdict |
| --- | --- | --- | --- |
| #247 | 2026-09-25｜方案收敛｜C13/C14 Lite｜对齐Owner职责基线并固化Lite V2设计 | closed, unmerged | `RETIRED` |
| #248 | 2026-09-25｜实施中｜C13/C14 Lite V2｜接入14-Cell调度并实现独立规则审查与质量验收 | closed, unmerged | `RETIRED` |
| #249 | 2026-09-25｜实施中｜C13/C14 Lite V2｜接入调度并实现CC/HK双见证与最终聚合 | closed, unmerged | `RETIRED` |
| #250 | 2026-09-25｜实施中｜C13/C14 Lite V2｜打通CC/HK GitHub只读见证凭据 | closed, unmerged | `RETIRED` |
| #251 | 2026-09-25｜实施中｜C13/C14 Lite V2｜全链验收模拟（真候选＋CC/HK真签名）止于人工门 | closed, unmerged | `RETIRED` |

Classification: **`HISTORICAL_EXPERIMENT / RETIRED / NOT_CURRENT_ARCHITECTURE`.**

What they explored, so a future reader does not have to re-read them:

- a **CC witness / HK witness** pair, and a **dual-witness** acceptance chain;
- **real signatures** as part of that chain;
- a **final aggregation** step producing a third root over the two cells;
- using **additional machinery to demonstrate independence** rather than to prevent a failure;
- multi-layer witness / authority thinking in general.

Conclusion — read this as a closed chapter, not a roadmap:

> These were historical explorations. They are **not** an unfinished backlog.
> Unless a **new, concrete, real failure** appears that one of them would actually prevent,
> do **not** resurrect them by finding the old PRs.

Do **not** write "this still has to be implemented later". The repository position is the
opposite: main deliberately contains *no* witness layer, *no* aggregator, *no* `FINAL_ROOT`
and *no* receipt/signature chain for this purpose, and the test suite asserts their absence.

### 3.B Merged — the fix chain that is actually in main

Verified state (GitHub read-only, 2026-09-26). Each of these is **merged into `main`**.

| PR | Title | Merged | Merge commit | The real failure it fixed |
| --- | --- | --- | --- | --- |
| #252 | 2026-09-25｜待注册｜C13/C14 Lite V2｜登记C14规则审查与C13质量验收工作流 | yes | `7db7b2aa52ecabc1ff1c92d9d1673f44f5ce68c5` | The two production workflows (C14 rule review, C13 quality acceptance) had to be registered on the default branch as real, dispatchable cells |
| #253 | 2026-09-25｜待合并｜C13/C14 Lite V2｜修复真实C14暴露的边界与工作流绑定缺陷 | yes | `3cd7be752330f377e3446942da4f881df13d183d` | The first real C14 run exposed boundary and workflow-binding defects: a merge commit produced an **empty** changed-path boundary, and the workflow identity was inferred from the workspace instead of the executing ref |
| #254 | 2026-09-25｜待合并｜C13/C14 Lite V2｜修复BLOCKED封存语义并保留原始审查证据 | yes | `64715d308954049eb6675d81196d7f4cd853199b` | A refused seal discarded the only copy of the reviewer's reasoning; `BLOCKED` / refusal had to stay explainable after the run |
| #255 | 2026-09-26｜待合并｜C13/C14 Lite｜收口核心审核链并改用真实规则来源 | yes | `568b59980a01fcf61b55a14897337e5969780a27` | C14 was reviewed against **three rule-set names our own backend had invented**. The rule set became governance data resolved read-only from the default branch, and "insufficient information" became `BLOCKED` instead of `NOT_APPLICABLE` |
| #256 | 2026-09-26｜待验证｜C13 Lite｜补齐机器验收候选依赖安装并解除首次E2E阻断 | yes | `fa7b581508816db930262ac3dc022d48bc17e578` | C13's machine job installed only pytest, so the inventory could not even collect: the candidate's own declared dependencies were missing |
| #257 | 2026-09-26｜待验证｜C13/C14 Lite｜修复审核内容输入链并把真实候选差异交给Reviewer | yes | `16d5f0b99d3de00dfbf02a3d16ffc05adf5c180e` | The reviewer was handed **names of changed paths but no change surface and no diff** — the facts carried an empty list while the frozen scope carried eight paths, and every digest still recomputed |

The two later merged items are described in their own sections: **#261** (Monitor, section 6)
and **#262** (Review Brief + threshold review, section 5), whose merge commit is the current
main head.

Commit-level history is not reproduced here — the PR numbers above are the entry points.

## 4. What the first real Review E2E taught

These are lessons, not a mandate for a new architecture:

1. **A reviewer that does not receive the real diff will review the wrong thing — competently.**
   The first E2E produced a clean verdict over an empty change surface.
2. **A machine-acceptance environment missing the candidate's declared dependencies cannot even
   start testing.** "No failures" and "never ran" must not look the same.
3. **The rule source must not be a set of names the reviewer backend invented for itself.**
   A rule set we made up is not evidence about anything.
4. **`BLOCKED` / seal refusal must not take the reviewer's reasoning with it.** A refusal has to
   stay explainable after the run.
5. **Matching evidence digests do not prove the input was semantically correct.** Every digest
   in the first E2E recomputed, and the review was still wrong.
6. **The value of C13/C14 comes from role separation and real inputs — not from proving that
   they are an independent institution.**

## 5. PR #262 — final closeout

`PR #262` — "2026-09-26｜待验证｜C13/C14 Lite｜补齐Review Brief并收敛为及格审核" —
**merged**; merge commit `065d03712f54067c58d14da4941882d82089135d` (current main).

What it establishes:

- **`REVIEW_BRIEF_V1`** — both cells are now given the task context they grade against
  (see below), resolved read-only and matched uniquely or refused.
- **acceptance, not perfection** — the shared reviewer standard now states that the review goal
  is acceptance against the brief, the rules and the evidence; that finding nothing blocking is
  a valid and successful result; that minor / advisory / stylistic / cleanup / readability /
  optional-hardening / future-improvement findings do not require rework; and that rework is
  justified only by a real blocking defect inside the reviewer's remit.
- **C14: ordinary mechanical GitHub metadata no longer forms a semantic blocker on its own.**
  Branch existence, review counts, GitHub CI/check status, PR-template fields, change-class
  strings and ordinary PR metadata completeness belong to a deterministic preflight, not to
  semantic rule review. C14 *does* still judge whether what the brief claims is true of the
  actual change.
- **C13: minor / advisory / refactoring / documentation polish must not by itself produce a
  non-PASS verdict.** Those belong in `quality_findings` or `remaining_risks` with the verdict
  left at `PASS_SCOPED`.
- **`PASS_SCOPED` may include non-blocking findings and remaining risks.** The verdict says the
  candidate is acceptable, not perfect.

### 5.1 `REVIEW_BRIEF_V1` — exact meaning

```text
REVIEW_BRIEF_V1 =
the associated pull request's declared delivery brief.
```

It **is**:

- the task context the reviewer grades against;
- taken from the **candidate's associated pull request** (GitHub's own commit → pull requests
  answer, matched uniquely on `head.sha` or `merge_commit_sha`; zero or several matches is a
  refusal — never a guess);
- frozen as GitHub's own raw facts: `number`, `title`, `body`, `base_ref`, `head_ref`,
  `head_sha`, `merge_commit_sha`, `state`, `merged_at`, `html_url` (the URL is navigation only).

It is **not**:

- an immutable original production task;
- an independent authority;
- a proof that the original task was delivered faithfully.

Recorded explicitly, because it is easy to over-read:

> `input_sha256` can show **what brief this reviewer actually saw in this round**.
> It **cannot** show that this PR body equals the immutable original specification the
> production AI originally received — a pull request body can be edited after it was opened.
> Binding and provenance are different questions; this mechanism answers only the first.

Forward-looking, and **not yet enforced**:

- Real production candidates' PRs should carry the original task faithfully —
  **objective, scope, out-of-scope, acceptance criteria, validation / test plan** — so the
  declared brief is as close as possible to the task the candidate actually received.
- At present there is **no template gate** and **no immutable task registry**.

## 6. AI Production Quality Monitor

Two different objects, often confused:

- **Issue #260** — "AI Production Quality Monitor｜C01-C14 产量、一次通过率与返工深度"
  — an **issue**, not a pull request. Verified: open, author `chenzhenxi1-sudo`, comments 1.
- **PR #261** — "2026-09-26｜已验证·待审核｜AI生产质量监控｜新增Issue #260旁路统计与每日刷新"
  — the **pull request** that implemented it. Verified: **merged**, merge commit
  `9d80095c2817fbb9c6931125d5d39c59f7a8e92d`; landed as
  `.github/workflows/ai-production-quality-monitor.yml` + `ci/ai_production_monitor/`.

What the Monitor does: it collects C13/C14 production review statistics (Today / 7d / 30d,
C14 `PASS_SCOPED` / `NOT_APPLICABLE` / `FAIL` / `BLOCKED`, C13 `PASS_SCOPED` / `FAIL` /
`BLOCKED`), and later — once enough real data exists — first-pass rate and rework depth.

What it is not:

- **It is not C15.** It is not a cell, not a reviewer and not a new review stage.
- It does **not** review a candidate.
- It does **not** change any verdict.
- It does **not** participate in authority.
- It does **not** block merge or deploy.
- Its alerting is **OFF** initially: observe real data first.

## 7. Current production state, and the remaining gate

Established from the canonical main above (not from PR text):

| Item | State |
| --- | --- |
| `CURRENT MAIN SHA` | `065d03712f54067c58d14da4941882d82089135d` |
| C13 / C14 Lite V2 backend | **in main** — [`control-plane/c13-c14-lite/`](../../control-plane/c13-c14-lite/README.md) |
| Current workflows | [`c14-rule-compliance.yml`](../../.github/workflows/c14-rule-compliance.yml), [`c13-quality-acceptance.yml`](../../.github/workflows/c13-quality-acceptance.yml) (both `workflow_dispatch`-only, `active` on main) |
| C14 rule source | [`C14_RULE_SOURCES.json`](../governance/C14_RULE_SOURCES.json) → [`CHANGE_CONTROL_POLICY.md`](../governance/CHANGE_CONTROL_POLICY.md), resolved read-only from the default branch |
| Review Brief | **in the reviewer facts** — `review_brief` is a facts key for both C13 and C14, bound by the existing `input_sha256` |
| Threshold review | **in the prompt** — shared `REVIEW STANDARD` reaches both cells |
| Evidence / seal / chain | **retained** — sealed bundles, readback, raw-evidence preservation, prerequisite gate, end-to-end round verification |
| Command Center (CC) | **not modified** |
| HK agent / executor | **not modified** |
| Deployment chain | **not modified** |
| Witness / aggregator / `FINAL_ROOT` / POC workflow | **not in main** (deliberately absent; asserted by tests) |

### 7.1 Remaining gate

**One gate remains:**

> A **next real new candidate**, run once as a **post-#262 formal C14 → C13 production E2E**.

The current status must therefore be written as:

```text
IMPLEMENTATION_MERGED / POST_FIX_PRODUCTION_E2E_PENDING
```

It must **not** be written as `C13/C14 production fully proven`: after #262 was merged, no real
new candidate has yet been taken through the full C14 → C13 path.

## 8. DO NOT RESURRECT BY ARCHAEOLOGY

A future AI that finds old PRs or old documents must **not** automatically re-add any of the
following to the architecture merely because they once existed:

- "C13/C14 must prove they are an external independent authority";
- CC witness;
- HK witness;
- dual-witness acceptance;
- `FINAL_ROOT`;
- an independent notarial / certification body;
- a third-party AI reviewer;
- C15;
- a second authority;
- a second ledger;
- adding one more AI in order to prove that an AI is independent;
- an infinite recursion of "proving that the reviewer's reviewer is also independent".

Resurrection is permitted only when **a new, concrete, real failure** exists **and** the
proposal can answer:

> Which real failure does this new control actually prevent?

If that question cannot be answered with a specific failure, the correct answer is: do not add it.

## 9. Current engineering principle

GO is:

> **two humans + AI, a small team.**

The primary purpose of control here is to prevent:

> AI mistakes, mis-operation, wrong inputs, wrong evidence, and unauthorized execution.

It is **not**:

> treating AI as a malicious attacker and building an enterprise-grade judicial system around it.

Every new control must be:

- simple;
- traceable;
- testable;
- rollback-able;
- and able to say which real failure it prevents.

## 10. This document is not `CURRENT_AUTHORITY`

This closeout must never be cited as:

- `CURRENT_AUTHORITY`;
- canonical authority;
- a constitution;
- supreme truth;
- final authority.

It is only:

```text
historical closeout + current-state navigation
```

Real facts continue to come from:

- current `main`;
- current code;
- formal Policy;
- the actual GitHub state;
- runtime evidence;
- explicit human authorization.

## 11. Background facts this closeout does not own

Observed while establishing the facts above, recorded as background only. **None of these is
ours to modify, comment on, take over, close or merge**, and this closeout does **not** decide
anything about them:

- **PR #258** (author `yuguangzhi3836-glitch`, open) — "C01–C14 第七轮最终证据归档：C13限定通过与五组CI全绿".
  This is the boss's Round-7 evidence archive; it is **not** the current C13/C14 Lite V2
  implementation.
- **PR #259** (author `yuguangzhi3836-glitch`, open) — "Round8: isolated Aoluguya operating day,
  exceptions and reconciled close".
  Whether this becomes the first formal C13/C14 E2E candidate is a **human decision for later**;
  this closeout does not make it.
- **PR #61** (ours, open, Draft) — Payment Center technical reality discovery. Unrelated to this
  closeout; its age grants nothing.

## Appendix A — how the GitHub facts in this document were verified

- Method: **GitHub REST, read-only** (`GET /repos/{owner}/{repo}/pulls/{n}` and
  `/issues/{n}`), plus the repository checked out at canonical main
  `065d03712f54067c58d14da4941882d82089135d`.
- `main` resolved locally by fetching `origin` at execution time — **not** taken from any
  previously quoted SHA.
- PR "merged" is read from the API's own `merged` field, **not** inferred from `state` or from
  `merge_commit_sha`.
- ⚠ Note for future readers: GitHub returns a non-empty `merge_commit_sha` for a **closed but
  unmerged** PR too (the prospective test-merge commit). A non-empty `merge_commit_sha` on a
  PR whose `merged` is `false` is **not** a merge point. This is why section 3.A lists no merge
  commits.
- Verified counts of the retired set: PR #247–#251 each `closed` / `merged=false`.
- Verified counts of the merged set: PR #252–#257, #261, #262 each `merged=true`.

GO_C13_C14_LITE_V2_CLOSEOUT_STATUS=RECORDED_AT_MAIN_065d0371
