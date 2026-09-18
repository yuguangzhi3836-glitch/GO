# Hyatt gallery media UI — independent local candidate

Base: PR 195 `f2976f9cebe9555e8eab424817d956bf611fe19f`. Exact frontend and media_harvester source blobs verified. No commits, submission, deployment, browser login or live API calls were made. The fixed `catalog-import-ui/` candidate was not changed.

Ready files:

- application/frontend/admin/hotel-page-factory.js
- application/tests_frontend/hotel_catalog_hyatt_gallery.test.mjs
- application/tests_frontend/fixtures/aoluguya_hyatt_gallery_harvest_plan.json

Adds a normal product panel on the primary Aoluguya detail page: select approved Hyatt-gallery JSON, review existing/pending images, then sequentially harvest with per-image progress. It preserves the scope-archive and facts-import controls inherited from PR195. A shared page mutation flag prevents overlapping fact/media button submissions in that page; it is not a cross-browser/database lock.

The JSON is bound to the real C01 plan by semantic SHA256 `4e59c43e72ef21a5ee3333381adb146bd84599b5cb58cf70ec0f7b2d4aa535eb`; altered content, official URL, rights, expected bytes or invented harvest kwargs are rejected. Only the 21 fixed Hyatt official image URLs are submitted. The plan's local EASON filenames and expected hash metadata never become harvest request fields. Each request is GALLERY + OFFICIAL_WEBSITE, has no room_type_id, and does not call rights/publication/compose or any other mutation API. Historical 17-room mappings are not inferred.

Uses existing ctx.api and normal admin:rules authorization only. No credential/token/cookie extraction, custom fetch or direct database access. Requires reviewed protected scope to be active, no running regional builds, and 17 unique room records with a DRAFT page before harvesting.

Before each POST, rereads existing asset metadata. A single matching source URL must match protected hotel identity, GALLERY role, null room binding, official source, expected SHA256/byte_size/width/height/MIME, RIGHTS_UNKNOWN, publishable=false and VALIDATED cache state. Matching records are reused. Ambiguous duplicate URL records, mismatched metadata or changed rights stop before a new write. After each POST, compares the returned metadata and rereads the index for the same asset ID and metadata. A lost POST response stops the run; a later review/retry rereads the existing index before issuing another POST, preventing a blind replay. Concurrent administrators in different pages can still race because the existing harvest API has no idempotency key contract; no cross-client exactly-once claim is made.

Any mismatch stops subsequent harvest. The failed response may already have created an indexed RIGHTS_UNKNOWN asset. Neither UI nor report claims transactional rollback. Final index checks all 21 planned records and confirms page DRAFT. It never grants authorization, binds historical room IDs, publishes the page, claims 199 original images recovered, or claims every room has three photos.

## Verification boundary

The existing harvester computes SHA256 from downloaded bytes and validates dimensions/MIME before admitting the cache file; this UI verifies its response and index against C01 expected bytes metadata. **This is not independent served-byte hash verification.** The existing JSON-only ctx.api does not return binary bodies for hashing. The result explicitly sets `independentServedByteHashVerified: false`, and the product text says file readback and rights review remain pending. C01 plan's admin content byte-hash check and public-content denial must still be performed as separate approved post-import acceptance; they have not been completed by this patch.

Product authorization remains distinct from deployment acceptance: root must verify exact integrated-candidate signed DEPLOY/VERIFY and fresh host identity before any live click, as already required. No deployment proof/key upload is added to the hotel UI and no deployment gate is waived.

Inherited fact-import identity preflight sees the primary/secondary visible profiles; it cannot inspect 112 already-archived profiles. Global source-identity conflicts remain enforced by the backend during ingestion. As with the original sequential API workflow, an earlier UNPUBLISH/source write may have completed before a later source conflicts; no global all-or-nothing promise is made.

Validation: syntax check PASS; 9 media behavioral tests PASS; all 12 inherited scope/facts behavioral tests PASS against the new frontend file. Coverage includes exact plan verification, unauthorized/no-write, supported harvest arguments, existing reuse, lost-response retry, metadata mismatch stopping, duplicate-record rejection, absent readback, rights and room-binding rejection. Tests use the actual browser module and API doubles, not a live browser or server. No visual/browser or live acceptance is claimed.
