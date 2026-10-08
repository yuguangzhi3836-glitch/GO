# GO Forge — Boss / Boss GPT usage

**Date:** 2026-10-08
**Status:** CURRENT — reflects the GO Forge V1 closeout of 2026-10-08
**Owner:** chenzhenxi1-sudo
**Scope of this document:** how the Boss (or a Boss GPT with zero context) asks GO Forge to work on
HK-STAGING-01, and what Forge will and will not do. It records usage only; it does not deploy, and
it changes nothing about the runtime.

---

## 1. The one question Forge answers

> **Does the actual runtime on HK-STAGING-01 match the authorised candidate?**

Everything Forge does exists to answer that one question with evidence rather than assertion.

The normal chain is:

```text
Boss / Boss GPT
  -> GitHub Task  (one JSON document, in chenzhenxi1-sudo/go-control-tasks)
  -> GO Forge     (resident operator on the Command Center host, user go-forge)
  -> existing HK capability   (sealed executor go-hk-deployctl: verify | canary | deploy | rollback)
  -> HK-STAGING-01
  -> Evidence (signed) + WeCom notification
```

The legacy Command Center is **not** in this path. Its source stays in the tree as
break-glass history, but it runs nothing: its request bridge and its web service are stopped
and disabled, and its periodic timers were retired on 2026-10-08.

---

## 2. The normal deployment request

Say exactly this, and nothing more:

```text
Deploy PR <number> to HK-STAGING.
```

Concretely it becomes **one JSON document** committed to `tasks/` in
`chenzhenxi1-sudo/go-control-tasks` on `main`:

```json
{
  "authority": "GO-FORGE",
  "action_id": "FORGE_DEPLOY",
  "environment": "HK-STAGING-01",
  "target_pr": 320,
  "schema_version": "1",
  "task_id": "forge-deploy-pr320-20261008T000000Z",
  "issued_at": "2026-10-08T00:00:00.000000Z",
  "nonce": "<random, at least 16 characters>",
  "parameters": {}
}
```

That is the entire contract.

| Field | Who supplies it | Notes |
|---|---|---|
| `authority` | **you** | must be exactly `GO-FORGE`, or Forge ignores the task |
| `action_id` | **you** | `FORGE_DEPLOY` to deploy, `FORGE_INSPECT` to inspect only, `FORGE_STOP` to stop a run |
| `environment` | **you** | `HK-STAGING-01` |
| `target_pr` | **you** | the pull-request number. **This is the whole intent.** |
| `schema_version` | envelope | `"1"` |
| `task_id` | envelope | unique; also the filename stem: `tasks/<task_id>.json` |
| `issued_at` | envelope | UTC ISO-8601 |
| `nonce` | envelope | unique per task |
| `parameters` | envelope | leave `{}`. Do **not** put candidate facts here. |

The envelope fields exist because the bus consumer expects them. They carry no intent.

Do **not** supply any of these — Forge derives every one of them from live state:

```text
source commit        candidate id          artifact digest      package SHA256
candidate contract   migration head        image id             compose path
TEST_PR parameters   canary/verify steps   recovery plan        the deployctl argv
```

`FORGE_INSPECT` is the same document with `"action_id": "FORGE_INSPECT"`. It authorises **no
mutation** and is the safe way to check the environment. In plain words:

```text
Inspect HK-STAGING for the current runtime identity.
```

You supply **intent only** — a pull-request number and whether Forge should inspect or deploy.
Everything else is derived. If you find yourself describing how to do it, you are supplying
more than intent and it will be ignored or refused.

`FORGE_STOP` is handled by the worker without any AI involvement at all:

```json
{
  "authority": "GO-FORGE",
  "action_id": "FORGE_STOP",
  "environment": "HK-STAGING-01",
  "target_run_id": "<the run to stop, or omit to stop whatever is running>",
  "reason": "why",
  "schema_version": "1", "task_id": "...", "issued_at": "...", "nonce": "...",
  "parameters": {}
}
```

A valid document of every shape above can be produced by the operator's own publisher, which also
stamps the envelope fields:

