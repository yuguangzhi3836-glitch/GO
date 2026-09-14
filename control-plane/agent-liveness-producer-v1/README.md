# CC V1-03 - HK Agent liveness producer

Status: part of `cc/v1-finalization-20260914` (Issue #98, CC V1 order 03).

This component adds the one thing the Command Center V1 liveness story was
missing: **a timer**. The mechanism itself already existed and is unchanged.

```
CONTROL_PLANE_HEALTH   already in the agent allowlist
                       already has a read-only executor path (uname nodename,
                       /proc/meminfo, disk free)
                       already publishes its result as ordinary signed Evidence
```

What did not exist is anything that drives that action on a schedule, so the
control bus carried no fresh liveness Evidence and `hk_agent_online` honestly
read `UNKNOWN` even while the agent was healthy. This adds the producer, and
nothing else.

## What this component is not

* **Not a signing authority.** It holds no private key, never builds a Task and
  never signs anything. It emits an untrusted Request, the same shape the Boss
  Request Bridge already treats as a proposal. Turning a Request into a signed
  Task stays where it already is.
* **Not a monitor.** It cannot express a cadence faster than
  `MIN_INTERVAL_SECONDS` (600 s), and it cannot emit any action other than
  `CONTROL_PLANE_HEALTH`. A policy that asks for either is refused at load.
* **Not a heartbeat.** It never writes a liveness conclusion. It records what it
  *asked*, never what it concluded.

The last point is the whole design. A producer that could assert liveness would
be a heartbeat without a signer, which is exactly what the issue forbids.

## Why the cadence is structurally bounded

Two independent mechanisms, so neither has to be trusted alone:

1. **Hard bounds in code.** `interval_seconds` must fall inside
   `[600, 86400]` and `max_probes_per_window` inside `[1, 48]`. A policy outside
   those ranges, naming another action, naming another environment, or omitting
   the read-only flag is refused before the producer does anything.
2. **Bucket idempotence.** `request_id` is a pure function of
   `floor(epoch / interval_seconds)`. Two ticks inside one bucket mint the same
   `request_id`, so the duplicate detection the Request channel already performs
   makes double-probing impossible even if the timer fires twice, restarts, is
   replayed, or is driven by hand.

Throttling is measured against the **last published probe**, never against the
last tick. A timer firing faster than the policy interval therefore cannot
starve the bucket it was throttled in - a property with a dedicated test.

## Cadence

| Setting | Value | Note |
|---|---|---|
| `interval_seconds` | 1800 | 30 min. Inside the schema's recommended 10-30 min band. |
| `max_probes_per_window` | 48 | Rolling 24 h ceiling. Bounds a malfunction, not the normal rate. |
| interval floor / ceiling | 600 / 86400 | Enforced in code. |

One probe per interval is one signed Task plus one signed Evidence on the
existing repositories. The freshness window the projection uses is
`1800 s` by default; running the interval at or below it keeps
`hk_agent_online` answerable while the agent is healthy. Operators who want
tolerance for a single missed probe should raise
`--liveness-window-seconds` on the projector rather than shorten the interval,
so the producer's rate stays low.

## Answers this does not change

The two questions stay separate, and the producer only supplies input to one
of them:

```
hk_agent_recent_activity   newest signed probe at any age   -> "when did we last hear from it"
hk_agent_online            PROVEN only from signed liveness Evidence inside the window
                                                             -> "is it online now"
```

`fresh signed liveness => ONLINE/PROVEN`, `old signed liveness => STALE`,
`missing / invalid => UNKNOWN/HOLD` are decided by
`control-plane/command-center-state-v1/state_projection.py` from signed
Evidence. The producer never contributes to that decision. It only makes fresh
Evidence possible.

`VERIFY`, `TEST_PR`, `DEPLOY` and `ROLLBACK` authorizations are not referenced
by this component in any form. A test asserts the source cannot even express
their names.

## Usage

```sh
# one bounded tick, intended to be driven by a timer
go-liveness-producer --state-dir /var/lib/go-command-center/liveness-producer-v1 tick

# achieved cadence - never a liveness claim
go-liveness-producer --state-dir /var/lib/go-command-center/liveness-producer-v1 status

# built-in checks
go-liveness-producer selftest
```

Per tick the producer decides one of:

```
PUBLISHED   due; a Request was placed in the outbox
DUPLICATE   this bucket already published; nothing written
THROTTLED   interval or rolling-window budget not met; nothing written
REFUSED     the policy or a pre-condition failed; fails closed
```

Every decision is appended to `ledger.jsonl`, tagged
`signed_by_producer: false` and `grants_execution: false`.

## Files

| Path | Purpose |
|---|---|
| `command-center/go-liveness-producer` | the producer (stdlib only) |
| `command-center/liveness-producer-policy-v1.json` | the only place cadence is expressed |
| `contracts/agent_liveness_producer_v1.schema.json` | policy, ledger, request and authority boundary |
| `tests/test_liveness_producer.py` | isolated tests, including coherence with the state layer |
| `run_checks.py` | isolated verification; forbids network, subprocess and runtime paths |

## Boundaries and remaining gap

```
HONG_KONG_TOUCHED=NO        CONTROL_PLANE_TOUCHED=NO
DEPLOY_PERFORMED=NO         ROLLBACK_PERFORMED=NO
PRODUCTION_TOUCHED=NO       PRIVATE_KEY_HELD=NO
INSTALLED=NO                DEPLOYED=NO
```

**This PR defines the producer. It does not install it.** No systemd unit, timer
or scheduler change is made here, and the outbox the producer writes is picked
up by the existing Request channel only once an operator wires it. Until that
happens the control bus still carries no fresh liveness Evidence and
`hk_agent_online` still honestly reads `UNKNOWN`. That gap is reported, not
smoothed over: the producer removes the *missing mechanism*, not the
*missing installation*.
