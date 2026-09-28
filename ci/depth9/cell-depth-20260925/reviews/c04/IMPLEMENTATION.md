# C04 rental damage case increment

Base: PR #246, commit 6acf9fdcde4b208b12a8c9d57ef74497e745faae. Four modified/new files are bound in MANIFEST.json.

Implemented: persisted append-only evidence under the existing rental order lock; immutable initial synthetic contract and inspection submissions; one case per order; consumer accept/dispute response; distinct authorized administrator adjudication; owner/role isolation; bounded amounts; expected revision; exact command replay/conflicting-payload refusal; authenticated API routes. Main adds router import and include only. No migration/new table.

Money: no C11 root, intent, movement or ledger writes. Adjudication ends in C11_MONEY_REVIEW_REQUIRED, including zero awards (a zero award is not evidence of deposit release). No payment callback or supplier execution. Runtime writes restricted to local/test/demo.

Source limitations: existing rental schema has no verified supplier tenant/vehicle/contract-policy identity. Consequently supplier users are denied direct case access. Administrator records isolated inspection references and digests with ADMIN_RECORDED_UNVERIFIED status; this is not supplier authentication, authenticated media or an approved real contract. Snapshot amounts come from existing isolated rental fixture. No legal liability/deadline/default acceptance rule is invented.

Remaining: approved contract provenance/version and vehicle/media binding; scoped supplier intake; supplementary evidence and appeals/compensating decisions; C11 dedicated rental deposit/damage fact binding and authorization/capture/release semantics; unknown-outcome reconciliation; complete API/frontend journey; isolated PostgreSQL acceptance. This is not rental 100% or deposit funds closure.

Tests: 21 passed using frozen dependencies, isolated SQLite. Includes HTTP principal/body-injection rejection; wrong-owner/supplier/readonly denial; independent adjudicator; maximum amounts; full insurance zero-cap refusal; exact replays; conflicting payloads; competing responses; competing open retries; frozen policy snapshot; injected failure after evidence flush with rollback and successful retry; staging writes denied; no money movements. JUnit: ../c04-rental-damage-junit.xml.

No GitHub write, Hong Kong operation, deployment or merge performed by C04.

C13 independent review found missing evidence-chain validation. Fixed before acceptance: validate complete chain ordering/hashes, row execution item, embedded order/vertical, and case owner. Five corruption regressions prove no continuation or new evidence on damaged history.

Existing rental regression: 16 passed (test_depth06_rental_settlement.py and test_v70_round2_c04_rental_receipts.py), JUnit ../c04-rental-regression-junit.xml. New + regression total 37 tests.

Round 2: consumer appeal preserves earlier adjudication, sets DISPUTE_HOLD and removes actionable award. An independently authorized reviewer distinct from claimant, owner, and all prior reviewers may revise the business decision; linked decision history is retained. No timeout/default consent. Money remains C11_MONEY_REVIEW_REQUIRED. New suite 26 passed, including appeal crash rollback, concurrent reviewers, API role isolation and historical evidence preservation. Snapshot in MANIFEST_ROUND2.json.
