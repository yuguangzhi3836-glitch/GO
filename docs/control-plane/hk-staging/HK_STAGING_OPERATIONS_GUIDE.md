# HK-STAGING operations guide

This guide helps people and AI agents choose a safe path. It does not grant
authority. Do not reconstruct procedures from chat memory.

## Choose the action

- Use **VERIFY** to measure the current approved baseline without mutation.
- Use **CANARY** before a proposed DEPLOY when the signed Task and approval
  require it; it is isolated from business runtime.
- Use **DEPLOY** only after explicit approval, a fresh signed Task, CANARY
  binding where required, and clean live drift checks. Current DEPLOY is a
  fixed eight-service operation, not a scoped deployment.
- Use **ROLLBACK** only after explicit approval and only from a mechanically
  eligible successful DEPLOY source. The caller cannot select an image.

## Normal path

Human Approval → fresh Signed Task → published private Tasks repository →
normal timer pickup → Agent validation → narrow Executor → durable record
before mutation when applicable → Signed Evidence → independent verification.
The Agent polls nominally every 60 seconds; this is not a SLA. Do not manually
invoke the Executor merely because pickup is not immediate.

## Stop conditions and durable history

Stop on any signature, lineage, binding, drift, health, or non-target
integrity failure. A dispatched Task is permanently single-attempt: it must
not be reused, extended, re-signed, or copied. Check the durable Agent ledger
and Signed Evidence to determine whether it was consumed.

Never manufacture historical SUCCESS Evidence from current live state, chat,
or human recollection. A Control Plane runtime update is not itself a business
deployment. Current live state, Human Approval, Signed Task, installed runtime,
durable record, and Signed Evidence remain authoritative.

Migration, Production, automatic retry, automatic rollback, and automatic
recovery are forbidden. Docs are not Execution Authority.
