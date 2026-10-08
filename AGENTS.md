# GO — AI operating instructions

> This file is the **only CURRENT AI entry point** for this repository.
> The human entry point is [`README.md`](README.md) (Chinese).
> Every other Markdown file in this repository is **HISTORY for current-routing purposes**:
> it may still contain valid evidence, constraints, or component-local facts, but it does not
> define the repository's normal operating path and cannot override this root `AGENTS.md`.
>
> **Byte-pinned historical exception:** `application/AGENTS.md` is retained unchanged because
> existing source/evidence checks bind its exact bytes. Its old `HK_STAGING_*` / Old Command
> Center routing is not CURRENT. For deployment, inspection, GO Forge, fallback selection, and
> HK-STAGING routing, this root `/AGENTS.md` always wins unless the Owner explicitly authorizes
> Old Command Center fallback mode.
>
> Version note: this file deliberately hard-codes no fast-changing value (commit SHA, image id,
> migration head, service state). Read those live. Runtime identity comes from the newest
> **signed VERIFY Evidence**, never from a file in this repository.

---

## CURRENT NORMAL PATH

```text
Deploy:
Boss GPT -> GO-FORGE / FORGE_DEPLOY -> GO Forge -> HK-STAGING

Inspect:
Boss GPT -> GO-FORGE / FORGE_INSPECT -> GO Forge -> HK-STAGING

Build:
Boss -> Formal C01-C12 Issue -> Persistent Runtime -> Builder -> Draft PR -> C14 -> C13

Review:
Boss -> C14 · REVIEW Issue -> Runtime -> C14 -> C13 when admitted

Stop:
GO-FORGE / FORGE_STOP

Do NOT use Old Command Center or HK_STAGING_* unless the Owner explicitly requests fallback mode.
```

If you are a zero-context AI: **the four lines above are the whole answer.** Everything below is
detail. Do not go looking for a GUIDE/RUNBOOK/HANDOFF to learn "how it is done now" — those are
HISTORY and several of them contradict the path above.

---

## 1. Truth order

When two sources disagree, the higher one wins. Do not average them.

1. **Live state** — the real host, the real GitHub state (`main`, PR head, checks), the real
   running process.
2. **Signed Evidence** — `chenzhenxi1-sudo/go-control-evidence`. The newest signed VERIFY
   Evidence is the only thing that says what HK-STAGING is actually running.
3. **This file and `README.md`** — the current operating definition.
4. **HISTORY** — everything else, including anything that calls itself CURRENT / FINAL / GUIDE /
   HANDOFF / RUNBOOK. HISTORY means "not a CURRENT operating entry point"; it does **not** mean
   every statement inside is invalid. Evidence, governance constraints, rollback material, and
   byte-pinned component facts may still be valid when this root file explicitly relies on them.

Two hard consequences:

- **`main` is not the host.** A merged PR does not move a running environment. Repository bytes
  and host bytes differ routinely; treat that as normal, not as a defect to fix.
- **No file in this repository declares what a machine is running.** The pointer that used to
  (`docs/canonical-baseline/CURRENT_HK_RUNTIME.json`) was retired on 2026-10-08 and deleted.

## 2. Ownership and authority

- **余总 / Boss** — product owner and final business-direction decision maker.
- **Boss GPT** — product exploration/development agent. Its branches, PRs and documents are
  **candidates**: not automatically canonical, not Execution Authority.
- **陈震曦 / Eason** — technical operator, integrator, reviewer, execution coordinator.
- **Eason's ChatGPT** — coordination / context / review layer. Not product owner, not deployment
  authority.
- **Codex / WorkBuddy** — execution agents under Eason's control. Command capability is not
  deployment authority.

Rules:

- **Do not touch any PR authored by `yuguangzhi3836-glitch` (the Boss).** No branch, commit,
  merge, close, retarget, or edit — ever, regardless of how stale it looks.
- A Pull Request is a proposal/review boundary, **not** Execution Authority. Never merge unless
  the responsible human explicitly authorizes that specific merge, in that turn.
- Documentation is not Execution Authority. Execution Authority is: live state · human approval ·
  Signed Task · installed artifact · usable recovery record · signed Evidence.
- Servers are **read-only by default**. Connectivity is capability, not authorization. Every
  mutation requires fresh, explicit, per-action authorization.

