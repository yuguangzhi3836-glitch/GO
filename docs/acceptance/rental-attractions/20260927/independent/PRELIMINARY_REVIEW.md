# C04 / C06 independent preliminary review

Status: BLOCKERS_REPRODUCED / FULL_SCOPE_NOT_VERIFIED.

The reviewer did not modify application implementation. All probes used isolated TestClient HTTP, synthetic payment/supplier fixtures, and a fresh local SQLite test database. These are development-time counterexamples, not PostgreSQL concurrency or actual browser/native evidence and not bound to a frozen final candidate. Product files may be under concurrent development; original logs remain unmodified.

Frozen scope is indexed verbatim in SCOPE_REVIEW_INDEX.json: C04 30 obligations / 108 cases, C06 14 obligations / 44 cases. Every complete case remains NOT_VERIFIED until exact candidate-bound evidence and the full required assertions are reviewed. Historical PASS is not transferred.

| Finding | Reproduction | Observed | Required correction |
|---|---|---|---|
| ATTRACTION_WINDOW | Create, pay and issue a synthetic tokyo_skytree voucher dated 2020-01-01; submit consumer redeem in 2026 | HTTP 200, FULFILLED; LEGACY_UNVERIFIED window permits redemption | New usable vouchers need trusted/frozen time policy; absent/unverified window must not authorize redemption; expired window rejects without state mutation |
| ATTRACTION_COMPLETED_MONEY | Complete refund; separately tamper its confirmed REFUND movement amount to 1, currency to USD, or state to UNKNOWN; replay refund via HTTP | All 3 return HTTP 200 / REFUND_COMPLETED | Completed replay must verify actual funds and exact immutable completion evidence, not merely cached receipt/order state |
| RENTAL_COMPLETED_MONEY | Complete rental cancel; separately tamper actual REFUND movement amount/currency/state; replay cancel via HTTP | All 3 return HTTP 200 / REFUND_COMPLETED | Rental has separate completed branches; frozen consent/plan hash alone does not establish actual money truth |

Raw failure evidence: attractions-before.log/xml (4 failures); rental-before.log/xml (3 failures). Probe sources: test_attraction_independent.py and test_rental_independent.py. Failures occurred at intended negative outcome assertions, not setup errors. Fake money tampering is restricted to each isolated fixture database.

Rental deposit compensation was statically reviewed: its money graph already checks captures/compensations, exact double-entry ledger, original capture account reversal, and authority lineage. No PASS or no-defects conclusion follows from that limited read. Rental supplier access is explicitly disabled in the damage workspace until a verified tenant binding exists; complete supplier operations must therefore not be counted implemented based on denial tests. Full role, SLA/escalation, browser/native, interrupted-money recovery, capacity and complete 152-case evidence remain outstanding.

## Development repair review

A fresh process re-ran the original seven counterexamples after repairs, preserving original probes/logs, and added an explicit missing-policy branch by removing only the synthetic fixture's supplier_validity_policy. Result: 8 PASS in review-after.xml/log. Expired synthetic windows and absent policies now refuse redemption; changed refund movement amount/currency/state now refuse completed replay. These are scoped development checks, not final acceptance.

Additional blocker discovered while inspecting the money verification change: the common _confirmed_money_in verifies movements but not corresponding double-entry ledger. test_completed_ledger.py changes only one completed refund ledger entry amount to 1, leaving the movement correct. Both ATTRACTION and RENTAL replay returned HTTP 200 / REFUND_COMPLETED. ledger-before.xml/log record 2 FAIL. Full movement and ledger row snapshots remain unchanged during replay; the defect is a falsely trusted completion response, not an extra payout. This finding remains OPEN pending correction/retest.

The completed-ledger repair was independently re-tested in a new process. Both verticals were tested with refund ledger amount, currency, account code, and evidence hash corruption (8 cases): all reject; all movement/ledger row snapshots remain equal before and after each rejected replay. ledger-after.xml/log: 8 PASS in 9.77 seconds. The initial 2-case ledger probe is retained as ledger_probe_before.py. This closes the reproduced ledger flaw for these tested inputs in the development tree; no frozen-candidate or full-scope PASS is issued.
