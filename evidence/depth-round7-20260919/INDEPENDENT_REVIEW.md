# Round 7 independent scoped review

Reviewed by a separate session agent on 2026-09-19. This is a scoped code and test review, not formal C13/C14 acceptance, deployment approval, or browser acceptance.

## Scope and conclusion

Reviewed the new administrator review UI, supplier manifest submission and state UI, authenticated image blob handling, review inspection/list endpoints, and supplier ownership-scoped reads. After root identified an additional displayed-facts race, review was reopened and the fact-fingerprint fix independently inspected and retested. No remaining blocking defect was found in the reviewed UI path. Full rendered desktop/mobile acceptance and PostgreSQL concurrency remain unverified; this is not an all-system approval.

## Findings resolved during review

1. The administrator default queue sent `state=` while the API only permits explicit review states. This made the default queue return a conflict. Empty filter values are now omitted.
2. The initial supplier history only displayed the first 25 reviews without navigation. The UI now shows the total/range with previous/next controls.
3. Administrator asynchronous work initially depended only on the mounted DOM. The UI now also snapshots the session CSRF value, invalidates results/actions when that context changes, and clears stale details. Returning from the module clears the delegated click handler.
4. Two initial inspection-test failures were fixture/assertion defects: missing required `created_at`, and assuming normalized asset order equals input order. Both were corrected; the subsequent scoped test run passed.
5. Root found that hotel/room facts could change while the submitted manifest hash stayed unchanged. Inspection now computes a physical-facts fingerprint using the same ORM session as its displayed property/profile/rooms. The UI requires that fingerprint, compares it during confirmation, and sends it with the approval. The approval transaction compares the expected fingerprint before storing approval. Independent API tests changed a room name after inspection and observed rejection, then successful approval only after re-inspection; UI tests independently reject changed or absent fingerprints. Exact review identity is checked in responses as well.

## Checks performed

- Untrusted hotel names, room names, rights references and identifiers are escaped before HTML rendering. Status messages use text content; supplier URLs are not embedded as image sources.
- Original-image preview is fetched through the existing authenticated API client. Accepted content types are JPEG, PNG and WebP; SVG and unexpected responses are rejected. Preview requests are lazy and object URLs are released when details change.
- Approval uses the exact displayed manifest SHA-256 plus physical-facts fingerprint, re-reads current state/capability before sending, and then re-reads the resulting state. The UI separates approval from publication and does not report success for failed/ambiguous responses.
- Inspection responses from an older selected review cannot replace newer ones. Supplier file preview/list/action results require the same property, route generation and mounted form node. Mutation busy state prevents an in-flight hotel switch.
- Administrator reads use the existing `admin:rules` authority. Supplier list/detail reads first validate property ownership; a caller-selected canonical hotel ID cannot expose another hotel's canonical details.
- Queue filtering is server-side, bounded to 100 rows, and uses stable timestamp/ID ordering. Supplier history is scoped by the owned property.
- Inspection actions consider current original bytes, authorization, room mappings, provenance conflicts and publication quality. Public availability is reported separately from approval and requires the canonical public-page read to succeed.

## Independently executed tests

From `application/`:

```text
node --test tests/test_hotel_direct_review_ui.cjs
17 passed

node --test tests/test_supplier_hotel_import_ui.cjs
30 passed

PYTHONPATH=src /workspace/scratch/7375eae00ed5/go-depth-venv/bin/python -m pytest -q tests/test_hotel_direct_submission_inspection.py tests/test_hotel_direct_submission_api.py tests/test_hotel_direct_submission_real_identity.py
18 passed
```

The Python integration uses isolated synthetic accounts with actual password/JWT/database-session behavior. It is a scoped FastAPI router application backed by SQLite, not the full deployed application or production login.

## Remaining limits

- The cloud browser was reported blocked by the root agent's permitted navigation attempt. No network/policy workaround was attempted by this reviewer, and no screenshot, responsive-layout or real mobile journey is claimed.
- No actual Aoluguya hotel review was approved or published in this review. Source-room/canonical-room reconciliation, original hotel images and authoritative rights evidence remain operational prerequisites.
- SQLite tests do not establish PostgreSQL locking correctness under concurrent approve/revoke/publish operations. Large-gallery response measurements also do not establish browser image-decode or mobile scrolling performance.
- The additional approval fingerprint is required by both the new UI and the HTTP approval schema. The internal Python service retains an optional parameter for existing internal callers; HTTP callers cannot omit it. The tests do not prove atomic exclusion of concurrent PostgreSQL updates to every related row.
- The supplier entry accepts a prepared structured manifest; this does not claim an end-to-end visual manifest authoring workflow.
