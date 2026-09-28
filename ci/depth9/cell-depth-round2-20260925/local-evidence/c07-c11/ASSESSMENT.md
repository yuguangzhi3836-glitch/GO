# C07–C11 five-axis development depth assessment

Input: PR #246 `7a290b2` integrated candidate (parent-provided identity and five CI PASS), followed by this round's unmerged isolated source additions. Score is a capability level, **not completion percentage**. 0 absent; 1 definition/skeleton; 2 substantive partial capability; 3 broad implemented and tested capability with material remaining evidence; 4 complete within a frozen explicitly agreed scope. No score here is 4. No live supplier, PSP, browser device or operations observation was substituted with source-code presence.

| Cell | Function closure | Permission / consistency | Failure / recovery | Cross-end experience | Operations evidence |
|---|---:|---:|---:|---:|---:|
| C07 traveler intelligence | 3 | 3 | 3 | 2 | 2 |
| C08 AI planning / execution | 3 | 3 | 3 | 2 | 2 |
| C09 judgment / trust | 3 | 3 | 2 | 2 | 2 |
| C10 unified Trips | 3 | 3 | 3 | 2 | 2 |
| C11 transaction / finance | 3 | 3 | 3 | 2 | 2 |

All paths below are relative to `application/`. Existing tests are cited as evidence entry points, not a claim that each was re-executed this round. Last-round local C07–C11 review ran 206 scoped regressions plus 52 follow-up regressions; its logs remain in `reviews/c07-c11/`. This round's new tests and precise result are in `reviews/round2/c07-c11/`.

| Cell / axis | Evidence entry points | Remaining before level 4 |
|---|---|---|
| C07 function 3 | `src/go_hotel/travel_intelligence/preferences.py`, `service.py`; `tests/test_round2_c07_explicit_preferences.py` | Frozen full intent/profile/behavior journey inventory and independent complete acceptance; current intent extraction has deterministic coverage, not unrestricted semantic completeness. |
| C07 permission 3 | Live purpose/consent locks in `preferences.py`; owner/companion, withdrawal and unregistered-key cases in the same test file | Final candidate complete API/UI permission denial matrix and privacy-purpose review. |
| C07 recovery 3 | `tests/test_round2_c07_process_recovery.py`: committed/uncommitted exit, competing revision, consent withdrawal | Bind PostgreSQL process evidence to final integrated tree and operational restart procedure. |
| C07 cross-end 2 | Authenticated preference HTTP test in `test_round2_c07_explicit_preferences.py` | Complete consumer/mobile visibility, withdrawal and session refresh walkthrough; route tests are not physical device acceptance. |
| C07 operations 2 | `ProfileAccessAuditRow` writes in `preferences.py`, purpose-scoped evidence | Continuous consent expiry/retention/audit monitoring evidence from deployed runtime. |
| C08 function 3 | `src/go_hotel/go_ai/planner.py`, `service.py`; `tests/go_ai/test_c08_complete_task_plan.py` | Frozen end-to-end multi-vertical execution scenarios, including user-visible resumption; all required plan tasks retained does not prove all journeys. |
| C08 permission 3 | Deterministic core authority and audit in `go_ai/service.py`; `tests/go_ai/test_c08_audit_commit_failure.py` | Final integrated tool authority/role denial inventory reviewed independently. |
| C08 recovery 3 | Database-time lease/fencing/checkpoint code; `tests/go_ai/test_c08_durable_execution.py`, `test_c08_hard_exit_recovery.py` | Final-tree PG hard-exit/run takeover evidence plus deployed worker recovery observation. |
| C08 cross-end 2 | `go_ai` service and request audit API; synthesis finalization tests | C/B/admin/mobile interruption, reconnect, progress and final-result presentation journey. |
| C08 operations 2 | Request/attempt audit, cost/provider registry and recovery assessment in `go_ai/service.py` | Sustained queue/lease/latency/cost alerting and incident closure evidence. |
| C09 function 3 | `src/go_hotel/judgment/service.py`, `good_hotel_standard.py`; `tests/judgment/test_round2_evidence_authority.py` | Complete frozen recommendation/risk-evidence freshness scenario inventory. |
| C09 permission 3 | Persisted evidence authority and commercial fields excluded in `judgment/service.py`; six-dimension/explicit attestation tests | Independent final cross-role mutation/override and rule-revision acceptance. |
| C09 recovery 2 | Judgment hook processing and `tests/judgment/test_next_depth_concurrent_judgment.py` | Risk update→hook interruption→recovery→recommendation invalidation end-to-end evidence still needs explicit binding and complete operational acceptance. |
| C09 cross-end 2 | `api/routes/judgment.py`, public judgment view | Consumer explanation and admin evidence correction/invalidation visible journey across devices. |
| C09 operations 2 | Judgment evidence packages / decision versions / hook worker | Continuous freshness, stale evidence and serious-risk escalation observation. |
| C10 function 3 | `services/consumer_unified_lifecycle.py`, `consumer_trip_index.py`; unified/external Trips tests | Complete native/external booking→changes→refunds timeline inventory and cross-domain reconciliation acceptance. |
| C10 permission 3 | Immutable account/supplier; authoritative payment source route; `tests/test_c10_lifecycle_supplier_identity.py` | Final cross-tenant API/UI proof for all entry points and historical-repair policy. |
| C10 recovery 3 | Stale replay guards; source/parent/ledger-bound supplier payment projection; `tests/test_c10_supplier_money_projection.py` | Broader late event/recovery propagation matrix tied to PG candidate, not only scoped SQLite regression. |
| C10 cross-end 2 | `tests/test_depth29_trip_reentry.py`, `test_depth43_hotel_change_trips.py`; Trips navigation | Full three-end/mobile visual itinerary and after-sales journeys. |
| C10 operations 2 | Lifecycle event/evidence references and source timestamps | Continuous projection lag, orphan/mismatch detection and safe manual repair evidence. |
| C11 function 3 | `services/omnichannel_payment.py`, `unified_money_movement.py`; new `rental_deposit_money.py` | New isolated deposit path still needs independent final acceptance; post-settlement appeal compensation and real provider certification are distinct remaining scopes. |
| C11 permission 3 | `create_consumer_intent`, original FactBinding/Root; `tests/test_c11_consumer_payment_source_boundary.py`; new source-scope deposit guard | Full generic ingress/callback/command-center authority inventory final review. |
| C11 recovery 3 | `tests/payments/test_c11_flight_idempotency_recovery.py`; deposit atomic rollback/retry, unknown denial and concurrency tests | Deposit PG race and process termination evidence; UNKNOWN is safe HOLD, not completed reconciliation automation. |
| C11 cross-end 2 | Existing payment routes and owner-checked deposit status; strict internal authorization/settlement schema | Integrated C/B/admin/mobile complete money and after-sales UX with no inferred success. |
| C11 operations 2 | Root/movement/ledger reconciliation and scoped close, deposit source/hash validation | Deployed close/recovery scans, monitoring/alert resolution and independent operational ledger evidence. |

Boundary: scoring does not downgrade previously accepted facts. It distinguishes source/function evidence from remaining cross-end and operational evidence. Candidate completion does not imply Hong Kong or Production deployment, or real funds readiness.
