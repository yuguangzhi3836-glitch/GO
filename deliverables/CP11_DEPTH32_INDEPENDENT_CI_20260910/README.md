# DEPTH32R2 scoped independent acceptance

2026-09-10 10:05:39 Asia/Shanghai: CI 34427905965 completed successfully for candidate
1289e9c3e3c7e7c35e553df80dc6a9d4111d88e3. All 1,236 source fingerprints match before
and after tests. Original JUnit: 187 backend and 224 frontend/native pure-function
tests; zero failures, errors or skips. This is component acceptance only.

Changes: disclose and validate change fees, transport details and hotel lower-price
forfeiture before consent; bind flight refund consent to the account, exact quote,
refund identity and verified append-only evidence chain. Preserve original money
idempotency keys and recover historical pending refunds without inventing consent.

The initial failed candidate and CI 34427342231 are preserved separately. Its six
failures were a genuine implementation error (using a rail/attraction-constrained
table for flight). The corrected candidate uses the existing evidence chain and
does not change schema or migrations. Do not combine results across candidates.

## Remaining work

- Ride and rental accepted-refund terms still need backend binding. Ride currently
  moves money before locking the order; a durable pending state and recovery must
  precede money execution, preserving its existing idempotency key.
- Selected official PSP contract/materials and sandbox configuration were not
  obtained in the permitted sources. Contract simulation is not PSP certification.
- Native build/device and three-role desktop/mobile real browser verification are
  outstanding. Tests here use SQLite TestClient and native pure functions only.
- Multi-leg airline changes/professional supplier conditions are incomplete.
- Six-vertical real E2E, complete sealed Node gate, rollback and package-to-runtime
  binding require separate primary evidence. Offline source restoration is not
  a rollback rehearsal or a deployment approval.
- HK docs report polling behavior; the four cited task/receipt commits still return
  no commit in the selected GO repository. No live failure or success is inferred.

All development remains with GO Command Center. Hong Kong operates approved
artifacts only. PR #11 remains draft and unmerged. No deployment instruction sent.
