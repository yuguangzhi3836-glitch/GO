# GO Runtime Host — C1 GitHub AI Execution Backend V1

Date: 2026-10-01

Stacked on PR #297 at `1e442d5db1a852c0bd263eece87138eec5bfd9ac`.

## Scope

This change re-architects the C1 real-AI path that an earlier revision of this branch
placed **on the Runtime Host**, and carries it as far as a complete code candidate for
both legs of the loop:

```
Runtime task
  -> Runtime/Agent forms a fixed dispatch request      (c1_execution_contract.py)
  -> durable intent, one dispatch at most              (c1_dispatch_outbox.py)
  -> GitHub workflow_dispatch                          (BLOCKED ON CREDENTIAL, see below)
  -> C1 GitHub-hosted ephemeral AI execution           (.github/workflows/c1-ai-execution-backend-v1.yml)
  -> fixed, identity-bound sealed result
  -> GitHub persists the result                        (artifact, identity in the name)
  -> rt01 Agent pulls it
  -> Runtime.complete()  ->  TASK_COMPLETED
```

It does not mutate PR #297, does not replace the probe path, and does not touch
HK-STAGING or Production.

## Superseded design (removed)

```
- Runtime (rt01) -> persistent ECS C1 worker -> OPENAI_API_KEY on rt01 -> OpenAI
+ Runtime Host   = durable coordination kernel only
+ GitHub Actions = ephemeral AI execution backend
+ OPENAI_API_KEY = repository secret, only inside a disposable runner process
```

Removed artifacts: `c1_real_ai_worker.py`, `systemd/go-runtime-worker-c1.service`,
`test_c1_real_ai_worker.py`, and the document that described them.

## What this change adds

| Path | Role |
|---|---|
| `.github/workflows/c1-ai-execution-backend-v1.yml` | the ephemeral C1 execution backend (`workflow_dispatch`) |
| `.github/workflows/runtime-host-c1-offline-tests.yml` | offline regression for this directory (no credential) |
| `control-plane/runtime-host-channel-v1/c1_execution_contract.py` | the one definition of the dispatch and result identities, imported by both sides |
| `control-plane/runtime-host-channel-v1/c1_dispatch_outbox.py` | durable exactly-once state machine (no network, no credential) |
| `control-plane/runtime-host-channel-v1/c1_ai_execution_backend.py` | executes one bound task in the runner and seals one result |
| `test_c1_execution_contract.py`, `test_c1_dispatch_outbox.py`, `test_c1_ai_execution_backend.py` | offline tests |

## Dispatch contract

Fixed configuration — never a task input: repository, workflow file, git ref, owner
cell, task kind, payload, provider and endpoint.

Carried by the task: `runtime_task_id`, `attempt`.

Derived, never supplied as an independent value:

```
execution_request_id = sha256(canonical(task binding + fixed binding))
```

The dispatch inputs are exactly the identity triple; the workflow's own `run-name` is
that same identity, which is what makes an unknown dispatch outcome resolvable by
lookup instead of by a second POST.

## Exactly-once model

The failure this exists for: the Runtime, the Agent, the network or the GitHub API
loses track of a dispatch that may or may not have started, and a naive retry buys a
second real model call.

- the intent is written durably **before** anything is sent;
- the outbox stores a dispatch counter and refuses a second dispatch for the same
  `execution_request_id` — `SECOND_DISPATCH_FORBIDDEN`;
- an ambiguous outcome is recorded as ambiguous and resolved by **lookup**;
- a terminal result is immutable: identical bytes are idempotent, different bytes
  raise `CONFLICTING_RESULT_BYTES`;
- the workflow additionally serialises the same Runtime task with `concurrency`, and
  copies forward a terminal result instead of calling the model again;
- completion hands `expected_attempt` back to `Runtime.complete()`, so the Runtime's
  own lease/attempt fencing is preserved and never bypassed.

No Redis, no queue, no distributed lock: SQLite outbox + GitHub run identity +
immutable result.

## Result contract

A sealed result is a canonical document with an exact field set:

