# GO Runtime Host — C1 GitHub AI Execution Backend V1

Date: 2026-10-01

Stacked on PR #297 at `1e442d5db1a852c0bd263eece87138eec5bfd9ac`.

## Scope

This change re-architects the C1 real-AI path that an earlier revision of this branch
placed **on the Runtime Host**, and implements the whole direct-dispatch loop:

```
Runtime task
  -> Runtime/Agent forms a fixed dispatch request      (c1_execution_contract.py)
  -> durable intent, one dispatch at most              (c1_dispatch_outbox.py)
  -> GitHub workflow_dispatch                          (c1_github_actions_client.py)
  -> C1 GitHub-hosted ephemeral AI execution           (.github/workflows/c1-ai-execution-backend-v1.yml)
  -> fixed, identity-bound sealed result
  -> artifact whose name is the execution identity
  -> rt01 Agent pulls and validates it                 (c1_result_pull.py)
  -> Runtime.complete()  ->  TASK_COMPLETED
```

No GitHub MCP Server, no gh-aw, no self-hosted runner, no ECS AI worker, no new AI
execution framework. It does not mutate PR #297, does not replace the probe path, and
does not touch HK-STAGING or Production.

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

| Path | Role | Runs where |
|---|---|---|
| `.github/workflows/c1-ai-execution-backend-v1.yml` | the ephemeral C1 execution backend (`workflow_dispatch`) | GitHub |
| `.github/workflows/runtime-host-c1-offline-tests.yml` | offline regression for this directory, no credential | GitHub |
| `c1_execution_contract.py` | one definition of the dispatch and result identities, imported by both sides; fixed topology constants | both |
| `c1_dispatch_outbox.py` | durable exactly-once state machine; no network, no credential | Runtime Host |
| `c1_github_actions_client.py` | the only Runtime-side GitHub REST client: dispatch, run lookup, run read, artifact pull | Runtime Host |
| `c1_result_pull.py` | pulls, validates and completes; never touches the Runtime DB directly | Runtime Host |
| `c1_ai_execution_backend.py` | executes one bound task in the runner and seals one result | GitHub |
| `test_c1_execution_contract.py`, `test_c1_dispatch_outbox.py`, `test_c1_github_actions_client.py`, `test_c1_result_pull.py`, `test_c1_secret_boundary.py`, `test_c1_ai_execution_backend.py` | offline tests | — |

## Execution identity

The Runtime contributes only `runtime_task_id` and `attempt`. Everything else — owner
cell, task kind, payload, provider, endpoint, repository, workflow file, git ref — is
fixed configuration. The identity is derived, never chosen:

```
execution_request_id = sha256(canonical(task binding))
```

where the task binding is `{schema_version, kind, owner_c, task_kind, smoke_id,
payload, idempotency_key, runtime_task_id, attempt, provider, prompt_sha256}`. This is
a superset of the required `(runtime_task_id, attempt, owner_c, kind,
fixed_schema_version)` tuple, so the required properties hold:

- same `runtime_task_id` + same `attempt` → the same `execution_request_id`, always,
  on both sides (the executor recomputes it and refuses a dispatch that disagrees);
- a different `attempt` → a different `execution_request_id`.

The workflow's `run-name` **is** that identity, which is what makes an unknown dispatch
outcome resolvable by lookup rather than by a second POST.

## Dispatch contract

Fixed configuration: repository, workflow file (`main` ref), owner cell `C1`, kind
`AI_WORK_V1`, payload `{"schema_version":1,"smoke_id":"C1_REAL_AI_WORKER_V1"}`,
provider `OPENAI_RESPONSES_API`, endpoint `https://api.openai.com/v1/responses`.

The dispatch inputs are exactly the identity triple. The workflow declares **no other
input** — not a prompt, not a model, not an endpoint, not a ref, not a C id.

The live/stub choice is **not an input** either: it is repo-controlled configuration
(`vars.C1_AI_LIVE_ENABLED`), and it defaults to the offline stub. A dispatch sent by
the Runtime therefore cannot turn a paid model call on.

## Exactly-once

The failure this exists for: the Runtime, the Agent, the network or the GitHub API
loses track of a dispatch that may or may not have started, and a naive retry buys a
second real model call.

- the intent is committed durably **before** anything is sent;
- a stored dispatch counter refuses a second dispatch for the same
  `execution_request_id` — `SECOND_DISPATCH_FORBIDDEN`;
- an ambiguous outcome (timeout, or a `204` with no run id) is recorded as ambiguous
  and resolved by **lookup on the deterministic run name — never by a second POST**;
- a terminal result is immutable: identical bytes are idempotent, different bytes
  raise `CONFLICTING_RESULT_BYTES`;
- the workflow serialises the same Runtime task with `concurrency`, and copies a
  terminal result forward instead of calling the model again;
- completion hands `expected_attempt` back to `Runtime.complete()`, so the Runtime's
  own lease/attempt fencing stays the authority.

State is the outward vocabulary `CREATED / DISPATCHED / RUNNING / COMPLETED / FAILED`,
projected from the internal states by `DispatchOutbox.dispatch_status()`. Storage is
SQLite only — no Redis, no queue, no new database.

