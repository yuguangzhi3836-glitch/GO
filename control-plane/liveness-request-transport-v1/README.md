# liveness-request-transport-v1 (`#98` / CC V1-03 wiring)

Puts a read-only `CONTROL_PLANE_HEALTH` probe Request onto the Request channel,
through **one** branch, on a timer, without opening a pull request per probe.

```text
producer tick -> outbox Request -> THIS -> one transport branch -> the Bridge signs
a read-only Task -> HK agent probes and publishes signed Evidence -> the projector
derives hk_agent_online
```

## Why this exists

`agent-liveness-producer-v1` decides whether a probe is due and writes the Request
into its own outbox. It never touches the bus. The operator wiring that put an
outbox Request on the bus (`agent-liveness-producer-v1/install/liveness_request_wiring.py`)
opened a **new branch and a new pull request for every probe**: 48 open pull
requests a day, and 48 more the next day.

The producer's own README records why that wiring was left as a manual step: the
exporter minted a fact per observation, so running the wiring on a timer would have
grown the fact store on a timer. That precondition is now met -- a fact's identity
is its semantics, not the instant it was seen -- so the wiring can be scheduled, and
this component is what can be scheduled safely.

## What is bounded, and how

```text
ONE branch, ONE pull request   boss-request-liveness-transport. Every cycle
                               force-updates that branch and the pull request
                               follows it. A new head is a new submission identity
                               to the Bridge, so a reused branch is still a fresh
                               submission.
ONE added file per submission  The Bridge accepts a submission only when
                               diff --name-status merge-base(main, head)..head is
                               exactly one "A  requests/<id>.json". So each
                               transport commit is built on the current main and
                               adds exactly one file. A cycle adds one and removes
                               none -- asserted before the push, refused otherwise.
NO API CLIENT                  The tool holds no HTTP client at all, checked against
                               its own source by run_checks. It speaks git over SSH
                               with the key that already writes the bus. It
                               therefore cannot create, merge or close a pull
                               request: the open-PR count can only grow if a human
                               opens one.
ONE ACTION, ONE ENVIRONMENT    CONTROL_PLANE_HEALTH, HK-STAGING-01, exactly the five
                               common Request fields. There is no code path that
                               publishes any other action.
AN APPEND-ONLY ARCHIVE         A superseded probe is moved to
                               request/liveness-archive before the transport drops
                               it, and a path the archive already holds is never
                               rewritten.
```

### Why the archive is not optional

A Request fact is immutable and permanent, and the projection attributes every fact
to the Request file it was read from. Rotating the transport therefore has to keep
the superseded file **somewhere on the bus**, or the fact-to-Request join breaks once
per probe and the projection emits one `REQUEST_FACT_WITHOUT_REQUEST` anomaly per
probe -- which is exactly the "another form of unbounded growth" that must not be
introduced.

`request/*` is the second namespace the state contract already declares for
Requests, and the two readers are already split across them:

| | `refs/heads/boss-request-*` | `refs/heads/request/*` |
|---|---|---|
| the Bridge | reads the pull-request head | does not look |
| the state collector | collects | collects |

So the transport submits, and the archive keeps the join intact.

## Usage

```sh
# relay the newest fresh probe (what the timer runs)
go-liveness-request-transport relay

# decide and report without pushing anything
go-liveness-request-transport relay --dry-run

# what the bus currently holds
go-liveness-request-transport status

# the rules, without git
go-liveness-request-transport selftest
```

Every run prints one JSON object matching
`contracts/liveness_request_transport_v1.schema.json`. `bounds` is present on **every**
result, including the ones that publish nothing, so the boundedness claims are
restated rather than only asserted when a cycle happens to succeed.

```text
PUBLISHED           the transport moved
ALREADY_PUBLISHED   this bucket is already on the bus; a tick that finds nothing
                    to do does nothing at all
SKIPPED_STALE       the newest probe is older than the window the Bridge accepts,
                    so publishing it would buy a refusal and a rejection fact
SKIPPED_NO_REQUEST  the outbox is empty
REFUSED             fail-closed: nothing was pushed, and why
```

## The five-minute timer against the thirty-minute probe

The producer publishes at most one probe per 1800 s bucket. This timer runs every
300 s, so a probe is on the bus within five minutes of being produced, and a tick
that finds the current bucket already relayed publishes nothing.

The publish window is 600 s, inside the Bridge's own 900 s staleness limit. That
margin is **transport slack**, not a second way to raise the probe rate: the rate
stays the producer's decision, and `run_checks` pins
`max_publish_age_seconds < bridge_max_age_seconds`.

## What it is not

* It is not Execution Authority. A report is a record of a git push.
* It holds no Task key, signs nothing, and has no code path to the Bridge, the
  agent or an executor.
* It cannot merge, close or revert anything, and it never writes to a pull-request
  ref.
* It never turns a probe into a liveness answer. It carries an untrusted Request;
  turning that into a signed Task stays where it already is, in the Bridge.

## Verification

```text
run_checks.py                            the rules, hermetically: no network, no
                                         subprocess, no runtime state, no credential
                                         -- 32 tests plus the contract cross-check
tests/test_liveness_request_transport.py the same rules, in the ordinary suite
install/verify_transport_is_bounded.py   the real plumbing against a real repository:
                                         ls-remote, fetch, hash-object, write-tree,
                                         commit-tree, push, push --force-with-lease
command-center/go-liveness-request-transport selftest
```

`install/verify_transport_is_bounded.py` is the one that matters most, because it
recomputes what the Bridge itself would compute for each submission and shows that
three consecutive buckets leave one branch pair, one file in the transport, one more
file in the archive, and no lost probe.

## Installation

See `install/INSTALL.md` for the install record, the before/after hashes and the
rollback.
