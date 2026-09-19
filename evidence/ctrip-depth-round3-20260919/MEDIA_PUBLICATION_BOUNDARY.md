# Hotel direct-upload publication boundary

Source inspected: PR #221, commit `181e7568b8ed640aba5c4b6a932f4d6c6e74c5b3`.

## Implemented and tested in this slice

- Supplier-owned high-resolution originals can be attached to a property and its rooms as draft references. A different role or room creates a distinct deterministic asset identity, reusing the immutable bytes; approval on the previous binding is not copied. Existing bindings are retained, so this is additive usage, not a move/delete operation.
- The supplier submits an explicit selection into the existing durable `HotelPartnerChangeRequestRow` queue with `field_group=MEDIA_PUBLICATION`. Whole-batch ownership, original-file integrity, room ownership and binding checks precede the write. Identical pending requests deduplicate.
- Readback distinguishes `SUBMITTED` / `PUBLISH_REQUESTED`, rejected review history, rights review, and actual publication. Every response retains `published=false`; no supplier route grants rights or publishes the canonical webpage.
- Rights eligibility is recomputed through the existing media rights predicate. Revocation or expiry is reflected on subsequent reads. The stored proposed selection is a review snapshot, not a promise that future publication is authorized.
- Binding revision is an optimistic identity check; it is not a distributed SQL/media-index transaction. Binding does not grant rights. A failure after a derivative cache admission can leave an unbound private draft, never a published partial result.

## Why an adapter to the existing publish button is insufficient

Existing authority is adequate: `api/routes/hotel_autopage_factory.py::catalog_writer` requires administrator `admin:rules`, and controls rights decisions and `set_publication`. No new supplier authority should be introduced.

The blocking contract is more specific than missing authorization:

1. `hotel_catalog_quality.py` implements `OFFICIAL_CATALOG_REPLICATION_V1`. Each required field, including `media_candidates`, needs an official source type and an HTTPS provenance URL. Direct file uploads have neither a fetched official webpage nor its source-document hash.
2. Canonical room `official_id`, inventory-review source, room-document references and each `official_image_urls` entry use HTTPS identities. The manifest must prove declared/captured room parity and an independently reviewed complete inventory.
3. Approved cached assets count only when their official source type and source URL match the exact canonical room/image inventory. `hotel_autopage_factory._catalog_media` repeats that selection when serving a page. Direct upload records deliberately use `HOTEL_DIRECT_UPLOAD` and partner property/room identities, not inferred canonical identities.
4. Partner property IDs and room IDs are separate from canonical hotel IDs and canonical JSON room IDs. Registration's `official_supplement_json.property_id` is an explicit scoped convention, not a schema-enforced room mapping. Name matching or selecting the latest registration would risk publishing to the wrong hotel.

Relabeling a direct upload as a downloaded official source, inventing an HTTPS source URL, replacing canonical room identities, or bypassing the quality predicate would misrepresent evidence. None was done.

## Concrete next integration

Introduce a versioned hotel-direct-submission evidence contract while preserving `OFFICIAL_CATALOG_REPLICATION_V1` unchanged for official-site replication. Its reviewable inputs must contain: an approved property-to-registration-to-canonical-hotel association; explicit partner-room-to-canonical-room mappings; a hotel-confirmed complete room inventory; immutable original hashes and declared usages; rights evidence, expiry and the existing authorized review decision; and a manifest hash reviewed by the existing catalog writer.

An isolated administrator adapter can then promote the manifest into an immutable official-submission snapshot, attach approved assets to those exact canonical identities, compose the page, and invoke existing publication controls. Promotion needs an idempotent/recoverable boundary across the application database and local SQLite media index; publication and every public read must recheck current rights, integrity and scope. Approval and final publication must remain separate audit events.

Required acceptance scenarios: cross-hotel and cross-room rejection; ambiguous/missing identity rejection; complete/incomplete inventory; invalid or changed manifest hash; unknown/expired/revoked rights; original corruption; repeated request and interrupted promotion recovery; catalog-scope activation during promotion; successful approved publication; public read after revocation; and unchanged official-replication tests. Current supplier draft/request tests are not these publication tests.

This slice does not certify canonical image publication, a live hotel page, a distributed object store, PostgreSQL concurrency, C14/C13 acceptance, or deployment.
