# Projection of the live control bus — 2026-09-14

A real, unedited projection produced by `state_projection.py` against the live
control repositories, kept here so the value of the layer can be reviewed without
re-running anything.

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
| GO `main` (canonical pointers) | `4b03281977a77263b1ce0dedb1b889c2008b6b00` |
| Projection instant (`--now`) | `2026-09-14T12:00:00Z` |

Verifier keys: **neither supplied**. The Command Center task key and the Hong
Kong evidence key are not published in the GO repository, so every signature in
this snapshot is `NOT_PERFORMED`, the projection is capped at `OBSERVED`, and no
claim in these files is `PROVEN`. That limitation is real and is listed as
delivery blocker 1.

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

# 3. Project
python control-plane/command-center-state-v1/state_projection.py \
  --tasks-repo ../go-control-tasks --evidence-repo ../go-control-evidence \
  --requests-dir ../requests --go-repo ../GO \
  --tasks-head 5b7caecd8e47751b13e4661d14b27880f19d1d71 \
  --evidence-head 350dc628075ebd4cea9a3a2d8040caf23f957f57 \
  --go-head 4b03281977a77263b1ce0dedb1b889c2008b6b00 \
  --repository-main-sha 4b03281977a77263b1ce0dedb1b889c2008b6b00 \
  --now 2026-09-14T12:00:00Z --out .
```

`REQUESTS_MANIFEST.json` records the control-bus ref, head SHA and path each
Request was read from. Nothing in this directory contains a workstation path.

## What the projection found

```
tasks                        46   (45 current-schema, 1 preserved legacy-schema)
evidence                     24
requests                     13
task_signature_verification  NOT_PERFORMED   (no Command Center task key supplied)
evidence_signature_verif.    NOT_PERFORMED   (no Hong Kong evidence key supplied)
identities_separated         true
hk_agent_liveness            UNKNOWN
runtime_verification         NOT_RECENTLY_VERIFIED
active_stuck_tasks           0
enabled_request_actions      HK_STAGING_VERIFY, HK_STAGING_TEST_PR
by_lifecycle                 EVIDENCE_PUBLISHED 24 | TASK_EXPIRED 21 | POLICY_HOLD 1
anomalies                    TASK_PARAMETER_CONTRACT_DRIFT
```

Findings that were not previously answerable in one place:

1. **Declared runtime and proven runtime are different, and the proof is stale.**
   The repository pointer declares `sha256:57beafa2…` (`go-hotel:depth48-runtime-6d0fd905`).
   The newest VERIFY Evidence names `sha256:66c54087…`, the superseded R3.1
   runtime. The relation is `DIFFER` and the verdict is `NOT_RECENTLY_VERIFIED`
   because the newest proof is older than the verification window. No VERIFY
   Evidence of any rank exists for the declared runtime.

2. **Agent liveness is genuinely unknown.** The newest signed
   `CONTROL_PLANE_HEALTH` Evidence is 690 395 s old. `hk_agent_recent_activity`
   still answers "we last heard from `iZj6ccs8t04f1p4d8pe69zZ` at
   2026-09-06T12:13:25Z", and `hk_agent_online` stays `UNKNOWN`. The agent may
   well be healthy; the control bus cannot say so.

3. **Nothing is stuck.** `active_stuck_tasks` is empty. 13 tasks expired inside
   the recent window and 8 expired before it; both are indexed separately and do
   not change the current-health answer.

4. **Deployability resolves to HOLD**, and the request channel reports
   `HK_STAGING_DEPLOY` as `CAPABILITY_PRESENT_BUT_DISABLED` with
   `deploy_request_enabled=false`. The live Command Center switch is reported as
   `UNKNOWN` because it is a live-host fact.

5. **One historical Task is preserved rather than dropped.** A 2026-09-09 CANARY
   Task carries a parameter contract that predates the current one. It is kept
   with `POLICY_HOLD` and an explicit drift anomaly and cannot be counted as
   proof. Silent deletion would have made the state look cleaner and less true.

6. **Rollback candidates can be enumerated from proof, not from memory.** Four
   successful `HK_STAGING_DEPLOY` Evidence records exist; the newest is
   `go-boss02-final-deploy-20260911T025420Z`. A candidate set derived from signed
   results, explicitly *not* an approval and *not* a signed ROLLBACK Task.

## Files

| File | Contents |
|---|---|
| `CURRENT_CONTROL_STATE.json` | the full projection: every Request, Task and Evidence, each with state, reason and references |
| `CONTROL_STATUS_V1.json` | the compact read contract and the question map |
| `TASK_INDEX.json` | one row per Task, linked to its Evidence and both signature verdicts |
| `LATEST_EVIDENCE.json` | newest Evidence per action |
| `REQUESTS_MANIFEST.json` | the control-bus ref, head SHA and path each Request was read from |
