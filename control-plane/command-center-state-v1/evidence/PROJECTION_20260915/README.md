# Projection of the live control bus — 2026-09-15

```text
HISTORICAL_SCHEMA_SNAPSHOT
NOT_CURRENT_CONTRACT_COMPATIBLE
```

This directory is a record of what `state_projection.py` produced at a pinned
instant from pinned revisions, under the contract **as it stood at that time**.
Its bytes are immutable: it is deliberately not rewritten when a later contract
revision adds a field, and it is not re-projected. The live contract is
`contracts/`, and a current projection is produced from the current revision and
current pinned inputs as a new run -- never by overwriting this one.

A real, unedited projection produced by `state_projection.py` against the live
control repositories and the **published verifier identities**.

Scope: `CONTROL_STATE_AND_STATUS_ONLY`.

**This snapshot is derived and NON-AUTHORITATIVE.** It is not Execution
Authority, it is not a signed record, and it must never be used to authorize an
operation. The Signed Task is the only Execution Authority and the Signed
Evidence is the only proof.

## Exact inputs (pinned)

| Input | Revision |
|---|---|
| `chenzhenxi1-sudo/go-control-tasks` `main` | `1d4c3595a466cd2d6692af3634c1eeda4feec677` |
| `chenzhenxi1-sudo/go-control-evidence` `permission-test` | `350dc628075ebd4cea9a3a2d8040caf23f957f57` |
| GO source read for the canonical pointers | `bbd9d26966c146476bb976fe514f17c7b353f84c` |
| GO canonical `main` at projection time | `8610a4dbfd58cbe595f3d161c049de37dd81d3cc` |
| Projection instant (`--now`) | `2026-09-15T01:31:58Z` |

Verifier keys: both supplied, from the published identity contract
`identity/VERIFIER_IDENTITIES_V1.json`.

## What this snapshot adds over `PROJECTION_20260914`

Exactly two Tasks, both published on 2026-09-15 during the approved pre-deploy
evidence round, and both **unclaimed**:

| Task | Action | Lifecycle | Evidence | Bound to |
|---|---|---|---|---|
| `go-boss-test-pr-52-c39d85ecbb02` | `HK_STAGING_TEST_PR` | `TASK_EXPIRED` | none | `bd25d7acca1b5f54a7fb555008ed60b76ee45f21` |
| `go-boss-request-verify-20260915T011158Z-c9ccc0f13432` | `HK_STAGING_VERIFY` | `TASK_EXPIRED` | none | `sha256:66c54087...` |

Both signatures verify against the published Command Center task identity
(`identity/keys/cc-task-manifest-signing.pub`, `SHA256:bkwH368M...`), so the
publication half of the channel is proven live. Neither was picked up: the Hong
Kong agent published no Evidence for either, so the execution half is not
observable in this snapshot. There is no liveness producer (`INSTALLED=NO`), so
"not picked up" is a fact about the bus, not a diagnosis of the agent.

The TEST_PR is bound to `bd25d7ac`, the head of PR #52, and **not** to the
`source_commit` the canonical candidate pointer declares (`8a22a4fc`). Both carry
the same `application/` tree (`ad7d1de1...`), but `readiness.gate_test_pr` looks
up the declared commit, so this Task does not satisfy that gate as written.

Reading:

```text
tasks                        48   (was 46)
by_lifecycle                 COMPLETE 24 | TASK_EXPIRED 20 | POLICY_HOLD 4
evidence                     24
requests                     15  all REQUEST_CREATED, no Bridge facts supplied
runtime_verification         NOT_RECENTLY_VERIFIED
task / evidence identity     BOUND, signatures PERFORMED
anomalies                    TASK_PARAMETER_CONTRACT_DRIFT
```

The live Command Center request switch is a live-host fact and is **not** in this
document. It was read read-only on the Command Center and is reported separately:
`deployment_requests_enabled=true` at config sha256 `1ac0ad42...`, written at
`2026-09-13T15:55:34+08:00` by a deliberate, self-labelled enable operation with
no authority record recovered.
