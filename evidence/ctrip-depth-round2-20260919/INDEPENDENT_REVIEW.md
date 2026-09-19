# Independent source review — Ctrip depth round 2

Review date: 2026-09-19. Review performed by a separate reviewing agent without editing product files. Integrator-provided base is PR #219, commit `5f62478b970fdd2bce9ef2f6e7dea7e35d67cc38`. This review inspected the local materialized candidate; it does not independently attest a complete fresh checkout or every repository-wide caller.

## Result

No remaining blocker identified within the inspected source scope after the room-import UI correction below. This is scoped engineering review, **not** formal C14 Gate, C13 acceptance, deployment approval, or 100% product completion.

## Finding and correction

The initial room import UI offered source-identified rooms but omitted the API's required owner-confirmed room mappings. Such requests could never succeed. The final inspected UI disables that selection with a Chinese explanation and also guards submission; selected hotel fields remain usable. This is an intentional incomplete UI capability, not a claim that room mapping is usable end to end.

## Inspected behavior

- Media intake checks supplier/property ownership and optional room ownership, actual decodable image bytes, allowed format, image dimensions/size, and explicit rights declaration. Deterministic asset identity includes ownership and binding. It uses the existing transactional local media index and immutable digest file admission. Original readback repeats authorization and validates file integrity/path; response is private/no-store. Records remain RIGHTS_UNKNOWN and unpublished drafts. Media tests check the existing content-path publication gate rejects these drafts.
- Room mapping resolves explicit source/provider identity and confirmed targets, rejects cross-property targets, rebinds and alias conflicts, and preserves omitted room fields. It validates the complete mapping before writes and commits data, bindings, import job and audit together. ID-less legacy imports intentionally retain append semantics. PostgreSQL row locking is present but not independently exercised here.
- Exact cancellation deadlines use the property's timezone and reject ambiguous/nonexistent local cutoff times. Confirmation-based cooling-off uses persisted confirmation events; missing evidence fails closed. Earliest qualifying event is used, avoiding a repeated event extending the grace period. Existing rules without the new anchor retain order-created semantics. Quote expiry is bounded by the next fee transition.
- Import UI preview performs no server write, escapes displayed data, submits selected fields only and excludes OTA media. Failed requests preserve inputs and render Chinese messages. Media upload requires a declared right and a positive unpublished draft response before reporting success.

## Independent execution

`node --test tests/test_supplier_hotel_import_ui.cjs`: **13 passed, 0 failed**, exit 0.

`PYTHONPATH=src /workspace/scratch/7375eae00ed5/go-depth-venv/bin/python -m unittest discover -s tests -p test_hotel_cancellation_clock.py -q`: **18 passed**, exit 0, independently rerun by this reviewer after dependency completion. The suite uses its own isolated in-memory SQLite engine.

The first cancellation attempt had failed collection because the partial materialization lacked `vertical_reservation_expiry`. The cancellation owner completed dependencies from the declared base and corrected the test fixture to store UTC timestamps matching the real event producer. The independent rerun above supersedes that failed collection; no product behavior was weakened. No concurrent shared-database reset suite was run by this reviewer.

## Remaining limits

- The page currently chooses and clearly labels the first supplier property; no multi-hotel selector, source-room mapping editor, or room-photo assignment UI is delivered here.
- Uploaded originals are private local-cache drafts. Canonical hotel/room publication binding, explicit rights approval, distributed storage operations, full image inventory recovery and real hotel uploads are not verified.
- No actual Ctrip download/import, supplier session, live hotel mutation, production authentication flow, full browser rendering/mobile journey, full application build, PostgreSQL concurrency test, or Hong Kong deployment was performed in this review.
- Raw original bytes may include original image metadata; this interface is authenticated. A future public publication pipeline must retain its own metadata/privacy review.

The final narrow follow-up changed anchor membership checking from a set to a tuple, so malformed list/dictionary anchors now raise the intended validation error instead of TypeError. Reviewed this change and independently reran all 18 isolated cancellation tests successfully.

## Inspected source SHA-256

Changes after these hashes require re-review or explicitly recorded narrow verification.

- `application/src/go_hotel/services/hotel_partner_media_upload.py`: `f61fe8b3a6a46b1da054f2e923189f92b8d48c726670b2df7468041c6a1a4730`
- `application/src/go_hotel/services/hotel_partner_core.py`: `d79caab3738e9bcad5e76c9af03bbf6bdd942c56612012200875ef45e41abdbe`
- `application/src/go_hotel/api/routes/hotel_partner_core.py`: `eabc93b78b7a1162b3671c2198dd9f271cb8910fbca178623d36b83f592e06f0`
- `application/src/go_hotel/services/hotel_cancellation_clock.py`: `123e99568e52f418c66699b97dd3db371db0ca9acb13e69c4618a488375dc6e2`
- `application/src/go_hotel/services/hosted_fare_rules.py`: `3ac91d435cd683081d93a82316621c47a02d8075dc48fa67c5080092094e2ecb`
- `application/src/go_hotel/services/catalog_fare_snapshot.py`: `bcf3ae135a8d6e1ed8bf352a4c9617d30d9223abe981c00229a3734792d97972`
- `application/frontend/shared/app.js`: `a1b9da369bca8e46a1d2dae0b3060c3db5c43dd91439c213bff488ec2c4a0604`
- `application/frontend/supplier/config.js`: `05ed4f6512b4018dd3378b9c7dbbc1e39de3432a6b5049e6c8666eab4b462b3e`
