# C04 deposit source and consumer consent authority

Implemented on parent-provided PR246 7a290b2 local workspace. No remote write, deployment, real supplier/PSP or financial fact created by C04.

- New server-owned isolated contract fixture derives deposit amount/currency/insurance from known COMPACT/SUV fixtures and checks the order matches. A caller cannot submit amount/payee/vehicle or select live/fixture bypass via request.
- Source freezes order, owner, synthetic vehicle, verified-synthetic payee (explicit real_payee_verified=false), full terms hash, fixture version, currency, cap and 24-hour fixture validity. This validity is engineering data, not a real supplier deadline or law.
- PROPOSED revision 1 becomes ACTIVATED on the next revision only when the authenticated consumer explicitly accepts the exact source hash. ACTIVATED is agreement, not an authorization/capture receipt. No default consent or timeout transition.
- Source identity is durable: existing evidence table and append-only order chain; deterministic initial event primary key makes a second obligation for the same order impossible at DB level. Order lock serializes proposals/consent; full sequence/hash/order/owner validation rejects damaged history.
- Server resolver locks order first, verifies current accepted source revision/hash/consent and current order-source match, and returns immutable facts for C11. New authorization/capture denies expiry and ineligible order status. Internal allow_expired exists only for proven authorization release or evidence lookup; it is never user/API controlled and is not a money instruction.
- A damage case freezes its accepted deposit source binding when opened. Historical unbound cases remain unbound and cannot settle against a new deposit. Latest adjudication version/hash is mandatory; appeal hold rejects consumption, and a subsequent decision has a new hash. C11 remains sole authority for money instructions/receipts/ledger and compensation.
- New routes: owner proposal/acceptance, scoped current obligation and latest damage-case discovery, authorized decision preview. Root handles main router mounting and frontend.

Validation: 28 new source/release tests plus 26 existing damage tests, 54 passed using frozen Python dependencies, no pytest cacheprovider. Covers no inferred consent, full source hash, server-derived amounts, wrong owner/admin/supplier consent, HTTP field spoofing, expiry, source drift, crash rollback, concurrent proposal/retry, unique DB anchor, detached anchor rejection, historical case hold, source-bound decision and appeal hold, no financial facts. JUnit authority-junit.xml.

Internal remaining scope: C11 isolated movement integration/receipt consumption (parallel owner); source amendment/revocation and related release orchestration are not implemented, so revisions are immutable once accepted rather than silently rewritten; approved media intake and full client/admin dispute workflow; periodic operational queue and recovery evidence; PostgreSQL concurrency verification for the new source path. These are not asserted complete.

External prerequisites separately: real supplier tenant/payee/vehicle binding, approved real contract/policy provenance, real media authenticity, PSP/business onboarding and official runner/release authority. None is fabricated and absence does not reduce internal mechanism scores.

## Independent review corrections and normal release closure

C13 found that an expired unaccepted proposal had no recovery path. Added explicit consumer renewal only for an expired PROPOSED obligation: same obligation identity, append new revision/source hash, and require fresh acceptance. Accepted obligations cannot renew or silently change. Competing renewals are serialized and stale old hash is refused.

Root/C14 identified missing ordinary no-damage return and cancellation release. Added a separate admin final-inspection business fact, with no fake zero-damage case. Requires an accepted source, distinct admin from owner, no damage case at all, and COMPLETED status or REFUNDED with existing read-only refund reconciliation proving MATCHED_COMPLETED. Consumer return status alone cannot authorize release. One deterministic release-fact PK anchor per order; later damage case opening is blocked; C11 resolves the latest fact and owns all actual release movements.

C04 readonly release resolver carries release_revision/hash, obligation/source revision, order/owner/payee/currency, reason and isolation flags. No amount is supplied by caller or approved in this fact; C11 must release only confirmed remaining authorization. Tests include expiry, unproven cancelled-state refusal, full original-rental cancel positive flow, concurrent return/claim mutual exclusion, return-audit crash rollback, API identity boundaries, and no new financial facts.
