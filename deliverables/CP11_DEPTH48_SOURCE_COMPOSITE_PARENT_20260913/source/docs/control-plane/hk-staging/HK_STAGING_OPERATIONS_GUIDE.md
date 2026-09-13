# HK-STAGING operations guide

This guide helps people and AI agents choose a safe path. It does not grant
authority. Do not reconstruct procedures from chat memory.

Repository changes are governed by `docs/governance/CHANGE_CONTROL_POLICY.md`.
Planned permanent changes use a branch and Pull Request; normal work must not
write directly to `main`.

## Choose the action

- Use **VERIFY** to measure the current approved baseline without mutation.
- Use **CANARY** before a proposed DEPLOY when the signed Task and approval
  require it; it is isolated from business runtime.
- Use **DEPLOY** only after explicit approval, a fresh signed Task, CANARY
  binding where required, clean live drift checks, and compatibility with the
  currently approved deployment topology.
- Use **ROLLBACK** only after explicit approval and only from a mechanically
  eligible successful DEPLOY source. The caller cannot select an image.

The current approved/proven HK-STAGING business topology is
`HK_STAGING_BUSINESS_TOPOLOGY` version `1`, defined in
`DEPLOYMENT_TOPOLOGY_V1.json`. It contains exactly eight business service roles
using one shared business image, with `redis` and `caddy` as protected
non-targets. The installed Executor still enforces this fixed eight-service
scope. The number eight describes the current proven topology; it is not a
permanent architectural limit.

If a candidate adds/removes/renames a runtime service role, introduces another
business image family, changes protected non-targets, or otherwise requires a
different topology, normal DEPLOY must stop with `TOPOLOGY_CHANGE_REQUIRED`
(or equivalent HOLD). Follow `TOPOLOGY_CHANGE_POLICY.md`; do not accept an
arbitrary caller-supplied service list or silently expand deployment scope.

## Normal path

Human Approval -> fresh Signed Task -> published private Tasks repository ->
normal timer pickup -> Agent validation -> narrow Executor -> durable record
before mutation when applicable -> Signed Evidence -> independent verification.
The Agent polls nominally every 60 seconds; this is not a SLA. Do not manually
invoke the Executor merely because pickup is not immediate.

## Stop conditions and durable history

Stop on any signature, lineage, binding, topology, drift, health, or non-target
integrity failure. A dispatched Task is permanently single-attempt: it must
not be reused, extended, re-signed, or copied. Check the durable Agent ledger
and Signed Evidence to determine whether it was consumed.

Never manufacture historical SUCCESS Evidence from current live state, chat,
or human recollection. A Control Plane runtime update is not itself a business
deployment. Current live state, Human Approval, Signed Task, installed runtime,
durable record, and Signed Evidence remain authoritative.

Migration, Production, automatic retry, automatic rollback, and automatic
recovery are forbidden. Docs are not Execution Authority.
