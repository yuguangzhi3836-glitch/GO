# GO Runtime Host — C1 Real AI Worker V1

Date: 2026-10-01

## Scope

This change adds the first deliberately narrow real model worker on top of the current Runtime Host baseline.

It is stacked on PR #297 at `1e442d5db1a852c0bd263eece87138eec5bfd9ac`.

It does **not** mutate PR #297 and does not replace the existing probe path.

Current probe remains:

```
RUNTIME_PROBE
  -> existing Runtime Supervisor
  -> NoopWorker
```

New path:

```
AI_WORK_V1
  -> go-runtime-worker-c1.service
  -> C1RealAIWorker
  -> OpenAI Responses API
  -> Runtime.complete()
  -> TASK_COMPLETED
```

## Why a separate service

The existing Runtime kernel and NoopWorker have already been validated as the bounded health path. Giving the same process API credentials or outbound network access would expand the failure surface for no benefit.

The new service is separate so that:

- the Runtime kernel remains unchanged;
- `RUNTIME_PROBE` remains claimable only by the current NoopWorker runner;
- the real worker claims only `C1 / AI_WORK_V1`;
- API credentials live only in the worker environment file;
- the real worker can use outbound network without removing `PrivateNetwork=true` from the Runtime kernel;
- worker restart/failure does not terminate the Runtime service.

## V1 task contract

The queue task is intentionally fixed:

```json
{"schema_version":1,"smoke_id":"C1_REAL_AI_WORKER_V1"}
```

There is no externally supplied prompt, URL, command, path, model, C-id or tool.

The worker sends one fixed prompt and accepts success only when the model replies exactly:

```
GO_C1_REAL_AI_WORKER_V1_OK
```

Any schema mismatch, API failure, parse failure or output mismatch completes the Runtime task as failed and opens a human-required escalation.

The smoke task uses `max_attempts=1` and the fixed idempotency key:

```
c1-real-ai-worker-v1:smoke:1
```

so the first live proof cannot silently fan out into repeated paid model calls.

## Credentials / model

No secret is committed to GitHub.

The service reads:

```
/etc/go-runtime-worker-c1.env
```

which must contain:

```
OPENAI_API_KEY=<secret>
GO_C1_OPENAI_MODEL=<explicit API model id>
```

Both values are deployment inputs. The model name is not hard-coded in source.

## Runtime isolation

The frozen Runtime already supports kind-filtered claims:

```python
Runtime.claim("C1", worker_id=..., kinds=("AI_WORK_V1",))
```

The current resident runner uses the topology task-kind set containing only `RUNTIME_PROBE`.

Therefore the two services are disjoint at queue admission:

- Noop runner: `RUNTIME_PROBE`
- real C1 worker: `AI_WORK_V1`

No Runtime schema change is required.

## Network boundary

The Runtime kernel service stays unchanged and keeps its existing network isolation.

Only the new worker has outbound network because a real model API call requires it. The worker opens no listener and receives no caller-controlled URL.

## Rollback

Rollback is stop/remove only:

1. stop and disable `go-runtime-worker-c1.service`;
2. remove its environment file;
3. remove the candidate worker file/unit if desired.

The Runtime database, current NoopWorker path, bridge service, Management Agent and registration channel do not need rollback.

## Live proof required before any broader work

A live E2E is not claimed by this PR alone.

The required first proof is exactly one task:

```
Runtime.enqueue(C1, AI_WORK_V1, fixed smoke payload)
 -> real model call
 -> Runtime.complete()
 -> TASK_COMPLETED
 -> evidence chain still valid
```

After that proof, separately decide whether an external signed action should be allowed to enqueue `AI_WORK_V1`. This PR deliberately does not add such an external action.
