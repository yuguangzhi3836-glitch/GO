# Independent scoped review — round 3

Review date: 2026-09-19. Reviewer: independent agent r3_review; product files were not edited by the reviewer. This is a source-candidate review, not formal C14/C13 acceptance and not deployment authorization.

## Scope and outcome

Reviewed supplier property selection, explicit source-room mapping UI, direct-media draft binding and publication-request API, and property-specific canonical webpage lookup. The scoped candidate is suitable for a Draft PR with the limitations below. Canonical media promotion and real browser acceptance remain incomplete; do not call this full publication or 100% completion.

Confirmed by inspection:

- Property-specific workspace resolves only a registration with both matching supplier and explicit property identity; it no longer guesses the newest account-level registration. Multiple properties without selection fail closed.
- Source-room mappings require explicit target/create selection and a confirmation for each source identity. Foreign or repeated target identities are rejected client-side; backend ownership validation remains authoritative.
- Media binding authenticates the supplier/property and room ownership, verifies original bytes, writes draft bindings, and does not modify canonical publication state. A different role/room produces an additive derivative identity rather than moving or deleting the previous binding. Rights are not copied from the prior identity.
- Publication requests require confirmed, bound, same-property assets and reject invalid batches before persisting a request. The response expressly says unpublished and retains the canonical-review blocker. There is no new supplier-controlled rights approval or canonical publishing bypass.

## Findings and remediation

1. Upload read the selected room from live DOM after FileReader completed, risking navigation to a different DOM. Fixed by capturing room identity before awaiting and checking the builder identity before POST.
2. Import and upload had separate busy guards and could overlap. Both now consult the shared operation guard; hotel switching also rejects in-flight requests.
3. A saved import-draft callback could dereference missing nodes after navigating away. The callback now returns unless its original builder is current. Builder preload checks sequence/hash before rendering stale data.
4. Publication history previously labelled every request PUBLISH_REQUESTED, including non-submitted states. The media service now derives a review-state label from the stored request state.

## Verification and limits

Reviewer independently ran `node --test application/tests/test_supplier_hotel_import_ui.cjs`: 21 passed, 0 failed. This uses a bounded DOM/request harness, not a browser or actual HTTP backend. Backend persistence/HTTP tests were inspected; the root agent runs and records the final backend suite separately to avoid concurrent access to the shared test database.

Real cloud browser access to the local test page was reported blocked by ERR_BLOCKED_BY_CLIENT. No rendered desktop/mobile acceptance is claimed. Legacy unrelated route handlers retain pre-existing asynchronous navigation behavior; this review is scoped to the changed hotel selection/builder paths. Media-binding revision validation is a snapshot check, not an atomic cross-database transaction. The cache and partner database remain distinct stores. Role changes are additive usage bindings, not unbind/replace functionality.

## Inspected content hashes (SHA-256)

```text
d367c454789387cd2437821e0c55edc4dc30625daaee9fcaf766af8b4020e7f2  application/frontend/shared/app.js
04504f8253ff9b2ae75a017a9305dfea0ab26fe9791573fe1e9e6aa18d2dbc0b  application/src/go_hotel/services/hotel_partner_core.py
5e5f56edc4a80ade7e53e3737ed6353734976297f33e9c1c9c96f6b257b7a141  application/src/go_hotel/services/hotel_partner_media_upload.py
3bb264e7f7b9d0e237771136fd3d87f648754ba68131022a32991d605e4fa2ab  application/src/go_hotel/api/routes/hotel_partner_core.py
e10b0587248d7f33142fde64b5077f2b07162c474049db406ea9b78392cfbe5f  application/tests/test_supplier_hotel_import_ui.cjs
12d50b89ca836cd773f8d41f2aa71edf17443cb41ca69952f2fa7cec3961c20b  application/tests/test_hotel_property_workspace.py
cb6a2bc717415b9b74036eb59aaea9d5a1f3e259fd42d15b3a113bd2d24d3f4e  application/tests/test_hotel_partner_media_publication.py
```

Hashes bind this inspection snapshot. Later edits need re-review and refreshed hashes before claiming this review covers the final candidate.