```
version, kind, runtime_task_id, attempt, execution_request_id,
github_run_id, github_run_attempt, provider, model, response_id,
status, output_sha256, output, accepted, reused_terminal_result,
authorizes_any_action            (+ failure_reason only when status = FAILED)
```

`validate_result()` refuses, by name: missing or unexpected fields, wrong kind or
version, wrong task, wrong attempt, wrong execution_request_id, unknown status,
`accepted`/`status` disagreement, an output hash that does not recompute to the
output, an accepted result whose output is not the expected smoke string, a result
that authorizes any action, and a failure without a reason.

## Result transport

Chosen for **minimum credential**: the run publishes the sealed result as an artifact
whose **name is the execution identity**, and the Agent pulls it with `Actions: read`
only. The artifact carries a platform digest, which makes it verifiable without
trusting the transfer.

The alternative of having the Action write into `chenzhenxi1-sudo/go-control-evidence`
was checked and rejected for this round:

- the direction of the Agent's existing `runtime-host-evidence-write` key is fine for
  **reading** (a read/write deploy key pulls as well as pushes);
- but the **writer** side has no credential at all — `github.token` in a
  `yuguangzhi3836-glitch/GO` workflow cannot write to a `chenzhenxi1-sudo` repository,
  so the Action would need a second, new secret. That is out of scope for this round
  and would be a strictly larger credential surface than the artifact path.

Known limitation: artifacts expire (90 days here). A permanent record is a later,
separately-authorized step; the artifact is the right shape for a first loop.

## Minimum GitHub credential for rt01

Verified against the GitHub REST documentation, not inferred:

| Operation | Fine-grained permission |
|---|---|
| `POST /repos/{owner}/{repo}/actions/workflows/{id}/dispatches` | **Actions: write** |
| `GET /repos/{owner}/{repo}/actions/runs` (find the run) | Actions: read |
| `GET /repos/{owner}/{repo}/actions/runs/{id}` (run identity) | Actions: read |
| `GET /repos/{owner}/{repo}/actions/runs/{id}/artifacts` | Actions: read |
| `GET /repos/{owner}/{repo}/actions/artifacts/{id}` | Actions: read |
| `GET /repos/{owner}/{repo}/actions/artifacts/{id}/zip` | Actions: read |

So the minimum is a single permission — **`Actions: Read and write`** on
`yuguangzhi3836-glitch/GO` — plus the mandatory automatic Metadata read. **Contents is
not required** (neither read nor write), and Pull requests, Issues and Administration
are not required at all.

Two operational facts that shape the design:

- `POST .../dispatches` returns **`200` with `workflow_run_id`, `run_url`, `html_url`**
  under API version `2026-03-10`, but **`204` with no body** under the older
  `2022-11-28`. The outbox therefore never depends on the body: a dispatch with no run
  id is recorded as ambiguous and resolved by the deterministic run name.
- `workflow_dispatch` only triggers when the workflow file exists on the **default
  branch**. Until PR #300 is merged, this backend cannot be dispatched for real.

## Credential boundary

rt01 will eventually hold exactly one thing: the minimal GitHub credential above.
It must never hold `OPENAI_API_KEY`, `GO_C1_OPENAI_MODEL`, or a copy of any C13/C14 AI
secret. This round creates no credential of any kind.

## What can be proven before merge, and what cannot

Provable now (and proven in this branch):

- the contract: determinism, identity binding, closed dispatch inputs, result
  validation matrix, conflicting-bytes refusal, stale-attempt refusal;
- the exactly-once model end to end, including a simulated dispatch timeout and an
  ambiguous outcome, with the dispatch counter surviving a restart;
- the execution backend itself, end to end, in stub mode, with no credential;
- the workflow contract: dispatch-only trigger, GitHub-hosted runner, one secret, the
  identity triple as the only task inputs, a repo-side model constant, and no route
  back into the Runtime Host.

Requires post-merge / provisioned credential:

- a **real** `workflow_dispatch` against the backend (404 until the file is on `main`);
- a real run id returned by the dispatch and a real artifact pulled by the Agent;
- a real model call (deliberately not run in this round).

`RUNTIME_PROBE -> NoopWorker` is unchanged. The Runtime kernel keeps no credential.