```text
python3 /opt/go-forge/forge_publish.py --action-id FORGE_DEPLOY  --target-pr 320
python3 /opt/go-forge/forge_publish.py --action-id FORGE_INSPECT --target-pr 320
python3 /opt/go-forge/forge_publish.py --stop --target-run-id <run_id> --reason "..."
```

---

## 3. What Forge then does, on its own

```text
read the pull request's live state           (the head commit is authoritative)
establish the immutable source identity
find the candidate for that head             (or prepare one: see §5)
inspect the real HK-STAGING runtime
verify a real recovery path before mutating
run the sealed CANARY, then the sealed DEPLOY, verifying each step
roll back automatically if a step verifies badly
publish signed Evidence, then notify WeCom
```

The order is Forge's to choose. It is not a fixed workflow, and it may revise its plan mid-run when
reality changes — revisions are recorded, never hidden.

---

## 4. Where the result is

* **GitHub:** `chenzhenxi1-sudo/go-control-evidence` -> `evidence/`. Each terminal task publishes
  exactly one document.
* **WeCom:** one message per accepted task, to the owner's single chat.

The terminal message states the facts plainly, not a verdict to be interpreted:

```text
干的什么 / 目标环境 / 目标 PR / 结果
是否执行了部署
是否改过环境
回滚状态
GitHub 记录
需要你处理
```

Terminal results:

| Result | Meaning |
|---|---|
| `DEPLOY_SUCCESS` | deployed and verified against the real running system |
| `FAILED_ROLLBACK_SUCCESS` | the deployment failed, the environment was put back, a human is needed |
| `FAILED_NEEDS_HUMAN` | Forge found a fact that stops it. The Evidence names the fact. |
| `PASS` | a non-deploying action (e.g. `FORGE_INSPECT`) completed |
| `STOPPED_BY_HUMAN` | a `FORGE_STOP` was honoured |

Forge reports facts. It does not interpret them for you.

---

## 5. Preparing a candidate that has no candidate record yet

Forge will build and test a release that has no candidate record yet: it runs the host's
existing `TEST_PR` build/test/seal executor, and the verdict comes from **that machine**,
never from Forge's own judgement.

Forge then **derives** the candidate's identity from the machine's own output. It never
*invents* one: a field with no producer is refused **by name**, together with the component
that owns it. There is nothing for a human to mint first, and there is no baseline document
for anyone to advance afterwards — both of those items are gone with the retired pointer.

---

## 6. What Forge compares, and what DRIFT means

Forge compares the **authorised candidate** against the **actual runtime**, and asks whether
the actual runtime is *accounted for* by a verified record:

* If the difference **is accounted for** by a verified record — a previous deployment record,
  signed Evidence, or the previous known-good image — Forge records `comparison=DRIFT`,
  `drift_explained=true`, names the record(s) in `drift_explained_by`, and **continues**. A
  runtime that a record already explains is not a reason to stop.
* If the difference is **unexplained** — an actual runtime that no verified record accounts
  for — Forge investigates read-only (GitHub, Evidence, past deployment records, logs) and, if
  it still cannot account for it, **stops and asks a human**. It will not mutate an
  environment it cannot account for.

The candidate and the running version are different things by definition: a deployment turns
one into the other. That difference is never, on its own, drift.

**Why this is not "compare against a baseline document".** Until 2026-10-08 there was a
repository pointer, `docs/canonical-baseline/CURRENT_HK_RUNTIME.json`, which claimed to
declare what was running; Forge was told to compare the runtime against it. It was wrong in
exactly the way a declaration inside a repository has to be wrong. On 2026-10-03 the PR #376
deployment completed and self-verified (sealed VERIFY = `VERIFY_OK`, 8/8 services, protected
non-targets unchanged) but was never written back into that file, so the file still named the
PR #320 image (`sha256:26c95472d494…`) while all eight services ran the PR #376 image
(`sha256:01632507d0d3…`). On 2026-10-07 that stale declaration made a correct deployment read
as DRIFT, and a blanket rule then refused `DEPLOY_SUCCESS` for the rest of the run even
though Forge's own VERIFY proved the target was live. The declaration was the thing that was
wrong and the operator had no way to say so.

