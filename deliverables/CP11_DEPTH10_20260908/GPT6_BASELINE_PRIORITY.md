# GPT-6 baseline priority policy

Status: ACTIVE

## Authority order

1. The verified GPT-6/DEPTH09 candidate and its inherited DEPTH08/DEPTH07 artifacts are the primary baseline.
2. DEPTH10 work is additive closure only. It may fill an explicit remaining gap, strengthen fail-closed behavior, or add missing runtime evidence.
3. If any DEPTH10 change conflicts with a verified GPT-6 behavior, architecture, visual contract, data contract, or acceptance truth, the DEPTH10 change must be removed or rewritten. The GPT-6 baseline wins.
4. A DEPTH10 implementation is not retained merely because it is newer or more complex.

## Verified GPT-6 baseline facts that must not regress

The DEPTH09 README records the inherited candidate as HOTEL_REPLICATION_GATE=HOLD and FINAL_RELEASE_GATE=HOLD, not deployed, with 1063 Python tests passed, 6 PostgreSQL checks skipped, and 0 failures. It also records the remaining closure scope: screenshot/onboarding entry, official-template/full-room-catalog verification, automatic media pipeline, regional durable recovery, generic direct-booking room-pool mapping, real cross-hotel speed, browser and Hong Kong acceptance.

DEPTH10 therefore exists to close those remaining gaps and must not re-implement already verified DEPTH09 capabilities without a demonstrated defect.

## Change admission rule

A DEPTH10 change may remain only when all are true:

- It maps to a documented unresolved baseline gap or a newly proven defect.
- It preserves existing public contracts unless the old contract is proven wrong.
- It does not weaken an existing release gate.
- It remains fail-closed when runtime truth is unavailable.
- It does not claim runtime PASS from authored code or tests alone.
- It can be removed independently without destroying unrelated GPT-6 baseline functionality.

## Conflict rule

When review finds a conflict between morning DEPTH10 work and the GPT-6 baseline, use this disposition order:

- REVERT DEPTH10 if it replaces a correct GPT-6 implementation.
- REBASE DEPTH10 if its improvement can be expressed as a small compatible patch.
- RETAIN DEPTH10 only when it closes a real baseline gap and all inherited gates remain intact.

## Completion truth

The planning estimate is approximately 90% baseline completion and approximately 10% remaining closure work. This percentage is not a release assertion. 100% is reached only when the final integrated candidate passes the complete release gate and the single final Hong Kong real-environment acceptance. Code volume, commit count, authored tests, or code-side freezes do not constitute 100%.
