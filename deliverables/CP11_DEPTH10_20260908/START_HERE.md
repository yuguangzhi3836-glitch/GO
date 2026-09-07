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

## Implemented in this branch

- `chain_hotel_registry.py`: locked chain order, official-host policy, stable chain/property idempotency key and bounded adapter contract.
- `hyatt_directory_adapter.py`: Hyatt China official-directory enumerator with official-host enforcement, stable official property codes, deduplication, bounded pagination, resumable cursor and snapshot-hash protection. A changed directory snapshot cannot be silently mixed into a resumed inventory.
- `chain_task_lease.py`: persistent DB event-ledger state machine: QUEUED -> LEASED -> ACKED or RETRY_WAIT/DEAD. PostgreSQL advisory transaction locks serialize claims; expired leases are reclaimable after worker death; heartbeat extends ownership; ACK requires a live owned lease.
- `chain_autonomous_build.py`: verified Hyatt directory seeds are converted into `GROUP_OFFICIAL` discovery seeds and handed to the existing official catalog pipeline. Deterministic identity/source failures dead-letter; recoverable failures retry with bounded backoff.
- tests cover official host boundaries, Hyatt property dedupe, cursor resume, snapshot drift, conflicting identities, task claimability/state folding and the official discovery bridge.

The current production regional worker still uses the legacy Redis queue path. DEPTH10 does **not** claim that legacy path is now safe merely because the new durable chain task ledger exists. Cutover must occur only after PostgreSQL integration and forced-worker-termination tests pass.

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

1. ~~Add chain registry + property seed model.~~ Implemented.
2. ~~Add first Hyatt directory adapter behind a bounded interface.~~ Implemented, pending real official-directory capture validation.
3. ~~Feed verified Hyatt seeds into the existing official capture pipeline.~~ Bridge implemented, pending real multi-hotel run.
4. **Cut the chain worker over to persistent claim/lease/ACK/retry/resume semantics and prove PostgreSQL crash recovery.**
5. Move media indexing to atomic durable storage before enabling high concurrency.
6. Validate at least 10 real hotels across multiple official-site templates.
7. Add C-end masterpiece visual benchmark before release.

`HOTEL_REPLICATION_GATE=HOLD` and `FINAL_RELEASE_GATE=HOLD` remain in force until the above gates pass.
