> **HISTORY / BREAK-GLASS REFERENCE**
>
> This document is not the normal current operating path.
>
> Normal deployment and inspection are defined by [`/AGENTS.md`](../../../AGENTS.md) and use GO Forge.
>
> Do not issue `HK_STAGING_*` requests unless the Owner explicitly authorizes Old Command Center fallback mode.

---

# HK-STAGING proven ROLLBACK runbook

This is a proven path, not standing authorization. It permits no direct
Docker/Compose action by a caller or GPT.

1. Obtain explicit Human Approval for the exact environment, source, fixed
   eight-target mutation, no Migration, no Production, and no automatic
   recovery/retry.
2. Identify an eligible successful DEPLOY source. Verify its Signed DEPLOY
   Task, Signed DEPLOY Evidence, DEPLOY_RECORD_V2, Task/Evidence/record
   bindings, release/nonce/environment/action, lineage, and consumed-source
   status. Same image equality alone never proves lineage.
3. Recheck Compose/environment hashes, eight targets, Redis/Caddy integrity,
   health, and other fresh drift gates. Stop on any mismatch.
4. Publish exactly one fresh signed `HK_STAGING_ROLLBACK` Task with new task
   ID, nonce, release ID, and signature. Formal Task `release_id` is always
   `parameters.release_id`.
5. Let the Agent timer pick it up. The Agent provides fixed source metadata;
   the Executor independently verifies the source and derives rollback targets
   only from the DEPLOY_RECORD_V2 pre-mutation state. Caller-controlled image,
   scope, Compose path, or runtime environment path is not supported.
6. The Executor persists a rollback record before mutation, force-recreates
   exactly the eight fixed targets, performs bounded readiness/postcheck, and
   returns `ROLLBACK_OK` only on success.
7. Verify Signed Rollback Evidence, then issue a separate fresh post-rollback
   `HK_STAGING_VERIFY` Task. Do not reuse the Rollback Task.

If a credible durable rollback attempt/record exists for a source, it is
consumed even if later Evidence handling fails. Mark it `AMBIGUOUS_CONSUMED`
and fail closed; never retry it automatically.
