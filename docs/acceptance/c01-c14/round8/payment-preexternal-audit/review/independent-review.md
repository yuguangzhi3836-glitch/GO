# C13 independent review: FAIL

Scope: supplied minimal dependency subset reconstructed from parent candidate 138e24d76a9f87b9fac9862c7f44a523679aef0b. This review did not independently verify the repository reconstruction or the reported 17 upstream blob identities. No implementation changes, real PSP calls, merchant secrets, Hong Kong actions, deployment, GitHub writes, or merge were performed.

## Independently reproduced findings

1. HIGH — Resource identity validation is bypassed by discovery filtering. `_events` selects only matching `resource_type` and `resource_id` before `_chain_valid` checks them. Changing either identity field on the sole grant causes the existing damaged event to disappear; a new grant is committed instead of raising EVIDENCE_CHAIN_INVALID. Both field cases reproduced. This directly violates the scoped rule that damaged audit data must block continued certification writes. This finding does not claim protection against a DBA rewriting an entire chain or deleting a complete tail; those require independent trusted anchoring.
2. HIGH — Concurrent appends can commit an audit fork. Two independent SQLite sessions read the existing tail, with a Barrier placed after the actual `_events` read to deterministically reproduce the interleaving. Both `_append_event` transactions then commit successfully. The resulting ledger is invalid and authorization fails closed, creating an availability/integrity failure. The barrier alters scheduling only, not returned data or writes. Not all entry points lock a shared row and there is no atomic chain-head comparison/constraint.
3. MEDIUM — `certification_preflight()['payment_sandbox_certified']` trusts merchant state alone. After grant actor tampering, `status()['certification_valid']` is false, but preflight still reports certification true. This is a cross-layer false-positive status, not a demonstrated real payment execution bypass.

## Minimal repair directions

Discover candidate events with an independent marker (e.g. the existing PAYMENT_SANDBOX_CONTROL audit role) and validate identity, using link closure to catch displaced successors; do not make both discovery and validation depend only on the same mutable identity. Clearly document limits without independent persisted chain heads. Serialize every per-channel append at the database boundary or use an atomic versioned chain-head compare-and-swap, including grant, kill switch and approval paths. Reuse validated cutover certification state in preflight.

## Independently executed checks

- `PYTHONPATH=src python -m pytest tests/test_payment_sandbox_audit_integrity.py -q --junitxml=review/independent-baseline.xml`: 19 passed.
- `PYTHONPATH=src:tests python -m pytest review/test_independent_review.py -q --junitxml=review/independent-adversarial.xml`: 4 failed, reproducing the three findings above.
- readiness gate: PASS; certification gate: PASS; cutover safety gate: PASS (all use isolated local SQLite and fake delegate).
- Missing full-repository pytest config yields the expected unknown no_db mark warning.

Existing tests and gates therefore pass while independent adversarial checks fail. This candidate is FAIL, not PASS_SCOPED. Neither local results nor a future scoped pass establishes full payment business-journey 100%, production database concurrency safety, provider/network correctness, real callback authentication, settlement correctness or readiness for external payment connection.

## Verified source SHA256

- `src/go_hotel/services/payment_sandbox_cutover.py`: `4500d18dcc709fed8ade0728faaeade102045d739686e12b1790f9e881d73c99`
- `src/go_hotel/services/payment_sandbox_runtime.py`: `12927728159841c4ada8bc7ba3726c57c03fc4c1a9711fa6a9ec687fd9f3fdaa`
- `tests/test_payment_sandbox_audit_integrity.py`: `409735cf7d2e11e5a54aa42114b5b384333c60b2f371a03714418411587b4d1b`