So the file was retired on 2026-10-08, and with it the whole idea of a repository declaring a
runtime. Nothing in the repository declares what a host is running; the newest signed VERIFY
Evidence is what says so. There is no pointer to advance, by Forge or by you.

---

## 7. What Forge never does

```text
merge a pull request                 comment on a pull request
close a pull request                 change a pull request's state
advance any baseline declaration     touch Production
touch any human-owned pull request   invent a candidate identity
```

Refusals happen in the tool layer, not only in a prompt. They are not negotiable, and nothing you
write in a task changes them.

---

## 8. Do not do these during normal Forge mode

**Do not** manually issue any of:

```text
HK_STAGING_TEST_PR      HK_STAGING_CANARY      HK_STAGING_VERIFY      HK_STAGING_DEPLOY
```

**Do not** supply: image digest, artifact digest, package digest, migration commands, Docker
commands, compose paths.

**Do not** run the Forge path and the Command Center path for the same deployment at the same time.

---

## 9. Fallback

The legacy Command Center's source is retained in the tree, so the old path can be
reconstructed deliberately. It is a **fallback only**: used when the owner explicitly
switches to fallback mode, not when a deployment is inconvenient. It is not running: the
request bridge and the web service are stopped and disabled, and re-enabling them is an
owner-side operation.

A Boss GPT must never decide on its own to use both paths at the same time.

---

## 10. The READY handoff — and the merge boundary

When a deployment is verified, Forge publishes a READY document through its normal result channel.
The boundary travels inside that artifact, so it does not depend on anyone reading this file:

```text
GO_FORGE_READY = YES
TARGET_PR = #<n>
FORGE_MERGE_ACTION = NONE
OWNER_ACTION = Review product/business functionality; if acceptable, merge PR #<n> yourself.
```

Read that literally. **READY is not a handover of the merge.** Forge never merges a candidate PR,
never comments on one, never closes one, and never advances any baseline declaration or a branch
head. Those actions
are refused in Forge's tool layer — they are not merely discouraged in a prompt. If you are the
owner: review the product and business behaviour yourself, and merge it yourself if you are
satisfied.

---

## 11. Current state recorded by the 2026-10-08 closeout

Recorded so a fresh reader does not have to reconstruct it:

| Fact | Value |
|---|---|
| Primary operator | GO Forge, `forge-worker.service`, resident on the Command Center host as user `go-forge` |
| Operator prompt version | `GO_FORGE_OPERATOR_PROMPT_V6` |
| Operator source | `chenzhenxi1-sudo/go-control-tasks`, `main`. The installed bytes were promoted to canonical `main` on 2026-10-08 by merging the `forge-operator-candidate-identity-closure-20261007` line (PR #145, 11 commits, head `36bc636`), because the installed operator *was* that head |
| HK sealed executor | `/usr/local/libexec/go-hk-deployctl` — `verify | canary | deploy | rollback`; accepts `--task-authority GO-FORGE` |
| Repository runtime pointer | **retired and deleted on 2026-10-08** (`docs/canonical-baseline/CURRENT_HK_RUNTIME.json`). No replacement pointer exists; the live runtime identity comes from the newest signed VERIFY Evidence |
| Old Command Center | not running: request bridge and web service stopped + disabled on 2026-10-08; its periodic liveness / state / registration timers were retired earlier the same day; source retained as break-glass history |
| HK Agent polling timer | retired on 2026-10-08 — Forge reaches HK directly over SSH, it never waited for a bus poll |
| Migration graph input | declared to the HK installer by the operator (`GO_MIGRATION_HEAD`); it used to be copied out of the retired repository pointer |
| Live check performed | one non-mutating `FORGE_INSPECT` on 2026-10-08 -> `result = PASS`, no runtime change, Evidence published, WeCom delivered |
| Answer returned | **the actual runtime matched the authorised candidate** — all eight business services on the candidate's artifact image |

The authoritative, always-current copy of the Boss-facing usage lives **with the operator**, in
`chenzhenxi1-sudo/go-control-tasks` -> `GO_FORGE_BOSS_USAGE.md`. That file is the source of truth for
the request contract; this document places the same contract in the repository the Boss reads, and
adds the 2026-10-08 closeout state.
