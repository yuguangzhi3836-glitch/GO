# C07/C09 scoped product comparability

Base: PR #223, f66129b718dfb9db2a156a46c69cd58674a2de0b. No remote writes, deployment or real provider request.

A fresh verified personal quote remains visible when product terms are missing or unsupported. `eligible_for_price_comparison` is now false in that case. Existing tests were updated intentionally to distinguish verified price display from ranking, while preserving freshness, user isolation, amount and occupancy checks.

The new adapter-normalized `product_terms` contract requires: canonical room identity with GO_CANONICAL_VERIFIED mapping assertion; provider-specific room and rate-plan ids as provenance; explicit ROOM_ONLY/BREAKFAST and breakfast count per room; complete NON_REFUNDABLE or FREE_UNTIL cancellation terms with timezone-aware exact deadline and normalized penalty; PREPAY/PAY_AT_PROPERTY timing; instant/on-request confirmation; explicitly empty additional benefits. Richer meals, nonempty benefits, extra conditions and unsupported policies are visible but unrankable. Provider ids never establish cross-provider equivalence.

Fingerprints include the original complete search-basis fingerprint and normalized product conditions. Rank and savings exist only within a matching group containing two or more valid quotes. Separate groups and singleton groups have no rank or savings. Equivalent cutoff instants normalize across offsets. More than one quote for a provider is rejected explicitly, preserving the existing one-option-per-provider response instead of silently discarding variants.

Authority boundary: as before, `provider_quotes` is a trusted internal adapter input, not an authorization verifier. GO_CANONICAL_VERIFIED is an adapter assertion; this change does not implement an OTA connector, canonical mapping registry, or permit client assertions to substitute for trusted server verification. Wiring a real adapter requires independently authenticated room mappings and complete contractual terms. No current real-provider coverage is claimed. More detailed benefits, child/meal eligibility, installment/payment guarantees, complex multi-stage cancellation and multiple same-provider offers remain future contract work and must not be represented as this narrow normalized schema.

Verification command:

```sh
PYTHONPATH=application/src /workspace/scratch/7375eae00ed5/go-depth-venv/bin/python -m pytest -o addopts= -q application/tests/test_member_product_comparability.py application/tests/test_member_comparison_quote_validity.py application/tests/test_supplier_onboarding_and_member_comparison.py -k 'not member_context_api' --tb=short
```

Raw log: comparison-pytest.log. Member-context API test remains explicitly deselected because its wider route dependencies are not materialized. These SQLite service tests are not browser, full-build, real-provider or formal C13/C14 evidence.
