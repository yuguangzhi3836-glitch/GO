# Round 5 independent scoped source review

Base: PR #223, commit f66129b718dfb9db2a156a46c69cd58674a2de0b.

Result: no remaining blocking source defect identified in the reviewed narrow changes after the fixes below. This is an independent source review, not formal C14 approval, C13 acceptance, a full build, or browser acceptance. Publication remains blocked by design.

## Findings resolved before review closure

- Product equivalence: malformed meal and penalty enum values could raise TypeError rather than suppress comparison. Membership validation now safely rejects malformed values; tests cover list values.
- Meal/benefit equivalence: breakfast count alone cannot describe half-board/all-inclusive packages, and an opaque AIRPORT_TRANSFER label cannot establish equal quantities or service scope. Only room-only/breakfast and explicitly empty extra benefits are currently comparable. Richer products retain verified price display but no rank or savings.
- Registration approval: a reviewer name/time on a rejected registration is not approval. The verifier now always retains the registration-review and trusted canonical-room-mapping blockers. Supplier-editable metadata cannot remove them.
- Current rights: server approval alone must not validate a mismatched or expired submission declaration. Per-asset current_rights_verified now requires exact matching declaration, current declaration expiry, valid server grant, correct distribution scope, reviewer metadata and matching evidence. The expiry regression uses a matching expired persisted declaration while the reviewed grant remains unexpired, independently exercising declaration expiry rather than a mismatch.

## Reviewed behavior and limits

The comparison fingerprint uses the complete search-basis fingerprint, canonical room, meal, cancellation instant and penalty, payment timing, confirmation mode and benefit contract. Provider room/rate ids are retained as provenance and are not used as cross-provider equivalence. Different groups and singleton groups receive no rank or savings. Multiple quotes for one provider are explicitly rejected instead of silently overwritten.

The quote service still trusts its internal official-adapter input. GO_CANONICAL_VERIFIED is an adapter assertion, not an independent mapping registry implemented by this patch. Real adapter integration must authenticate canonical mappings and must not expose this assertion as client-controlled authority. No real-provider evidence is claimed.

The manifest endpoint authenticates supplier ownership before resolving submission facts, reads the cached original bytes, compares SHA-256/size/decoded image dimensions/MIME, checks current media rights and checks property room inventory. It writes no image, mapping, rights or publication approval. Canonical room inventory, registration approval of the particular manifest and independent association evidence remain unverified. Success-shaped HTTP 200 responses still contain verification_state BLOCKED and publishable/published/rights_granted false.

## Evidence examined

- comparison-pytest.log: 52 passed, 1 explicitly deselected member-context API test.
- manifest-verification.xml and command/log: 16 passed using isolated SQLite and real uploaded image bytes; HTTP dependency tests cover unauthenticated 401 and foreign supplier 404.
- Reviewer independently executed five pure comparison probes: accepted narrow contract; distinct provider IDs share the same canonical group; malformed meal, ambiguous benefit and malformed confirmation mode all suppress comparison. These probes used sqlite:// only for module import and did not access a shared database. Initial import without DATABASE_URL failed because the default PostgreSQL driver is not installed; the isolated import then passed. No PostgreSQL evidence is claimed.

## Reviewed source SHA-256

- `application/src/go_hotel/services/consumer_ota_comparison.py`: `dcb09a917a02db95d04e06c6eb32fdf257e573d79424b051b33a668cc069358b`
- `application/src/go_hotel/services/hotel_direct_submission_verification.py`: `7046fb2f8fb2e0382bfcceb0a202ae8c5b60071b8aafb07b64209dca21a8936f`
- `application/src/go_hotel/api/routes/hotel_partner_core.py`: `2dde8cf67711117b7d7af730e9e769b8066aac12585ef137788ca4ffec30ba24`
