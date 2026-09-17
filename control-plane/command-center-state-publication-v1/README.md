# CC V1-04 - derived Control State publication target

Status: part of `cc/v1-finalization-20260914` (Issue #99, CC V1 order 04).

The projector already turned the control bus into four documents
(`CURRENT_CONTROL_STATE.json`, `CONTROL_STATUS_V1.json`, `TASK_INDEX.json`,
`LATEST_EVIDENCE.json`). What it did not have is a place to put them that a
reader can rely on: the CI run uploaded an artifact that expires, and the
committed `PROJECTION_20260914` directory is a manual copy. This component
defines the target and maintains it.

## The target

```
CURRENT.json                       the pointer - the only entry point a reader follows
runs/<generated_at>_<digest12>/    immutable snapshot, never rewritten after publication
    CURRENT_CONTROL_STATE.json
    CONTROL_STATUS_V1.json
    TASK_INDEX.json
    LATEST_EVIDENCE.json
    PUBLICATION_MANIFEST.json      provenance for that snapshot
INDEX.json                         append-only list of published snapshots
LAST_FAILURE.json                  present only while the most recent attempt failed
```

A reader follows `CURRENT.json`, reads the snapshot it names, and stops. That
path is stable, read-only, and carries a bounded status contract.

## The four states a reader may report

```
CURRENT   a validated snapshot is published and inside the reader's window
STALE     a validated snapshot exists but the pointer is older than the window
FAILED    the most recent attempt failed after the last success
UNKNOWN   nothing has ever been published
```

This is the state of the **publication**, not of the agent or the runtime. The
publisher never re-derives control state and never edits a projection document.

## Why a failed publication cannot masquerade as success

Publication is two-phase, and the order is the guarantee:

1. the projection output is validated (all four documents present, valid, and
   free of machine-specific paths)
2. the snapshot is written to a staging directory and **round-trip verified**
   against its manifest before it becomes visible
3. only then is `CURRENT.json` advanced, atomically, via a temp file and rename

Any failure between those steps leaves `CURRENT.json` byte-identical and records
`LAST_FAILURE.json`. A test asserts exactly that.

## Determinism

`run_id = <generated_at>_<content_digest12>`, where `content_digest` covers the
four projection documents and nothing else. The consequences are tested, not
assumed:

* identical inputs produce an identical run id and an identical manifest
* re-publishing identical content leaves the snapshot untouched and only
  advances `published_at`
* the same run id with **different** content is a failure, never an overwrite
* every read recomputes the document digests and compares them with the
  manifest, so a hand-edited snapshot is detected

## Traceability

Every manifest records the source refs and, where established, the pinned heads
of the tasks, evidence and GO repositories, plus the `projector_revision` that
produced the documents. A publication with no pinned source head, or without a
projector revision, is refused. An unattributed snapshot cannot enter the target.

## Not execution authority

Everything the publisher writes carries `execution_authority: false`, and a test
asserts that no file it authors may contain an authority-shaped key: no
`signature`, no `signed_task`, no `nonce`, no `action_id`, no `parameters`, no
`grants_execution`. The publisher holds no key, signs nothing, invokes nothing,
and references neither the Request channel nor the executor. It is a one-way
copy of what the projector derived.

## Usage

```sh
# validate a projection output and publish it
go-state-publication --target <dir> --now <iso> publish \
    --projection <projector-out> \
    --tasks-ref main --tasks-head <sha40> \
    --evidence-ref permission-test --evidence-head <sha40> \
    --go-ref main --projector-revision <sha40>

# a reader
go-state-publication --target <dir> status
go-state-publication --target <dir> verify

# built-in checks
go-state-publication selftest
```

Global options (`--target`, `--now`, `--max-age-seconds`) precede the
subcommand.

## Files

| Path | Purpose |
|---|---|
| `command-center/go-state-publication` | the publisher (stdlib only) |
| `contracts/state_publication_v1.schema.json` | layout, pointer, manifest, rules, authority boundary |
| `tests/test_state_publication.py` | isolated tests, including against the committed real projection |
| `run_checks.py` | isolated verification; forbids network, subprocess and runtime paths |

## Boundaries and remaining gap

```
HONG_KONG_TOUCHED=NO        CONTROL_PLANE_TOUCHED=NO
DEPLOY_PERFORMED=NO         PRODUCTION_TOUCHED=NO
PRIVATE_KEY_HELD=NO         EXECUTION_AUTHORITY=NO
TARGET_INSTALLED=YES        SCHEDULED_PUBLICATION=YES
```

**The target and the publisher are installed and driven.** On the Command Center
host `go-command-center-state-cycle.timer` (900 s) refreshes the control-bus
checkouts, collects the Request files the bus carries, runs the projector
read-only, and hands the projection to this publisher. The publisher still does
the two-phase write; the schedule only decides when it is asked to. The install
record, before/after hashes, live smoke output and rollback are in
`install/INSTALL.md`.

Two things this install deliberately does not do:

* the target lives on the Command Center host. Mirroring it to a branch, so that a
  remote reader can follow `CURRENT.json`, is a separate decision rather than a
  detail of this publisher;
* `runs/` is append-only by contract and is not pruned. The schedule republishes
  when its sources move and at least hourly, which bounds growth to roughly 24
  snapshots a day. A retention policy is a decision, not something to hide inside
  the publisher.

