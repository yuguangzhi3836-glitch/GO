# C02/C03 local depth continuation — 2026-09-18

Candidate source commit: `7af43cc64cdae062389950baca3518e11512d4b1`. Base: `42f3e62da844279cc3569c90eaa58d24a291a4d5`. Source is a local candidate, not remote PR/canonical or a runtime artifact.

Flight prebooks are now consumed once in a transaction. Same owner and passenger retries return the original order across restart, expiry and changed HTTP keys. Changed owners/passengers cannot claim the booking; historical single orders remain recoverable and historical duplicate orders require review. An evidence write failure rolls the claim back. The existing PostgreSQL row lock / SQLite immediate transaction helper is used; PostgreSQL execution remains unverified in this session.

Rail selecting a change supersedes all unselected quotes under the same order lock. Quote issuance uses that lock too. Authorization failure can resume the selected quote, while supplier success/failure requires a fresh quote for another choice. Existing capacity and money decisions are preserved.

The missing PR208 change-quote idempotency route delta and original two HTTP identity/idempotency tests are included. PR216 airport source and its expanded test superset are preserved byte-for-byte. The older airport resolver is not copied over newer work.

Before repair: 12 tests, 10 failed, 2 passed. Final affected regression: **203 passed, 0 failed, 0 skipped**. Raw pytest logs, JUnit, exact commands and changed-source SHA256 are adjacent. `focused` records an intermediate 30-test run, not the final source result. Final run includes 13 new defect checks, inherited HTTP checks and existing flight/rail lifecycle, capacity, multi-party, refund and C11 recovery coverage.

GAP → TASK → TEST → EVIDENCE mappings and NEXT_TASK are in SOURCE_BINDING.json. Final integrated-tree C14 and independent C13 review are pending. No provider, live environment, browser/physical-device or global 100% acceptance is claimed. No schema/topology change, remote write, merge or deployment occurred.