## 3. Mutation boundary

Without **current explicit authorization** for that exact action, never:

```text
merge to main                     write directly to main
force-push shared history         delete remote branches holding evidence/work
deploy to HK-STAGING              deploy to Production
run a migration against live DB   restart / enable / disable a host service
change host configuration         change network / proxy / DNS / firewall
rotate, create or copy credentials
treat a Draft PR as approved release authority
```

- **Production is FORBIDDEN** unless the Owner explicitly authorizes it in writing, per action.
- Credentials, private keys, tokens, AccessKeys, cookies, session values and runtime `.env` values
  must never enter Git, PR text, published logs, or project documentation.
- Never weaken, bypass or falsify a required gate to save time or runner minutes. If a required
  remote gate exists, report the cost instead of pretending local testing is equivalent.

## 4. GO Forge Task — Boss GPT operating contract

Boss GPT submits the Boss's intent as one GO-FORGE Task in `chenzhenxi1-sudo/go-control-tasks/main/tasks/<task_id>.json`, then **tracks the Receipt and final Evidence and reports back**. It does not execute the task.

Do not perform candidate resolution, deployment planning, runtime guessing, or HK operations in Boss GPT. GO Forge owns all of that after the Task arrives.

### Deploy

Boss intent:

```text
Deploy PR 558 to HK-STAGING.
```

Task:

```json
{
  "authority": "GO-FORGE",
  "action_id": "FORGE_DEPLOY",
  "environment": "HK-STAGING-01",
  "target_pr": 558,
  "schema_version": "1",
  "task_id": "forge-deploy-pr558-<unique>",
  "issued_at": "<UTC ISO-8601>",
  "nonce": "<unique random string>",
  "parameters": {}
}
```

**A deploy Task means: GO Forge deploys.**

### Inspect a PR / deployment

For a specific PR, use the same envelope with:

```json
{
  "action_id": "FORGE_INSPECT",
  "target_pr": 558
}
```

`FORGE_INSPECT` is read-only: inspect and report, never deploy.

### Inspect the actual HK runtime / files

A general runtime inspection does not need a PR first. Example Boss intent:

```text
Show me what version HK-STAGING-01 is actually running, which source/image/files it corresponds to, and return the evidence.
```

Task:

```json
{
  "authority": "GO-FORGE",
  "action_id": "FORGE_INSPECT",
  "environment": "HK-STAGING-01",
  "schema_version": "1",
  "task_id": "forge-inspect-<unique>",
  "issued_at": "<UTC ISO-8601>",
  "nonce": "<unique random string>",
  "parameters": {
    "request": "Inspect the actual HK-STAGING-01 runtime identity, corresponding source/image/key file paths and Evidence, then report the result."
  }
}
```

GO Forge reads live state and Evidence, finds the relevant version / source / image / file paths, and returns the result. Boss GPT must not guess them.

### After submitting: follow the result

**Submitting a Task is not proof that it succeeded. Boss GPT reads and reports Evidence; it never writes Evidence.**

1. Retain the exact submitted `task_id`.
2. Read `chenzhenxi1-sudo/go-control-tasks` at `main/receipts/<task_id>.json` for the `RECEIVED` / `FINAL` status, result and Evidence reference.
3. If `FINAL` is not yet present, tell the Boss the observed state and check again later using the **same** `task_id`. Do not issue a duplicate deploy Task merely because a result is pending.
4. On terminal result, open the corresponding **formal Evidence** under `chenzhenxi1-sudo/go-control-evidence/evidence/`, read the actual outcome and blockers, and report them with the Evidence link.
5. If only a notification or Receipt is available without verifiable final Evidence, report that the formal outcome is still unconfirmed; never claim success.

Only **GO Forge** publishes formal Evidence. Boss GPT may read, link and summarize it, but must never manufacture or publish it on Forge's behalf.

### Hard rules

