# C08 next depth: interruption recovery boundary

Source anchor: `fef9c748adb77d37ba5d4dc4fa4662eb668303a1`.
Inherited candidate: `a274f77e4c1479fb143cdc7ef45d63b9c4f8cc1b`.

`GOAIService.assess_recovery(request_id)` is a new **read-only local service
helper**, with no route, recovery worker, scheduler, migration or external
provider call. It inspects the existing durable hash-only request/invocation
audit. It never changes a request state or repeats compute.

The subprocess test actually terminates its worker with `os._exit(73)` at
three checkpoints. Provider calls are written and fsynced before returning
the deterministic test answer. The parent opens the same file-backed SQLite
database using a new session after the worker has exited.

| Hard exit checkpoint | Durable state | Invocation rows | Persisted compute calls | Assessment |
| --- | --- | ---: | ---: | --- |
| Compute returned, before invocation commit | ROUTING | 0 | 1 | HOLD |
| After first invocation commit | ROUTING | 1 | 1 | HOLD |
| After final request completion commit | COMPLETED | 2 | 2 | NO_RECOVERY_REQUIRED |

For all three, two successive assessments preserve the complete request audit
and the exact call-counter bytes. Existing synthesis-finalization, transient
audit-commit, persistent-audit-outage and commit-ACK-loss tests are retained;
the combined local suite has 9 passing tests.

ROUTING recovery remains **HOLD**. The durable schema does not establish an
execution lease/owner or termination, the complete task plan/checkpoint, a
reconstructable final answer, or whether an unrecorded provider call completed.
Age and a successful invocation hash do not supply those facts. Therefore the
helper always reports `model_replay_allowed: false`, `safe_to_finalize: false`
and `database_mutation_performed: false`.

This closes the scoped hard-interruption experiment and explicit recovery
assessment contract. It does not implement automatic recovery. The next
development scope is a reviewed durable lease/ownership and checkpoint design
that can distinguish live, terminated and ambiguous execution without persisting
sensitive prompt/answer bodies or replaying a completed model call. Schema,
privacy and provider idempotency choices require separate review before code
is permitted to finalize an interrupted request.

The results are isolated SQLite and deterministic compute evidence; they are
not PostgreSQL crash recovery, real provider exactly-once acceptance, Hong Kong
deployment or independent C13 acceptance. C14 and C13 remain reviewer-owned.
