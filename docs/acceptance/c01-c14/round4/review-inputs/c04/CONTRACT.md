# C04 current and historical compensation authority

Baseline cb8928f, frozen v1.1 requirements unchanged. Scope directly supports C04-20/C04-22 and C11 compensation; UNKNOWN recovery remains HOLD without independent trustworthy outcome evidence.

## Current execution source

`resolve_compensation(session, order_id, obligation_id, case_id, expected_case_version, expected_decision_hash)` retains the order-first lock and verified evidence chain. It accepts only the latest independently reviewed appeal whose award is strictly lower than the preceding decision. It validates immutable source/owner/currency/contract binding; each historical administrator must match the recorded reviewer and be distinct from owner, claim maker and all prior reviewers. Each superseding decision must match the owner's appeal and earlier decision version. New pending appeal or new version invalidates old commands. Equal/upward awards do not authorize compensation or another charge.

Result preserves v1 current decision fields/hash, adding prior_decisions [{case_version, decision_hash, awarded_minor, reviewer_id}], latest reviewer_id/approval_evidence, fixed payee_id/vehicle_id, authority_scope=REDUCE_ONLY and financial_effect_asserted=false. Exact historical decision hashes are reconstructed from immutable case snapshots using the original hashing algorithm. It does not assert which decision settled, that a capture exists, or how much to refund.

C11 must prove its original capture belongs to one of these historical decisions, retain that capture and release history unchanged, then determine remaining over-collection from actual confirmed capture minus all prior confirmed compensation minus the current target retained amount. No client amount or C04 scalar becomes financial truth. A stale/replayed approval cannot refund twice; higher liability is held rather than debited again.

## Historical receipt validation source

`resolve_compensation_history(session, order_id, obligation_id)` returns historical independent reduction facts with exactly the hash/lineage they had when current. Later pending appeals or upward decisions do not erase their existence. This is read-only evidence for verifying already-booked C11 receipts and deterministic operation keys. It MUST NOT authorize new money; the current resolver is mandatory for execution. No receipt is created or accepted by C04.

## UI

Shared rental operations shows prior and current adjudicated liability and explicitly says a favorable review is not confirmation of returned money. Upward revision says this entry will not make another charge. Consumer monetary amounts stay in C11's widget. No global app/router or C11 file was modified.

## Validation

64 isolated SQLite tests pass (10 new source cases and 54 existing damage/deposit regression cases). New cases cover partial/zero reduction, exact old hash reconstruction, initial/equal/upward refusal, new pending/version invalidation, role and replay refusal, competing independent reviews, semantic history inconsistency, historical authority during later appeal/upward review, and consecutive reduction hashes. Each C04 operation leaves money rows unchanged. PostgreSQL/concurrency and real browser evidence are separately owned by root/C12/C13, not inferred from SQLite. Current manifest binds the three changed files.