- Task path: `chenzhenxi1-sudo/go-control-tasks/main/tasks/<task_id>.json`
- `authority = GO-FORGE`
- deploy = `FORGE_DEPLOY`
- inspect / current version / corresponding files = `FORGE_INSPECT`
- `environment = HK-STAGING-01`
- generate a unique `task_id`, current `issued_at`, unique `nonce`; keep deploy `parameters = {}`
- never supply source commit, candidate id, artifact digest, package SHA, image id, migration head, compose path, TEST_PR parameters, canary/verify steps, recovery plan or deployctl argv
- never issue `HK_STAGING_TEST_PR / HK_STAGING_CANARY / HK_STAGING_VERIFY / HK_STAGING_DEPLOY` during normal operation; Old Command Center is fallback only
- read `receipts/<task_id>.json` for receipt/status; signed Evidence is the final authority

`FORGE_STOP` remains available for a specifically authorized stop order; it is not part of normal deploy/inspect usage.

## 5. Runtime / Cell routing (the Boss build/review channel)

Persistent Runtime runs on `go-runtime-test-01`. It is a **different axis** from Forge.

- **Builder**: a GitHub Issue titled `Cxx · <task-id> · <scope>` with `Cxx` in **C01–C12**, body
  carrying a `Task:` paragraph and `Canonical source: <full 40-char SHA of current main at the
  moment the Issue was created>`. The gate is `source_anchor == current main`; a stale SHA is
  refused and no paid Builder runs.
- **Review**: a GitHub Issue titled `C14 · REVIEW · <description>` with `Candidate PR: #<n>` and
  `Candidate SHA: <the exact PR head at the moment the Issue was created>`. The gate is
  `candidate_sha == PR head`; a later push invalidates it. **Never create a `C13 · REVIEW` Issue** —
  only C14's sealed result can cause Runtime to create C13.
- **kind IS the routing.** Each executor claims one kind; two executors claiming one kind is a
  race and the boundary test asserts disjointness.
- After a Builder produces exactly one Draft PR, Runtime automatically runs C14 and then C13.
  C13/C14 produce sealed evidence **only** — they never merge and never deploy.
- `c1_worker.py` is a **shared library**, not a worker. The retired thing is the unit that ran it
  as a standalone executor. Do not infer status from a `c1-` filename prefix.
- **"14 workers" is a wrong reading.** 14 = C01–C14 **Cells**; C13 and C14 are `control_only`.
  Two executors actually run.

Cells: C01 Hotel · C02 Flight · C03 Rail · C04 Rental · C05 Ride · C06 Attraction ·
C07 Traveler Intelligence · C08 GO AI Planning & Execution · C09 GO Judgment & Trust ·
C10 Unified Trips · C11 Transaction & Finance · C12 Platform/Security/Model Gateway ·
C13/C14 control-only review.

## 6. Candidate identity boundary

- An open PR or branch is a **candidate**. It is never silently promoted to current truth because
  it is newer or larger.
- The live runtime identity is the newest signed VERIFY Evidence, and nothing else.
- `comparison=DRIFT` is **not** a defect by itself. If the difference is accounted for by a
  verified record it is recorded (`drift_explained=true`) and the run continues; only an
  **unexplained** runtime stops a run and asks a human.
- "Candidate" and "running version" are different things by definition — a deployment turns one
  into the other.

## 7. Evidence

| What | Where |
|---|---|
| HK runtime identity (**only authority**) | `chenzhenxi1-sudo/go-control-evidence` → `evidence/`, newest signed VERIFY |
| Forge task results | same repo — exactly one document per terminal task |
| Forge run ledger | `chenzhenxi1-sudo/go-control-tasks` → `receipts/` |
| Boss notification | one WeCom message per accepted task, to the owner's single chat |
| C13/C14 round decisions | Runtime / GitHub Actions sealed artifacts |

## 8. Active capability vs. history

ACTIVE: `application/` (business source) · `deploy/hk-staging/` (runtime definition) ·
`application/Dockerfile` (build) · Forge operator source in `go-control-tasks`
(`forge-operator/source/`) · `tasks/` + `receipts/` · the evidence repo ·
Persistent Runtime on rt01.

RETIRED / NOT ON THE NORMAL PATH: Old Command Center request / bridge / web lineage
(`command-center/`, legacy Old-CC components under `control-plane/`,
`hk-staging/source/{agent,executor}`) — retained only where history or break-glass value remains;
its request bridge and web service are stopped and disabled and its periodic timers were retired.
**Do not classify all of `control-plane/` as retired**: active Persistent Runtime source remains
under `control-plane/runtime-host-channel-v1/`, and other deterministic capabilities may still
have real consumers.