## Result contract

```
version, kind, runtime_task_id, attempt, execution_request_id,
github_run_id, github_run_attempt, provider, model, response_id,
status, output_sha256, output, accepted, reused_terminal_result,
authorizes_any_action            (+ failure_reason only when status = FAILED)
```

(`kind` is `c1-ai-execution-result`. The suggested `C1_AI_EXECUTION_RESULT` spelling was
not adopted: the field set here is a superset of the requested one and the value is
already cell-specific. Recorded as a deliberate deviation.)

`validate_result()` refuses by name on: missing/unexpected fields, wrong kind or
version, wrong task, wrong attempt, wrong `execution_request_id`, unknown status,
`accepted`/`status` disagreement, an output hash that does not recompute, an accepted
result whose output is not the expected smoke string, any result that authorizes an
action, and a failure without a reason.

## Result transport

The run publishes the sealed result as an artifact **whose name is the execution
identity**, and the Runtime pulls it with `Actions: read` only. Three integrity layers,
each in its own place:

1. the **client** checks the downloaded zip against the platform-reported digest;
2. the **puller** checks the extracted bytes against the digest it was handed;
3. `validate_result()` recomputes `output_sha256` from `output`, so a document that
   does not hash to itself cannot complete a task.

The download follows GitHub's `302` to a **presigned URL that rejects an
`Authorization` header**, so the follow-up request is deliberately unauthenticated —
verified by a test that asserts no bearer token is sent to the signed URL.

### On reusing `chenzhenxi1-sudo/go-control-evidence`

Checked, and **not sufficient on its own**:

- the Agent's existing `runtime-host-evidence-write` deploy key is a **read/write** key,
  so the *reading* direction is fine;
- but the **writer** side has no credential: `github.token` inside a
  `yuguangzhi3836-glitch/GO` workflow cannot write to a `chenzhenxi1-sudo` repository.
  Making the Action write there would need a **second, new secret**, i.e. a strictly
  larger credential surface than the artifact path used here.

What is missing, stated precisely and **not** acted on: one credential that lets the
GO workflow write into the evidence repository (a deploy key for that repository stored
as a GO secret, or a fine-grained token with `Contents: write` there).

## The GitHub credential, and why rt01 does not have one yet

Verified against the GitHub REST documentation, not inferred:

| Operation | Fine-grained permission |
|---|---|
| `POST /repos/{owner}/{repo}/actions/workflows/{id}/dispatches` | **Actions: write** |
| `GET /repos/{owner}/{repo}/actions/runs` (find the run) | Actions: read |
| `GET /repos/{owner}/{repo}/actions/runs/{id}` | Actions: read |
| `GET /repos/{owner}/{repo}/actions/runs/{id}/artifacts` | Actions: read |
| `GET /repos/{owner}/{repo}/actions/artifacts/{id}` | Actions: read |
| `GET /repos/{owner}/{repo}/actions/artifacts/{id}/zip` | Actions: read |

**Minimum: one permission — `Actions: Read and write` on `yuguangzhi3836-glitch/GO`**,
plus the mandatory automatic Metadata read. Contents is not required (neither read nor
write); Pull requests, Issues and Administration are not required.

Call-site and configuration interface (implemented, no credential created):

- the token is read through an injected loader; the shipped loader reads
  **`/etc/go-runtime-host/c1-github-token`** (`root:root`, `0600`), path overridable by
  `C1_GITHUB_TOKEN_PATH`;
- `token_from_file()` refuses a file readable by group or other, so a mis-set mode
  fails closed rather than silently working;
- the token is sent only as an `Authorization` header to `api.github.com`, never in a
  URL, never in a result, never in the outbox;
- two operational facts shape the design: a dispatch answers `200` with
  `workflow_run_id` under API version `2026-03-10` but `204` with no body under
  `2022-11-28` (the client accepts either, and a missing run id routes to lookup); and
  `workflow_dispatch` only triggers when the workflow file exists on the **default
  branch**, so this backend cannot be dispatched for real until PR #300 is merged.

## Secret boundary

`OPENAI_API_KEY` never reaches the Runtime side. Asserted, not merely stated:
the credential name appears in exactly one module (the GitHub-side executor), the
Runtime-side modules contain no provider reference at all, the outbox database bytes
never contain the credential or an `Authorization` header, the sealed result has no
field that could carry one, the one line the executor prints is an explicit allowlist
of nine non-sensitive fields, and the artifact step has no credential in its
environment.

## What can be proven before merge, and what cannot

Proven in this branch: the contract and its refusal matrix; the exactly-once model
including a simulated dispatch timeout, an ambiguous outcome and a restart with the
counter intact; the whole GitHub-side path in stub mode with no credential; the
Runtime-side client against a faked transport including the signed-URL rule; the
secret boundary above.

Requires post-merge / a provisioned credential: a **real** `workflow_dispatch` (404
until the file is on `main`), a real run id and artifact pulled by the Agent, and a
real model call (deliberately not run).
