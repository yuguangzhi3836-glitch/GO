# GO Runtime Host · Per-Pass Read Snapshot (2026-10-01)

This document records a bounded I/O optimisation of the Management Agent polling
pass. It changes clone counts only; no task, Evidence, registry or registration
semantics change.

---

## 1. Observed problem

`flow.poll_once()` read the remote stores once per operation:

```
tasks.keys()                 -> one clone of the tasks repository
tasks.read(key)              -> one clone of the tasks repository (per task)
evidence.read(dest)          -> one clone of the evidence repository
evidence.read(dest) again    -> one clone of the evidence repository
```

For the retained completed E2E probe this made a single Agent pass take roughly
60–90 s against `tick_seconds=30`. Passes are serial, so there was no backlog —
the cost was pure repeated cloning.

## 2. Change

`git_transport.GitTransport` gains one read-only facility:

```python
with transport.snapshot() as view:
    view.keys()
    view.read(key)
```

`snapshot()` creates one temporary directory, clones the configured repository
exactly once, and yields a read-only view bound to that clone. The temporary
directory is removed when the block exits.

The view keeps every existing rule: `path()` validation, the
`runtime-host-v1/` prefix, the correct kind namespace, `100644 blob` object mode,
the 16384-byte object ceiling, no path escape and no symlink trust. It exposes
`keys()` and `read()` only — no `create()`, no push, no remote/branch input.

`read()` and `keys()` are refactored onto shared helpers (`read_path`, `keys_in`)
so the snapshot and the ordinary calls cannot drift apart. `create()` is
unchanged and still clones and pushes exactly as before.

`flow.poll_once()` now runs one pass inside one task snapshot and one evidence
snapshot. `flow.read_snapshot()` falls back to the transport itself
(`contextlib.nullcontext`) when it has no `snapshot()`, so the in-memory test
transports keep working unchanged.

The redundant second evidence read is removed **only** for the case where the
remote object was already read inside the snapshot and matched byte for byte. A
newly written Evidence object still gets its mandatory fresh post-write readback.

## 3. Clone counts

Per pass, steady state with the retained completed probe:

| repository | before | after |
|---|---|---|
| tasks | 2+ clones (one per `keys()`/`read()`) | **1** |
| evidence | 2+ clones (one per `read()`) | **1** |

Zero tasks: tasks 1, evidence 0.

A new task with no Evidence yet: tasks 1, evidence 1, plus the unchanged
`create()` + fresh readback on the write path.

`GitTransport` also carries a `clones` counter. It is observability only: nothing
reads it in production code.

## 4. Invariants preserved

- the completed task is still inspected on every pass;
- a rebound task digest is still rejected;
- existing Evidence is still byte-compared;
- conflicting Evidence is still rejected and never overwritten;
- a missing Evidence object still republishes the exact stored receipt bytes;
- a lost write acknowledgement still reuses the stored bytes;
- no task is executed twice;
- no task is deleted;
- no Evidence is regenerated for a completed task.

## 5. Digest

Because `flow.py` and `git_transport.py` are part of the installed Management
Agent bundle, the executor digest changes:

```
OLD_EXECUTOR_SHA256 = 593a01acf4a593e04e5243673dfe33830e1401de2b7dcf5c865c4d20391e7c7b
NEW_EXECUTOR_SHA256 = cdba176afb53533be3cf5d23bebe65edbeda2b1c98b4e5e71b0178525bf8dbf4
```

Six-file bundle, 481-byte manifest, no CR. `adapter.py`, `agent_service.py`,
`channel.py` and `registration_sync.py` are unchanged.

The frozen PR #287 Runtime candidate (`7b9d53ad…`, tree `bd102d9b…`) is unchanged
and is not part of this patch.

## 6. Not changed

No persistent local Git mirror, no cache database, no daemon. No task-expiry or
replay semantic change. No Evidence byte change. No Registry change. No task
schema change. No `Runtime.enqueue()` bridge, no AI Worker, no Boss Request enum
change. `EXTERNAL_TASK_TO_C1_C14_RUNTIME = NOT_IMPLEMENTED` and
`REAL_AI_WORKER = NOT_IMPLEMENTED` remain.
