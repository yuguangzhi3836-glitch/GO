# C01 reviewed catalog JSON import UI — local candidate only

Base: PR 192 source `96721782158b5d665f7723305e5fb2212bd256ae`, application tree `c209bfba79f4fce05c504df1b192f3a285010cb3`. Exact frontend blob verified. No submission, deployment, login or live mutation was performed.

Files ready for an independent next candidate:

- application/frontend/admin/hotel-page-factory.js
- application/tests_frontend/hotel_catalog_reviewed_import.test.mjs
- application/tests_frontend/fixtures/aoluguya_normalized_ingest_plan.json

The primary Aoluguya detail page gains a file chooser, “核对资料” and “确认导入为草稿”. It uses the existing authenticated ctx.api client only; no cookie/token access, custom authentication, database access, account creation or privilege escalation. Both review and execute check the normal `/bff/auth/me` principal for GO_ADMIN and admin:rules; the backend remains the security authority. The feature is deployed only through the usual candidate gates; the UI does not claim that selecting a file verifies deployment.

Input is limited to the actual audited C01 four-operation JSON by canonical semantic SHA256 `a78aed8aa3a504a7ab165e3c6e4d9f5b335cd49a7d4d3c0128c7a2f4eae2db66`. Whitespace/key-order changes are accepted; any fact, source, rights, identity or operation alteration is rejected. The returned validated plan is deeply frozen and admitted through a WeakSet before running. Other hotels and unknown input are refused. It does not turn the JSON into an arbitrary endpoint runner.

Before import: require the protected scope preview, two visible protected profiles and zero running regional tasks; read the current profile and secondary identity; refuse conflicting source-key binding or higher-priority/unknown provenance. A separate normal page panel now provides protected-scope preview and activation before import. It displays the two retained identities and all 112 archived identities, with a review fingerprint under details; it requires admin:rules, exact expected counts/identity closure, no RUNNING regional task, and physical_deletion=false/audit retained. Confirming re-reads the fingerprint before calling the existing activate API. After activation it verifies the two-profile overview and all 112 archived detail rejections (HTTP409 + CATALOG_RECORD_ARCHIVED). Scope change or any readback failure stops completion. No physical reset endpoint is used. Import remains blocked until the visible catalog contains only the two protected profiles.

Write contract: exactly UNPUBLISH + three existing `/sources/ingest` calls. Official info and FAQ retain OFFICIAL_WEBSITE/9500; historical 17-room evidence retains PUBLIC_SOURCE/5000. No source priority manipulation. The unsupported canonical field `recovery_source_manifest_sha256` stays in the reviewed file and is removed from the submitted payload. Fixed source key/external ID/payload exercise existing server idempotence. APIs are sequential, not a cross-request transaction: partial failure stops further calls, reports successful source count, and requires review before retry. It never auto-publishes. Final readback checks every fact, phone contact, 17 rooms, DRAFT state and zero publishable media; failure never reports completion.

## Existing API and media gaps

| Capability | Current contract / limitation |
|---|---|
| Normal authorization | GET /bff/auth/me; existing admin:rules required for writes |
| Scope validation | GET catalog-scope/preview, review list and fingerprint, then POST catalog-scope/activate with scope_sha256 only; factory/archived-detail readback |
| Fact/room ingestion | POST /internal/v1/hotel-autopage/sources/ingest; canonical_hotel_id/source identity/rights/confidence/payload; actual merge follows existing source priority |
| Unpublish | POST /internal/v1/hotel-autopage/factory/hotels/{id}/publication with UNPUBLISH |
| Readback | Existing factory hotel detail; includes canonical fields, contacts, media counts and provenance |
| Existing media harvest | URL-based harvest accepts source_url/hotel_id/role/room_type_id/source_type/observed_at plus transport options; it downloads and computes SHA256 |
| Local recovered media upload | No supported local-byte/binary-upload contract found; cannot send EASON paths to URL harvest |
| Expected media SHA256 | No expected_sha256 argument in exact PR192 harvest signature; do not invent one. Any future recovery must compare returned bytes SHA256 per asset using a reviewed supported flow |
| Rights decision | Separate API requires expected_revision and actual authorization evidence/owner; UNKNOWN files are not automatically authorized |
| Current recovery limits | Thirty recovered objects, rights UNKNOWN; no image import in this patch; original 199-image manifest not recovered; no 100% completeness/publication claim |

Verification: Node syntax check PASS and twelve behavioral tests PASS. Tests load the actual browser module in a VM and use an API double to verify exact JSON acceptance, readonly/no-write, scope/priority rejection before UNPUBLISH, unreviewed-object rejection, the four allowed writes, partial-stop behavior, final readback failure, scope preview/activation/readback, fingerprint drift, running-task refusal, readback leak refusal and Chinese anomaly labels. No browser visual QA or live API acceptance is claimed. Independent review should precede integration.

## Execution precondition belongs to the deployment operator

This product UI deliberately does not ask hotel operators to upload signing keys, deployment receipts or runtime technical proofs. It uses only the normal authenticated API client and the existing backend admin:rules, protected scope and source/rights gates. It does not verify or claim signed deployment acceptance. For this specific execution, root must independently establish exact new-candidate signed DEPLOY_OK + independent VERIFY_OK + fresh live host/image identity before using the normal browser buttons. Existing operator deployment prerequisites continue to apply to root's action; adding this UI does not replace, waive or self-certify them. The browser session stays in its browser: no cookie/token export to scripts.

The patch also maps only known catalog anomaly codes to Chinese descriptions (including field missing/source/conflict and room/media parity codes). Existing human-readable Chinese labels are preserved; unknown raw codes fall back to “酒店资料需要核对” and are never exposed as a label.
