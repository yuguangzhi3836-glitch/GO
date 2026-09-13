# C07–C10 scoped convergence result

Baseline: `main@286e294d92df4b7d1c0073116a8e628734abec6c`.
Canonical application tree: `3025b2b6b36ea9211da561a4631f304216de9d90`.
Scope: source candidate and isolated local acceptance only. No Hong Kong,
Production, live-provider, remote Git mutation, migration, or topology changes
were performed by this workstream. C14 and C13 decisions remain independent.

| Cell | Actual result | New execution evidence | Remaining boundary |
| --- | --- | --- | --- |
| C07 Traveler Intelligence | Existing context-only authority retained; `evaluate_judgment` and `independent_judgment` still deny C07 judgment authority; traveler graph does not auto-promote session signals into durable preferences. No forced source rewrite. | Bounded source inspection, no new C07 test or whole-domain PASS claimed. | Preferences endpoint explicitly remains `P0_EMPTY_PURPOSE_BOUND`; durable preference capability and end-to-end purpose/consent acceptance are not established by this inspection. |
| C08 GO AI Planning | Closed request-audit failure after successful subtasks followed by synthesis failure. The parent request is finalized FAILED instead of remaining ROUTING. Existing exception/status conventions reused; successful response and compute-only boundaries retained. | New tests: baseline 2 failed / 1 passed; candidate 3 passed. | No live model/provider acceptance or full orchestration audit claimed. Advisory model verification content and broader request lifecycle remain outside this narrow change. |
| C09 Judgment & Trust | Existing six-dimension evidence, commercial-independence attestation, explicit worth-the-journey, and serious-risk veto rules retained. No recommendation policy change or forced rewrite. | Bounded inspection of judgment service and existing tests; no new C09 execution or whole-domain PASS claimed. | Independent source-bound complete judgment acceptance remains unproven by this workstream. |
| C10 Unified Trips | Closed stale list projection for existing attached orders. List and detail now both read current canonical vertical status; historical attachment snapshots are not rewritten. | New tests: baseline 12 failed / 3 passed; candidate 15 passed. All six verticals × owner/member; outsider/revoked member; foreign-order privacy; missing-order fallback. | Synthetic ORM projection tests are not actual booking/refund journeys. C14/C13 pending. No concurrency/load or browser acceptance claimed. |

## Changed paths

1. `application/src/go_hotel/journey/service.py`: use existing read-only
   `_serialize(..., refresh=True)` for journey list, matching get().
2. `application/tests/journey/test_c10_current_status_projection.py`: 15 new
   isolated nine-table SQLite tests.
3. `application/src/go_hotel/go_ai/service.py`: finalize failures from the
   existing synthesis task with the same `GO_AI_ORCHESTRATION_TASK_FAILED`
   convention already used for subtask failures. Original provider ValueError
   is preserved; unexpected exceptions get the existing normalization.
4. `application/tests/go_ai/test_c08_synthesis_audit_finalization.py`: three new
   two-table SQLite / deterministic-provider tests.

No existing tests, unrelated source, runtime configuration, topology, or
business rules were rewritten.

## Evidence inventory

- `baseline-red.log` / `baseline-red.junit.xml`: C10 before patch, 12 failed and
  3 passed, exit 1. Failure is list CONFIRMED versus get/canonical CANCELLED.
- `candidate-green.log` / `candidate-green.junit.xml`: C10 after patch,
  15 passed, exit 0.
- `c08-baseline-red.log` / `c08-baseline-red.junit.xml`: C08 before patch,
  2 failed and 1 passed, exit 1.
- `c08-candidate-green.log` / `c08-candidate-green.junit.xml`: C08 after patch,
  3 passed, exit 0.
- `reproduce_c08_synthesis_audit_gap.py` / `c08-unfixed-diagnostic.log`:
  historical pre-fix diagnosis, bound to baseline GO AI blob
  `672ffe3dbab8a7d2de253e198041c7c91381ea34`. The script intentionally asserts
  the OLD defect and is NOT a candidate-green test or release gate.

Runner: `/workspace/scratch/2d68c25b0133/go-venv/bin/python`; `PYTHONPATH=src`.
New test execution uses pytest `no_db` to bypass the shared business test reset;
each fixture provisions and disposes its own isolated database. Providers are
explicit deterministic test doubles and never call a network.

## Candidate SHA256

| Path | SHA256 |
| --- | --- |
| journey/service.py | `cbb4ad735e6a3a6632154dace37a80ef7945e95706bbfc17e1a32f674e0ab67b` |
| test_c10_current_status_projection.py | `a87fb62bc980726a5ee5cb83ff57f1f452e9944b7a836c23b7f5ccd0a0059f16` |
| go_ai/service.py | `9b0ef8d9907155a60c143f55c8ecb32ec18dc2262a44354144d2fad71e1adf45` |
| test_c08_synthesis_audit_finalization.py | `1c431307f6c97dd2389950391bcaf0af93e99f9f3004088a8c0f31196d022327` |

## Specific residual risks

- C10 refreshing lists adds a canonical order lookup per item, consistent with
  existing detail behavior. Large-list query count / load impact is not measured
  here and is not hidden under the correctness PASS.
- Existing missing/not-owned canonical order fallback preserves the saved
  snapshot. These tests preserve current semantics; they do not assert that a
  missing order has fresh verification.
- C10 `_attach` permits caller `facts` to overwrite default snapshot facts
  (`amount_minor`, `currency`, etc.). This is a source-inspection finding only;
  its accepted custom-fact contract and downstream consumers need separate
  focused reproduction/review before changing semantics.
- Create/attach response refresh behavior, browser visibility, real six-category
  transactional journeys, refunds/ledger finality, and PostgreSQL execution are
  not covered by these projection tests.

Next action for these candidates: C14 scoped gate review followed by C13
independent reproduction against fixed candidate hashes. Neither workstream
self-certifies release or authorizes automatic deployment.
