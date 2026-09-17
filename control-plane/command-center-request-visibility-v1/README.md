# CC V1-05 — Request visibility: the Bridge's facts on the control bus

Issue: **#100 · CC V1-05｜请求可见性｜将 Bridge Ledger 事实投影到 Control Bus**
Scope stays `CONTROL_STATE_AND_STATUS_ONLY`. This component adds no execution
capability, holds no private key, signs nothing and deploys nothing.

## The gap it closes

A Request is one `requests/<request_id>.json` file a human drops on the control
bus. What the Command Center Bridge then did with it was visible only on the
Command Center host:

| Bridge outcome | Where it lived before |
|---|---|
| accepted, Task signed and published | the durable ledger — **and nowhere else** |
| **refused, with a reason** | printed to the Bridge's stdout, kept in no file at all |
| duplicate `request_id` | a `Reject` raised before anything was written |
| a submission re-presented | the ledger's `already_seen`, never published |

So the projection could only ever report `REQUEST_CREATED`, and the question an
operator most wants answered — *"why did my Request not become a Task?"* — had
no answer on the control bus. `LIFECYCLE_V1.md` recorded exactly that as a
delivery blocker instead of guessing.

This component is the missing half of the pipe. It reads the Bridge's own
records **read-only** and writes one Request fact per Request identity.

## What it reads

| Input | What it is | Written by |
|---|---|---|
| `--ledger` | the Bridge ledger `ledger.json` | the Bridge |
| `--poll-results` | the Bridge's own poll output, journalled | the operator's timer wrapper |
| `--requests-dir` | Request files collected from the control bus | the collector |

The Bridge prints one JSON object per poll and keeps nothing, so the instant that
places its observations in time can only come from the journal wrapper. A
journalled document is:

```json
{"schema_version": "1", "journaled_at": "<ISO8601>",
 "bridge_output": {"bridge_version": "...", "channel_mode": "PERSISTENT",
                   "publish_enabled": true,
                   "results": [{"pr": "42", "head": "<sha>", "status": "rejected",
                                "reason": "pr_head_not_found"}]}}
```

`bridge_output` is **byte-for-byte what the Bridge already prints** — no Bridge
change is required, and none is made here. Redirecting that stdout into a durable
journal is an installation concern, and it has not been done.

## The closed fact vocabulary

```
REQUEST_CREATED          the Bridge's own ledger is non-terminal (claiming,
                         prepared, publishing): spoken, not settled -> the weakest
                         kind, claims no Task, needs no proof
REQUEST_VALIDATED        the Bridge recorded a published Task   -> proof required
REQUEST_REJECTED         the Bridge refused it, reason preserved
REQUEST_DUPLICATE        a distinct submission reused a consumed request_id
REQUEST_REPLAY_REJECTED  a consumed submission identity was presented again
```

`REQUEST_CREATED` is emitted rather than dropped because "the Bridge is still
working on it" is an answer to "why did my Request not become a Task", and
dropping it left an in-flight Request indistinguishable from one the Bridge never
spoke about. It cannot be read as an acceptance: `binding.claimed` and
`binding.proof_required` are false, no Task is named, no reason is claimed, and
the projection ranks it `0`, below every settled fact.

Every fact binds `request_id`, `action_id`, `submission` (pr + head), `source`
(the control-bus ref the Request was read from) and `nonce` when a signed Task
bound one. A submission whose Request identity cannot be established produces
**no fact** — a fact must bind an identity — and is recorded at submission level
in the export index with its reason intact, rather than being silently dropped.

### Reasons are classified, never dropped

The Bridge's own token is copied through verbatim with an `origin` naming which
Bridge record said it:

```
BRIDGE_REJECT_TOKEN    a token from the Bridge's own Reject
BRIDGE_POLL_STATUS     a poll status such as already_seen
BRIDGE_LEDGER_STATE    a terminal ledger state, e.g. dry_run_no_task_published
```

The closed classes and the tokens that map to them live in
`contracts/request_fact_v1.schema.json`, not in the exporter's code. The test
suite extracts **every** refusing token the Bridge can emit from the three Bridge
sources in this repository — 96 of them today — and fails if the contract cannot
classify any one of them. Both call shapes are scanned: `Reject("token")` raised
directly, and the `reason` argument of `exact(...)` / `match(...)`. Scanning only
the first shape under-counts the vocabulary by 15 tokens, which is a blind spot
this gate exists to catch — and did catch. A token nobody has seen yet is carried as
`UNCLASSIFIED_REJECT` with the token intact.

## An acceptance is never taken on faith

`REQUEST_VALIDATED` sets `proof_required = true`. The exporter only forwards the
claim; the consumer must corroborate it, and in `state_projection.py` all of the
following must hold before a Request is reported as validated:

1. the named Task exists on the control bus;
2. its `task_id` carries `sha256(request_id)[:12]`, the digest the Bridge derives
   the identity from — so a Task from another Request can never be borrowed;
3. the claimed `task_sha256` is the digest of the Task as the bus stores it;
4. the Task's own signature verifies; and
5. the verifier that checked it is **bound** to the published Command Center task
   identity, because a key that merely loads is not the right key.

Any failure keeps the Request at `REQUEST_CREATED`, reports the claim and why it
failed in `requests[].binding`, and records a `REQUEST_BINDING_UNPROVEN` anomaly.
It never leaves `REQUEST_VALIDATED`. A forged fact therefore cannot fabricate an
acceptance: forging a positive fact needs the Task signing key.

