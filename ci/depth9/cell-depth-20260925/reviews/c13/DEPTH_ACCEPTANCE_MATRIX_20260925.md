# C13 independent read-only depth planning review

Date: 2026-09-25. Reviewer role: C13 scope/evidence review only. No product code changes, tests rerun, formal C13 opinion, deployment, merge, real provider or PSP access occurred.

## Frozen review baseline

- Canonical main observed: `aa2ec62b68b49679c6d54217c7cb75f63a9c3ef0`.
- Continue from unified candidate PR #246, head `6acf9fdcde4b208b12a8c9d57ef74497e745faae`.
- Product commit `5c8bb7cc5922a2c1c36babaef446c76a583e81fd`; application tree `9cc68fa3a805f9f0df09b937a7c2df618cf6795f`, 1490 files, SHA256 `80d19a5791c3a824421638df36b92616fb16e02ac6504b234bbce2571a76fadd`.
- `ci/depth9/CANDIDATE.json` includes #202/#204/#205/#208/#216/#217/#226/#227/#235/#240 exact source inputs. Do not restart from their older branches.
- GitHub API independently read back all five final-head workflows as completed/success: 36090817260, 36090817281, 36090817287, 36090817267, 36090817269. This review did not download/re-hash their raw artifacts; no formal PASS inferred.
- `ci/depth9/RESULTS.json` binds earlier `911a08c...` / `f0449feb...`, not final head. `ci/depth9/README.md` has historical pending PG wording. Use final-head CI for current execution results while preserving old records as history.
- C13/C14 organization follows Owner's 2026-09-25 decision and #247 Lite V2 design: C13 quality; C14 rules/compliance. Old #246 C14 Hong Kong retest language is stale. Do not implement a second quality reviewer or modify #247 in this workstream.

## Meaning of 100% in this workstream

100% means all agreed internal/pre-external scope acceptance obligations are implemented and evidenced on one immutable candidate. It does not mean every possible defect is impossible, real supplier/PSP certified, native devices tested when they were not, or production capacity proven. Requirements and denominator must be frozen; UNKNOWN and BLOCKED_EXTERNAL are not PASS.

For every Cell: enumerate states, legal and forbidden transitions, permission/tenant boundaries, replay and conflicting replay, concurrent competing mutations, crash before/after commit, timeouts/UNKNOWN, recovery ownership/fencing, cross-domain authoritative facts, audit and operational diagnostics. Each requirement maps to source/test/evidence and fixed identity. Database-dependent cases require disposable real PostgreSQL evidence, not an idle PG service beside SQLite tests. UI claims require actual browser journeys; type checks do not prove real-device execution. Only rerun affected scope and integration gates necessary to resolve changed behavior.

## C01–C12 matrix

Rows labelled 'coverage audit' are unproven completeness, not newly discovered code defects. Existing source tests were read or located on the exact candidate; paths alone do not establish full acceptance.

