# Current RENTAL / Personal Vault guard repairs

Owner direction, 2026-10-02: abandon PR217; still fix confirmed gaps in current code.

Base: PR320 `eeafca1b15a4754ba36a0f138a27347cbbd12c73`, application tree `6f97ac5d572dae1de0b3e38b6201da2a6de14216`.
This is a forward fix on that explicit candidate, not a migration of PR217 and not a claim that PR320 is deployed.

Change classes: PRODUCT_FIX / TEST_ONLY / DOCUMENTATION. No schema migration, topology change, credential change, merge or deployment.

## Implemented

- RENTAL change completion reads durable capture / authorization, payment root, payer, payee, currency, business identity, amount, idempotency key and capture ledger. An executor response alone cannot finalize a change.
- Reduced-price change refunds reuse the existing authoritative refund verifier and additionally compare the full multiset of intent / capture / amount / key with the frozen plan. Plan ownership and allocation keys are checked before executing refunds. Completed retries revalidate their evidence and receipts.
- Public profile imports reject server-owned metadata and invalid metadata types before insertion. Normal arbitrary descriptive metadata still works.
- Provider callbacks and export uploads use an internal import path that constructs reserved metadata only after checking the owned connection, consumed state, provider, source type/reference and expected fingerprint. `trusted_source` retains its original verification meaning; it is not used as a blanket reserved-metadata bypass.
- Fingerprint replay cannot cross provider-connection bindings or alias a connection-intent row. An authorization callback cannot reset a disconnected connection to PREVIEW_READY.

## Validation and evidence

See `validation.json` for local test counts, versions and source hashes. The local database is temporary SQLite, not HK or production.

Tests cover metadata injection through HTTP and service calls, provider binding mutations, legitimate official authorization and file uploads, nonreserved metadata and ordinary replay, forged or missing capture/refund receipts, ledger corruption, frozen refund allocation mismatch, completed receipt revalidation, concurrent same-quote retry, partial refund recovery, and interruption after durable money commit but before order completion.

The original PR320 source fails three new representative tests: client `connection_intent` injection; a missing top-up capture receipt; a refund receipt with the wrong allocation key. These cases pass with the repair.

An exploratory broader run found three failures. The frontend static test was invoked from the repository root instead of application and passes from the correct directory. Two unrelated attraction assertions fail identically on original PR320: `test_attraction_redemption_unknown_recovery_closed_and_illegal_states` and `test_attraction_supplier_closure_blocks_consumer_mutations`. They are not fixed or waived by this PR. The scoped final suite includes the existing RENTAL UNKNOWN compatibility test.

The added GitHub workflow runs the scoped suite separately on SQLite and PostgreSQL 18.4. A workflow definition is not a passing execution; CI outcomes must be read from the actual runs. No C14/C13 opinion is claimed or inherited.

## Remaining historical-data-dependent work (OPEN)

RENTAL UNKNOWN episode anti-reuse, strict confirmation correlation, and stricter recovery-chain validation are not enabled in this patch. The handoff identified a supplier-fulfillment path that writes legacy UNKNOWN payloads without required fields, and callers that omit confirmation_episode_reference. Turning on the old strict validator can strand existing orders.

Before implementing/enabling that part, obtain a read-only HK aggregate report (no customer payloads or credentials):

1. RENTAL evidence-chain tail status versus order status; counts of missing/broken chains.
2. UNKNOWN payload counts missing previous_status, actor or supplier_reference, grouped by entry path and recoverable order state.
3. Evidence references reused across UNKNOWN episodes within one order, with separate counts for current unresolved episodes.
4. Property publication_state distribution to validate the reported obsolete draft-only guard.
5. Provider import fingerprints and provider_connection_id binding mismatches, and server-reserved metadata observed in ordinary imports.

No live query, historical data rewrite or backfill has been performed in this work. Existing UNKNOWN recovery behavior and HTTP semantics remain unchanged. These open items are not declared fixed merely because PR217 is closed. A compatibility fix must distinguish new episodes from legacy records using durable evidence, retain a tested recovery path, and revalidate the eventual candidate through C14 then C13 before release.

## Review / integration

This PR targets PR320's branch to expose only the small forward-fix delta. Do not overwrite PR320 or any current main/application tree with PR217. Integrate only after candidate-specific review and tests, then repeat the required final-candidate release gates. Rollback is the inverse of this patch; it does not require a database downgrade.
