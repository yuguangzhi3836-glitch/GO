# Projection of the live control bus — 2026-09-14

A real, unedited projection produced by `state_projection.py` against the live
control repositories and the **published verifier identities**, kept here so the
value of the layer can be reviewed without re-running anything.

Scope: `CONTROL_STATE_AND_STATUS_ONLY`.

**This snapshot is derived and NON-AUTHORITATIVE.** It is not Execution
Authority, it is not a signed record, and it must never be used to authorize an
operation. The Signed Task is the only Execution Authority and the Signed
Evidence is the only proof.

## Exact inputs (pinned)

| Input | Revision |
|---|---|
| `chenzhenxi1-sudo/go-control-tasks` `main` | `5b7caecd8e47751b13e4661d14b27880f19d1d71` |
| `chenzhenxi1-sudo/go-control-evidence` `permission-test` | `350dc628075ebd4cea9a3a2d8040caf23f957f57` |
| GO source read for the canonical pointers | `bbd9d26966c146476bb976fe514f17c7b353f84c` |
| GO canonical `main` at projection time | `8610a4dbfd58cbe595f3d161c049de37dd81d3cc` |
| Projection instant (`--now`) | `2026-09-14T12:00:00Z` |

The GO pointer files are byte-identical between `bbd9d269` and canonical `main`
`8610a4db`; the branch only adds a roadmap document.

Verifier keys: **both supplied, from the published identity contract**
`identity/VERIFIER_IDENTITIES_V1.json`. That is the difference from the previous
revision of this snapshot, which supplied none.

## Exact reproduction

```sh
# 1. Read-only checkouts of the control repositories
git clone --depth 1 https://github.com/chenzhenxi1-sudo/go-control-tasks.git
git clone --depth 1 https://github.com/chenzhenxi1-sudo/go-control-evidence.git

# 2. Request files live on control-bus refs, not on main; collect them read-only
cd go-control-tasks
git fetch --depth 1 origin \
  '+refs/heads/boss-request-*:refs/remotes/origin/boss-request-*' \
  '+refs/heads/request/*:refs/remotes/origin/request/*'
# for each such ref: git show <ref>:requests/<id>.json, wrapped as
# {"ref":..., "head_sha":..., "path":..., "request":{...}}

# 3. Project, binding the keys to the published identities
python control-plane/command-center-state-v1/state_projection.py \
  --tasks-repo ../go-control-tasks --evidence-repo ../go-control-evidence \
  --requests-dir ../requests --go-repo ../GO \
  --task-verify-key \
    control-plane/command-center-state-v1/identity/keys/cc-task-manifest-signing.pub \
  --evidence-verify-key \
    control-plane/command-center-state-v1/identity/keys/hk-evidence-signing.pub \
  --verifier-identities \
    control-plane/command-center-state-v1/identity/VERIFIER_IDENTITIES_V1.json \
  --tasks-head 5b7caecd8e47751b13e4661d14b27880f19d1d71 \
  --evidence-head 350dc628075ebd4cea9a3a2d8040caf23f957f57 \
  --go-head bbd9d26966c146476bb976fe514f17c7b353f84c \
  --repository-main-sha 8610a4dbfd58cbe595f3d161c049de37dd81d3cc \
  --now 2026-09-14T12:00:00Z --out .
```

`REQUESTS_MANIFEST.json` records the control-bus ref, head SHA and path each
Request was read from. Nothing in this directory contains a workstation path.

## What the projection found

```
tasks                        46   (45 current-schema, 1 preserved legacy-schema)
evidence                     24
requests                     13
task_identity_binding        BOUND               (GO-CC-TASK-MANIFEST-SIGNER)
evidence_identity_binding    BOUND               (HK-AGENT-EVIDENCE-SIGNER)
identities_separated         true
proven_allowed               true
task_signature_verification  PERFORMED
evidence_signature_verif.    PERFORMED
hk_agent_liveness            UNKNOWN
runtime_verification         NOT_RECENTLY_VERIFIED
active_stuck_tasks           0
enabled_request_actions      HK_STAGING_VERIFY, HK_STAGING_TEST_PR
deploy_readiness_evaluation  NOT_IN_SCOPE
rollback_readiness_evaluation NOT_IN_SCOPE
by_lifecycle                 COMPLETE 24 | TASK_EXPIRED 18 | POLICY_HOLD 4
request_lifecycles           REQUEST_CREATED 13   (zero Request facts supplied)
request_facts                0
anomalies                    TASK_PARAMETER_CONTRACT_DRIFT
```

Every Request reads `REQUEST_CREATED` because **zero Bridge Request facts were
supplied to this projection**: the read-only exporter that publishes them exists
(`control-plane/command-center-request-visibility-v1`, CC V1-05) but nothing
drives it or publishes its output yet, so `request_visibility.facts_collected`
is 0 and no Request can be reported as accepted or refused. That is the honest
state of the control bus, not a projection defect: a Request file on the bus
means a human wrote it and nothing more.

