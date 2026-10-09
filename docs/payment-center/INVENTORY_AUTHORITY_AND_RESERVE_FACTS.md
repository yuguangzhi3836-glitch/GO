# D02 — Current Hotel Inventory Authority and Reserve Facts

Status: READ_ONLY_DISCOVERY
Evidence baseline: `main@286e294d92df4b7d1c0073116a8e628734abec6c`
Scope: HOTEL P0

## 1. Verified facts

### 1.1 No central HOTEL inventory authority was found in current main

Repository search found hotel offer-level `inventory_units`, merge/drift comparisons, prebook inventory status, and connector capability flags, but did not identify a HOTEL central inventory bucket/claim table equivalent to the existing rail/attraction `VerticalCapacityBucketRow` / `VerticalCapacityClaimRow` model.

The current hotel path delegates inventory checking/holding to the selected hotel connector via `prebook()`.

### 1.2 Current registered hotel inventory provider is mock-only

`application/src/go_hotel/connectors/registry.py` currently registers only `conn_mock_hotel` as the default/known hotel connector.

Therefore repository evidence does not establish a production hotel/PMS/channel-manager inventory authority.

### 1.3 Prebook is the current HOTEL reserve-like primitive

`BookingService.prebook()` calls the connector `prebook(offer)`, then records:

- price status;
- inventory status;
- policy status;
- benefit status;
- `hold_type`;
- `inventory_held`;
- `lock_expires_at`.

`BookingConsistencyGuard.validate_prebook_result()` maps inventory to:

- `HELD` when `prebook.inventory_held=True`;
- `AVAILABLE_NOT_HELD` otherwise.

Therefore current code intentionally distinguishes observed availability from an actual held inventory commitment.

### 1.4 Mock connector defaults to SOFT / not held

`MockHotelConnector` advertises capabilities including hard inventory hold and hard hold release, but its runtime default is:

- `prebook_hold_type = "SOFT"`;
- `inventory_held = False` for normal prebook.

Only when the mock is configured with hold type `HARD` does it return `inventory_held=True`.

Thus the existence of hard-hold capability metadata does not prove that the normal hotel prebook path currently reserves inventory.

### 1.5 Hard-hold release exists as an explicit connector contract

`hotel_hard_hold_release.release_locked()` requires the connector to advertise:

- `hard_inventory_hold`;
- `hard_hold_release`;
- `idempotent_hard_hold_release`.

It uses a stable idempotency key and reconciles timeout/unknown release by connector lookup. UNKNOWN does not become local cancellation.

This is strong evidence that the code distinguishes a real connector-native hard hold from a local status flag.

### 1.6 Offer merge detects conflicting inventory snapshots but is not inventory authority

`OfferMergeEngine` can detect differing `inventory_units` across equivalent offers and records an `INVENTORY_CONFLICT` in merge evidence.

It selects a source based on authorization/SLA/fare flexibility/cost, but this is a search/offer merge decision. It is not an atomic decrement or reserve operation.

## 2. Missing / not verified

No repository evidence was found for HOTEL of:

- one central inventory quantity ledger shared by GO, hotel and OTA;
- atomic `check-and-decrement` or `check-and-reserve` across hotel inventory;
- a row-level or optimistic version protecting the final HOTEL room across channels;
- multi-room/multi-night atomic reserve semantics;
- OTA-originated inventory synchronization participating in one atomic authority;
- a production connector proving that two simultaneous final-room requests yield exactly one hard commitment before payable credentials are created.

These are not disproved; they are simply not established by current main.

## 3. Final-room concurrency status

Current mock connector uses a simple boolean `inventory_available` and does not implement a shared quantitative last-room allocator.

Therefore current repository behavior cannot be used as evidence that HOTEL last-room concurrency is solved.

If A and B both see the last room, current HOTEL P0 repository evidence does not yet prove:

- where the single authoritative inventory row lives;
- what lock/version protects it;
- which request wins;
- whether the loser is prevented from receiving a real PSP-payable credential;
- how an OTA/hotel-side concurrent sale participates in the same decision.

## 4. Relationship to Payment Center

Inventory authority should not be silently moved into Payment Center.

The Payment Center discovery must consume an approved/verified reservation fact from the HOTEL inventory/booking side. The exact reserve API and lifecycle remain undecided because the current production HOTEL inventory authority is unknown.

## 5. Blockers

D02_BLOCKER_01=NO_PRODUCTION_HOTEL_INVENTORY_AUTHORITY_PROVEN
D02_BLOCKER_02=NO_ATOMIC_LAST_ROOM_RESERVE_PROVEN
D02_BLOCKER_03=OTA_HOTEL_GO_SHARED_INVENTORY_SERIALIZATION_NOT_PROVEN

## 6. Evidence paths

- `application/src/go_hotel/services/booking.py`
- `application/src/go_hotel/services/consistency.py`
- `application/src/go_hotel/connectors/registry.py`
- `application/src/go_hotel/connectors/mock_hotel.py`
- `application/src/go_hotel/services/hotel_hard_hold_release.py`
- `application/src/go_hotel/merge/engine.py`
- `application/src/go_hotel/domain/models.py`

D02_RESULT=BLOCKED_ON_REAL_HOTEL_INVENTORY_INTEGRATION_FACTS