| Cell | Located evidence/source on #246 | Completion obligation / next bounded work | Finding class |
|---|---|---|---|
| C01 Hotel | `application/tests/test_v70_r4_c01_unknown_episode.py`; `test_v70_next_c01_authorization_replay.py`; #246 browser and hotel ledger audit | Preserve episode digest fencing, no writes without an open episode, audit rollback, GO_ADMIN-only resolution, authorization replay after lawful fare change. Trace original charge/adjustments/refunds to the same money authority. Audit tenant isolation and media approval/revoke concurrency before declaring complete hotel depth. | Existing focused coverage; full matrix reconciliation pending |
| C02 Flight | #240 C13 comment 5813794676; #246 PG recovery run 36090817287; `application/tests/flight/test_c02_three_end_change_quote.py` | Retain checkout/change idempotency, partial-party authority, four hard-kill recovery cases and active lease extension. Require fixed candidate PG evidence and no duplicate money root/side effects. #246 contains 12 process scenarios; do not repeat old #240 solely because roles changed. | Focused PASS retained; integration review pending |
| C03 Rail | `application/tests/test_next_depth_c03_payment_inventory_races.py` | Tests explicitly cover reservation expiry/cancel race before root, committed root blocking cancellation during capture, full target capacity refusal before extra money or release of original inventory. Reconcile complete ticket/return/change/recovery matrix and PG execution against exact successor, especially inventory and money conservation. | Coverage audit; no new defect established |
| C04 Rental | `application/src/go_hotel/mobility/rental/{service,changes,reconciliation}.py`; `application/tests/test_depth06_rental_settlement.py`; `test_v70_round2_c04_rental_receipts.py`; #246 stated remaining work | Implement pickup/return inspection evidence, bilateral damage/fee dispute, admin adjudication, deposit authorization/hold/release with original money root binding. Test competing adjudications, duplicate/conflicting requests, tenant denial, claim amount limits, unknown payment recovery, crash boundaries and PG concurrency. Existing cancellation/change refund tests do not prove this. | Confirmed business implementation gap |
| C05 Ride | `application/tests/test_v70_r5_c05_concurrent_unknown.py`; #205 head `6a7377321b90e38e2a09ef4b9a5cc3673bb34d19` integrated | Preserve exactly one committed UNKNOWN-opening winner, losing attempt fail-closed, no replay evidence append, corrupted execution-item binding refusal. Audit fulfillment/cancellation race, current episode provenance, supplier/admin/consumer permissions and recovery to Trips. | Existing focused coverage; matrix reconciliation pending |
| C06 Attractions | `application/tests/test_c06_internal_policy_registry.py`; `test_v70_r5_c06_raw_payload_binding.py` | Internal scope includes missing/malformed rule refusal, atomic imports, replay/conflict, version/supersession, expiry, state precedence, redemption and DST boundaries. Keep real supplier identity/auth/raw response/provenance and E2E separately BLOCKED_EXTERNAL, never synthesize their PASS. | Internal evidence present; external boundary retained |
| C07 Traveler intelligence | `application/tests/test_v70_r4_c07_consent_provenance.py`; `test_round2_c07_process_recovery.py`; #246 PG C07 scope | Exact-purpose active consent provenance; no grant means no release. Cover revoke/expire races, foreign-account denials, immutable audit context and recovery. Account connection/provider facts must remain account-scoped. | Existing focused coverage; completeness audit pending |
| C08 AI planning/execution | `application/tests/go_ai/test_c08_hard_exit_recovery.py`; `test_c08_complete_task_plan.py`; `test_c08_audit_commit_failure.py` | Hard-exit recovery must not replay completed effects or invent terminal success. Audit complete plans, durable checkpoint/lease fencing, audit commit failure and cancel/takeover interleavings. Need actual PG evidence for DB-dependent concurrency if making that claim. | Coverage audit; no new defect established |
| C09 Judgment/trust | `application/tests/judgment/test_next_depth_concurrent_judgment.py`; #246 C09 PG scope | One active judgment, sealed evidence reuse without reactivating old decisions, immutable hook replay, missing/foreign binding refusal, evidence validation before writes, atomic events/outbox. Preserve failure history. | Existing concrete concurrency/atomicity coverage; full review pending |
| C10 Unified Trips | `application/tests/journey/test_c10_current_status_projection.py`; `test_c10_attachment_canonical_facts.py`; #246 six-domain same-order browser/SQL checks | List/detail same canonical current state; read-only projections; revoked/foreign membership denial; attachment provenance; booking/change/refund external-order transitions consistent. Add only evidenced gaps, do not create second order/payment truth. | Existing projection and synthetic journey coverage |
| C11 Transactions/finance | #235 C13 comment 5806892027; #246 PG payments/recovery/outbox; `application/tests/payments/test_c11_flight_idempotency_recovery.py` | Keep PaymentOrderRoot/FactBinding → Intent/Attempt → MoneyMovement → Ledger authority. Frozen all-state matrix must cover duplicate/conflicting/out-of-order facts, refund cap, partial capture settlement, unknown resolution, finance-close races, recovery and cross-domain compensation. Existing 44/47 focused tests are not automatically exhaustive. Real PSP certification excluded and recorded separately. | Important matrix/evidence reconciliation; no broad completion claim |
| C12 Platform/security/operations | `ci/round2/test_c12_worker_liveness.py`; #246 mobile/capacity scopes | Heartbeat must not be called identity authentication or proof of live process; signature assertions still need nonce/expiry/storage failure guards. Prove scheduler stale/recovery behavior and actual persisted state. Isolated transactional write/soak load and resource/SLA evidence remain absent; 420 reads / max64 SQLite concurrency is only read baseline. Native prebuild is not real-device journey. | Confirmed operational evidence gaps |