HISTORY (bound to their original commit): `deliverables/`, `evidence/`, `hk-staging/`
(2026-09-11 snapshot), all DEPTH parents, `docs/audits/**`, `docs/reviews/**`,
`docs/control-plane/**`, `docs/project/**`, `docs/state/**`, `docs/runtime/**`, `docs/go-forge/**`.

> **Known and deliberately unfixed:** parts of the Persistent Runtime (`runtime.py`,
> runtime-host-agent, runtime bridge) have **zero bytes on `main`**; their source-of-record is a
> retained branch, while the host runs more enabled units than `main` declares. This is a
> **provenance gap**. Report it. Do not fix, stop, delete, reinstall or reconcile it as part of a
> documentation or unrelated task.

## 9. Repository change control

All planned permanent changes follow
[`docs/governance/CHANGE_CONTROL_POLICY.md`](docs/governance/CHANGE_CONTROL_POLICY.md), for humans,
ChatGPT, Codex and other automation alike.

```text
current main -> short-lived branch -> commits/tests -> Pull Request -> review -> merge
```

Never write directly to `main` — including for probes, convenience edits, temporary test files,
documentation fixes, or AI-generated changes.

Any change that adds/removes/renames runtime service roles, introduces another business image
family, changes protected non-targets, or otherwise alters HK-STAGING deployment topology is a
**topology change** and must follow
[`docs/control-plane/hk-staging/TOPOLOGY_CHANGE_POLICY.md`](docs/control-plane/hk-staging/TOPOLOGY_CHANGE_POLICY.md).

**Protected non-targets** (never stop, remove or recreate as part of a business cutover):
`caddy` · `redis` · PostgreSQL/RDS business data · persistent media volumes · HK Agent · Executor ·
signing keys · Task/Evidence/ledger · Control Plane authority data · SSH access and key material ·
Production.

### Git and CI discipline

- Prefer local iteration and targeted local tests; **GitHub Actions are an acceptance/checkpoint
  layer, not the edit-test-fix loop.** Do not push merely to make CI repeat tests that already
  passed locally.
- Push only at a real boundary: explicit request · a coherent stage ready for review ·
  remote-only validation is materially required · remote commit identity is required for a
  candidate/artifact/Evidence/deployment binding · the task is complete.
- Inspect `git diff` before commit; checkpoint locally whenever useful. A local commit does not
  imply a push.
- **Do not equate PR numbers with product generations.** PR #40 is an HK-STAGING archive, not
  DEPTH40.

## 10. Break-glass

Old Command Center is used **only** when the Owner explicitly requests fallback mode for a
specific action. It is not a convenience path.

When explicitly in fallback mode, the only documents that may be consulted are:

- `docs/control-plane/hk-staging/README.md`
- `docs/control-plane/hk-staging/HK_STAGING_OPERATIONS_GUIDE.md`
- the action-specific `HK_STAGING_*` runbook linked there

They are HISTORY with break-glass value. They are not the normal path, and reading them is not a
reason to use them. A Boss GPT must never choose on its own to use both paths at the same time.

## 11. Working style (for execution agents)

- **Lead with the conclusion, then the current state, then the next action.** Chinese by default;
  keep SHAs, branches, paths, commands, protocol names in English.
- Give exact, copy-pasteable commands. If one command is enough, do not list ten alternatives.
- Make routine, reversible, low-risk decisions yourself. Ask only when the ambiguity materially
  affects product intent, irreversible data/history, credentials, deployment/Production, a
  conflict between valid baselines, destructive operations, or authority boundaries.
- Do not ask twice for information already present in the task, this file, `README.md`, or Git state.
- **Prefer evidence over confidence**: report branch, HEAD, test counts, PASS/FAIL/SKIP, changed
  files, hashes, exact command output, PR number, CI status. Never convert partial evidence into a
  broader PASS claim.
- Correct mistakes directly, including mistakes by Eason, another AI, an older README, or a prior
  assumption — say so and replace it with the verified fact.
- Keep progress visible on long tasks. Do not narrate every trivial command.
- Never hide a failed test behind an otherwise successful summary; never call a candidate
  "canonical" without evidence.
