# Runtime Issue Ingress — source binding (candidate, 2026-10-04)

## What this closes

The formal Issue ingress would have admitted ten open issues that are no longer work.

On 2026-10-04, `main` was `e4076276d70058d16f68fda5db047161ca6ef4cc`. These open owner
issues each carried `Canonical source: \`main 8ffcde66d36c1bbf849218529ef015f6e81725af\``:

| #79 | #80 | #81 | #82 | #83 | #84 | #85 | #86 | #87 | #88 |
|---|---|---|---|---|---|---|---|---|---|
| C01 | C02 | C03 | C04 | C05 | C08 | C09 | C10 | C11 | C12 |

Each one was still open, still well formed, and still parsed into a valid
`GHAW_BUILDER_V1` work order for a cell the Builder serves. Measured with the shipped
ingress and the live bodies: **`WOULD_ENQUEUE = 10`**. None of them is today's queue -
their threads have moved on to R4/R5/R6 successors - so an unattended scanner would have
started ten paid engineering executions against a tree none of them was written for.

That is the whole failure this candidate closes. **Not one of those issues was edited,
relabelled or closed.** They are historical Evidence and they stay exactly as they are;
the ingress simply stops agreeing that an old task is work.

## The two gates

### Layer 1 — admission (`c1_issue_ingress.plan_ingress` / `ingest`)

An issue states the source it was written against, and the parser already read it
(`source_anchor`). What was missing is the comparison. Admission now compares it with the
CURRENT head of the default branch and refuses anything else with a stable reason:

```
INGRESS_SOURCE_ANCHOR_NOT_CURRENT
```

`current_source_anchor` is a **required keyword argument with no default** on both entry
points. That is the design, not an accident: an optional parameter with a `None` default
would be a gate a live caller could step over by forgetting an argument, which is exactly
the failure mode this exists to prevent. Omitting it is a `TypeError`; passing something
that is not a canonical 40-hex commit id is `INGRESS_CURRENT_SOURCE_ANCHOR_INVALID`.

The refusal is a `SourceAnchorNotCurrent(Refused)` carrying `issue_number`,
`parsed_source_anchor` and `current_source_anchor`, so a shadow poll line shows *why* a
backlog is stale rather than only that it is.

**Strict equality only.** No ancestry, no tree equivalence, no PR-lineage inference, no
"close enough". The Builder is dispatched with `ref = main`, so the source a task will be
executed on is the current main and nothing else. A relaxation would admit a task whose
execution source is not the source it was written against.

### Layer 2 — pre-agent (`c1-gh-aw-builder-v1.md`)

Layer 1 cannot see the future. A task admitted at T0 against `A` can be dispatched at T3
after main has become `B`, and then it would run on `B` while claiming to be about `A`.
The workflow therefore re-checks the same equality against **GitHub's own record of what
the run is executing**:

```
payload.source_anchor  ==  ${{ github.sha }}      else  SOURCE_ANCHOR_DOES_NOT_MATCH_WORKFLOW_SHA
```

`github.sha` is a context, **not an input**: the authority is the platform's record of the
run, not a claim a dispatch could make. The check sits in the pre-agent `steps:` block, so
a mismatch stops the run **before the agent starts** - `paid AI = 0`, `Draft PR = 0`.

## One poll, one source snapshot

The consumer's poll reads the default branch head **once**, before it reads the tracker,
and admits every candidate in that poll against that one value. One extra GET per issue
would make the poll N+1; more importantly, two issues in one tick judged against two
different mains would mean the reported plan describes no single state of the repository.

If that read does not succeed - HTTP failure, transport failure, a body that is not JSON,
not an object, or without a canonical `sha` - the poll reports `SOURCE_HEAD_LOOKUP_FAILED`
and does nothing else: nothing planned, **no Runtime constructed**, nothing enqueued. There
is no fallback to a remembered main, a local checkout, or the issue's own claim.

Both GitHub paths are `GET`, and only `GET`
(`/repos/<repo>/issues`, `/repos/<repo>/commits/main`).

## Measured against the live backlog (read-only, candidate code)

Real issue bodies from the API, planned by this candidate with the live `main` as current:

```
live main = e4076276d70058d16f68fda5db047161ca6ef4cc
open issues 43 ; candidates by the pre-filter 24

#79..#88  REFUSED  INGRESS_SOURCE_ANCHOR_NOT_CURRENT
#95       REFUSED  INGRESS_SOURCE_ANCHOR_NOT_FOUND
#146, #351..#362  REFUSED  ISSUE_TITLE_TASK_ID_NOT_FOUND

WOULD_ENQUEUE_UNDER_THE_CANDIDATE = 0
```

The ten historical tasks that the shipped ingress would plan are refused as stale. This is
what the candidate *would* do - it is not installed, the ingress is not enabled, and no
live shadow run is claimed.

## What is deliberately unchanged

* **Task identity.** `(kind, cell, external_task_id)` still derives the idempotency key, and
  the payload the contract sees is unchanged apart from the anchor the issue itself
  supplied. Source freshness is an admission gate, not an identity redesign. The C1 golden
  identities, the run-name identity and the legacy Responses identity are all pinned by
  the existing tests and still hold.
* **De-duplication.** Still the Runtime's `UNIQUE(idempotency_key)`, and nothing else. No
  local seen-store was added.
* **The parser.** `parse_c01_issue()` still reads a historical issue perfectly well, anchor
  included. Teaching it to disown old issues would lose the ability to say why one is old.
* **Authority.** The compiled workflow's permission surface is byte-identical to the one
  merged in #387/#389: the agent job stays read-only; `merge_pull_request`, `auto_merge`,
  `push_to_pull_request_branch` and `create_or_update_secret` still do not appear at all.
* **C13/C14.** Still excluded at every layer; `control-plane/c13-c14-lite/**` untouched.
* **U6.** Still `enabled=false`, `decision=PASS`, `reason=GATE_DISABLED`, `reviewed=false`,
  `model_called=false`, `calls=0`. No checker was written and no model was configured.

## Verification

Offline, WSL `Ubuntu-24.04`, root, ext4 extraction, `PYTHONDONTWRITEBYTECODE=1`:
`Ran 471 tests OK` (444 before this candidate).

Five mutations, each disabling one new guard, each expected to turn its own test red:

| | mutation | verdict |
|---|---|---|
| M1 | ingress stops comparing the issue anchor with the current source | CAUGHT |
| M2 | a failed source read falls back to a remembered main | CAUGHT |
| M3 | workflow stops comparing the payload source with its execution SHA | CAUGHT |
| M4 | workflow accepts any well-formed anchor instead of the exact SHA | CAUGHT |
| M5 | the reader stops validating the sha it was handed | CAUGHT |

`CAUGHT=5  MISSED=0  INVALID=0`.