## Duplicate and replay are separate kinds, on purpose

`REQUEST_DUPLICATE` and `REQUEST_REPLAY_REJECTED` are their own lifecycles and
each carries `counted_as_success = false` in the state document. A duplicate can
never be read as an acceptance, and neither can a replay.

## What it is not

```
is_execution_authority=false   grants_execution=false   can_create_task=false
can_sign=false                 holds_private_key=false may_authorize_retry=false
may_authorize_replay=false     may_edit_a_request=false
```

Every file the exporter authors carries the same eight `false` values, and the
projection refuses any fact that claims otherwise. There is no code path from a
fact to an executor. The exporter never writes a ledger, never signs, and never
opens the ledger for writing.

## One immutable fact per semantic identity

A fact's identity is its **semantics**, not the moment it was looked at:

```
semantic identity = the Request identity + the normalized outcome
                  + the normalized reason + the normalized binding result

excluded from it  = first_observed_at, time_source, and the submission the
                    observation happened to be keyed by
```

`fact_id` covers the body except `first_observed_at` and `time_source`;
`semantic_id` is inside it. Everything is **aggregated before anything is
minted**: every observation is loaded, normalized, grouped by semantic identity,
and then exactly one immutable fact is written per identity, carrying
`MIN(first_observed_at)` over its group. The result does not depend on poll file
order, filesystem order, journal order, or how many times the exporter ran.

```text
same outcome at T1, T2, T3   ->  ONE fact, first_observed_at = T1
timestamp-only change        ->  NO new fact, and not one changed byte
outcome changed              ->  exactly one new fact, the earlier one kept
same id, different bytes     ->  REFUSED (fact_id_collision), never overwritten
```

This replaces a rule under which a fact was minted per (semantics, observation
instant): an unchanged outcome sitting at a new instant produced a new immutable
fact on every poll, so the store and the Git history grew with **observations**
instead of with **outcomes** -- 36 fact files for 18 submissions, measured.

`first_seen_at`, `first_seen_time_source`, `last_seen_at`, `observation_count` and
`observed_instants` live in a **local, non-authoritative observation ledger**
written outside the export root (`--observations`, defaulting to a sibling of
`--out`). It exists because the poll journal is pruned: when the document a
semantics was first observed in falls off the end, the earliest known instant has
to come from somewhere, or the immutable fact would have to move. None of it is
published and none of it can reach a fact id. Facts written by the earlier rule are
still on the bus and are still read -- the projection folds them into the same
identity.

## Usage

```sh
# export (read-only), reproducibly
python control-plane/command-center-request-visibility-v1/command-center/go-request-fact-export \
  export --ledger /var/lib/go-command-center/boss-request-bridge-v1/ledger.json \
         --poll-results <journalled-bridge-output.json> \
         --requests-dir <collected-requests> \
         --out <export-root> --now <ISO8601> \
         --observations <local-ledger.json>      # defaults to a sibling of --out

# the exporter's own rules
python control-plane/command-center-request-visibility-v1/command-center/go-request-fact-export selftest

# isolated verification, writes summary.json
python control-plane/command-center-request-visibility-v1/run_checks.py <outdir>
```

Then the projection consumes it:

```sh
python control-plane/command-center-state-v1/state_projection.py ... \
  --request-facts-dir <export-root>
```

Re-exporting the same Bridge outcome reproduces the same `fact_id`, so the store
is append-only and idempotent; a hand-edited fact is detected because the
projection recomputes the id over the whole body.

## Installed in two phases

```
PHASE 1  journal the Bridge's own poll output + drive the read-only exporter   INSTALLED
PHASE 2  publish the facts to the control bus                                  INSTALLED
```

Both phases run on the Command Center host.

Phase 1: `go-request-fact-cycle.timer` (300 s, oneshot, root, hardened) captures
the object the Bridge already prints every poll into an append-only journal — only
when that object actually changes — and then runs this exporter over the Bridge
ledger plus that journal. Installed artifacts, before/after hashes, live smoke
output and the rollback procedure are in `install/INSTALL.md`.

Phase 2: `go-command-center-state-cycle.timer` (900 s) re-exports the facts,
publishes the export to branch `request-facts/live` of `go-control-tasks` — the ref
namespace the state contract already declares for facts — and then drives the
projection and the publication target, so the derived state is built from what is
on the control bus rather than from the host that produced it. That install's
record and evidence are in
`../command-center-state-publication-v1/install/INSTALL.md`.

Two defects were found by installing rather than by reading:

* journalling unconditionally placed an unchanged observation at a new instant
  every cycle and minted a fresh fact per submission per cycle — 2 cycles
  produced 36 fact files for 18 facts. Journal capture is now on change only;
* publishing on "the index file differs" would have committed to the bus on every
  cycle, because the exporter stamps `INDEX.json` with the instant of the run. The
  publication gate is a digest over the facts plus the index with that one instant
  field removed, so three consecutive cycles leave the branch at the same commit.

A third thing only installing could show: a fact alone does not put a Request on
the bus. Projected without the Request files, every Request read `UNKNOWN` and the
projection recorded 18 `REQUEST_FACT_WITHOUT_REQUEST` anomalies. Collecting the
Request files the bus carries on its `boss-request-*` branches took the anomalies
19 → 7 and produced real lifecycles —
`REQUEST_VALIDATED 13 / REQUEST_CREATED 1 / UNKNOWN 4`.

`run_checks.py` reports `installed = PHASE_1_AND_2`, `installed_publish_side = YES`.

