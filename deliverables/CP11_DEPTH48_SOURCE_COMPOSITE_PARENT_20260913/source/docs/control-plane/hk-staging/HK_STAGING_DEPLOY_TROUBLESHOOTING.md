# HK-STAGING Control Plane troubleshooting

Use this guide only after reading the runbook and verifying live state. It is
not permission to run commands or retry a Task.

## Same-image Compose no-op

**Symptom:** a normal Compose operation may not recreate services when the
image is unchanged.

**Proven resolution:** the narrow Executor owns fixed `--force-recreate`
semantics for exactly eight target services. The formal E2E proved this for a
same-image candidate. It is not a caller-provided option, and the same-image
scenario must not be generalized as a required condition for every future
deployment.

## `GO_RUNTIME_ENV_FILE` missing

**Symptom:** Compose reports that required variable `GO_RUNTIME_ENV_FILE` is
missing a value.

**Root cause:** the Executor subprocess environment lacked the fixed runtime
environment-file path.

**Proven resolution:** R3 added internal fixed environment injection. The
caller does not control this path. The R4 baseline retains that behavior.

## Eight containers recreated but Executor returned 2

**Symptom:** all eight target container IDs changed, but post-deploy
verification rejected the deployment.

**Root cause:** an immediate API health observation raced application
readiness; the observed API was approximately one to two seconds old.

**Proven resolution:** R4 uses bounded post-deploy API readiness polling:
12 attempts, five seconds apart, followed by the full post-deploy check.

## CANARY Evidence lacks a digest or a field named `result`

**Symptom:** Signed CANARY Evidence does not repeat `candidate_repo_digest`
or have a field literally named `result`.

**Proven resolution:** use signed Evidence-to-signed Task transitive binding
when Evidence binds task ID, nonce, action, and environment. The actual proven
success representation was `status=SUCCESS` and `executor_result=CANARY_OK`.

## Failed formal Task

**Rule:** never reuse a dispatched Task, including after a tooling failure.
Retry only with a new task ID, nonce, release ID, signature, and durable
previous-state record. Do not extend expiry, alter, copy, or re-sign the old
Task.

## `ROLLBACK_OK` but no Signed Evidence

First determine whether a real mutation occurred and whether a durable rollback
record was written. Do **not** retry. A historical parser defect compared an
absent Rollback Task `candidate_image_id` with the Executor's empty value using
DEPLOY-style correlation. A credible durable attempt consumes the source even
when post-executor processing fails.

## Valid rollback source unexpectedly rejected

Formal Task release identity lives at `task.parameters.release_id`, not
`task.release_id`. The Evidence and V2 record carry their bound release value
at their documented record fields. Missing, malformed, top-level-only, or
mismatched values must reject; do not introduce a permissive fallback.

## Successful mutation followed by processing failure

Preserve durable audit material and fail closed. No automatic retry, recovery,
or rollback is permitted. A source with a credible durable rollback attempt is
`AMBIGUOUS_CONSUMED` unless the authoritative record proves otherwise.

## Historical Evidence recovery

Never infer a historical SUCCESS Evidence object from current containers,
chat, or an operator statement. Only the signed object, durable record, and
immutable repository history can establish historical success.

## Unknown condition

If a fact cannot be derived from live state, a signed object, installed bytes,
or the durable record, record it as `NOT_PROVEN` or `UNKNOWN`; do not infer it
from chat history or historical commands.
