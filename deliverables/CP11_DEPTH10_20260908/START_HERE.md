# GO CP11 DEPTH10 · Chain-first Autonomous Hotel Factory

Status: **IN PROGRESS**. This branch starts from DEPTH09 archive lineage and does not claim release completion.

## Locked product constitution

**Official-source truth + Ctrip-grade ease of use + GO masterpiece visual system + AI-shortened decision path.**

GO does not reproduce an OTA or hotel group's proprietary visual design. Official hotel/group sources are the primary truth source for hotel identity, room catalog, facilities and official media; the GO consumer experience is independently designed and benchmarked against the strongest consumer travel flows for speed, clarity and trust.

## Autonomous acquisition order

1. Hyatt
2. Marriott
3. Hilton
4. IHG
5. H World / Huazhu
6. Atour
7. Independent hotels discovered after chain coverage, with canonical identity resolution and preference for hotel-owned/authorized sources

No manual screenshot or per-hotel seed is required for normal nationwide operation. Screenshots remain an optional ad-hoc entry path only.

## DEPTH10 work package

This depth establishes the group-directory control plane required before wide crawling:

- chain registry and execution order
- per-group directory enumerator contract
- canonical property seed contract
- per-domain concurrency and request-budget policy
- resumable cursor/checkpoint contract
- deterministic idempotency key per chain/property
- source policy enforcement before a hotel enters the existing DEPTH09 capture pipeline
- explicit states: DISCOVERED -> IDENTITY_VERIFIED -> CATALOG_CAPTURE -> MEDIA_CAPTURE -> QUALITY_GATE -> READY_TO_PUBLISH / NEEDS_ENRICHMENT
- no failure may replace a last-known-good published page

## Concurrency policy

Initial operational target is 50 hotels concurrently active across the fleet, not 50 requests against one domain. Domain-level throttling is mandatory. Validation tier is 200 concurrent hotels; 1000+ nationwide tasks may be queued/active only after persistence, ACK/lease recovery, media atomicity and real multi-group tests pass.

## Masterpiece C-end release gate

The hotel consumer surface is a release gate, not decoration. Representative real hotels must pass mobile 375/390/430, tablet and desktop checks for:

- typography hierarchy and spacing rhythm
- photography crop/order quality
- room/rate comprehension
- sticky CTA behavior
- search/filter/map interaction
- checkout and after-sales task length
- loading/error/sold-out/sparse-media/long-name/many-room edge states
- visual regression consistency
- clear GO identity without generic OTA template appearance

## Immediate engineering sequence

1. Add chain registry + property seed model.
2. Add first Hyatt directory adapter behind a bounded interface.
3. Feed verified Hyatt seeds into the existing official capture pipeline.
4. Add persistent claim/lease/ACK/retry/resume semantics to the regional build path.
5. Move media indexing to atomic durable storage before enabling high concurrency.
6. Validate at least 10 real hotels across multiple official-site templates.
7. Add C-end masterpiece visual benchmark before release.

`HOTEL_REPLICATION_GATE=HOLD` and `FINAL_RELEASE_GATE=HOLD` remain in force until the above gates pass.
