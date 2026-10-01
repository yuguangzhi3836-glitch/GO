# GO Runtime Host — C1 GitHub AI Execution Backend V1

Date: 2026-10-01

## Scope

This change re-architects the C1 real-AI path that an earlier revision of this branch
placed **on the Runtime Host**. It is stacked on PR #297 at
`1e442d5db1a852c0bd263eece87138eec5bfd9ac`.

It does not mutate PR #297, does not replace the existing probe path, and does not
touch HK-STAGING or Production.

## Superseded design (removed by this change)

```
Runtime (rt01)
  -> persistent ECS C1 worker process
  -> OPENAI_API_KEY written to /etc/go-runtime-worker-c1.env on the Runtime Host
  -> OpenAI
```

Removed artifacts:

```
control-plane/runtime-host-channel-v1/c1_real_ai_worker.py
control-plane/runtime-host-channel-v1/systemd/go-runtime-worker-c1.service
control-plane/runtime-host-channel-v1/test_c1_real_ai_worker.py
docs/runtime/GO_RUNTIME_C1_REAL_AI_WORKER_V1_20261001.md
```

## Current design

```
Runtime Host   = durable coordination kernel ONLY
                 queue / task identity / attempts + lease / completion / Evidence
GitHub Actions = ephemeral AI execution backend
OPENAI_API_KEY = repository secret; exists only inside a disposable runner process
```

```
Runtime
  -> C1 AI work request bound to an exact runtime_task_id / attempt
  -> GitHub Actions ephemeral run              (this workflow)
  -> secrets.OPENAI_API_KEY
  -> OpenAI Responses API
  -> sealed result bound to the same execution identity
  -> Runtime receives the result
  -> Runtime.complete()
  -> TASK_COMPLETED
```

The Runtime Host holds **no** model credential and needs **no** outbound model access.

## Why

The Runtime kernel is validated today as a probe-only, credential-free, network-free
coordination path (`RUNTIME_PROBE` -> Supervisor -> `NoopWorker`, local SQLite, no
external network). Giving it an OpenAI credential for the C1 cell would expand its
failure surface and its secret custody for a benefit that the existing C13 / C14
pattern already delivers without it: a fresh AI execution on a disposable
GitHub-hosted runner, using the repository secret that is already in use.

## What this change adds

| Path | Role |
|---|---|
| `.github/workflows/c1-ai-execution-backend-v1.yml` | the ephemeral C1 execution backend (`workflow_dispatch`) |
| `.github/workflows/runtime-host-c1-offline-tests.yml` | offline regression for this directory (no credential) |
| `control-plane/runtime-host-channel-v1/c1_ai_execution_backend.py` | executes exactly one bound task, seals exactly one result |
| `control-plane/runtime-host-channel-v1/test_c1_ai_execution_backend.py` | contract tests incl. credential hygiene and exactly-once |

## Boundaries enforced

- fixed smoke payload `{"schema_version":1,"smoke_id":"C1_REAL_AI_WORKER_V1"}`; the
  payload is a literal in the workflow and is **not** a dispatch input
- fixed model endpoint; the Responses API URL is not a parameter
- no arbitrary prompt, arbitrary URL, arbitrary C id, shell command, or deployment
- `authorizes_any_action` is `false` in every document produced
- the credential is injected only for an explicitly requested live call; the offline
  stub path never receives it, and a result document is refused if it carries it
- `concurrency` serialises one Runtime task, and a terminal result for an identical
  execution identity is reused instead of paying for a second model call

## Not implemented in V1

- the Runtime -> GitHub dispatch leg, and the GitHub -> Runtime result return leg
- C2..C14 execution backends
- any generic worker framework, tool calling, or arbitrary-prompt execution

`RUNTIME_PROBE -> NoopWorker` is unchanged. The Runtime kernel keeps no credential.
