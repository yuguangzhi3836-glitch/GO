# HK-STAGING proven DEPLOY runbook

## Preconditions

This is the proven golden path, not standing authorization. Before acting,
read `README.md`, this runbook, and `HK_STAGING_DEPLOY_BASELINE.md`; then
verify current live state. The live state, Human Approval, Signed Task,
installed artifact, durable record, and Signed Evidence remain authoritative.

1. Obtain explicit Human Approval for the exact environment, fixed eight
   targets, and the absence of migration, Production access, and automatic
   rollback. `--force-recreate` is a fixed Executor semantic, not a caller
   parameter.
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
7. Let the formal HK Agent timer pick it up. Do not substitute direct
   `sudo`/Executor invocation for the formal path.
8. The narrow Executor creates the durable previous-state record **before**
   any Docker mutation. Failure to create this record rejects the action.
9. The Executor uses its fixed deployment scope and performs `--force-recreate`
   for exactly the eight target services. `force_recreate` is not a caller
   parameter. The just-completed Formal R4 DEPLOY E2E proved this semantic in a
   **same-image** scenario. Same-image is therefore a proven E2E scenario, not
   a mandatory condition for every future `HK_STAGING_DEPLOY`.
10. No Formal R4 different-image DEPLOY E2E is claimed. Whether the installed
    R4 Executor supports a different-image candidate is `NOT_PROVEN` until the
    installed R4 implementation and a formal signed E2E result are mechanically
    verified; do not infer support or lack of support from this runbook.
11. `GO_RUNTIME_ENV_FILE` is injected by the Executor as a fixed subprocess
   environment input; it is not caller-controlled.
12. The Executor waits for bounded API readiness, then performs complete
   post-deploy checks: API health, worker process-liveness, Alembic
   current/head, immutable target-image binding, Compose/environment
   integrity, and non-target integrity.
13. On success, the HK Agent creates and pushes Signed DEPLOY Evidence.
   Command Center independently verifies the signature and binding.
14. Observe subsequent formal pickup cycles. Completion/replay protection must
   prevent another dispatch and another successful Evidence record.

## Formal post-deploy verification

15. Create a separate fresh signed `HK_STAGING_VERIFY` Task; do not reuse the
   DEPLOY Task.
16. Let the formal timer invoke the narrow VERIFY Executor once. VERIFY is
   read-only: it must not force-recreate, migrate, roll back, or mutate
   business runtime.
17. Verify the Signed VERIFY Evidence in Command Center and observe replay
   protection through subsequent formal pickup cycles.

## Non-negotiable retry rule

A failed or dispatched Task is never reused. Any retry requires a fresh
`task_id`, nonce, `release_id`, signature, and a new durable previous-state
record. Never extend, re-sign, or replay an old Task.

## Boundaries

- No migration.
- No automatic rollback.
- No Production action.
- No caller-controlled force-recreate or runtime environment path.
