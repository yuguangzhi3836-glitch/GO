# C14 evidence publication and 429 diagnostics repair

Classes: CONTROL_PLANE, TEST_ONLY, DOCUMENTATION.
Base: 5d907a398c7662d4e4b91425b47e1a857ddbe7b6.
Related candidate: #273 cb96de655f0c84596e85b379c6e9bd67f92817fe; ledger #270.

## Defects and change

The raw-evidence guard refuses the entire artifact when the complete first-parent
diff contains historical bearer values, including removed lines. The change
creates a publication-only `facts_redacted_projection.json` when needed. It
replaces only matching bearer strings in `candidate_diff`; all diff lines,
prefixes, hunks and paths remain. Original facts, reviewer inputs, scope,
contract, opinion, seal inputs and candidate identity are not changed.

The manifest explicitly labels the projection and records original byte and
canonical digests, public-byte digest, count and affected line numbers. It does
not claim to contain original facts; a verifier needing the originals must
reconstruct them from the frozen repository and inputs and verify the original
digest. It must not use the projection as original evidence or a seal input.
No secret values or per-secret hashes are recorded. Other secret patterns and
all fields outside candidate_diff still trigger publication refusal. Decoded
diff text is scanned so JSON escaping cannot conceal multiline patterns.

The prior classifier maps every HTTP 429 to AI_QUOTA_EXHAUSTED, conflating
temporary rate limiting with billing exhaustion. Only explicit quota wording
now selects AI_QUOTA_EXHAUSTED; other 429s use existing AI_PROVIDER_FAILURE.
Both remain BLOCKED; there is no model fallback, credential replacement,
automatic retry or change to C13 admission. The previous run's classification
alone cannot establish an exhausted account balance. The next run must retain
the provider diagnostic before an operational conclusion is drawn.

## Local validation

Command (from control-plane/c13-c14-lite):

`python -m unittest test_lite_public_projection test_lite_defect_fixes.RawEvidencePreservationTests test_lite_contract test_lite_negative_suite`

73 tests passed. Initial run: 72 passed, one new multiline-pattern test failed
because JSON escaped the newline; decoded-diff scanning fixed that defect.
Synthetic tokens only; no API/network call, live credential or deployment.

Validation includes removed/added/context lines, original-byte preservation,
projection digests, clean-byte identity, scan-before-write refusal for other
fields and secret classes, preserved BLOCKED outcome, explicit quota and
rate-limit distinction, existing contract and negative admission suites.

## Remaining gates

This is a proposed control-plane repair, not formal product C14/C13 acceptance.
It needs review and authorized merge before use on the canonical backend.
After activation, run fresh C14 against the unchanged product candidate and
read the published result. Only an admissible result permits C13. If the API
then reports actual insufficient quota, the existing account/project's credit
or limit must be restored by its authorized account operator. No account
settings, funds, secrets, Hong Kong runtime or registration admission changed.
