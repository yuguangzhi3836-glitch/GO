# HK-STAGING proven DEPLOY runbook

## Preconditions

This is the proven golden path, not standing authorization. Before acting,
read `README.md`, this runbook, and `HK_STAGING_DEPLOY_BASELINE.md`; then
verify current live state. The live state, Human Approval, Signed Task,
installed artifact, durable record, and Signed Evidence remain authoritative.

1. Obtain explicit Human Approval for the exact environment, fixed
   eight-target deployment scope, exact candidate or intended deployment,
   Docker runtime mutation, and the absence of migration, Production access,
   and automatic rollback. When the operation is a same-image
   force-recreate, that specific same-image mutation must be within the
   approval scope; same-image is not a universal precondition for future
   HK-STAGING deployments.
2. Validate current signed CANARY Evidence against its original signed Task.
   Candidate image and repository digest may bind transitively through the
   signed Task when the Evidence binds the task ID, nonce, action, and
   environment.
3. Run a fresh, read-only drift preflight against the live Compose hash,
   runtime environment hash, target image IDs, API health, worker state,
   Alembic state, and non-target inventory.
4. Stop if drift is found. Do not restore historical container IDs or a
   documented baseline over current live state.

## Fresh signed deployment

5. Create exactly one fresh `HK_STAGING_DEPLOY` Task. It requires a new
   `task_id`, nonce, `release_id`, timestamps, and Ed25519 signature.
6. Publish it through the authorized Command Center Tasks Writer to the
   private tasks repository. Read back and verify the committed Task.
7. Let the formal HK Agent timer pick it up. The timer nominally polls every
   60 seconds; a short observed pickup does not indicate a shorter configured
   interval. Allow the normal polling window before diagnosing a pickup
   failure, and do not substitute direct `sudo`/Executor invocation for the
   formal path merely because pickup is not immediate. Timer timing is
   operational behavior, not Execution Authority.
8. The narrow Executor creates the durable `DEPLOY_RECORD_V2` **before**
   any Docker mutation. Failure to create this record rejects the action.
9. The Executor uses its fixed deployment scope and owns `--force-recreate`
   for exactly the eight target services. `force_recreate` is not a caller
   parameter. The completed formal E2E proved this behavior for a same-image
   candidate; it does not make same-image a required scenario for every future
   `HK_STAGING_DEPLOY`.
10. `GO_RUNTIME_ENV_FILE` is injected by the Executor as a fixed subprocess
    environment input; it is not caller-controlled.
11. The Executor waits for bounded API readiness, then performs complete
    post-deploy checks: API health, worker process-liveness, Alembic
    current/head, immutable target-image binding, Compose/environment
    integrity, and non-target integrity.
12. On success, the HK Agent creates and pushes Signed DEPLOY Evidence. The
    Task, Evidence, and V2 record form the only possible future Rollback
    source; they must be mechanically bound and source lineage must remain
    eligible.
    Command Center independently verifies the signature and binding.
13. Observe subsequent formal pickup cycles. Completion/replay protection must
    prevent another dispatch and another successful Evidence record.

## Formal post-deploy verification

14. Create a separate fresh signed `HK_STAGING_VERIFY` Task; do not reuse the
    DEPLOY Task.
15. Let the formal timer invoke the narrow VERIFY Executor once. VERIFY is
    read-only: it must not force-recreate, migrate, roll back, or mutate
    business runtime.
16. Verify the Signed VERIFY Evidence in Command Center and observe replay
    protection through subsequent formal pickup cycles.

An approved future Rollback is a separate operation governed by
[`HK_STAGING_ROLLBACK_RUNBOOK.md`](HK_STAGING_ROLLBACK_RUNBOOK.md). It must
derive targets from the eligible V2 source record, not a caller image.

## Non-negotiable retry rule

A failed or dispatched Task is never reused. Any retry requires a fresh
`task_id`, nonce, `release_id`, signature, and a new durable previous-state
record. Never extend, re-sign, or replay an old Task.

## Boundaries

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
the fixed eight-service override. This is implementation-level support for a
different-image candidate, subject to those validations. A formal
different-image DEPLOY E2E is **NOT_PROVEN** and must not be claimed from the
same-image E2E.
