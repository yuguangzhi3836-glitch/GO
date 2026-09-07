# DEPTH10 · Hyatt 10 Real Hotel Gate

Status: **NOT YET EXECUTED**. This document is an executable acceptance contract; it is not evidence of a pass.

## Selection

The candidate list MUST be produced by `HyattDirectoryAdapter` from Hyatt official directory data. Operators may not hand-pick a convenient hotel list after seeing failures. The first ten eligible, identity-valid properties in the frozen directory snapshot form the acceptance cohort unless a property is demonstrably closed/redirected, in which case the exclusion and official evidence must be recorded.

For each property retain:
- official directory snapshot SHA-256
- Hyatt property code
- canonical official property URL
- observed property name/city/country
- capture start/end UTC
- request/retry counts
- all official source URLs used
- room catalog evidence and media evidence
- resulting GO hotel ID/page version

## Per-hotel hard gates

1. Identity: official Hyatt property code maps to exactly one GO canonical hotel; rerun cannot create another hotel.
2. Catalog: every room/suite type explicitly present in the captured official Hyatt catalog is represented once. No invented room type and no silent cross-room merge.
3. Facts: area/bed/occupancy/view/floor/amenities are stored only when supported by official evidence; absence is represented as unknown, never guessed.
4. Media: room media must bind to the same room; exterior, lobby/public, dining, wellness/recreation, meetings/events and other hotel-wide scenes are classified separately. Missing categories are visible completeness gaps, not filled by borrowing unrelated images.
5. Rights: downloadability does not equal publishability. Published media requires the configured rights policy/evidence gate.
6. Idempotency: three consecutive runs against the same frozen snapshot produce no duplicate canonical hotel, room, source snapshot or page proliferation beyond an intentional new source/page version.
7. Failure safety: an incomplete/new failed candidate cannot replace the last known good published page.
8. Recovery: terminate a worker after claim and before ACK; after lease expiry another worker resumes the same task, and exactly one terminal ACK is accepted.
9. UX data contract: generated C-end data is sufficient for hero/gallery, hotel summary, editable dates/guests, room cards, in-room rate comparison, sticky CTA, checkout and after-sales surfaces without using fabricated facts.
10. Evidence: every PASS assertion is backed by machine-readable evidence stored with the candidate.

## Fleet gates

Across all ten hotels:
- 10/10 identity PASS
- 10/10 official catalog parity PASS against the captured snapshot
- zero room/media cross-bind
- zero duplicate canonical hotels after reruns
- zero lost tasks under forced worker termination
- zero failed candidate overwriting a last-known-good page
- PostgreSQL lease/ACK gate PASS
- PostgreSQL durable media metadata gate PASS
- real browser validation at 375, 390 and 430 CSS px plus representative desktop

## Release rule

Any single failure keeps `HOTEL_REPLICATION_GATE=HOLD`.

This gate does not by itself permit `FINAL_RELEASE_GATE=PASS`; Hong Kong runtime acceptance and the GO masterpiece visual gate remain separate required gates.
