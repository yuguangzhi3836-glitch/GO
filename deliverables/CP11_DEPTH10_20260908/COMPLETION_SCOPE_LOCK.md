# DEPTH10 Final Completion Scope Lock

The following scope must be code-complete before Hong Kong Staging is asked to validate anything. No incremental HK validation is requested during implementation.

## A. Autonomous hotel factory
- whole-directory chain discovery without manual per-hotel input
- canonical identity, de-duplication and idempotency
- official-source truth capture for hotel facts, room catalog and media
- room-to-media isolation; no cross-room borrowing
- resumable build state and last-known-good protection
- batch operation suitable for horizontal scale

## B. Seven chain adapters and execution order
1. Hyatt
2. Marriott
3. Shangri-La
4. Hilton
5. IHG
6. H World / Huazhu
7. Atour

Each adapter must be official-host constrained, fail closed on source-shape drift, emit deterministic property identities, preserve resumable cursor/snapshot state and feed the same autonomous build pipeline.

## C. Durable execution and media authority
- PostgreSQL task authority: enqueue -> claim -> lease -> heartbeat -> ACK / retry -> DEAD
- expired-lease reclaim and idempotent terminal state
- Redis BRPOP cannot be a production authority
- PostgreSQL durable media metadata/rights/publication ledger
- process-local index.json cannot be a production authority
- media bytes content-addressed and integrity rechecked before publication

## D. GO C-end masterpiece product
Product constitution:
**official-source truth + Ctrip-grade ease of use + GO masterpiece visual system + AI-shortened decision path.**

Required surfaces: search/results, filtering/sorting, map/list, hotel detail, scene gallery, room cards, rate-plan comparison, checkout, confirmation, booking management, changes/cancellation/support and all loading/error/sold-out/sparse-data states.

Required responsive evidence contract: 375 / 390 / 430 CSS px mobile, tablet and desktop. Functional but visually average is not complete.

## E. Command Center <-> Hong Kong Control Plane closure
Code-complete control contract must include:
- HTTPS control endpoint contract
- node identity and scoped node token
- request signing with timestamp + nonce + task digest
- replay rejection and bounded clock skew
- allowlisted task types only; no arbitrary shell execution
- STAGING_READONLY and STAGING_CONTROLLED_EXECUTE separated by policy
- candidate SHA / task SHA binding
- durable task idempotency and dedupe
- structured execution state and evidence manifest return
- evidence bundle hash verification
- timeout, retry and network interruption semantics
- authority/constitution gate before controlled execution
- secrets never logged or returned in evidence
- production target remains blocked; this closure is HK Staging only

## F. Final candidate before HK
Before requesting Hong Kong validation, source side must produce one sealed candidate containing all of A-E plus:
- static compile/tests
- legacy production guard
- source-tree manifest/checksum
- exact candidate SHA-256
- one HK one-shot runner/instruction
- one expected evidence schema

## G. Single HK validation only after code-complete seal
Hong Kong receives exactly one final candidate and one one-shot instruction. The one-shot must run lineage/authority checks, PostgreSQL crash recovery, real Hyatt 10-hotel E2E, chain/runtime checks, durable media validation, browser/mobile masterpiece gate, control-plane round-trip and evidence sealing.

No PASS may be inferred from code presence. Until that final one-shot returns verifiable evidence:
- HOTEL_REPLICATION_GATE=HOLD
- CONTROL_PLANE_HK_DIRECT_GATE=HOLD
- GO_HOTEL_MASTERPIECE_GATE=HOLD
- FINAL_RELEASE_GATE=HOLD
