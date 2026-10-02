# GO Runtime Host — C01 Issue Consumer V1 (candidate, disabled by default)

Date: 2026-10-02
Base: `main` at `dd54b030351561ebbdfdf8528de4c5f7efa665d0`
Code: `control-plane/runtime-host-channel-v1/c1_issue_consumer.py`
Unit: `control-plane/runtime-host-channel-v1/systemd/go-runtime-host-c01-issue-consumer.service`
Tests: `control-plane/runtime-host-channel-v1/test_c1_issue_consumer.py`

## What this adds

```
GitHub open C01 issue -> consumer -> c1_issue_ingress -> Runtime.enqueue(AI_TASK_V1)
```

`c1_issue_ingress` (merged in #327) already owns the parser, the payload schema and the
idempotency key. This module owns none of that. It fetches open issues, decides which
ones are worth handing to the ingress, calls the ingress, and reports what happened.

## GitHub access is read-only, and only that

`GitHubIssuesReader` issues exactly one kind of request:

```
GET /repos/yuguangzhi3836-glitch/GO/issues?state=open&per_page=100&page=N&sort=created&direction=desc
```

No other verb and no other path exists in the file, and the test suite asserts that as
text: no `POST` / `PATCH` / `PUT` / `DELETE`, no `/comments`, no labels, no assignees.
A listing that exceeds the page bound is visible rather than silent - the result carries
`listed` and `pages_fetched`.

The credential is read through `c1_github_actions_client.token_from_file`, i.e. the same
loader the worker uses, so "single owner, mode 0600, not group- or other-readable" has
exactly one implementation rather than two that can drift. The token travels in an
`Authorization` header and never in the URL; a listing failure reports only the HTTP
status, never the response body.

## No local state, on purpose

The consumer keeps **no record of what it has already seen**. Idempotency is the
Runtime's: the ingress derives `idempotency_key` from `(cell, external_task_id)` and the
kernel's UNIQUE constraint turns a repeat into "here is the task id you already have".
Re-polling is therefore the mechanism, not a hazard.

A local "seen" store would be a second source of truth that can drift, go stale or be
lost on restart - precisely the kind of duplicate the project's own proportionality
principle says not to add. The price is one `enqueue` call per open C01 issue per poll,
which the kernel answers without creating anything, and it is bounded by
`MAX_CANDIDATES_PER_POLL = 10`.

## Fail closed

| Input | Outcome |
|---|---|
| a pull request in the listing | never considered |
| a title that is not the C01 three-segment shape (other cells, other shapes) | filtered before the parser; never planned |
| a C01-titled issue whose body is malformed | refused with the ingress's own reason code, no enqueue |
| a **closed** issue that arrives anyway | refused with `ISSUE_NOT_OPEN` - the consumer does not trust the `state=open` filter |
| listing failure | `LISTING_FAILED` with the status only |
| enabled but no Runtime reachable | `RUNTIME_UNAVAILABLE`, reported, not hidden |

## Disabled by default, with two independent layers

1. **The switch** is the ingress's own `C01_RUNTIME_INGRESS_ENABLED` - one switch, not
   two. Unset means the consumer still polls, parses and reports the task it *would*
   create, and never touches the Runtime: `ingest()` is not reachable from the shadow
   path, and the Runtime is not even constructed.
2. **The unit is not enabled.** Installing this file does not start anything;
   `systemctl enable` is a separate decision.

`--check` is offline by construction: it makes no network call and does not import the
Runtime kernel (the kernel is reached through `importlib` inside the factory, only when
enabled). It exits non-zero when the credential is unusable, which is what the unit's
`ExecStartPre` relies on.

## Installation note (not done in this PR)

The consumer is installed **beside the ingress**: `/opt/go/runtime-host-c1-worker/`.
A separate directory would mean a second copy of `c1_issue_ingress.py` and
`c1_execution_contract.py` that can drift from the installed ones. The C1 worker does not
enumerate its own directory - it imports named modules only - so an extra file there
cannot change the worker's behaviour.

It is **not** installed into `/opt/go/runtime-host-agent/`: that directory is hashed file
by file into the Agent's `executor_sha256`, which is bound by the registration, so adding
a file there makes the Agent refuse to start with `local_executor_mismatch`.

## Evidence

* 33 new cases; channel suite **308 tests OK (skipped=3)**, up from 275, with every
  pre-existing file keeping its exact `def test` count.
* A recorded transport stands in for the network, so the asserted thing is the request
  the consumer would really send: verb `GET`, the issues path, the token in a header.
* Ten consecutive polls over one issue produce **one** Runtime row and one task id.
* Offline only: no network, no Runtime host, no model call, no GitHub write.

## What is deliberately not here

Result write-back, issue comments, PR creation, candidate generation, C14/C13, and any
"stop the old executor" rule. The Owner has confirmed the cutover will be handled by
asking the Boss to pause C01 work, so double execution is an operational step rather than
a technical blocker - and nothing in this module depends on that decision.
