# C04 internal development depth — evidence scores (0–4)

Scoring object: implemented isolated rental domain, including original booking/change/refund and new damage/deposit source boundary. Scores are judgments, not test-count percentages. 4 requires an internally complete demonstrated lifecycle. External approvals/suppliers are listed separately and are not deducted from internal scores.

| Dimension | Score | Evidence and remaining internal gap |
|---|---:|---|
| Functionality | 3 | Rental booking/change/refund plus persisted dispute, appeal and accepted deposit source implemented. C11 capture/release integration is in progress; source amendment/revocation and full compensation closure are not yet verified. |
| Permission and consistency | 3 | Owner isolation, authenticated role checks, independent maker/checker, current decision fencing, full chain integrity, server-resolved immutable source and unique obligation anchor. End-to-end C11 instruction authority integration awaits independent verification. |
| Recovery | 3 | Replay/conflict fences, order serialization, concurrent retries, post-flush rollback and resumption tested. New deposit-source path still needs PostgreSQL concurrent/crash evidence and C11 unknown-outcome closure. |
| Cross-end journey | 2 | Consumer/admin authenticated APIs and existing rental after-sales page exist. Root is adding deposit view/accept UI; full source→authorize→dispute→appeal→money-status journey has not been independently driven across browser/mobile. |
| Operations | 2 | Durable evidence, current-case discovery, read-only source/decision verification and explicit held states support review. No proven scheduled queue, alert, expiry release, or operator takeover loop for the deposit/dispute path yet. |

External HOLD (separate): real contract/payee/vehicle/media trust, live supplier/PSP and deployment approval. Source is explicitly synthetic; no claim of legal or external production acceptance.
