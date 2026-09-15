# C13 independent acceptance

Anchor: `fef9c748adb77d37ba5d4dc4fa4662eb668303a1`.
Candidate application tree: `740d026e3723f5da015342ead3394969629541df`.
Source SHA256: `b4383b383dd54e472ef178f1804d925bebf55019dc17f3641712cc42d4aae7b4`; 1341 declared files.

**Scoped acceptance: 210/210 PASS, including 11 independent reviewer-authored boundary cases.**
**Separate C11 open-gap reproduction: 2/2 FAIL, pytest exit 1. Overall release remains HOLD.**

C14 finalized at 2026-09-14T03:17:15.048729+00:00. C13 runtime started at 2026-09-14T03:18:12.795567+00:00. Source bytes and both tree fingerprints match before and after each run; all C14 integration hashes still match. No business source or implementer test was edited.

| Cell | Decision | Scope / next task |
| --- | --- | --- |
| C01 | PASS_SCOPED | Mixed hotel credit/cash changes and cancellation retain forfeiture and original expiry; isolated rollback cases. Next: Unknown money outcomes during mixed credit/cash checkout. |
| C02 | PASS_SCOPED | Partial-passenger body/leg requests rejected with no quote/money/ticket side effects; unsupported feature remains explicit. Next: Passenger-coupon selection and allocation design/implementation; no claim of partial-party change completion. |
| C03 | PASS_SCOPED | Local rail API/change recovery, dual inventory holds, confirmed/failed resolution and final refund pool release. Next: Unpaid-expiry versus payment/cancellation race and full target-inventory rejection; PostgreSQL remains unproved. |
| C04 | PASS_SCOPED | Refund completion matches exact frozen-plan payment intent, capture, amount and operation key. Historical equal-amount, duplicate, amount/currency/parent/key faults stay pending and safely retry. Next: Read-only reconciliation design for historical refunded-state versus frozen-plan contradictions; no auto-repair or money execution. |
| C05 | PASS_SCOPED | Repeated unknown result episodes restore correct ride phase and preserve fulfillment terminal guards. Next: Evidence-loss/corruption recovery for unknown results and same-phase provider confirmation. |
| C06 | PASS_SCOPED | Attraction consumed quote contract, refund/redemption exclusion and changed-session capacity; SQLite synthetic runtime. Next: Destination timezone and validity-window facts plus local-session redemption boundary implementation. |
| C07 | PASS_SCOPED | P0 explicit SELF owner preference write/read, encrypted persistence, exact consent/purpose/key, revision, revocation and expiry; no admin impersonation or session auto-promotion. Next: PostgreSQL concurrent consent withdrawal and actual process-restart durability; companion preference graph remains outside this SELF-only scope. |
| C08 | PASS_SCOPED | Transient success-audit commit failure is bounded and fail closed; already-committed completion survives lost acknowledgement without repeating compute. Next: Durable restart recovery for persistent audit outage / process termination; ROUTING rows under permanent outage remain unclosed. |
| C09 | PASS_SCOPED | Persisted risk/review/remediation fields reject overrides; existing ACTIVE decision and sealed evidence remain unchanged on rejected input; serious risk veto retained. Next: Concurrent same-hotel reevaluation and durable hook replay preserve a single current judgment/evidence snapshot. |
| C10 | PASS_SCOPED | Six vertical create/attach preserve canonical order facts over caller amounts/currency while retaining notes and ownership behavior. Next: Batch N+1 current-state reads; historical attachment monetary snapshots not rewritten in this scope. |
| C11 | HOLD | 16 inherited completion-guard cases pass, but sync/async post-commit callback probes independently fail 2/2 on this candidate. Next: Explicit proven-no-side-effect versus uncertain outcome contract, then reconcile/replay implementation for flight checkout/change and reviewed call sites. |
| C12 | PASS_SCOPED | Local validator requires gate sequence and distinct reviewers; all 14 idle cells trigger SCHEDULER_FAIL and history-preserving ASSIGNED followups with no invented ACK/RUNNING. Next: Apply validator to actual central ledger; actual ongoing worker liveness and remote scheduler automation are unproved. |
| C13 | PASS_SCOPED | Independent exact-candidate source verification, 210 scoped passes, 11 new reviewer-authored boundaries, plus separate two-case known-failure hold. Next: Verify immutable archive/CI candidate binding and final central ledger references without manufacturing remote execution. |
| C14 | PASS_SCOPED | Independent C14 record, source manifest, timestamps and integration hashes verified; C04 change request is closed for this candidate. Next: Review subsequent depth changes as new exact candidates; this acceptance cannot transfer to changed source. |

Original red/green logs remain intact. Initial interpreter failures are distinct from product test failures; expanded C07/C08 cases are not claimed as original red cases. C04 same-order equal-amount historical refund receipt bypass was reproduced, fixed, reviewed by C14, and independently exercised with additional receipt faults.

No entire domain is marked 100 percent complete. No PostgreSQL, real supplier/funds, process-restart, frozen-image, complete browser/device or Hong Kong deployment acceptance is inferred. Local scheduler followups do not establish remote worker liveness.

Raw commands, UTC timestamps, logs, JUnit and before/after file fingerprints are in this directory. `FINAL_C13_REVIEW.json` is the machine-readable result.
