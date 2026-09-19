# Independent scoped review — round 6

Status: scoped review passed after corrections and independent retests. No unresolved blocking finding in the reviewed change. This is an independent code review, not formal C14/C13, full-application acceptance, or a real browser result.

Reviewed trusted binding service/verifier, publication adapter, canonical factory, quality gates, administrator routes and original-byte route. Supplier submission cannot approve itself through editable JSON. Approval/revocation requires existing administrator permission. Public originals require an actively published reviewed page and current ownership, registration, complete room inventory, rights and original integrity. Legacy public media route rejects direct uploads. Official-web gate remains a separate branch.

Findings:
1. Approval/revocation serialized on the review row using FOR UPDATE after review identified a stale-row race. PostgreSQL concurrency not executed.
2. Confirmed publication erased approved profile facts if source snapshots were absent; fixed by validation inside ingestion transaction. Independent destructive probe now passes.
3. Confirmed residual same-room-ID stale source snapshot changes physical room facts before publication error; profile mutation persisted. Fixed by comparing every merged canonical field except the reviewed pointer against the existing canonical facts inside the ingestion transaction, before commit. Both independent destructive probes now PASS.
4. Direct-source quality now retains source-conflict gates; the changed branch consults the server review resolver, never a supplier approval flag. Binding snapshot now also includes hotel core fields, not only room inventory.

Independent execution: 32 binding/verifier cases passed. Final publication/API/independent-probe run: 20 cases passed, exit code 0, including both destructive probes, revocation/rights/integrity/inventory changes, prepublication access, legacy gate, source conflict, rollback and retry. See accompanying command/log and probe file. These counts overlap root tests and must not be added to root totals as distinct coverage. Final inspected source hashes are recorded in independent-source-hashes.json.

Limits: isolated SQLite and actual generated JPEG bytes; synthetic test principals at current_principal dependency for API tests. No production authentication, real hotel images, PostgreSQL concurrency, full application build, cloud-browser acceptance, or load testing. Public reads verify full manifests/originals and have not been performance qualified. No merge or deployment performed by this reviewer.