## Existing accepted scope: preserve, do not reset

| PR | Frozen head | Acceptance record | Limits |
|---|---|---|---|
| #172 | `2d5fff4742949744cfba653ec9428c8f32a58c1a` | C13 comment 5709676119, DONE_SCOPED | Unified historical scope/tree b7fccc50; accepted Cell matrices inherited, not full external readiness |
| #240 | `d4376d6ae9a58eca3c7c32968ec96dffc5574122` | C13 comment 5813794676, PASS_SCOPED | 61 frozen tests + 10 PG18.4 process scenarios; application tree bee89f35 |
| #235 | `4ddb0e5eef6f80d446d0b9c3bb973b5392906ade` | C13 comment 5806892027, PASS_SCOPED | 44 PG18.4 tests, not full payment state matrix |
| #227 | `9f9fcf81570ae98a952ce48d34eb14c6cbb73209` | C13 comment 5806956626, PASS_SCOPED | 53 Python +32 Node SQLite/synthetic agreements; formal registration not enabled |
| #217 | `0c3da07bc32009dee16c69125111f8e4ea9d546b` | C13 comment 5806877682, PASS_SCOPED | 45 SQLite tests; comment binds tree f6d329352dd8484010036448810a927d5eec4be7, differing from older narrative; recalculate before using any historical tree |
| #216 | `ff0005dacc6e3aa6d6ea27003a3ccd5deb4f1de3` | C13 comment 5806893669, PASS_SCOPED | 23 Python+6 Node/static/mobile contract; no physical device |

These records were read from live GitHub comments. Old statements requiring C14 same-scope Hong Kong quality retest do not override the Owner's latest role definition. None automatically becomes a PASS for the new #246 composition.

## Prioritized remaining work and final acceptance

1. C04/C11 deliver rental dispute/deposit source and tests on #246-derived candidate, maintaining single money authority.
2. C01–C12 map internal state/invariant obligations to existing evidence; identify actual uncovered behavior rather than redoing accepted work.
3. C12/C08/C11 provide isolated real-PG transactional concurrency, recovery and bounded write-capacity evidence. Fix threshold/SLA claims to the environment actually measured.
4. C07/C01/C14 distinguish implementable registration/mailbox contracts from formal legal text approval and real delivery. Synthetic positive fixtures cannot enable real registration.
5. C13 independently review the final fixed integrated candidate and raw artifacts after developer completion; confirm full-byte binding, migration chain, no unexplained skips, per-scope results and retained negative tests. Formal opinion requires a separate fresh task; this document is planning evidence only.
6. Native iOS/Android real-device journeys remain explicitly NOT_EXECUTED until performed; this cannot be closed by contract tests. Real supplier/PSP and production execution remain outside this pre-external scope.

Source API basis: `https://api.github.com/repos/yuguangzhi3836-glitch/GO/` PRs, issue comments, contents at frozen SHA, recursive tree and workflow-runs endpoint. No external services invoked.
