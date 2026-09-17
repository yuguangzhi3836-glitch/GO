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
INSTALLED=YES               DEPLOYED=NO
```

**The producer is installed on the Command Center host and driven by a timer.** The
whole chain was proven end to end on 2026-09-15; the install record, the
before/after hashes, the live smoke output and the rollback are in
`install/INSTALL.md`.

```text
producer tick -> outbox Request -> Request PR on the control bus -> the Bridge
validates it and signs a read-only Task -> HK agent picks it up, executes the
read-only probe and publishes signed Evidence -> the projector derives
hk_agent_online = PROVEN
```

Two things to keep straight:

* **The producer is installed, and the wiring is now scheduled -- but it is not
  here.** The producer's timer decides whether a probe is due and places one
  Request in its outbox. It never publishes to the bus.
  `control-plane/liveness-request-transport-v1` is the wiring, and it is a separate
  component with its own timer and its own gate, because the wiring is where the
  bound had to be proved rather than asserted. It relays the newest fresh outbox
  Request through ONE long-lived branch and ONE pull request, and moves a
  superseded probe into `request/liveness-archive` so the fact-to-Request join
  survives the rotation.

  The wiring that used to live here opened a new branch and a new pull request for
  every probe -- 48 open pull requests a day -- and has been removed rather than
  left as a footgun.
* **The Bridge needed a revision for this.** `CONTROL_PLANE_HEALTH` was valid on
  the agent and understood by the projector, but the Bridge -- the only Task
  signer -- rejected the action outright. `control-plane/boss-deploy-request-v1`
  now accepts it (Bridge `1.5.0-control-plane-health`), read-only, parameterless,
  with an explicit fail-closed dispatch. The Request was never the hard part; the
  signer was.

### A measured growth defect this install exposed

Facts are minted per `(submission, observation instant)`, and every change in the
Bridge's own poll output creates a new observation instant. Measured on the host
after one such change: **36 facts for 18 submissions** -- 18 at `10:59:56Z` and 18
more at `12:56:27Z`. Nothing is wrong with any single fact, but the store grows
with the number of *observations*, not with the number of *Request outcomes*, so a
scheduled probe every 30 minutes would mint roughly 18 facts per probe.

That is why the wiring above was held back as an operator step rather than
scheduled. The precondition it named has since been met: a fact's identity is now
its semantics rather than the instant it was seen, so an unchanged outcome observed
again mints nothing at all. **This is the record of why the delay existed, not a
current limitation** -- the transport is now a component with a timer, and it is
`liveness-request-transport-v1`.