## What changed from OBSERVED to PROVEN

The previous revision supplied no verifier key, so every signature read
`NOT_PERFORMED`, all 24 evidence-bearing Tasks stopped at `EVIDENCE_PUBLISHED`,
and none of it could be called `PROVEN`.

With the published identities the same inputs now resolve:

```text
before   EVIDENCE_PUBLISHED 24 | TASK_EXPIRED 21 | POLICY_HOLD 1
after    COMPLETE            24 | TASK_EXPIRED 18 | POLICY_HOLD 4
```

All 24 signed Evidence records verify against `HK-AGENT-EVIDENCE-SIGNER`, and
their 24 Tasks verify against `GO-CC-TASK-MANIFEST-SIGNER`, across six actions:
VERIFY 12, DEPLOY 4, TEST_PR 3, CANARY 2, health 2, ROLLBACK 1.

## Findings that were not previously answerable in one place

1. **Three historical Tasks do not verify against the published Task signer.**
   With no key supplied these three were indistinguishable from the rest and were
   classified `TASK_EXPIRED`. Now that the identity is bound they resolve as
   `POLICY_HOLD` / `FAILED`:

   ```
   go-m3-042-e2e-health-20260905T151233846901Z   issued 2026-09-05T15:12:33Z
   go-m3-042-e2e-health-20260905T152130238921Z   issued 2026-09-05T15:21:30Z
   go-m3-042-e2e-health-20260906T011815978751Z   issued 2026-09-06T01:18:15Z
   ```

   They are structurally identical to Tasks that do verify: the same ten fields,
   the same 128-character lowercase-hex signature, no field dropped, no
   formatting drift. They do **not** verify under the Hong Kong evidence identity
   either, so they are not a crossed-identity artifact. The conclusion the
   evidence supports is that they were signed by a **third, earlier Task-signing
   identity whose public key is not published anywhere**, superseded before
   `2026-09-06T07:47:11Z`. The cause is **not** attributed here: whether that was
   a provisioning rotation, a per-run harness key or something else is an open
   attribution question, recorded as a remaining gap rather than guessed at.
   This is the clearest demonstration of why the publication was needed: it is
   what turned three silently-expired records into three explicit failures.

2. **Declared runtime and proven runtime are different, and the proof is stale.**
   The repository pointer declares `sha256:57beafa2…` (`go-hotel:depth48-runtime-6d0fd905`).
   The newest VERIFY Evidence names `sha256:66c54087…`, the superseded R3.1
   runtime. The relation is `DIFFER` and the verdict is `NOT_RECENTLY_VERIFIED`
   because the newest proof is older than the verification window. No VERIFY
   Evidence of any rank exists for the declared runtime.

3. **Agent liveness is genuinely unknown.** The newest signed
   `CONTROL_PLANE_HEALTH` Evidence is 690 395 s old. `hk_agent_recent_activity`
   still answers "we last heard from `iZj6ccs8t04f1p4d8pe69zZ` at
   2026-09-06T12:13:25Z", and `hk_agent_online` stays `UNKNOWN`. The agent may
   well be healthy; the control bus cannot say so. Nothing schedules a probe,
   which is what CC V1-03 has to fix.

4. **Nothing is stuck.** `active_stuck_tasks` is empty.

5. **DEPLOY stays a capability classification, not a readiness verdict.** The
   request channel reports `HK_STAGING_DEPLOY` as
   `CAPABILITY_PRESENT_BUT_DISABLED` with `deploy_request_enabled=false` and
   `readiness_evaluation=NOT_IN_SCOPE`. No `can_deploy`, no deployment
   eligibility, no rollback target selection and no release-gate verdict appears
   in `CONTROL_STATUS_V1`.

6. **One historical Task is preserved rather than dropped.** A 2026-09-09 CANARY
   Task carries a parameter contract that predates the current one. Its signature
   **does** verify, but it is kept with `POLICY_HOLD` and an explicit drift
   anomaly and cannot be counted as proof.

7. **Rollback candidate history is recorded, but rollback readiness is not
   claimed.** Four successful `HK_STAGING_DEPLOY` Evidence records exist and all
   four now verify. They stay as non-contract data at
   `control_state.informational.rollback_candidate_history`. A candidate list is
   not an approval and not a signed ROLLBACK Task.

## Files

| File | Contents |
|---|---|
| `CURRENT_CONTROL_STATE.json` | the full projection: every Request, Task and Evidence, each with state, reason and references |
| `CONTROL_STATUS_V1.json` | the compact read contract and the question map |
| `TASK_INDEX.json` | one row per Task, linked to its Evidence and both signature verdicts |
| `LATEST_EVIDENCE.json` | newest Evidence per action |
| `REQUESTS_MANIFEST.json` | the control-bus ref, head SHA and path each Request was read from |
