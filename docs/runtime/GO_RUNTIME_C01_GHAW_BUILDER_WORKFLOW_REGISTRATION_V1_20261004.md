# GO Runtime C01 — gh-aw Builder workflow registration and transport target (U1)

> Status: **candidate (stacked Draft PR)**. Date: 2026-10-04.
> Base: `chenzhenxi/runtime-c01-ghaw-u3-u10-20261004` @
> `9fb6cd8a4e275b7c78fb10804ff7a20e1d0d7d0f` (PR #381), itself on `main` @
> `ca1e5f8eeae397e96e6c97972b76c291960c60b3`.
>
> This document records one gap, the fix, and what was deliberately not done. It is not
> Evidence, not Authority, and not a current-state pointer. It grants no execution right
> and describes nothing that has been deployed.

## 1. The gap #381 could not close

#381 gave the gh-aw Builder its own task kind (`GHAW_BUILDER_V1`), its own outbox and its
own worker identity, and the contract began recording, on every gh-aw request, the
workflow file that class is aimed at:

```
GHAW_BUILDER_V1 -> build_dispatch_request() -> request.workflow_file
                                                 = c1-gh-aw-builder-v1.lock.yml
```

But the transport did not read it:

```
GitHubActionsClient.dispatch_workflow()
    self._call("POST", DISPATCH_ENDPOINT, payload)
DISPATCH_ENDPOINT = .../actions/workflows/c1-ai-execution-backend-v1.yml/dispatches
```

So a `GHAW_BUILDER_V1` task recorded the gh-aw Builder and was sent to the Responses
backend. That is not a cosmetic mismatch:

```
REAL_FAILURE_PREVENTED
  a GHAW_BUILDER_V1 task that records the gh-aw Builder target
  -> is dispatched to the Responses-API workflow
  -> the wrong executor receives Builder work
  -> a real dispatch, a real run, and for a paid class a real bill,
     for a task another executor owns
```

It is the same class of defect the whole executor/outbox boundary exists to prevent, one
layer further out: not "which worker claims it" but "which workflow the worker's dispatch
lands on". And it could not be caught by re-hashing, because `repo` / `workflow_file` /
`ref` are added to a request **after** `execution_request_id` is computed - they are
transport configuration, not identity.

## 2. The fix

### 2.1 The workflow target is executor configuration

`GitHubActionsClient` now takes `workflow_file` and `ref` at construction and derives its
dispatch endpoint from them:

| executor | bound workflow file | dispatches to |
|---|---|---|
| Responses-API executor | `c1-ai-execution-backend-v1.yml` | `.../c1-ai-execution-backend-v1.yml/dispatches` |
| gh-aw Builder executor | `c1-gh-aw-builder-v1.lock.yml` | `.../c1-gh-aw-builder-v1.lock.yml/dispatches` |

Both default to the channel's original values, so every existing construction of the
client - and the deployed Responses worker, which passes nothing - keeps the behaviour it
was proven with. The gh-aw worker states its own in one line
(`c1_ghaw_builder_worker.WORKFLOW_FILE`), and that value is part of the executor boundary
alongside its kind set, its outbox path and its worker id.

### 2.2 A mismatch fails closed, before anything is sent

`assert_bound_target()` runs as the first statement of the only method that POSTs:

```
request.workflow_file != this client's bound workflow_file  -> Refused(...)
request.ref          != this client's bound ref             -> Refused(...)
request.repo         != the one repository                  -> Refused(...)
```

Nothing is repaired and neither value is preferred. A mismatch can only mean the client
belongs to a different executor than the task does, and the test asserts the stronger
half of that: the transport records **zero** calls and the outbox row stays at
`INTENT` / `dispatches_sent = 0`. A refusal that had already sent something would not be
a refusal.

The three fields are still written by the contract, never by a caller, so this is a
check on wiring rather than input validation - which is exactly why it belongs at the
transport and not in the contract.

### 2.3 What deliberately did NOT change

* **One repo-level runs endpoint.** Runs and artifacts are repository-level, and the
  deterministic run name plus the execution-identity-named artifact already find the
  right execution from it. Partitioning the polling client per workflow would be a second
  mechanism for a problem that does not exist.
* **No registry, no router, no dispatcher service.** The target is one value on each
  executor, exactly like its kind set.
* **The Runtime completion path is untouched.** The workflow seals the same
  `c1_result.json` artifact the Responses executor seals, so the existing
  pull → validate → `Runtime.complete()` leg adopts it unchanged. No second result
  system, no receipt, no evidence layer.

## 3. The registered workflow

`c1-gh-aw-builder-v1.md` (source) and `c1-gh-aw-builder-v1.lock.yml` (compiled,
gh-aw v0.89.21, `strict: true`, codex engine) are added together. `.gitattributes`
carrying the compiler's own `linguist-generated` line is committed with them so the tree
stays clean after a recompile.

**Dispatch-only.** The only trigger is `workflow_dispatch`. The usual way to make a
non-default-branch workflow dispatchable early is an automatic trigger plus a step that
skips the agent; this workflow deliberately does not do that, because an automatic trigger
on a shared branch fires for reasons nobody chose, and release-acceptance-grade
bookkeeping (`[aw] Detection Runs`, U4) is exactly what that produces. Registration is
therefore a consequence of this file reaching the default branch - not the merge, and
nothing else. Until then a dispatch is a 404 and costs nothing.

**Inputs** are the contract's own real-dispatch set: `runtime_task_id`, `attempt`,
`execution_request_id`, `task_kind`, `task_payload`.

**Two fail-closed gates**, both of which refuse any kind but `GHAW_BUILDER_V1`:

* a pre-agent step that accepts the work order, verifies the payload's shape and cell,
  and materialises it as `c1_builder_task.json` for the agent to read. The markdown body
  is runtime-imported into the prompt verbatim and therefore cannot carry a per-task
  payload itself - which is why the work order travels as a file.
* a `post-steps` seal that reads the agent's `ghaw_builder_answer.txt`, refuses an empty
  answer, and writes `c1_result.json` bound to the identity triple with
  `provider = GITHUB_AGENTIC_WORKFLOWS`, uploaded as
  `c1-ai-execution-result-<execution_request_id>`.

**Capability surface: read-only.** The agent gets `edit` and nothing else - `bash: false`,
`cli-proxy: false`. The compiled workflow's only write permission anywhere is
`issues: write` on gh-aw's own conclusion and safe-outputs jobs; there is no
`contents: write`, no `pull-requests: write`, and no `create-pull-request`. The
Draft-PR capability Phase 1B proved is **not** enabled here: opening pull requests on the
repository is a policy decision (which branches, under whose authority) that belongs with
the first real Builder run, not with its registration.

## 4. What this round does not do

* **No dispatch.** `workflow_dispatch = NO`; nothing was sent to GitHub.
* **No AI execution.** `real AI call = NO`. The only processes spawned are the workflow's
  own embedded gate and seal scripts, run offline against fixtures.
* **No installation.** The systemd unit candidate
  (`systemd/go-runtime-host-ghaw-builder-worker.service`) reuses #381's four boundary
  values and the existing credential path; `ADD UNIT FILE ≠ INSTALL UNIT`, and no host was
  mutated.
* U4, U5, U6, U7, U8, U9 remain open and untouched.

## 5. Verification

Local, WSL `Ubuntu-24.04` as root on an ext4 extraction of the candidate tree:

```
python -m unittest discover -s control-plane/runtime-host-channel-v1 -p 'test_*.py'
Ran 358 tests   OK          (328 on the #381 head; +30 in test_c1_ghaw_registration)
```

The 30 new cases cover A transport isolation (both directions, asserted on the URL the
transport actually recorded), B target mismatch refused before any send with the outbox
row untouched, C the declared target existing and the lock's inputs / run name / artifact
name agreeing with the contract, D the workflow's gates **executed** offline rather than
read - including a sealed result accepted by the Runtime's own `validate_result`, and the
same bytes refused as a smoke result, E the Responses identities frozen to their recorded
values, F no automatic trigger, no write capability, no shell and no real connection.

**Mutation check.** Eight guards disabled one at a time, each required to turn its test
red: 8 mutations, 8 caught, 0 missed, 0 invalid. (M7 was missed on the first pass: the
test asserted the artifact name in the compiled file only, so editing the source without
recompiling went unnoticed. The test now asserts both, which is what closed it.)
