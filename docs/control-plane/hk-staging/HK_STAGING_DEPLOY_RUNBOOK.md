> **HISTORY / BREAK-GLASS REFERENCE**
>
> This document is not the normal current operating path.
>
> Normal deployment and inspection are defined by [`/AGENTS.md`](../../../AGENTS.md) and use GO Forge.
>
> Do not issue `HK_STAGING_*` requests unless the Owner explicitly authorizes Old Command Center fallback mode.

---

# HK-STAGING proven DEPLOY runbook

## Topology boundary

The currently approved/proven business topology is `HK_STAGING_BUSINESS_TOPOLOGY` version `1`, defined by `DEPLOYMENT_TOPOLOGY_V1.json`. It contains exactly eight business service roles using the current single-business-image model, while `redis` and `caddy` are protected non-targets.

The installed Executor still enforces this fixed eight-service scope. This is the current proven topology, not a permanent architectural limit for GO.

A candidate that adds/removes/renames a runtime service role, introduces another business image family, changes protected non-targets, or otherwise requires a different deployment topology must not be routed through ordinary DEPLOY. Stop with `TOPOLOGY_CHANGE_REQUIRED` (or equivalent HOLD) and follow `TOPOLOGY_CHANGE_POLICY.md`. Never accept an arbitrary caller-supplied service list or silently expand deployment scope.

## Preconditions

This is the proven golden path, not standing authorization. Before acting,
read `README.md`, this runbook, `HK_STAGING_DEPLOY_BASELINE.md`,
`DEPLOYMENT_TOPOLOGY_V1.json`, and `TOPOLOGY_CHANGE_POLICY.md`; then
verify current live state. The live state, Human Approval, Signed Task,
installed artifact, durable record, and Signed Evidence remain authoritative.

1. Obtain explicit Human Approval for the exact environment, the currently approved topology identity/version and fixed eight-target deployment scope, exact candidate or intended deployment, Docker runtime mutation, and the absence of migration, Production access, and automatic rollback. When the operation is a same-image force-recreate, that specific same-image mutation must be within the approval scope; same-image is not a universal precondition for future HK-STAGING deployments.
2. Confirm that the candidate is compatible with the currently approved topology. Any topology mismatch requires the separate topology-upgrade path and is not a normal DEPLOY retry or scoped deployment.
3. Validate current signed CANARY Evidence against its original signed Task. Candidate image and repository digest may bind transitively through the signed Task when the Evidence binds the task ID, nonce, action, and environment.
4. Run a fresh, read-only drift preflight against the live Compose hash, runtime environment hash, target image IDs, API health, worker state, Alembic state, and non-target inventory.
5. Stop if topology mismatch or drift is found. Do not restore historical container IDs or a documented baseline over current live state.

## Fresh signed deployment

6. Create exactly one fresh `HK_STAGING_DEPLOY` Task. It requires a new
   `task_id`, nonce, `release_id`, timestamps, and Ed25519 signature.
7. Publish it through the authorized Command Center Tasks Writer to the private tasks repository. Read back and verify the committed Task.
8. Let the formal HK Agent timer pick it up. The timer nominally polls every 60 seconds; a short observed pickup does not indicate a shorter configured interval. Allow the normal polling window before diagnosing a pickup failure, and do not substitute direct `sudo`/Executor invocation for the formal path merely because pickup is not immediate. Timer timing is operational behavior, not Execution Authority.
9. The narrow Executor creates the durable `DEPLOY_RECORD_V2` **before** any Docker mutation. Failure to create this record rejects the action.
10. The Executor uses its fixed topology-V1 deployment scope and owns `--force-recreate` for exactly the eight target services. `force_recreate` is not a caller parameter. The completed formal E2E proved this behavior for a same-image candidate; it does not make same-image a required scenario for every future HK-STAGING deployment. Topology changes are not inferred from candidate source and are not caller-controlled.
11. `GO_RUNTIME_ENV_FILE` is injected by the Executor as a fixed subprocess environment input; it is not caller-controlled.
12. The Executor waits for bounded API readiness, then performs complete post-deploy checks: API health, worker process-liveness, Alembic current/head, immutable target-image binding, Compose/environment integrity, and non-target integrity.
13. On success, the HK Agent creates and pushes Signed DEPLOY Evidence. The Task, Evidence, and V2 record form the only possible future Rollback source; they must be mechanically bound and source lineage must remain eligible. Command Center independently verifies the signature and binding.
14. Observe subsequent formal pickup cycles. Completion/replay protection must prevent another dispatch and another successful Evidence record.

## Formal post-deploy verification

15. Create a separate fresh signed `HK_STAGING_VERIFY` Task; do not reuse the DEPLOY Task.
16. Let the formal timer invoke the narrow VERIFY Executor once. VERIFY is read-only: it must not force-recreate, migrate, roll back, or mutate business runtime.
17. Verify the Signed VERIFY Evidence in Command Center and observe replay protection through subsequent formal pickup cycles.

An approved future Rollback is a separate operation governed by
[`HK_STAGING_ROLLBACK_RUNBOOK.md`](HK_STAGING_ROLLBACK_RUNBOOK.md). It must
derive targets from the eligible V2 source record, not a caller image.

## Formal topology change

A future topology version change is a separately reviewed engineering change governed by `TOPOLOGY_CHANGE_POLICY.md`. It requires a GitHub branch/PR trail, a new machine-readable topology version, corresponding updates to affected deployment/rollback/verification contracts and implementation, isolated validation, explicit Human Approval, and a first formal HK-STAGING E2E before it becomes the normal approved topology.

A topology PR or merge does not itself authorize runtime mutation.

## Non-negotiable retry rule

A failed or dispatched Task is never reused. Any retry requires a fresh
`task_id`, nonce, `release_id`, signature, and a new durable previous-state
record. Never extend, re-sign, or replay an old Task.

## Boundaries

- Current normal DEPLOY scope is topology V1: exactly eight approved business service roles.
- Caller-controlled or candidate-inferred topology expansion is forbidden.
- No migration.
- No automatic rollback.
- No Production action.
- No caller-controlled force-recreate or runtime environment path.

## Candidate-image evidence boundary

The current installed Executor (`0.4.3-rollback-runtime`,
`R11-release-binding-schema-correction`) retains the candidate-image and
repository-digest validation first proven by R4. It separately validates that
the current live image matches
`expected_current_image_id`; it does not require those two image IDs to be
identical. The current Executor then writes the validated candidate image into
the fixed eight-service topology-V1 override. This is implementation-level
support for a different-image candidate, subject to those validations. A formal
different-image DEPLOY E2E is **NOT_PROVEN** and must not be claimed from the
same-image E2E.
