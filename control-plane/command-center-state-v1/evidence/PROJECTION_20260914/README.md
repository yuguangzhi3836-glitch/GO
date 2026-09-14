# Projection of the live control bus — 2026-09-14

A real, unedited projection produced by `state_projection.py` against the live
control repositories, kept here so the value of the layer can be reviewed
without re-running anything.

**This snapshot is derived and NON-AUTHORITATIVE.** It is not Execution
Authority, it is not a signed record, and it must never be used to authorize an
operation. The Signed Task and the Signed Evidence remain the only authority and
the only proof.

## Exact inputs (pinned)

| Input | Revision |
|---|---|
| `chenzhenxi1-sudo/go-control-tasks` `main` | `5b7caecd8e47751b13e4661d14b27880f19d1d71` |
| `chenzhenxi1-sudo/go-control-evidence` `permission-test` | `350dc628075ebd4cea9a3a2d8040caf23f957f57` |
| GO `main` (canonical pointers) | `8ffcde66d36c1bbf849218529ef015f6e81725af` |
| Projection instant (`--now`) | `2026-09-14T12:00:00Z` |

Task verification key: **not supplied**. The Command Center / Hong Kong public
verifier keys are not published in the GO repository, so every signature in this
snapshot is `NOT_PERFORMED` and the projection is capped at `OBSERVED`. That
limitation is real and is listed as delivery blocker 1.

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
  --now 2026-09-14T12:00:00Z --out .
```

## What the projection found

```
tasks                        46   (45 current-schema, 1 preserved legacy-schema)
evidence                     24
requests                     13
signature_verification       NOT_PERFORMED   (no verifier key supplied)
hk_agent_liveness            UNKNOWN
control_plane_drift          DRIFT
by_lifecycle                 EVIDENCE_PUBLISHED 24
                             TASK_EXPIRED 21
                             POLICY_HOLD 1
anomalies                    TASK_PARAMETER_CONTRACT_DRIFT
```

Five findings that were not previously answerable in one place:

1. **Runtime drift is real and now measurable.** The canonical runtime pointer
   records image `sha256:57beafa2…` (DEPTH48) while the newest VERIFY Evidence
   refers to `sha256:66c54087…` (the superseded R3.1 runtime). No VERIFY Evidence
   of any rank exists for the runtime currently recorded as deployed.

2. **Agent liveness is genuinely unknown.** The newest signed
   `CONTROL_PLANE_HEALTH` Evidence is 690 395 s old — far outside any sane
   window. The agent may well be healthy, but the control bus cannot say so, and
   the projection refuses to promote the last successful task into a liveness
   claim.

3. **Rollback candidates can be enumerated from proof, not from memory.**
   Four successful `HK_STAGING_DEPLOY` Evidence records exist; the newest is
   `go-boss02-final-deploy-20260911T025420Z`. This is a candidate set derived
   from signed results — explicitly *not* an approval and *not* a signed
   ROLLBACK Task.

4. **One historical Task is preserved rather than dropped.** A 2026-09-09 CANARY
   Task carries a parameter contract that predates the current one. It is kept
   with `POLICY_HOLD` and an explicit drift anomaly, and it cannot be counted as
   proof. Silent deletion would have made the state look cleaner and less true.

5. **Every deployability question resolves to HOLD.** `hk_deploy`,
   `final_release` and `production` are all `HOLD` on canonical `main`, and the
   projection adds that deployability also depends on live Command Center state
   it deliberately cannot read.

## Files

| File | Contents |
|---|---|
| `CURRENT_CONTROL_STATE.json` | the full projection: every Request, Task and Evidence, each with state, reason and evidence references |
| `CONTROL_STATUS_V1.json` | the compact ChatGPT read contract and the question map |
| `TASK_INDEX.json` | one row per Task, linked to its Evidence and assertion state |
| `LATEST_EVIDENCE.json` | newest Evidence per action |
| `REQUESTS_MANIFEST.json` | the control-bus ref, head SHA and path each Request was read from |
